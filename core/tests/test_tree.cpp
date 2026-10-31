#include <ostream>

#include "dafree/model.hpp"

#include <doctest/doctest.h>

#include <array>
#include <cstdint>
#include <random>
#include <string>
#include <vector>

namespace {

std::uint16_t flags(dafree::NodeFlags flag) { return static_cast<std::uint16_t>(flag); }

std::string joined(std::string_view base, std::string_view name) {
#ifdef _WIN32
    constexpr char separator = '\\';
#else
    constexpr char separator = '/';
#endif
    std::string path(base);
    if (!path.empty() && path.back() != '/' && path.back() != '\\') {
        path.push_back(separator);
    }
    path.append(name);
    return path;
}

} // namespace

TEST_CASE("children_contiguous") {
    dafree::TreeBuilder builder({"/first", "/second"});

    const auto [root_first, root_last] = builder.add_children(
        1, std::array{
               dafree::TreeBuilder::NewNode{"a", flags(dafree::kDir), 0, 0, 0, 0, 0, std::nullopt},
               dafree::TreeBuilder::NewNode{"b", 0, 1, 1, 0, 0, 0, std::nullopt}});
    const auto [nested_first, nested_last] = builder.add_children(
        2, std::array{dafree::TreeBuilder::NewNode{"c", 0, 2, 2, 0, 0, 0, std::nullopt},
                      dafree::TreeBuilder::NewNode{"d", 0, 3, 3, 0, 0, 0, std::nullopt}});
    const auto tree = std::move(builder).finish({});

    CHECK(tree.roots().size() == 2);
    CHECK(tree.roots()[0] == 1);
    CHECK(tree.roots()[1] == 2);
    CHECK((tree.children(dafree::kRoot) == std::pair<dafree::NodeId, dafree::NodeId>{1, 3}));
    CHECK((tree.children(1) == std::pair<dafree::NodeId, dafree::NodeId>{root_first, root_last}));
    CHECK(
        (tree.children(2) == std::pair<dafree::NodeId, dafree::NodeId>{nested_first, nested_last}));
    CHECK(root_first == 3);
    CHECK(root_last == 5);
    CHECK(nested_first == 5);
    CHECK(nested_last == 7);
    CHECK(tree.node(3).parent == 1);
    CHECK(tree.node(4).parent == 1);
    CHECK(tree.node(5).parent == 2);
    CHECK(tree.node(6).parent == 2);
}

TEST_CASE("tree_accessors_and_invalid_ids") {
    dafree::TreeBuilder builder({"/root"});
    builder.add_children(
        1, std::array{dafree::TreeBuilder::NewNode{"file.TXT", 0, 8, 16, 0, 0, 0, std::nullopt}});
    auto tree = std::move(builder).finish({});
    CHECK(tree.name_bytes(0).empty());
    CHECK(tree.path_bytes(0).empty());
    CHECK_FALSE(tree.parent(0).has_value());
    CHECK_FALSE(tree.owner_name(2).has_value());
    CHECK_FALSE(tree.ext(1).has_value());
    REQUIRE(tree.ext(2).has_value());
    CHECK(*tree.ext(2) == "txt");
    CHECK(tree.depth(0) == 0);
    CHECK(tree.depth(1) == 0);
    CHECK(tree.depth(2) == 1);
    CHECK(tree.parent(2) == 1);
    const auto memory = tree.memory_usage();
    CHECK(memory.nodes == tree.size() * sizeof(dafree::Node));
    CHECK(memory.counts == tree.size() * sizeof(dafree::Counts));
    CHECK(memory.names > 0);
    CHECK(memory.interners > 0);
    CHECK_THROWS_AS(static_cast<void>(tree.node(tree.size())), std::out_of_range);
    CHECK_THROWS_AS(static_cast<void>(tree.counts(tree.size())), std::out_of_range);
    CHECK_THROWS_AS(static_cast<void>(tree.children(tree.size())), std::out_of_range);
    CHECK_THROWS_AS(static_cast<void>(tree.parent(tree.size())), std::out_of_range);
    CHECK_THROWS_AS(static_cast<void>(tree.depth(tree.size())), std::out_of_range);
    CHECK_THROWS_AS(dafree::TreeHandle(nullptr), std::invalid_argument);
}

TEST_CASE("parent_less_than_child_random_builds") {
    std::mt19937 random{0xDAF123u};
    for (std::uint32_t build = 0; build < 1000; ++build) {
        dafree::TreeBuilder builder({"/root" + std::to_string(build)});
        std::vector<dafree::NodeId> directories{1};
        std::uint32_t serial = 0;
        while (!directories.empty()) {
            const auto parent = directories.back();
            directories.pop_back();
            const auto count = static_cast<std::uint32_t>(random() % 4);
            std::vector<std::string> names;
            names.reserve(count);
            for (std::uint32_t index = 0; index < count; ++index) {
                names.push_back("entry-" + std::to_string(serial++));
            }
            std::vector<dafree::TreeBuilder::NewNode> entries;
            std::vector<bool> child_is_directory;
            entries.reserve(count);
            child_is_directory.reserve(count);
            for (std::uint32_t index = 0; index < count; ++index) {
                const bool is_directory = (random() & 1u) != 0 && serial < 25;
                entries.push_back({names[index],
                                   is_directory ? flags(dafree::kDir) : std::uint16_t{0}, 0, 0, 0,
                                   0, 0, std::nullopt});
                child_is_directory.push_back(is_directory);
            }
            const auto [first, last] = builder.add_children(parent, entries);
            for (auto child = first; child < last; ++child) {
                if (child_is_directory[child - first]) {
                    directories.push_back(child);
                }
            }
        }
        const auto tree = std::move(builder).finish({});
        for (dafree::NodeId parent = 0; parent < tree.size(); ++parent) {
            const auto [first, last] = tree.children(parent);
            if (tree.node(parent).child_count == 0) {
                REQUIRE(first == dafree::kNone);
                REQUIRE(last == dafree::kNone);
            } else {
                REQUIRE(last - first == tree.node(parent).child_count);
                for (auto child = first; child < last; ++child) {
                    REQUIRE(tree.node(child).parent == parent);
                }
            }
        }
        for (dafree::NodeId id = 1; id < tree.size(); ++id) {
            REQUIRE(tree.node(id).parent < id);
            const auto [first, last] = tree.children(tree.node(id).parent);
            REQUIRE(id >= first);
            REQUIRE(id < last);
        }
    }
}

TEST_CASE("path_reconstruction") {
    dafree::TreeBuilder builder({"/scan-root/"});
    const auto [directory, after_directory] =
        builder.add_children(1, std::array{dafree::TreeBuilder::NewNode{
                                    "Folder", flags(dafree::kDir), 0, 0, 0, 0, 0, std::nullopt}});
    REQUIRE(after_directory == directory + 1);
    builder.add_children(directory, std::array{dafree::TreeBuilder::NewNode{"file.txt", 0, 0, 0, 0,
                                                                            0, 0, std::nullopt}});
    const auto tree = std::move(builder).finish({});
    CHECK(tree.path_bytes(1) == "/scan-root/");
    CHECK(tree.path_bytes(directory) == joined("/scan-root/", "Folder"));
    CHECK(tree.path_bytes(directory + 1) == joined(joined("/scan-root/", "Folder"), "file.txt"));
    CHECK(tree.depth(1) == 0);
    CHECK(tree.depth(directory) == 1);
    CHECK(tree.depth(directory + 1) == 2);
}

TEST_CASE("find_path_case_rules") {
    dafree::TreeBuilder builder({"/Test/Éclair"});
    const auto [directory, last] =
        builder.add_children(1, std::array{dafree::TreeBuilder::NewNode{
                                    "Folder", flags(dafree::kDir), 0, 0, 0, 0, 0, std::nullopt}});
    REQUIRE(last == directory + 1);
    builder.add_children(directory, std::array{dafree::TreeBuilder::NewNode{
                                        "Straße.txt", 0, 0, 0, 0, 0, 0, std::nullopt}});
    const auto tree = std::move(builder).finish({});
    const auto expected = directory + 1;

#if defined(_WIN32) || defined(__APPLE__)
    CHECK(tree.find_path("\\test\\éclair\\fOLDER\\sTRAße.TXT") == expected);
#else
    CHECK(tree.find_path("/Test/Éclair/Folder/Straße.txt") == expected);
    CHECK_FALSE(tree.find_path("/test/Éclair/Folder/Straße.txt"));
#endif
    CHECK(tree.find_path("\\Test\\Éclair\\Folder\\Straße.txt") == expected);
    CHECK_FALSE(tree.find_path("/Test/Éclair/Folder/missing.txt"));
}

TEST_CASE("add_children_twice_throws") {
    dafree::TreeBuilder builder({"/root"});
    CHECK_THROWS_AS(builder.add_children(dafree::kRoot, {}), dafree::AlreadyPopulated);

    const auto [directory, last] = builder.add_children(
        1, std::array{dafree::TreeBuilder::NewNode{"directory", flags(dafree::kDir), 0, 0, 0, 0, 0,
                                                   std::nullopt}});
    REQUIRE(last == directory + 1);
    builder.add_children(directory, {});
    CHECK_THROWS_AS(builder.add_children(directory, {}), dafree::AlreadyPopulated);
}
