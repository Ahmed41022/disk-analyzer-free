#pragma once

#include <cstdint>

namespace dafree {

/// Timestamp selected by filters; analysis algorithms arrive in T2.5.
enum class TimeField { Modified, Created, Accessed };

/// Stable row category IDs; the extension classification table arrives in T2.5.
enum class ExtCategory : std::uint8_t {
    Image,
    Video,
    Audio,
    Archive,
    Document,
    Code,
    Executable,
    DiskImage,
    System,
    Other
};

} // namespace dafree
