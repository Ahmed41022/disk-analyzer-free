#pragma once

#include "dafree/backend.hpp"

#include <stdexcept>

namespace dafree::testing {

/// Build balanced virtual input: 8–40 byte names, ten children per directory, 10% directories.
inline MockSpec mock_tree(std::uint32_t nodes) {
    if (nodes < 12)
        throw std::invalid_argument("mock tree needs at least twelve nodes");
    MockSpec spec;
    const auto entries = nodes - 1; // Synthetic tree root is not a backend entry.
    const auto directories = (entries + 9) / 10;
    spec.entries.reserve(entries);
    RawEntry root;
    root.kind = EntryKind::Dir;
    root.dev = root.ino_lo = 1;
    spec.entries.push_back({platform::windows_paths() ? "C:/memory-tree" : "/memory-tree", root});
    for (std::uint32_t id = 1; id < entries; ++id) {
        RawEntry entry;
        entry.kind = id < directories ? EntryKind::Dir : EntryKind::File;
        entry.dev = 1;
        entry.ino_lo = id + 1;
        entry.nlink = 1;
        entry.name = "n" + std::to_string(id);
        const auto length = static_cast<std::size_t>(8 + id % 33);
        const auto has_extension = entry.kind == EntryKind::File && length >= entry.name.size() + 4;
        const auto suffix = has_extension ? ".dat" : "";
        const auto suffix_length = has_extension ? 4u : 0u;
        entry.name.append(length - entry.name.size() - suffix_length,
                          static_cast<char>('a' + id % 26));
        entry.name += suffix;
        if (entry.kind == EntryKind::File) {
            entry.size = (static_cast<std::uint64_t>(id) * 37) % 65'536;
            entry.alloc = ((entry.size + 4095) / 4096) * 4096;
        }
        const auto path = spec.entries[(id - 1) / 10].path + "/" + entry.name;
        spec.entries.push_back({path, std::move(entry)});
    }
    return spec;
}

} // namespace dafree::testing
