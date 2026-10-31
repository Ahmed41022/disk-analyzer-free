#pragma once

#include <cstdint>

namespace dafree::platform::detail {

// Linux's stable statx UAPI value, absent from manylinux_2_28's older headers.
// https://github.com/torvalds/linux/blob/master/include/uapi/linux/stat.h
inline constexpr std::uint64_t kStatxMountRoot = 0x00002000;

/// Interpret the mount-root attribute only when the kernel reports it supported.
constexpr bool statx_is_mount_root(std::uint64_t attributes, std::uint64_t supported) noexcept {
    return (attributes & supported & kStatxMountRoot) != 0;
}

} // namespace dafree::platform::detail
