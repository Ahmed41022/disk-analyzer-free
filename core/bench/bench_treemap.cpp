#include "dafree/treemap.hpp"

#include <benchmark/benchmark.h>

#include <algorithm>
#include <array>
#include <charconv>
#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

namespace {

struct Fixture {
    dafree::Tree tree;
    dafree::Palette palette;
};

Fixture make_fixture() {
    constexpr std::uint32_t count = 49'999; // Plus the selected root: exactly 50,000 nodes.
    dafree::TreeBuilder builder({"/bench"});
    std::vector<std::array<char, 24>> names(count);
    std::vector<dafree::TreeBuilder::NewNode> entries;
    entries.reserve(count);
    for (std::uint32_t i = 0; i < count; ++i) {
        auto &buffer = names[i];
        const auto prefix = std::string_view("file");
        std::copy(prefix.begin(), prefix.end(), buffer.begin());
        auto *end = std::to_chars(buffer.data() + prefix.size(), buffer.data() + 18, i).ptr;
        const auto ext = std::string_view(".bin");
        std::copy(ext.begin(), ext.end(), end);
        const auto length = static_cast<std::size_t>(end + ext.size() - buffer.data());
        const auto size = (static_cast<std::uint64_t>(i) * 48'271u) % 100'003u + 1u;
        entries.push_back({std::string_view(buffer.data(), length), 0, size, size, 0, 0, 0, {}});
    }
    builder.add_children(1, entries);
    auto tree = std::move(builder).finish({});
    dafree::Palette palette;
    for (std::size_t i = 0; i < palette.by_class.size(); ++i)
        palette.by_class[i] =
            static_cast<std::uint32_t>(0x204060FFu + static_cast<std::uint32_t>(i) * 0x00030700u);
    for (std::size_t i = 0; i < palette.dir_by_depth.size(); ++i)
        palette.dir_by_depth[i] =
            static_cast<std::uint32_t>(0x607080FFu + static_cast<std::uint32_t>(i) * 0x00020100u);
    palette.background = 0x101010FFu;
    palette.border = 0x000000FFu;
    return {std::move(tree), palette};
}

void BM_Layout50k(benchmark::State &state) {
    auto fixture = make_fixture();
    dafree::TreemapOptions options;
    options.max_depth = 1;
    options.min_px = 0;
    options.padding = 0;
    options.max_rects = 50'000;
    if (fixture.tree.size() != 50'001) {
        state.SkipWithError("50k fixture has an unexpected node count");
        return;
    }
    for (auto _ : state) {
        (void)_;
        auto layout = dafree::treemap_layout(fixture.tree, 1, 1920, 1080, options);
        benchmark::DoNotOptimize(layout.rects().data());
        if (layout.rects().size() != 50'000)
            state.SkipWithError("layout did not return the guarded 50,000 rectangles");
    }
}

void BM_Render1920x1080Cushion(benchmark::State &state) {
    auto fixture = make_fixture();
    dafree::TreemapOptions options;
    options.max_depth = 1;
    options.min_px = 0;
    options.padding = 0;
    options.max_rects = 50'000;
    auto layout = dafree::treemap_layout(fixture.tree, 1, 1920, 1080, options);
    if (layout.rects().size() != 50'000) {
        state.SkipWithError("render fixture must have 50,000 rectangles");
        return;
    }
    constexpr std::size_t expected = 1920u * 1080u * 4u;
    for (auto _ : state) {
        (void)_;
        auto rgba = dafree::treemap_render(layout, 1920, 1080, fixture.palette, true);
        benchmark::DoNotOptimize(rgba.data());
        if (rgba.size() != expected)
            state.SkipWithError("render returned an unexpected RGBA byte count");
    }
}

BENCHMARK(BM_Layout50k)->UseRealTime()->Unit(benchmark::kMillisecond);
BENCHMARK(BM_Render1920x1080Cushion)->UseRealTime()->Unit(benchmark::kMillisecond);

} // namespace
