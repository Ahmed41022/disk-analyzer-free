#include "dafree/analysis.hpp"

#include <doctest/doctest.h>

#include <algorithm>
#include <array>
#include <limits>
#include <numeric>
#include <ostream>
#include <string>
#include <vector>

namespace {
using namespace dafree;

TEST_CASE("child chart ranks direct visible children and aggregates remainder") {
    TreeBuilder builder({"/scan"});
    const std::array entries{
        TreeBuilder::NewNode{"z.txt", 0, 7, 3, 0, 0, 0, {}},
        TreeBuilder::NewNode{"a.txt", 0, 7, 8, 0, 0, 0, {}},
        TreeBuilder::NewNode{"folder", kDir, 0, 0, 0, 0, 0, {}},
        TreeBuilder::NewNode{"hidden", kDir | kExcluded, 100, 100, 0, 0, 0, {}},
        TreeBuilder::NewNode{"duplicate", kHardlinkDup, 90, 90, 0, 0, 0, {}},
        TreeBuilder::NewNode{"zero", 0, 0, 0, 0, 0, 0, {}},
    };
    const auto [first, end] = builder.add_children(1, entries);
    const std::array nested{TreeBuilder::NewNode{"deep.txt", 0, 200, 200, 0, 0, 0, {}}};
    builder.add_children(first + 2, nested);
    const auto tree = std::move(builder).finish({});

    const auto size = child_chart_data(tree, 1, ChildChartField::Size, 1);
    REQUIRE(size.size() == 2);
    CHECK(tree.name_bytes(size[0].node) == "folder");
    CHECK(size[0].value == 200);
    CHECK(size[1].other);
    CHECK(size[1].node == kNone);
    CHECK(size[1].value == 14);
    CHECK(child_chart_data(tree, 1, ChildChartField::Size, 0).size() == 1);
    CHECK(child_chart_data(tree, 1, ChildChartField::Size, 0)[0].value == 214);

    const auto alloc = child_chart_data(tree, 1, ChildChartField::Alloc, 10);
    REQUIRE(alloc.size() == 3);
    CHECK(tree.name_bytes(alloc[0].node) == "folder");
    CHECK(alloc[0].value == 200);
    const auto files = child_chart_data(tree, 1, ChildChartField::Files, 10);
    REQUIRE(files.size() == 4);
    CHECK(tree.name_bytes(files[0].node) == "a.txt");
    CHECK(files[1].value == 1);
    CHECK(tree.name_bytes(files[1].node) == "folder");
    CHECK(files[2].value == 1);
    CHECK(tree.name_bytes(files[2].node) == "z.txt");
    CHECK(tree.name_bytes(files[3].node) == "zero");
    CHECK(end - first == entries.size());
    CHECK(child_chart_data(tree, first + 2, ChildChartField::Size, 10).size() == 1);
    CHECK(child_chart_data(tree, first + 2, ChildChartField::Size, 10)[0].value == 200);
    CHECK(child_chart_data(tree, first + 3, ChildChartField::Size, 10).empty());
}

TEST_CASE("child chart remainder saturates without overflowing") {
    TreeBuilder builder({"/scan"});
    constexpr auto maximum = std::numeric_limits<std::uint64_t>::max();
    const std::array entries{TreeBuilder::NewNode{"a", 0, maximum, maximum, 0, 0, 0, {}},
                             TreeBuilder::NewNode{"b", 0, maximum, maximum, 0, 0, 0, {}},
                             TreeBuilder::NewNode{"c", 0, maximum, maximum, 0, 0, 0, {}}};
    builder.add_children(1, entries);
    const auto tree = std::move(builder).finish({});
    const auto rows = child_chart_data(tree, 1, ChildChartField::Size, 1);
    REQUIRE(rows.size() == 2);
    CHECK(rows[0].value == maximum);
    CHECK(rows[1].other);
    CHECK(rows[1].value == maximum);
}

TEST_CASE("bounded chart ranking matches a full-sort oracle on wide siblings") {
    constexpr std::size_t count = 2'000, top = 15;
    TreeBuilder builder({"/scan"});
    std::vector<TreeBuilder::NewNode> entries;
    std::vector<std::string> names;
    entries.reserve(count);
    names.reserve(count);
    for (std::size_t index = 0; index < count; ++index) {
        auto name = std::to_string(index);
        name.insert(0, 8 - name.size(), '0');
        names.push_back(std::move(name));
        entries.push_back({names.back(), 0, (index * 71) % 97, (index * 31) % 79, 0, 0, 0, {}});
    }
    const auto [first, end] = builder.add_children(1, entries);
    const auto tree = std::move(builder).finish({});
    for (const auto field : {ChildChartField::Size, ChildChartField::Alloc}) {
        const auto value = [&](NodeId id) {
            return field == ChildChartField::Size ? tree.node(id).size : tree.node(id).alloc;
        };
        std::vector<NodeId> oracle;
        for (auto id = first; id < end; ++id)
            if (value(id) != 0)
                oracle.push_back(id);
        std::sort(oracle.begin(), oracle.end(), [&](NodeId left, NodeId right) {
            return value(left) != value(right) ? value(left) > value(right) : left < right;
        });
        const auto result = child_chart_data(tree, 1, field, top);
        REQUIRE(result.size() == top + 1);
        for (std::size_t index = 0; index < top; ++index) {
            CHECK(result[index].node == oracle[index]);
            CHECK(result[index].value == value(oracle[index]));
        }
        const auto other = std::accumulate(oracle.begin() + top, oracle.end(), std::uint64_t{},
                                           [&](auto sum, NodeId id) { return sum + value(id); });
        CHECK(result.back().other);
        CHECK(result.back().value == other);
    }
}
} // namespace
