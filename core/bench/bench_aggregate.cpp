#include "dafree/model.hpp"

#include <benchmark/benchmark.h>

#include <cstdint>

namespace {

void BM_Aggregate(benchmark::State &state) {
    const auto count = static_cast<std::uint32_t>(state.range(0));
    dafree::SegVector<dafree::Node> nodes;
    dafree::SegVector<dafree::Counts> counts;
    dafree::Node root;
    root.flags = static_cast<std::uint16_t>(dafree::kDir | dafree::kSynthetic);
    nodes.push_back(root);
    counts.push_back({});
    for (std::uint32_t id = 0; id < count; ++id) {
        dafree::Node file;
        file.parent = dafree::kRoot;
        file.size = id % 4096 + 1;
        file.alloc = id % 4096 + 1;
        nodes.push_back(file);
        counts.push_back({});
    }

    for (auto _ : state) {
        (void)_;
        dafree::aggregate(nodes, counts);
    }
    state.SetItemsProcessed(static_cast<std::int64_t>(state.iterations()) * count);
}

BENCHMARK(BM_Aggregate)->Arg(10'000'000);

} // namespace

BENCHMARK_MAIN();
