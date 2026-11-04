#include "dafree/analysis.hpp"
#include "dafree/view.hpp"

#include <doctest/doctest.h>

#include <algorithm>
#include <array>
#include <numeric>
#include <ostream>
#include <random>
#include <string>

namespace {

using namespace dafree;

Tree analysis_tree() {
    TreeBuilder builder({"/scan"});
    const std::array entries{
        TreeBuilder::NewNode{"photo.JPG", 0, 8, 16, 90, 91, 0, {}},
        TreeBuilder::NewNode{"older.txt", 0, 5, 6, 70, 80, 95, {}},
        TreeBuilder::NewNode{"README", 0, 3, 4, 0, 0, 0, {}},
        TreeBuilder::NewNode{"duplicate.txt", kHardlinkDup, 80, 81, 95, 0, 0, {}},
        TreeBuilder::NewNode{"excluded", kDir | kExcluded, 0, 0, 0, 0, 0, {}},
        TreeBuilder::NewNode{"nested", kDir, 0, 0, 0, 0, 0, {}},
    };
    const auto [first, end] = builder.add_children(1, entries);
    const std::array ignored{TreeBuilder::NewNode{"ignore.zip", 0, 100, 100, 0, 0, 0, {}}};
    builder.add_children(first + 4, ignored);
    const std::array child{TreeBuilder::NewNode{"new.txt", 0, 6, 6, 120, 0, 0, {}}};
    builder.add_children(end - 1, child);
    return std::move(builder).finish({});
}

TEST_CASE("top_n_equals_sort_take") {
    constexpr std::size_t count = 20'000, take = 41;
    TreeBuilder builder({"/scan"});
    std::vector<std::uint64_t> sizes(count);
    std::iota(sizes.begin(), sizes.end(), std::uint64_t{1});
    std::mt19937 random(81);
    std::shuffle(sizes.begin(), sizes.end(), random);

    std::vector<TreeBuilder::NewNode> entries;
    entries.reserve(count);
    for (auto value : sizes)
        entries.push_back({"file", 0, value, value, 0, 0, 0, {}});
    const auto [first, end] = builder.add_children(1, entries);
    const auto tree = std::move(builder).finish({});
    std::vector<NodeId> expected(count);
    std::iota(expected.begin(), expected.end(), first);
    REQUIRE(expected.back() == end - 1);
    std::sort(expected.begin(), expected.end(),
              [&](auto a, auto b) { return tree.node(a).size > tree.node(b).size; });
    expected.resize(take);
    CHECK(top_n(tree, kRoot, TopKind::Files, take, SortKey::Size) == expected);
    CHECK(top_n(tree, 1, TopKind::Files, 0, SortKey::Size).empty());
}

TEST_CASE("top_dirs_include_nested_and_use_leaf_threshold") {
    const auto tree = analysis_tree();
    const auto dirs = top_n(tree, kRoot, TopKind::Dirs, 10, SortKey::Size);
    REQUIRE(dirs.size() == 2);
    CHECK(tree.name_bytes(dirs[0]) == "/scan");
    CHECK(tree.name_bytes(dirs[1]) == "nested");
    const auto leaves = top_n(tree, kRoot, TopKind::Dirs, 10, SortKey::Size, true);
    CHECK(leaves == std::vector<NodeId>{dirs[1]});
}

TEST_CASE("ext_breakdown_sums_to_total") {
    const auto tree = analysis_tree();
    const auto result = ext_breakdown(tree, 1);
    REQUIRE(result.size() == 3);
    CHECK(result[0].ext == "txt");
    CHECK(result[0].files == 2);
    CHECK(result[1].ext == "jpg");
    CHECK(result[1].category == ExtCategory::Image);
    CHECK(result[2].ext.empty());
    CHECK(classify_extension("ISO") == ExtCategory::DiskImage);
    std::uint64_t files = 0, size = 0, alloc = 0;
    for (const auto &row : result) {
        files += row.files;
        size += row.size;
        alloc += row.alloc;
    }
    CHECK(files == 4);
    CHECK(size == 22);
    CHECK(alloc == 32);
    const auto hidden_file = tree.children(tree.children(1).first + 4).first;
    CHECK(ext_breakdown(tree, hidden_file).empty());
}

TEST_CASE("age_buckets_partition_all_files") {
    const auto tree = analysis_tree();
    const std::array buckets{AgeBucket{"new", std::uint64_t{10}},
                             AgeBucket{"middle", std::uint64_t{30}},
                             AgeBucket{"old", std::nullopt}};
    const auto rows = age_histogram(tree, 1, TimeField::Modified, buckets, 100);
    REQUIRE(rows.size() == 4);
    CHECK(rows[0].size == 6);
    CHECK(rows[1].size == 8);
    CHECK(rows[2].size == 5);
    CHECK(rows[3].bucket == buckets.size());
    CHECK(rows[3].files == 1);
    CHECK(rows[3].size == 3);
    CHECK(rows[3].alloc == 4);
    CHECK(age_histogram(tree, 1, TimeField::Accessed, buckets, 100)[0].size == 5);
    CHECK_THROWS_AS(age_histogram(tree, 1, TimeField::Modified, std::span{buckets}.first(1), 100),
                    std::invalid_argument);
}

} // namespace
