#include "dafree/view.hpp"

#include <benchmark/benchmark.h>

#include <algorithm>
#include <array>
#include <charconv>

namespace {

// Stable contiguous name storage avoids millions of temporary string allocations.
std::pair<std::vector<std::array<char, 24>>, std::vector<dafree::TreeBuilder::NewNode>>
files(std::uint32_t count, bool scramble_sizes) {
    std::vector<std::array<char, 24>> names(count);
    std::vector<dafree::TreeBuilder::NewNode> entries;
    entries.reserve(count);
    for (std::uint32_t i = 0; i < count; ++i) {
        auto &buffer = names[i];
        std::copy_n("file", 4, buffer.data());
        auto end = std::to_chars(buffer.data() + 4, buffer.data() + 20, i).ptr;
        std::copy_n(".bin", 4, end);
        const auto length = static_cast<std::size_t>(end + 4 - buffer.data());
        const auto size = scramble_sizes ? ((std::uint64_t{i} * 48271) % count + 1) : count - i;
        entries.push_back({std::string_view(buffer.data(), length), 0, size, size, 0, 0, 0, {}});
    }
    return {std::move(names), std::move(entries)};
}

void BM_Expand100kChildren(benchmark::State &state) {
    dafree::TreeBuilder builder({"/bench"});
    const std::array<dafree::TreeBuilder::NewNode, 1> directory{{
        {"wide", dafree::kDir, 0, 0, 0, 0, 0, {}},
    }};
    builder.add_children(1, directory);
    {
        auto [names, entries] = files(100'000, true);
        builder.add_children(2, entries);
    }
    auto tree = std::make_shared<dafree::Tree>(std::move(builder).finish({}));
    for (auto _ : state) {
        (void)_;
        state.PauseTiming();
        auto view = std::make_unique<dafree::TreeView>(tree, dafree::ViewOptions{});
        state.ResumeTiming();
        auto inserted = view->expand(2); // Cold sibling cache on every iteration.
        benchmark::DoNotOptimize(inserted);
        if (inserted != 100'000)
            state.SkipWithError("cold expansion returned the wrong number of rows");
        state.PauseTiming();
        view.reset();
        state.ResumeTiming();
    }
}

void BM_RowsWindow10M(benchmark::State &state) {
    dafree::TreeBuilder builder({"/bench"});
    {
        // The root is visible too: exactly 10M rows, with a 100-row final window.
        auto [names, entries] = files(9'999'999, false);
        builder.add_children(1, entries);
    }
    auto tree = std::make_shared<dafree::Tree>(std::move(builder).finish({}));
    dafree::TreeView view(tree, {});
    if (view.row_count() != 10'000'000) {
        state.SkipWithError("fixture must have exactly ten million visible rows");
        return;
    }
    for (auto _ : state) {
        (void)_;
        auto rows = view.rows(9'999'900, 100);
        benchmark::DoNotOptimize(rows.data());
        if (rows.size() != 100)
            state.SkipWithError("tail window must contain one hundred rows");
    }
}

BENCHMARK(BM_Expand100kChildren)->UseRealTime()->Unit(benchmark::kMillisecond);
BENCHMARK(BM_RowsWindow10M)->UseRealTime()->Unit(benchmark::kMillisecond);

} // namespace
