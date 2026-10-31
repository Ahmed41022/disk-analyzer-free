#pragma once

#include <cstddef>

namespace dafree::testing {

/// Requested C++ heap bytes and successful allocation calls, excluding harness bookkeeping.
struct AllocationSnapshot {
    std::size_t live, peak, calls;
};

/// Reset the high-water mark to current live allocations before an isolated measurement.
void reset_allocation_peak() noexcept;
/// Read live requested bytes and their high-water mark without allocating.
AllocationSnapshot allocations() noexcept;

} // namespace dafree::testing
