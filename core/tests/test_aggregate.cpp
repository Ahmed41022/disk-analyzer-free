#include <ostream>

#include "dafree/model.hpp"

#include <doctest/doctest.h>

#include <algorithm>
#include <array>
#include <cstdint>
#include <limits>
#include <random>
#include <string>
#include <vector>

namespace {

template <typename T> T add_saturating(T left, T right) {
    const auto maximum = std::numeric_limits<T>::max();
    return right > maximum - left ? maximum : static_cast<T>(left + right);
}

std::uint16_t node_flags(bool is_directory, std::uint16_t additional = 0) {
    return static_cast<std::uint16_t>((is_directory ? dafree::kDir : 0) | additional);
}

struct Expected {
    std::uint64_t size = 0;
    std::uint64_t alloc = 0;
    dafree::Counts counts;
};

Expected recursive_oracle(const dafree::SegVector<dafree::Node> &nodes, dafree::NodeId id,
                          std::vector<Expected> &expected_by_id) {
    const auto &node = nodes[id];
    Expected expected{node.size, node.alloc, {}};
    if ((node.flags & dafree::kDir) == 0) {
        expected_by_id[id] = expected;
        return expected;
    }
    expected.size = 0;
    expected.alloc = 0;
    for (dafree::NodeId child_id = node.first_child;
         node.child_count != 0 && child_id < node.first_child + node.child_count; ++child_id) {
        const auto child = recursive_oracle(nodes, child_id, expected_by_id);
        const auto &child_node = nodes[child_id];
        if ((child_node.flags & (dafree::kHardlinkDup | dafree::kExcluded)) == 0) {
            expected.size = add_saturating(expected.size, child.size);
            expected.alloc = add_saturating(expected.alloc, child.alloc);
        }
        if ((child_node.flags & dafree::kExcluded) == 0) {
            if ((child_node.flags & dafree::kDir) != 0) {
                expected.counts.dirs = add_saturating(
                    expected.counts.dirs, add_saturating(std::uint32_t{1}, child.counts.dirs));
                expected.counts.files = add_saturating(expected.counts.files, child.counts.files);
            } else {
                expected.counts.files = add_saturating(expected.counts.files, std::uint32_t{1});
            }
        }
    }
    expected_by_id[id] = expected;
    return expected;
}

void make_random_tree(std::mt19937 &random, dafree::SegVector<dafree::Node> &nodes,
                      dafree::SegVector<dafree::Counts> &counts, std::uint32_t requested) {
    dafree::Node root;
    root.flags = static_cast<std::uint16_t>(dafree::kDir | dafree::kSynthetic);
    nodes.push_back(root);
    counts.push_back({});
    std::vector<dafree::NodeId> directories{dafree::kRoot};
    std::size_t next_directory = 0;
    while (nodes.size() < requested && next_directory < directories.size()) {
        const auto parent = directories[next_directory++];
        const auto remaining = requested - nodes.size();
        const auto count =
            std::min<std::uint32_t>(remaining, static_cast<std::uint32_t>(random() % 8 + 1));
        auto &parent_node = nodes[parent];
        parent_node.first_child = nodes.size();
        parent_node.child_count = count;
        for (std::uint32_t index = 0; index < count; ++index) {
            const bool is_directory = (random() % 4 != 0) && nodes.size() + 1 < requested;
            const auto extra =
                static_cast<std::uint16_t>(((random() % 13) == 0 ? dafree::kHardlinkDup : 0) |
                                           ((random() % 17) == 0 ? dafree::kExcluded : 0));
            dafree::Node child;
            child.parent = parent;
            child.flags = node_flags(is_directory, extra);
            child.size = random() % 100'000;
            child.alloc = random() % 100'000;
            if (is_directory) {
                child.size = 0;
                child.alloc = 0;
            }
            nodes.push_back(child);
            counts.push_back({});
            if (is_directory) {
                directories.push_back(nodes.size() - 1);
            }
        }
    }
    nodes.shrink_last();
    counts.shrink_last();
}

dafree::Tree make_deletion_fixture(bool incremental) {
    dafree::TreeBuilder builder({"/root"});
    const auto [dir_a, dir_a_end] = builder.add_children(
        1, std::array{
               dafree::TreeBuilder::NewNode{"a", node_flags(true), 0, 0, 0, 0, 0, std::nullopt},
               dafree::TreeBuilder::NewNode{"b", node_flags(true), 0, 0, 0, 0, 0, std::nullopt}});
    REQUIRE(dir_a_end == dir_a + 2);
    const auto duplicate = static_cast<std::uint16_t>(dafree::kHardlinkDup);
    builder.add_children(
        dir_a, std::array{dafree::TreeBuilder::NewNode{"one.bin", 0, 12, 8, 0, 0, 0, std::nullopt},
                          dafree::TreeBuilder::NewNode{"link.bin", duplicate, 12, 8, 0, 0, 0,
                                                       std::nullopt}});
    builder.add_children(dir_a + 1, std::array{dafree::TreeBuilder::NewNode{"two.bin", 0, 30, 20, 0,
                                                                            0, 0, std::nullopt}});
    if (!incremental) {
        builder.mark(dir_a, static_cast<std::uint16_t>(dafree::kExcluded));
    }
    auto tree = std::move(builder).finish({});
    if (incremental) {
        tree.mark_deleted(dir_a);
    }
    return tree;
}

} // namespace

TEST_CASE("aggregate_matches_recursive_oracle") {
    for (std::uint32_t seed = 0; seed < 500; ++seed) {
        std::mt19937 random{seed};
        const auto requested = static_cast<std::uint32_t>(random() % 5000 + 1);
        dafree::SegVector<dafree::Node> nodes;
        dafree::SegVector<dafree::Counts> counts;
        make_random_tree(random, nodes, counts, requested);
        dafree::aggregate(nodes, counts);
        std::vector<Expected> expected_by_id(nodes.size());
        recursive_oracle(nodes, dafree::kRoot, expected_by_id);
        for (dafree::NodeId id = 0; id < nodes.size(); ++id) {
            const auto &expected = expected_by_id[id];
            CHECK(nodes[id].size == expected.size);
            CHECK(nodes[id].alloc == expected.alloc);
            CHECK(counts[id].files == expected.counts.files);
            CHECK(counts[id].dirs == expected.counts.dirs);
        }
    }
}

TEST_CASE("hardlink_dup_counted_once") {
    dafree::SegVector<dafree::Node> nodes;
    dafree::SegVector<dafree::Counts> counts;
    dafree::Node root;
    root.flags = static_cast<std::uint16_t>(dafree::kDir | dafree::kSynthetic);
    nodes.push_back(root);
    counts.push_back({});
    dafree::Node first;
    first.parent = dafree::kRoot;
    first.size = 100;
    first.alloc = 80;
    nodes.push_back(first);
    counts.push_back({});
    auto duplicate = first;
    duplicate.flags = static_cast<std::uint16_t>(dafree::kHardlinkDup);
    nodes.push_back(duplicate);
    counts.push_back({});

    dafree::aggregate(nodes, counts);
    CHECK(nodes[0].size == 100);
    CHECK(nodes[0].alloc == 80);
    CHECK(counts[0].files == 2);
}

TEST_CASE("excluded_not_counted") {
    dafree::SegVector<dafree::Node> nodes;
    dafree::SegVector<dafree::Counts> counts;
    dafree::Node root;
    root.flags = static_cast<std::uint16_t>(dafree::kDir | dafree::kSynthetic);
    nodes.push_back(root);
    counts.push_back({});
    dafree::Node excluded;
    excluded.parent = dafree::kRoot;
    excluded.flags = static_cast<std::uint16_t>(dafree::kExcluded);
    excluded.size = 99;
    excluded.alloc = 77;
    nodes.push_back(excluded);
    counts.push_back({});

    dafree::aggregate(nodes, counts);
    CHECK(nodes[0].size == 0);
    CHECK(nodes[0].alloc == 0);
    CHECK(counts[0].files == 0);
}

TEST_CASE("mark_deleted_equals_full_reaggregate") {
    const auto incremental = make_deletion_fixture(true);
    const auto full = make_deletion_fixture(false);
    REQUIRE(incremental.size() == full.size());
    CHECK(incremental.node(2).flags == full.node(2).flags);
    for (dafree::NodeId id = 0; id < incremental.size(); ++id) {
        CHECK(incremental.node(id).size == full.node(id).size);
        CHECK(incremental.node(id).alloc == full.node(id).alloc);
        CHECK(incremental.counts(id).files == full.counts(id).files);
        CHECK(incremental.counts(id).dirs == full.counts(id).dirs);
    }
    CHECK((incremental.node(2).flags & dafree::kExcluded) != 0);
    CHECK(incremental.node(4).size == 12);
    CHECK(incremental.node(6).size == 30);
}

TEST_CASE("aggregate_saturates_and_deletion_restores_totals") {
    dafree::TreeBuilder builder({"/root"});
    builder.add_children(
        1, std::array{dafree::TreeBuilder::NewNode{
                          "max.bin", 0, std::numeric_limits<std::uint64_t>::max(),
                          std::numeric_limits<std::uint64_t>::max(), 0, 0, 0, std::nullopt},
                      dafree::TreeBuilder::NewNode{"small.bin", 0, 7, 5, 0, 0, 0, std::nullopt}});
    auto tree = std::move(builder).finish({});
    CHECK(tree.node(1).size == std::numeric_limits<std::uint64_t>::max());
    CHECK(tree.node(1).alloc == std::numeric_limits<std::uint64_t>::max());
    tree.mark_deleted(2);
    CHECK(tree.node(1).size == 7);
    CHECK(tree.node(1).alloc == 5);
}
