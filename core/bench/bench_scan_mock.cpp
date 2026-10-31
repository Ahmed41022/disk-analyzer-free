#include "../src/testing/mock_tree.hpp"
#include "dafree/scan.hpp"

#include <benchmark/benchmark.h>

namespace {

void BM_ScanMock(benchmark::State &state) {
    const auto nodes = static_cast<std::uint32_t>(state.range(0));
    auto spec = dafree::testing::mock_tree(nodes);
    dafree::ScanOptions options;
    options.targets = {spec.entries.front().path};
    options.threads = 4;
    auto backend = dafree::make_mock_backend(std::move(spec));
    for (auto _ : state) {
        (void)_;
        auto handle = dafree::start_scan(options, backend);
        if (!handle.wait(std::chrono::minutes(2))) {
            handle.cancel();
            state.SkipWithError("mock scan timed out");
            break;
        }
        auto result = handle.take_result();
        auto bytes = result.tree->node(dafree::kRoot).size;
        benchmark::DoNotOptimize(bytes);
    }
    state.SetItemsProcessed(static_cast<std::int64_t>(state.iterations()) * nodes);
}

BENCHMARK(BM_ScanMock)
    ->Arg(10'000)
    ->Arg(100'000)
    ->Arg(1'000'000)
    ->UseRealTime()
    ->Unit(benchmark::kMillisecond);

} // namespace
