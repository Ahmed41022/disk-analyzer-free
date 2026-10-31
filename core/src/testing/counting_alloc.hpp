#pragma once

#include <cstddef>

namespace dafree::testing {

/// Requested C++ heap bytes, excluding the counting harness's own bookkeeping.
struct AllocationSnapshot {
    std::size_t live, peak;
};

/// Reset the high-water mark to current live allocations before an isolated measurement.
void reset_allocation_peak() noexcept;
/// Read live requested bytes and their high-water mark without allocating.
AllocationSnapshot allocations() noexcept;

} // namespace dafree::testing
