#include "internal.hpp"

#include <psapi.h>

namespace dafree::platform {

std::optional<std::uint64_t> peak_rss() {
    PROCESS_MEMORY_COUNTERS counters{};
    counters.cb = static_cast<DWORD>(sizeof(counters));
    if (!::GetProcessMemoryInfo(::GetCurrentProcess(), &counters, counters.cb))
        return std::nullopt;
    return static_cast<std::uint64_t>(counters.PeakWorkingSetSize);
}

} // namespace dafree::platform
