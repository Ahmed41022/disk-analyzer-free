#include "dafree/mft.hpp"

#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <limits>
#include <span>

/// Check decoded-run invariants while leaving unexpected exceptions visible to libFuzzer.
extern "C" int LLVMFuzzerTestOneInput(const std::uint8_t *data, std::size_t size) {
    constexpr std::size_t max_input_bytes = 1024u * 1024u;
    if (size > max_input_bytes)
        return 0;
    const auto input = std::as_bytes(std::span<const std::uint8_t>(data, size));
    const auto decoded = dafree::decode_runlist(input);
    if (!decoded.has_value())
        return 0;
    if (size == 0 || decoded.value().size() > (size - 1) / 2)
        std::abort();
    std::uint64_t total = 0;
    for (const auto &run : decoded.value()) {
        if (run.clusters == 0 || (run.lcn && *run.lcn < 0) ||
            run.clusters > std::numeric_limits<std::uint64_t>::max() - total)
            std::abort();
        total += run.clusters;
    }
    return 0;
}
