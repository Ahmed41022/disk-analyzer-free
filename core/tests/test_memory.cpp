#include "../src/testing/counting_alloc.hpp"
#include "../src/testing/mock_tree.hpp"
#include "dafree/scan.hpp"

#include <doctest/doctest.h>

#include <array>
#include <chrono>
#include <new>

namespace {

struct Measurement {
    std::size_t nodes, steady, peak;
};

Measurement measure() {
    constexpr std::uint32_t nodes = 1'000'000;
    auto spec = dafree::testing::mock_tree(nodes);
    const auto root = spec.entries.front().path;
    // Backend input represents the filesystem, and remains alive throughout the measurement.
    auto backend = dafree::make_mock_backend(std::move(spec));
    const auto baseline = dafree::testing::allocations().live;
    dafree::testing::reset_allocation_peak();
    dafree::ScanResult result;
    {
        dafree::ScanOptions options;
        options.targets = {root};
        options.threads = 4;
        auto handle = dafree::start_scan(std::move(options), backend);
        if (!handle.wait(std::chrono::minutes(2))) {
            const auto progress = handle.progress();
            handle.cancel();
            throw std::runtime_error(
                "million-node mock scan timed out after files=" + std::to_string(progress.files) +
                ", dirs=" + std::to_string(progress.dirs));
        }
        result = handle.take_result();
    }
    const auto snapshot = dafree::testing::allocations();
    REQUIRE(result.tree->size() == nodes);
    REQUIRE(snapshot.live >= baseline);
    REQUIRE(snapshot.peak >= baseline);
    return {nodes, snapshot.live - baseline, snapshot.peak - baseline};
}

} // namespace

TEST_CASE("counting_allocator_handles_alignment_and_arrays") {
    const auto before = dafree::testing::allocations().live;
    constexpr std::size_t bytes = 257, alignment = 128;
    void *memory = ::operator new[](bytes, std::align_val_t(alignment));
    const auto during = dafree::testing::allocations().live;
    CHECK(reinterpret_cast<std::uintptr_t>(memory) % alignment == 0);
    CHECK(during == before + bytes);
    ::operator delete[](memory, std::align_val_t(alignment));
    CHECK(dafree::testing::allocations().live == before);
}

TEST_CASE("builder_small_batches_reuse_allocations") {
    constexpr std::uint32_t batches = 20'000;
    constexpr std::size_t allocation_limit = 64;
    dafree::TreeBuilder builder({"/root"});
    const std::array child{dafree::TreeBuilder::NewNode{"child", dafree::kDir, 0, 0, 0, 0, 0, {}}};
    const auto before = dafree::testing::allocations().calls;
    dafree::NodeId parent = 1;
    for (std::uint32_t i = 0; i < batches; ++i)
        parent = builder.add_children(parent, child).first;
    const auto allocations = dafree::testing::allocations().calls - before;
    INFO("allocations while appending one child per directory: ", allocations);
    CHECK(allocations <= allocation_limit);
    auto tree = std::move(builder).finish({});
    CHECK(tree.size() == batches + 2);
    CHECK(tree.counts(1).dirs == batches);
}

TEST_CASE("memory_per_node_steady_le_100") {
    const auto result = measure();
    const auto bytes = static_cast<double>(result.steady) / static_cast<double>(result.nodes);
    MESSAGE("steady bytes/node: ", bytes);
    CHECK(bytes <= 100.0);
}

TEST_CASE("memory_per_node_peak_le_140") {
    const auto result = measure();
    const auto bytes = static_cast<double>(result.peak) / static_cast<double>(result.nodes);
    MESSAGE("peak bytes/node: ", bytes);
    CHECK(bytes <= 140.0);
}
