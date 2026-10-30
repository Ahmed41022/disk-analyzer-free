#include "dafree/model.hpp"

#include "unicode_fold_table.hpp"

#include <algorithm>
#include <functional>
#include <limits>
#include <stdexcept>

namespace dafree {
namespace {

bool decode_utf8(std::string_view input, std::size_t offset, char32_t &codepoint,
                 std::size_t &length) noexcept {
    const auto first = static_cast<unsigned char>(input[offset]);
    if (first <= 0x7F) {
        codepoint = first;
        length = 1;
        return true;
    }

    if (first >= 0xC2 && first <= 0xDF) {
        length = 2;
        codepoint = first & 0x1F;
    } else if (first >= 0xE0 && first <= 0xEF) {
        length = 3;
        codepoint = first & 0x0F;
    } else if (first >= 0xF0 && first <= 0xF4) {
        length = 4;
        codepoint = first & 0x07;
    } else {
        return false;
    }

    if (input.size() - offset < length) {
        return false;
    }
    for (std::size_t i = 1; i < length; ++i) {
        const auto byte = static_cast<unsigned char>(input[offset + i]);
        if ((byte & 0xC0) != 0x80) {
            return false;
        }
        codepoint = (codepoint << 6) | (byte & 0x3F);
    }
    if ((length == 3 && codepoint < 0x800) || (length == 4 && codepoint < 0x10000) ||
        (codepoint >= 0xD800 && codepoint <= 0xDFFF) || codepoint > 0x10FFFF) {
        return false;
    }
    return true;
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

bool is_space(char32_t codepoint) noexcept {
    return (codepoint >= 0x0009 && codepoint <= 0x000D) || codepoint == 0x0020 ||
           codepoint == 0x0085 || codepoint == 0x00A0 || codepoint == 0x1680 ||
           (codepoint >= 0x2000 && codepoint <= 0x200A) || codepoint == 0x2028 ||
           codepoint == 0x2029 || codepoint == 0x202F || codepoint == 0x205F || codepoint == 0x3000;
}

std::string folded_extension(std::string_view extension, bool &has_space) {
    std::string folded;
    folded.reserve(extension.size());
    has_space = false;
    for (std::size_t offset = 0; offset < extension.size();) {
        char32_t codepoint = 0;
        std::size_t length = 0;
        if (!decode_utf8(extension, offset, codepoint, length)) {
            folded.push_back(extension[offset]);
            ++offset;
            continue;
        }
        has_space = has_space || is_space(codepoint);
        append_utf8(folded, simple_fold(codepoint));
        offset += length;
    }
    return folded;
}

std::size_t combine_hash(std::size_t seed, std::size_t value) noexcept {
    return seed ^ (value + static_cast<std::size_t>(0x9E3779B9) + (seed << 6) + (seed >> 2));
}

} // namespace

ExtInterner::ExtInterner() {
    extensions_.emplace_back();
    ids_.emplace(std::string{}, 0);
}

std::uint32_t ExtInterner::intern(std::string_view filename, bool is_directory) {
    if (is_directory) {
        return 0;
    }
    const auto dot = filename.rfind('.');
    if (dot == std::string_view::npos || dot == 0 || dot + 1 == filename.size()) {
        return 0;
    }
    const auto extension = filename.substr(dot + 1);
    if (extension.size() > 16) {
        return 0;
    }
    bool has_space = false;
    auto folded = folded_extension(extension, has_space);
    if (has_space) {
        return 0;
    }
    if (const auto found = ids_.find(folded); found != ids_.end()) {
        return found->second;
    }
    if (extensions_.size() > std::numeric_limits<std::uint32_t>::max()) {
        throw CapacityError();
    }

    const auto id = static_cast<std::uint32_t>(extensions_.size());
    extensions_.push_back(folded);
    try {
        const auto [found, inserted] = ids_.emplace(std::move(folded), id);
        if (!inserted) {
            extensions_.pop_back();
            return found->second;
        }
    } catch (...) {
        extensions_.pop_back();
        throw;
    }
    return id;
}

std::string_view ExtInterner::get(std::uint32_t id) const { return extensions_.at(id); }

std::size_t ExtInterner::heap_bytes() const noexcept {
    std::size_t bytes =
        extensions_.capacity() * sizeof(std::string) + ids_.bucket_count() * sizeof(void *);
    for (const auto &extension : extensions_) {
        bytes += extension.capacity();
    }
    for (const auto &[extension, id] : ids_) {
        (void)id;
        bytes += extension.capacity();
    }
    return bytes;
}

OwnerKey OwnerKey::posix_uid(std::uint32_t owner_uid) { return {Kind::PosixUid, owner_uid, {}}; }

OwnerKey OwnerKey::windows_sid(std::string_view sid_bytes) {
    return {Kind::WindowsSid, 0, std::string(sid_bytes)};
}

OwnerKey OwnerKey::remote(std::string_view remote_key) {
    return {Kind::Remote, 0, std::string(remote_key)};
}

OwnerTable::OwnerTable() { displays_.emplace_back(); }

std::uint32_t OwnerTable::intern(const OwnerKey &key, std::string_view display) {
    if (const auto found = ids_.find(key); found != ids_.end()) {
        return found->second;
    }
    if (displays_.size() > std::numeric_limits<std::uint32_t>::max()) {
        throw CapacityError();
    }

    const auto id = static_cast<std::uint32_t>(displays_.size());
    displays_.emplace_back(display);
    try {
        const auto [found, inserted] = ids_.emplace(key, id);
        if (!inserted) {
            displays_.pop_back();
            return found->second;
        }
    } catch (...) {
        displays_.pop_back();
        throw;
    }
    return id;
}

std::string_view OwnerTable::get(std::uint32_t id) const { return displays_.at(id); }

std::size_t OwnerTable::heap_bytes() const noexcept {
    std::size_t bytes =
        displays_.capacity() * sizeof(std::string) + ids_.bucket_count() * sizeof(void *);
    for (const auto &display : displays_) {
        bytes += display.capacity();
    }
    for (const auto &[key, id] : ids_) {
        (void)id;
        bytes += key.value.capacity();
    }
    return bytes;
}

std::size_t OwnerTable::Hash::operator()(const OwnerKey &key) const noexcept {
    std::size_t seed = std::hash<std::uint8_t>{}(static_cast<std::uint8_t>(key.kind));
    if (key.kind == OwnerKey::Kind::PosixUid) {
        return combine_hash(seed, std::hash<std::uint32_t>{}(key.uid));
    }
    return combine_hash(seed, std::hash<std::string>{}(key.value));
}

} // namespace dafree
