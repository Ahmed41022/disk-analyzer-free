#include "dafree/model.hpp"

#include "unicode_fold_table.hpp"

#include <algorithm>
#include <stdexcept>

namespace dafree {
namespace {

#if defined(_WIN32) || defined(__APPLE__)
char32_t simple_fold(char32_t codepoint) noexcept {
    if (codepoint > 0xFFFF) {
        return codepoint;
    }
    const auto found = std::lower_bound(
        detail::kSimpleFoldPairs.begin(), detail::kSimpleFoldPairs.end(), codepoint,
        [](const detail::SimpleFoldPair &pair, char32_t value) { return pair.source < value; });
    return found != detail::kSimpleFoldPairs.end() && found->source == codepoint ? found->target
                                                                                 : codepoint;
}

void append_utf8(std::string &output, char32_t codepoint) {
    if (codepoint <= 0x7F) {
        output.push_back(static_cast<char>(codepoint));
    } else if (codepoint <= 0x7FF) {
        output.push_back(static_cast<char>(0xC0 | (codepoint >> 6)));
        output.push_back(static_cast<char>(0x80 | (codepoint & 0x3F)));
    } else if (codepoint <= 0xFFFF) {
        output.push_back(static_cast<char>(0xE0 | (codepoint >> 12)));
        output.push_back(static_cast<char>(0x80 | ((codepoint >> 6) & 0x3F)));
        output.push_back(static_cast<char>(0x80 | (codepoint & 0x3F)));
    } else {
        output.push_back(static_cast<char>(0xF0 | (codepoint >> 18)));
        output.push_back(static_cast<char>(0x80 | ((codepoint >> 12) & 0x3F)));
        output.push_back(static_cast<char>(0x80 | ((codepoint >> 6) & 0x3F)));
        output.push_back(static_cast<char>(0x80 | (codepoint & 0x3F)));
    }
}
#endif

std::string normalized_path(std::string_view path) {
#ifdef _WIN32
    constexpr char separator = '\\';
#else
    constexpr char separator = '/';
#endif
    std::string normalized;
    normalized.reserve(path.size());
    bool previous_separator = false;
    for (const char byte : path) {
        const bool is_separator = byte == '/' || byte == '\\';
        if (is_separator) {
            if (!previous_separator) {
                normalized.push_back(separator);
            }
            previous_separator = true;
        } else {
            normalized.push_back(byte);
            previous_separator = false;
        }
    }
    if (normalized.size() > 1 && normalized.back() == separator) {
        normalized.pop_back();
    }

#if defined(_WIN32) || defined(__APPLE__)
    std::string folded;
    folded.reserve(normalized.size());
    for (std::size_t offset = 0; offset < normalized.size();) {
        const auto first = static_cast<unsigned char>(normalized[offset]);
        char32_t codepoint = 0;
        std::size_t length = 0;
        if (first <= 0x7F) {
            codepoint = first;
            length = 1;
        } else if (first >= 0xC2 && first <= 0xDF) {
            codepoint = first & 0x1F;
            length = 2;
        } else if (first >= 0xE0 && first <= 0xEF) {
            codepoint = first & 0x0F;
            length = 3;
        } else if (first >= 0xF0 && first <= 0xF4) {
            codepoint = first & 0x07;
            length = 4;
        } else {
            folded.push_back(normalized[offset++]);
            continue;
        }
        if (normalized.size() - offset < length) {
            folded.push_back(normalized[offset++]);
            continue;
        }
        bool valid = true;
        for (std::size_t index = 1; index < length; ++index) {
            const auto continuation = static_cast<unsigned char>(normalized[offset + index]);
            if ((continuation & 0xC0) != 0x80) {
                valid = false;
                break;
            }
            codepoint = (codepoint << 6) | (continuation & 0x3F);
        }
        if (!valid || (length == 3 && codepoint < 0x800) || (length == 4 && codepoint < 0x10000) ||
            (codepoint >= 0xD800 && codepoint <= 0xDFFF) || codepoint > 0x10FFFF) {
            folded.push_back(normalized[offset++]);
            continue;
        }
        append_utf8(folded, simple_fold(codepoint));
        offset += length;
    }
    return folded;
#else
    return normalized;
#endif
}

} // namespace

std::uint32_t Tree::size() const noexcept { return nodes_.size(); }

const Node &Tree::node(NodeId id) const {
    if (id >= nodes_.size()) {
        throw std::out_of_range("tree node ID is out of range");
    }
    return nodes_[id];
}

Counts Tree::counts(NodeId id) const {
    if (id >= counts_.size()) {
        throw std::out_of_range("tree node ID is out of range");
    }
    return counts_[id];
}

std::string_view Tree::name_bytes(NodeId id) const {
    const auto &entry = node(id);
    if (id == kRoot) {
        return {};
    }
    return names_.get(entry.name_off, entry.name_len);
}

std::optional<std::string_view> Tree::ext(NodeId id) const {
    const auto extension_id = node(id).ext_id;
    if (extension_id == 0) {
        return std::nullopt;
    }
    return exts_.get(extension_id);
}

std::optional<std::string_view> Tree::owner_name(NodeId id) const {
    const auto owner_id = node(id).owner;
    if (owner_id == 0) {
        return std::nullopt;
    }
    return owners_.get(owner_id);
}

std::pair<NodeId, NodeId> Tree::children(NodeId id) const {
    const auto &entry = node(id);
    if (entry.child_count == 0) {
        return {kNone, kNone};
    }
    return {entry.first_child, entry.first_child + entry.child_count};
}

std::optional<NodeId> Tree::parent(NodeId id) const {
    const auto parent_id = node(id).parent;
    if (parent_id == kNone) {
        return std::nullopt;
    }
    return parent_id;
}

std::string Tree::path_bytes(NodeId id) const {
    if (id == kRoot) {
        return {};
    }
    const auto &entry = node(id);
    const auto name = name_bytes(id);
    if (entry.parent == kRoot) {
        return std::string(name);
    }
    auto path = path_bytes(entry.parent);
#ifdef _WIN32
    constexpr char separator = '\\';
#else
    constexpr char separator = '/';
#endif
    if (!path.empty() && path.back() != separator && path.back() != '/') {
        path.push_back(separator);
    }
    path.append(name);
    return path;
}

std::uint16_t Tree::depth(NodeId id) const {
    const auto &entry = node(id);
    if (entry.parent == kNone || entry.parent == kRoot) {
        return 0;
    }
    const auto parent_depth = depth(entry.parent);
    if (parent_depth == std::numeric_limits<std::uint16_t>::max()) {
        throw CapacityError();
    }
    return static_cast<std::uint16_t>(parent_depth + 1);
}

std::optional<NodeId> Tree::find_path(std::string_view native_path) const {
    const auto target = normalized_path(native_path);
    for (NodeId id = 1; id < nodes_.size(); ++id) {
        if (normalized_path(path_bytes(id)) == target) {
            return id;
        }
    }
    return std::nullopt;
}

std::span<const NodeId> Tree::roots() const { return roots_; }

MemoryReport Tree::memory_usage() const {
    std::size_t roots_bytes =
        roots_.capacity() * sizeof(NodeId) + root_paths_.capacity() * sizeof(std::string);
    for (const auto &path : root_paths_) {
        roots_bytes += path.capacity();
    }
    return {nodes_.heap_bytes(), counts_.heap_bytes(), names_.heap_bytes(),
            exts_.heap_bytes() + owners_.heap_bytes() + roots_bytes};
}

void Tree::set_owner(NodeId id, OwnerKey key, std::string_view display) {
    (void)node(id);
    nodes_[id].owner = owners_.intern(key, display);
}

const ScanMeta &Tree::meta() const noexcept { return meta_; }

} // namespace dafree
