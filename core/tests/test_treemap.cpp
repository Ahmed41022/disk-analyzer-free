#include "dafree/analysis.hpp"
#include "dafree/treemap.hpp"

#include <doctest/doctest.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <limits>
#include <random>
#include <string>
#include <vector>

namespace {

using dafree::NodeId;
using dafree::Tree;
using dafree::TreeBuilder;
using dafree::TreemapOptions;

Tree make_tree(std::uint32_t count, std::uint32_t seed = 7) {
    TreeBuilder builder({"/treemap"});
    std::vector<std::string> names;
    std::vector<TreeBuilder::NewNode> entries;
    names.reserve(count);
    entries.reserve(count);
    std::mt19937 rng(seed);
    std::uniform_int_distribution<std::uint32_t> sizes(1, 100'000);
    for (std::uint32_t i = 0; i < count; ++i) {
        names.push_back("f" + std::to_string(i) + ".dat");
        const auto size = static_cast<std::uint64_t>(sizes(rng));
        entries.push_back({names.back(), 0, size, size, 0, 0, 0, {}});
    }
    builder.add_children(1, entries);
    return std::move(builder).finish({});
}

Tree make_nested_tree(std::uint32_t seed) {
    TreeBuilder builder({"/nested"});
    const std::array<TreeBuilder::NewNode, 5> folders{{{"d0", dafree::kDir, 0, 0, 0, 0, 0, {}},
                                                       {"d1", dafree::kDir, 0, 0, 0, 0, 0, {}},
                                                       {"d2", dafree::kDir, 0, 0, 0, 0, 0, {}},
                                                       {"d3", dafree::kDir, 0, 0, 0, 0, 0, {}},
                                                       {"d4", dafree::kDir, 0, 0, 0, 0, 0, {}}}};
    const auto [first, last] = builder.add_children(1, folders);
    (void)last;
    std::mt19937 rng(seed);
    std::uniform_int_distribution<std::uint32_t> sizes(1, 1'000'000);
    std::array<std::string, 40> names;
    std::array<TreeBuilder::NewNode, 40> files{};
    for (std::size_t i = 0; i < files.size(); ++i) {
        names[i] = "nested" + std::to_string(i) + ".bin";
        const auto size = static_cast<std::uint64_t>(sizes(rng));
        files[i] = {names[i], 0, size, size, 0, 0, 0, {}};
    }
    for (NodeId dir = first; dir < first + 5; ++dir)
        builder.add_children(dir, files);
    return std::move(builder).finish({});
}

bool overlaps(const dafree::TmRect &a, const dafree::TmRect &b) {
    return std::max(a.x, b.x) < std::min(a.x + a.w, b.x + b.w) &&
           std::max(a.y, b.y) < std::min(a.y + a.h, b.y + b.h);
}

} // namespace

TEST_CASE("rects_within_parent") {
    for (const auto seed : {19u, 71u, 109u}) {
        auto tree = make_nested_tree(seed);
        TreemapOptions options;
        options.max_depth = 3;
        options.padding = 0;
        options.min_px = 0;
        auto layout = dafree::treemap_layout(tree, 1, 900, 600, options);
        const auto rects = layout.rects();
        REQUIRE_FALSE(rects.empty());
        CHECK(rects.front().node == 1);
        CHECK(rects.front().depth == 0);
        std::vector<const dafree::TmRect *> by_node(tree.size(), nullptr);
        std::vector<double> child_areas(tree.size(), 0);
        for (const auto &rect : rects)
            by_node[rect.node] = &rect;
        for (std::size_t i = 0; i < rects.size(); ++i) {
            const auto &r = rects[i];
            CHECK(std::isfinite(r.x));
            CHECK(std::isfinite(r.y));
            CHECK(std::isfinite(r.w));
            CHECK(std::isfinite(r.h));
            CHECK(r.w >= 0.0F);
            CHECK(r.h >= 0.0F);
            CHECK(r.x >= -0.01F);
            CHECK(r.y >= -0.01F);
            CHECK(r.x + r.w <= 900.01F);
            CHECK(r.y + r.h <= 600.01F);
            if (r.depth == 0)
                continue;
            bool found_parent = false;
            for (std::size_t p = 0; p < i; ++p) {
                const auto &parent = rects[p];
                if (parent.node == tree.node(r.node).parent && parent.depth + 1 == r.depth &&
                    r.x >= parent.x - 0.01F && r.y >= parent.y - 0.01F &&
                    r.x + r.w <= parent.x + parent.w + 0.01F &&
                    r.y + r.h <= parent.y + parent.h + 0.01F) {
                    found_parent = true;
                    break;
                }
            }
            CHECK(found_parent);
            const auto parent_id = tree.node(r.node).parent;
            REQUIRE(by_node[parent_id] != nullptr);
            const auto &parent = *by_node[parent_id];
            const auto expected_area = double{parent.w} * parent.h *
                                       static_cast<double>(tree.node(r.node).size) /
                                       static_cast<double>(tree.node(parent_id).size);
            const auto actual_area = double{r.w} * r.h;
            CHECK(actual_area == doctest::Approx(expected_area).epsilon(0.0001));
            child_areas[parent_id] += actual_area;
        }
        for (const auto &rect : rects)
            if (rect.flags & dafree::kTmDirectory)
                CHECK(child_areas[rect.node] ==
                      doctest::Approx(double{rect.w} * rect.h).epsilon(0.0001));
        for (std::size_t i = 1; i < rects.size(); ++i)
            for (std::size_t j = i + 1; j < rects.size(); ++j)
                if (rects[i].depth == rects[j].depth && rects[i].node != dafree::kNone &&
                    rects[j].node != dafree::kNone &&
                    tree.node(rects[i].node).parent == tree.node(rects[j].node).parent)
                    CHECK_FALSE(overlaps(rects[i], rects[j]));
    }
}

TEST_CASE("siblings_do_not_overlap") {
    auto tree = make_tree(800, 23);
    TreemapOptions options;
    options.max_depth = 1;
    options.padding = 0;
    options.min_px = 0;
    const auto layout = dafree::treemap_layout(tree, 1, 1200, 800, options);
    const auto rects = layout.rects();
    for (std::size_t i = 1; i < rects.size(); ++i)
        for (std::size_t j = i + 1; j < rects.size(); ++j)
            if (rects[i].depth == rects[j].depth &&
                tree.node(rects[i].node).parent == tree.node(rects[j].node).parent)
                CHECK_FALSE(overlaps(rects[i], rects[j]));
}

TEST_CASE("area_proportional_to_size") {
    TreeBuilder builder({"/area"});
    builder.add_children(1, std::array{TreeBuilder::NewNode{"one.bin", 0, 1, 1, 0, 0, 0, {}},
                                       TreeBuilder::NewNode{"three.bin", 0, 3, 3, 0, 0, 0, {}}});
    auto tree = std::move(builder).finish({});
    TreemapOptions options;
    options.max_depth = 1;
    options.padding = 0;
    options.header_px = 0;
    options.min_px = 0;
    options.max_rects = 10;
    const auto layout = dafree::treemap_layout(tree, 1, 400, 300, options);
    const auto rects = layout.rects();
    REQUIRE(rects.size() == 3);
    const auto first_area = static_cast<double>(rects[1].w) * rects[1].h;
    const auto second_area = static_cast<double>(rects[2].w) * rects[2].h;
    CHECK((first_area < second_area ? second_area / first_area : first_area / second_area) ==
          doctest::Approx(3).epsilon(0.01));
}

TEST_CASE("treemap_uint64_order_does_not_round_distinct_sizes_into_ties") {
    TreeBuilder builder({"/uint64"});
    const auto maximum = std::numeric_limits<std::uint64_t>::max();
    const auto [first, end] = builder.add_children(
        1, std::array{TreeBuilder::NewNode{"smaller.bin", 0, maximum - 2, 1, 0, 0, 0, {}},
                      TreeBuilder::NewNode{"middle.bin", 0, maximum - 1, 1, 0, 0, 0, {}},
                      TreeBuilder::NewNode{"largest.bin", 0, maximum, 1, 0, 0, 0, {}}});
    REQUIRE(end == first + 3);
    const auto tree = std::move(builder).finish({});
    TreemapOptions options;
    options.padding = 0;
    options.min_px = 0;
    const auto full = dafree::treemap_layout(tree, 1, 300, 300, options);
    REQUIRE(full.rects().size() == 4);
    CHECK(full.rects()[1].node == first + 2);
    CHECK(full.rects()[2].node == first + 1);
    CHECK(full.rects()[3].node == first);
    options.max_rects = 3;
    const auto capped = dafree::treemap_layout(tree, 1, 300, 300, options);
    REQUIRE(capped.rects().size() == 3);
    CHECK(capped.rects()[1].flags == dafree::kTmOther);
    CHECK(capped.small_items(1) == 2);
    CHECK(capped.rects()[2].node == first + 2);
}

TEST_CASE("respects_max_rects") {
    auto tree = make_tree(1000);
    TreemapOptions options;
    options.max_depth = 1;
    options.min_px = 0;
    options.padding = 0;
    options.max_rects = 17;
    const auto bounded = dafree::treemap_layout(tree, 1, 1000, 800, options);
    CHECK(bounded.rects().size() <= 17);
    options.max_rects = 0;
    auto empty = dafree::treemap_layout(tree, 1, 1000, 800, options);
    CHECK(empty.rects().empty());
    CHECK(empty.width() == doctest::Approx(1000));
    CHECK(empty.height() == doctest::Approx(800));
}

TEST_CASE("hit_test_smallest_containing") {
    TreeBuilder builder({"/hit"});
    const auto [first, last] = builder.add_children(
        1, std::array{TreeBuilder::NewNode{"dir", dafree::kDir, 0, 0, 0, 0, 0, {}},
                      TreeBuilder::NewNode{"outside.bin", 0, 20, 20, 0, 0, 0, {}}});
    builder.add_children(first,
                         std::array{TreeBuilder::NewNode{"inside.bin", 0, 10, 10, 0, 0, 0, {}}});
    auto tree = std::move(builder).finish({});
    TreemapOptions options;
    options.max_depth = 3;
    options.min_px = 0;
    options.padding = 0;
    options.max_rects = 20;
    auto layout = dafree::treemap_layout(tree, 1, 500, 300, options);
    REQUIRE(last == first + 2);
    REQUIRE(layout.rects().size() >= 4);
    const auto &leaf = layout.rects()[3];
    CHECK(layout.hit_test(leaf.x + leaf.w / 2, leaf.y + leaf.h / 2) ==
          std::optional<NodeId>(first + 2));
    CHECK_FALSE(layout.hit_test(-1, -1).has_value());
    CHECK_FALSE(layout.hit_test(layout.width(), layout.height()).has_value());
}

TEST_CASE("treemap_hit_test_matches_half_open_rectangles") {
    TreeBuilder builder({"/edges"});
    const auto [first, last] = builder.add_children(
        1, std::array{TreeBuilder::NewNode{"folder", dafree::kDir, 0, 0, 0, 0, 0, {}},
                      TreeBuilder::NewNode{"root.bin", 0, 13, 13, 0, 0, 0, {}}});
    builder.add_children(first,
                         std::array{TreeBuilder::NewNode{"nested.bin", 0, 7, 7, 0, 0, 0, {}}});
    auto tree = std::move(builder).finish({});
    TreemapOptions options;
    options.max_depth = 2;
    options.min_px = 0;
    options.padding = 0;
    auto layout = dafree::treemap_layout(tree, 1, 91, 67, options);
    REQUIRE(last == first + 2);
    std::vector<float> xs, ys;
    for (float x = 0.5F; x < layout.width(); x += 7.0F)
        xs.push_back(x);
    for (float y = 0.5F; y < layout.height(); y += 7.0F)
        ys.push_back(y);
    for (const auto &rect : layout.rects()) {
        for (const auto edge : {rect.x, rect.x + rect.w}) {
            xs.push_back(edge - 0.001F);
            xs.push_back(edge);
            xs.push_back(edge + 0.001F);
        }
        for (const auto edge : {rect.y, rect.y + rect.h}) {
            ys.push_back(edge - 0.001F);
            ys.push_back(edge);
            ys.push_back(edge + 0.001F);
        }
    }
    for (const auto x : xs)
        for (const auto y : ys) {
            std::optional<NodeId> expected;
            std::uint8_t deepest = 0;
            for (const auto &rect : layout.rects()) {
                if (rect.node != dafree::kNone && x >= rect.x && y >= rect.y &&
                    x < rect.x + rect.w && y < rect.y + rect.h &&
                    (!expected || rect.depth >= deepest)) {
                    expected = rect.node;
                    deepest = rect.depth;
                }
            }
            CHECK(layout.hit_test(x, y) == expected);
        }
}

TEST_CASE("treemap_input_and_tree_edge_cases") {
    auto tree = make_tree(4);
    TreemapOptions options;
    for (const auto &[w, h] :
         {std::pair{-1.0F, 20.0F},
          {20.0F, -1.0F},
          {std::numeric_limits<float>::infinity(), 2.0F},
          {2.0F, std::numeric_limits<float>::quiet_NaN()},
          {static_cast<float>(std::numeric_limits<int>::max()) + 4096.0F, 2.0F}})
        CHECK_THROWS_AS(static_cast<void>(dafree::treemap_layout(tree, 1, w, h, options)),
                        std::invalid_argument);
    options.padding = -1;
    CHECK_THROWS_AS(static_cast<void>(dafree::treemap_layout(tree, 1, 20, 20, options)),
                    std::invalid_argument);
    options.padding = 0;
    options.min_px = std::numeric_limits<float>::quiet_NaN();
    CHECK_THROWS_AS(static_cast<void>(dafree::treemap_layout(tree, 1, 20, 20, options)),
                    std::invalid_argument);
    options.min_px = 0;
    options.header_px = -1;
    CHECK_THROWS_AS(static_cast<void>(dafree::treemap_layout(tree, 1, 20, 20, options)),
                    std::invalid_argument);
    options.header_px = 0;
    auto zero = dafree::treemap_layout(tree, 1, 0, 0, options);
    CHECK(zero.rects().empty());
    CHECK_THROWS_AS(static_cast<void>(dafree::treemap_layout(tree, 999, 20, 20, options)),
                    std::out_of_range);
}

TEST_CASE("treemap_filters_invalid_items_and_limits_depth") {
    TreeBuilder builder({"/filter"});
    const auto [dir, end] = builder.add_children(
        1,
        std::array{TreeBuilder::NewNode{"positive.bin", 0, 7, 7, 0, 0, 0, {}},
                   TreeBuilder::NewNode{"zero.bin", 0, 0, 0, 0, 0, 0, {}},
                   TreeBuilder::NewNode{"duplicate.bin", dafree::kHardlinkDup, 11, 11, 0, 0, 0, {}},
                   TreeBuilder::NewNode{"folder", dafree::kDir, 0, 0, 0, 0, 0, {}}});
    builder.add_children(dir + 3,
                         std::array{TreeBuilder::NewNode{"nested.bin", 0, 3, 3, 0, 0, 0, {}}});
    auto tree = std::move(builder).finish({});
    TreemapOptions options;
    options.max_depth = 0;
    options.min_px = 0;
    options.padding = 0;
    options.max_rects = 20;
    const auto layout = dafree::treemap_layout(tree, 1, 500, 300, options);
    const auto rects = layout.rects();
    REQUIRE(end == dir + 4);
    CHECK(rects.size() == 1);
    options.max_depth = 1;
    const auto one_level_layout = dafree::treemap_layout(tree, 1, 500, 300, options);
    const auto one_level = one_level_layout.rects();
    CHECK(std::none_of(one_level.begin(), one_level.end(),
                       [=](const auto &r) { return r.node == dir + 1 || r.node == dir + 2; }));
}

TEST_CASE("treemap_padding_header_and_directory_classes") {
    TreeBuilder builder({"/header"});
    const auto [directory, end] = builder.add_children(
        1, std::array{TreeBuilder::NewNode{"folder", dafree::kDir, 0, 0, 0, 0, 0, {}}});
    REQUIRE(end == directory + 1);
    builder.add_children(directory,
                         std::array{TreeBuilder::NewNode{"picture.png", 0, 10, 10, 0, 0, 0, {}}});
    const auto tree = std::move(builder).finish({});
    TreemapOptions options;
    options.min_px = 0;
    options.padding = 5;
    options.header_px = 14;
    const auto layout = dafree::treemap_layout(tree, 1, 400, 200, options);
    REQUIRE(layout.rects().size() == 3);
    const auto &dir = layout.rects()[1];
    const auto &leaf = layout.rects()[2];
    CHECK(dir.x == doctest::Approx(5));
    CHECK(dir.y == doctest::Approx(5));
    CHECK(dir.w == doctest::Approx(390));
    CHECK(dir.h == doctest::Approx(190));
    CHECK(dir.cls == 1);
    CHECK(leaf.x == doctest::Approx(10));
    CHECK(leaf.y == doctest::Approx(24));
    CHECK(leaf.w == doctest::Approx(380));
    CHECK(leaf.h == doctest::Approx(166));
    CHECK(leaf.cls == static_cast<std::uint8_t>(dafree::ExtCategory::Image));
    CHECK(layout.hit_test(10, 10) == std::optional<NodeId>(directory));
    CHECK(layout.hit_test(1, 1) == std::optional<NodeId>(1));
    options.max_rects = 0;
    const auto empty = dafree::treemap_layout(tree, 1, 4, 3, options);
    dafree::Palette palette;
    palette.background = 0x12345678;
    const auto background = dafree::treemap_render(empty, 4, 3, palette, true);
    REQUIRE(background.size() == 48);
    for (std::size_t pixel = 0; pixel < background.size(); pixel += 4) {
        CHECK(background[pixel] == 0x12);
        CHECK(background[pixel + 1] == 0x34);
        CHECK(background[pixel + 2] == 0x56);
        CHECK(background[pixel + 3] == 0x78);
    }
}

TEST_CASE("treemap_merges_small_children_and_reports_count") {
    TreeBuilder builder({"/small"});
    builder.add_children(1,
                         std::array{TreeBuilder::NewNode{"large.bin", 0, 1000, 1000, 0, 0, 0, {}},
                                    TreeBuilder::NewNode{"a.bin", 0, 1, 1, 0, 0, 0, {}},
                                    TreeBuilder::NewNode{"b.bin", 0, 1, 1, 0, 0, 0, {}},
                                    TreeBuilder::NewNode{"c.bin", 0, 1, 1, 0, 0, 0, {}}});
    auto tree = std::move(builder).finish({});
    TreemapOptions options;
    options.max_depth = 1;
    options.min_px = 10;
    options.padding = 0;
    options.max_rects = 20;
    auto layout = dafree::treemap_layout(tree, 1, 100, 100, options);
    bool other = false;
    for (std::size_t i = 0; i < layout.rects().size(); ++i) {
        if ((layout.rects()[i].flags & dafree::kTmOther) != 0) {
            other = true;
            CHECK(layout.rects()[i].node == dafree::kNone);
            CHECK(layout.small_items(i) == 3);
            CHECK(layout.hit_test(layout.rects()[i].x + layout.rects()[i].w / 2,
                                  layout.rects()[i].y + layout.rects()[i].h / 2) ==
                  std::optional<NodeId>(1));
        }
    }
    CHECK(other);
}

TEST_CASE("treemap_extreme_sizes_and_tiny_bounds_stay_finite") {
    TreeBuilder builder({"/extreme"});
    builder.add_children(
        1, std::array{TreeBuilder::NewNode{
                          "huge.bin", 0, std::numeric_limits<std::uint64_t>::max(), 1, 0, 0, 0, {}},
                      TreeBuilder::NewNode{"tiny.bin", 0, 1, 1, 0, 0, 0, {}}});
    auto tree = std::move(builder).finish({});
    TreemapOptions options;
    options.max_depth = 1;
    options.min_px = 0;
    options.padding = 0;
    options.max_rects = 10;
    for (const auto &[w, h] :
         {std::pair{0.001F, 0.001F}, {0.25F, 0.125F}, {10'000'000.0F, 0.01F}}) {
        const auto layout = dafree::treemap_layout(tree, 1, w, h, options);
        const auto rects = layout.rects();
        REQUIRE(rects.size() == 3);
        for (const auto &r : rects) {
            CHECK(std::isfinite(r.x));
            CHECK(std::isfinite(r.y));
            CHECK(std::isfinite(r.w));
            CHECK(std::isfinite(r.h));
            CHECK(r.x >= 0.0F);
            CHECK(r.y >= 0.0F);
            CHECK(r.w >= 0.0F);
            CHECK(r.h >= 0.0F);
            CHECK(r.x + r.w <= w + 0.01F);
            CHECK(r.y + r.h <= h + 0.01F);
        }
    }
}

TEST_CASE("treemap_render_palette_and_modes") {
    TreeBuilder builder({"/render"});
    builder.add_children(1,
                         std::array{TreeBuilder::NewNode{"photo.png", 0, 100, 100, 0, 0, 0, {}}});
    auto tree = std::move(builder).finish({});
    TreemapOptions options;
    options.max_depth = 1;
    options.min_px = 0;
    options.padding = 0;
    auto layout = dafree::treemap_layout(tree, 1, 64, 64, options);
    dafree::Palette palette;
    palette.by_class.fill(0x112233FFu);
    palette.dir_by_depth.fill(0xA0B0C0FFu);
    palette.background = 0x010203FFu;
    palette.border = 0xFF0000FFu;
    const auto flat = dafree::treemap_render(layout, 64, 64, palette, false);
    const auto flat_again = dafree::treemap_render(layout, 64, 64, palette, false);
    const auto cushion = dafree::treemap_render(layout, 64, 64, palette, true);
    REQUIRE(flat.size() == 64u * 64u * 4u);
    CHECK(flat == flat_again);
    const auto center = (32u * 64u + 32u) * 4u;
    CHECK(flat[center] == 0x11);
    CHECK(flat[center + 1] == 0x22);
    CHECK(flat[center + 2] == 0x33);
    CHECK(flat[center + 3] == 0xFF);
    CHECK(flat[0] == 0xFF);
    CHECK(flat[1] == 0x00);
    CHECK(flat[2] == 0x00);
    CHECK(flat[3] == 0xFF);
    CHECK(flat != cushion);
    CHECK(cushion[3] == 0xFF);
    const auto clipped = dafree::treemap_render(layout, 70, 66, palette, false);
    CHECK(clipped.size() == 70u * 66u * 4u);
    const auto outside = (65u * 70u + 65u) * 4u;
    CHECK(clipped[outside] == 0x01);
    CHECK(clipped[outside + 1] == 0x02);
    CHECK(clipped[outside + 2] == 0x03);
    CHECK(clipped[outside + 3] == 0xFF);
    CHECK_THROWS_AS(static_cast<void>(dafree::treemap_render(layout, -1, 2, palette, false)),
                    std::invalid_argument);
    CHECK_THROWS_AS(
        static_cast<void>(dafree::treemap_render(layout, std::numeric_limits<int>::max(),
                                                 std::numeric_limits<int>::max(), palette, false)),
        std::length_error);
}

TEST_CASE("treemap_directory_shading_changes_with_hierarchy") {
    TreeBuilder builder({"/shade"});
    const auto [dir, end] = builder.add_children(
        1, std::array{TreeBuilder::NewNode{"folder", dafree::kDir, 0, 0, 0, 0, 0, {}},
                      TreeBuilder::NewNode{"root.bin", 0, 20, 20, 0, 0, 0, {}}});
    builder.add_children(dir, std::array{TreeBuilder::NewNode{"file.bin", 0, 20, 20, 0, 0, 0, {}}});
    auto tree = std::move(builder).finish({});
    TreemapOptions options;
    options.max_depth = 2;
    options.min_px = 0;
    options.padding = 0;
    auto layout = dafree::treemap_layout(tree, 1, 100, 100, options);
    dafree::Palette palette;
    palette.by_class.fill(0x778899FFu);
    palette.dir_by_depth.fill(0x778899FFu);
    const auto image = dafree::treemap_render(layout, 100, 100, palette, true);
    const auto flat = dafree::treemap_render(layout, 100, 100, palette, false);
    CHECK(end == dir + 2);
    CHECK(image.size() == 40'000);
    CHECK(image != flat);
    const dafree::TmRect *nested_file = nullptr;
    const dafree::TmRect *root_file = nullptr;
    for (const auto &rect : layout.rects()) {
        if (rect.node == dir + 1)
            nested_file = &rect;
        if (rect.node == dir + 2)
            root_file = &rect;
    }
    REQUIRE(nested_file != nullptr);
    REQUIRE(root_file != nullptr);
    const auto nested_x = static_cast<std::size_t>(nested_file->x + nested_file->w / 2);
    const auto nested_y = static_cast<std::size_t>(nested_file->y + nested_file->h / 2);
    const auto root_x = static_cast<std::size_t>(root_file->x + root_file->w / 2);
    const auto root_y = static_cast<std::size_t>(root_file->y + root_file->h / 2);
    const auto nested_pixel = (nested_y * 100 + nested_x) * 4;
    const auto root_pixel = (root_y * 100 + root_x) * 4;
    CHECK((image[nested_pixel] != image[root_pixel] ||
           image[nested_pixel + 1] != image[root_pixel + 1] ||
           image[nested_pixel + 2] != image[root_pixel + 2]));
}
