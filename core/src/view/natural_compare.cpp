#include "view_internal.hpp"

#include <algorithm>

namespace dafree::detail {
namespace {

bool digit(char value) noexcept { return value >= '0' && value <= '9'; }

char32_t fold_name(char32_t value) noexcept {
    if (value < 128)
        return value >= U'A' && value <= U'Z' ? value + (U'a' - U'A') : value;
    return fold_codepoint(value);
}

} // namespace

int natural_compare(std::string_view left, std::string_view right) noexcept {
    std::size_t l = 0, r = 0;
    while (l < left.size() && r < right.size()) {
        if (digit(left[l]) && digit(right[r])) {
            const auto begin_l = l, begin_r = r;
            while (l < left.size() && left[l] == '0')
                ++l;
            while (r < right.size() && right[r] == '0')
                ++r;
            const auto significant_l = l, significant_r = r;
            while (l < left.size() && digit(left[l]))
                ++l;
            while (r < right.size() && digit(right[r]))
                ++r;
            const auto len_l = l - significant_l, len_r = r - significant_r;
            if (len_l != len_r)
                return len_l < len_r ? -1 : 1;
            const auto comparison =
                left.substr(significant_l, len_l).compare(right.substr(significant_r, len_r));
            if (comparison != 0)
                return comparison < 0 ? -1 : 1;
            if (l - begin_l != r - begin_r)
                return l - begin_l < r - begin_r ? -1 : 1;
        } else {
            const auto a = fold_name(next_codepoint(left, l));
            const auto b = fold_name(next_codepoint(right, r));
            if (a != b)
                return a < b ? -1 : 1;
        }
    }
    return l == left.size() ? (r == right.size() ? 0 : -1) : 1;
}

} // namespace dafree::detail
