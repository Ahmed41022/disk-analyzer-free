#pragma once

#include "dafree/scan.hpp"

#include "../scan/glob.hpp"

#include <algorithm>
#include <array>
#include <chrono>

namespace dafree::io_detail {

inline bool invalid_scalar(char32_t cp) { return cp >= 0x110000 || (cp >= 0xd800 && cp <= 0xdfff); }

inline std::string_view node_type(const Node &node) {
    return (node.flags & kSymlink) ? "symlink" : (node.flags & kDir) ? "directory" : "file";
}

inline std::optional<std::array<char, 20>> iso_time(std::int64_t value) {
    using namespace std::chrono;
    constexpr auto first =
        duration_cast<seconds>(sys_days{year{1} / January / 1}.time_since_epoch()).count();
    constexpr auto end =
        duration_cast<seconds>(sys_days{year{10000} / January / 1}.time_since_epoch()).count();
    if (value == 0 || value < first || value >= end) {
        return std::nullopt;
    }
    const sys_seconds instant{seconds{value}};
    const auto day = floor<days>(instant);
    const year_month_day date{day};
    const hh_mm_ss clock{instant - day};
    std::array<char, 20> buffer{'0', '0', '0', '0', '-', '0', '0', '-', '0', '0',
                                'T', '0', '0', ':', '0', '0', ':', '0', '0', 'Z'};
    const auto digits = [&](std::size_t last_digit, unsigned number, std::size_t count) {
        for (std::size_t i = 0; i < count; ++i) {
            buffer[last_digit - i] = static_cast<char>('0' + number % 10);
            number /= 10;
        }
    };
    digits(3, static_cast<unsigned>(static_cast<int>(date.year())), 4);
    digits(6, static_cast<unsigned>(date.month()), 2);
    digits(9, static_cast<unsigned>(date.day()), 2);
    digits(12, static_cast<unsigned>(clock.hours().count()), 2);
    digits(15, static_cast<unsigned>(clock.minutes().count()), 2);
    digits(18, static_cast<unsigned>(clock.seconds().count()), 2);
    return buffer;
}

constexpr std::array flag_names{
    std::pair{kDir, "dir"},
    std::pair{kSymlink, "symlink"},
    std::pair{kReparse, "reparse"},
    std::pair{kMountPoint, "mount_point"},
    std::pair{kHardlinkDup, "hardlink_dup"},
    std::pair{kHidden, "hidden"},
    std::pair{kSystem, "system"},
    std::pair{kAccessDenied, "access_denied"},
    std::pair{kPartial, "partial"},
    std::pair{kSparse, "sparse"},
    std::pair{kCompressed, "compressed"},
    std::pair{kCloudPlaceholder, "cloud_placeholder"},
    std::pair{kExcluded, "excluded"},
    std::pair{kError, "error"},
    std::pair{kAllocUnreliable, "alloc_unreliable"},
    std::pair{kSynthetic, "synthetic"},
};

inline void path_of(const Tree &tree, NodeId id, std::string &path) {
#ifdef _WIN32
    constexpr char sep = '\\';
#else
    constexpr char sep = '/';
#endif
    // Append backward, then reverse in place, reusing storage for the next row.
    path.clear();
    while (id != kRoot) {
        const auto name = tree.name_bytes(id);
        if (!path.empty() && !name.empty() && name.back() != sep && name.back() != '/')
            path.push_back(sep);
        path.append(name.rbegin(), name.rend());
        id = tree.node(id).parent;
    }
    std::reverse(path.begin(), path.end());
}

inline bool visible(const Node &node, bool include_files) {
    return (node.flags & kExcluded) == 0 && (include_files || (node.flags & kDir) != 0);
}

inline NodeId next_visible(const Tree &tree, NodeId begin, NodeId end, bool include_files) {
    for (auto id = begin; id < end; ++id)
        if (visible(tree.node(id), include_files))
            return id;
    return kNone;
}

inline std::optional<std::string> resolved_owner(TreeHandle &handle, FsBackend &backend,
                                                 NodeId id) {
    const auto pending = handle.read([&](const Tree &tree) {
        const auto value = tree.owner_name(id);
        return value && value->empty();
    });
    if (pending)
        resolve_owners(handle, std::span(&id, 1), backend);
    return handle.read([&](const Tree &tree) -> std::optional<std::string> {
        const auto value = tree.owner_name(id);
        return value && !value->empty() ? std::optional(std::string(*value)) : std::nullopt;
    });
}

} // namespace dafree::io_detail
