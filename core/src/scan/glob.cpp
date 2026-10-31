#include "glob.hpp"
#include "../model/unicode_fold_table.hpp"
#include "dafree/scan.hpp"

#include <algorithm>
#include <array>
#include <cstdint>

namespace dafree::detail {

char32_t next_codepoint(std::string_view input, std::size_t &offset) noexcept {
    const auto first = static_cast<unsigned char>(input[offset]);
    if (first < 0x80u) {
        ++offset;
        return first;
    }
    unsigned count = 0;
    char32_t value = 0, minimum = 0;
    if (first >= 0xC2u && first <= 0xDFu) {
        count = 2;
        value = first & 31u;
        minimum = 0x80;
    } else if (first >= 0xE0u && first <= 0xEFu) {
        count = 3;
        value = first & 15u;
        minimum = 0x800;
    } else if (first >= 0xF0u && first <= 0xF4u) {
        count = 4;
        value = first & 7u;
        minimum = 0x10000;
    }
    if (count != 0 && input.size() - offset >= count) {
        bool valid = true;
        for (unsigned index = 1; index < count; ++index) {
            const auto next = static_cast<unsigned char>(input[offset + index]);
            if ((next & 0xC0u) != 0x80u) {
                valid = false;
                break;
            }
            value = (value << 6u) | (next & 0x3Fu);
        }
        if (valid && value >= minimum && value <= 0x10FFFFu) {
            offset += count;
            return value;
        }
    }
    ++offset;
    return 0x110000u + first;
}

char32_t fold_codepoint(char32_t value) noexcept {
    if (value > 0xFFFFu)
        return value;
    const auto found = std::lower_bound(
        kSimpleFoldPairs.begin(), kSimpleFoldPairs.end(), value,
        [](const SimpleFoldPair &pair, char32_t target) { return pair.source < target; });
    return found != kSimpleFoldPairs.end() && found->source == value ? found->target : value;
}

CompiledGlob CompiledGlob::compile(std::string_view pattern, bool ignore_case) {
    CompiledGlob result;
    result.ignore_case_ = ignore_case;
    const auto fail = [&](const std::string &message) {
        throw ExcludeError(std::string(pattern), message);
    };
    if (pattern.find('\0') != std::string_view::npos)
        fail("glob contains NUL");
    const auto literal = [&](std::size_t &offset) {
        if (pattern[offset] == '\\') {
            ++offset;
            if (offset == pattern.size())
                fail("dangling glob escape");
        }
        const auto value = next_codepoint(pattern, offset);
        return ignore_case ? fold_codepoint(value) : value;
    };
    for (std::size_t offset = 0; offset < pattern.size();) {
        const char character = pattern[offset];
        if (character == '*') {
            std::size_t count = 0;
            while (offset < pattern.size() && pattern[offset] == '*') {
                ++offset;
                ++count;
            }
            Kind kind = count == 1 ? Kind::Star : Kind::GlobStar;
            if (count > 1 && offset < pattern.size() && pattern[offset] == '/') {
                ++offset;
                kind = Kind::DirStar;
            }
            result.tokens_.push_back({kind, 0, false, {}});
        } else if (character == '?') {
            ++offset;
            result.tokens_.push_back({Kind::Any, 0, false, {}});
        } else if (character == '[') {
            ++offset;
            Token token{Kind::Class, 0, false, {}};
            if (offset < pattern.size() && (pattern[offset] == '!' || pattern[offset] == '^')) {
                token.negated = true;
                ++offset;
            }
            while (offset < pattern.size() && pattern[offset] != ']') {
                const auto low = literal(offset);
                auto high = low;
                if (offset + 1 < pattern.size() && pattern[offset] == '-' &&
                    pattern[offset + 1] != ']') {
                    ++offset;
                    high = literal(offset);
                    if (low > high)
                        fail("descending glob character range");
                }
                token.ranges.emplace_back(low, high);
            }
            if (offset == pattern.size())
                fail("unterminated glob character class");
            if (token.ranges.empty())
                fail("empty glob character class");
            ++offset;
            result.tokens_.push_back(std::move(token));
        } else {
            result.tokens_.push_back({Kind::Literal, literal(offset), false, {}});
        }
    }
    return result;
}

bool CompiledGlob::matches(std::string_view input, bool windows_path) const {
    constexpr std::size_t stack_capacity = 257;
    std::array<std::uint8_t, stack_capacity> stack_current{}, stack_next{};
    const std::size_t states = tokens_.size() + 1;
    std::vector<std::uint8_t> heap_current, heap_next;
    if (states > stack_capacity) {
        heap_current.resize(states);
        heap_next.resize(states);
    }
    auto *current = states <= stack_capacity ? stack_current.data() : heap_current.data();
    auto *next = states <= stack_capacity ? stack_next.data() : heap_next.data();
    const auto closure = [&](std::uint8_t *active, bool boundary) {
        for (std::size_t index = 0; index < tokens_.size(); ++index) {
            const auto kind = tokens_[index].kind;
            if (active[index] && (kind == Kind::Star || kind == Kind::GlobStar ||
                                  (kind == Kind::DirStar && boundary)))
                active[index + 1] = 1;
        }
    };
    current[0] = 1;
    closure(current, true);
    for (std::size_t offset = 0; offset < input.size();) {
        auto value = next_codepoint(input, offset);
        if (windows_path && value == '\\')
            value = '/';
        const bool separator = value == '/';
        if (ignore_case_)
            value = fold_codepoint(value);
        std::fill_n(next, states, std::uint8_t{0});
        for (std::size_t index = 0; index < tokens_.size(); ++index) {
            if (!current[index])
                continue;
            const auto &token = tokens_[index];
            switch (token.kind) {
            case Kind::Literal:
                if (token.value == value)
                    next[index + 1] = 1;
                break;
            case Kind::Any:
                if (!separator)
                    next[index + 1] = 1;
                break;
            case Kind::Star:
                if (!separator)
                    next[index] = 1;
                break;
            case Kind::GlobStar:
            case Kind::DirStar:
                next[index] = 1;
                break;
            case Kind::Class: {
                bool member = false;
                for (const auto &[low, high] : token.ranges)
                    member = member || (value >= low && value <= high);
                if (!separator && member != token.negated)
                    next[index + 1] = 1;
                break;
            }
            }
        }
        closure(next, separator);
        std::swap(current, next);
    }
    return current[tokens_.size()] != 0;
}

} // namespace dafree::detail
