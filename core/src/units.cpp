#include "dafree/units.hpp"

#include <array>
#include <cctype>
#include <limits>
#include <stdexcept>

namespace dafree {
namespace {

constexpr std::array<std::string_view, 7> kTraditionalLabels{"B",  "KB", "MB", "GB",
                                                             "TB", "PB", "EB"};
constexpr std::array<std::string_view, 7> kIecLabels{"B", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB"};
constexpr std::array<std::string_view, 7> kSiLabels{"B", "kB", "MB", "GB", "TB", "PB", "EB"};

std::uint64_t scale(std::uint32_t power, std::uint64_t base) {
    std::uint64_t result = 1;
    for (std::uint32_t index = 0; index < power; ++index) {
        result *= base;
    }
    return result;
}

std::string_view trim(std::string_view text) {
    while (!text.empty() && std::isspace(static_cast<unsigned char>(text.front())) != 0) {
        text.remove_prefix(1);
    }
    while (!text.empty() && std::isspace(static_cast<unsigned char>(text.back())) != 0) {
        text.remove_suffix(1);
    }
    return text;
}

char ascii_upper(char value) {
    return value >= 'a' && value <= 'z' ? static_cast<char>(value - 'a' + 'A') : value;
}

} // namespace

std::string format_size(std::uint64_t bytes, UnitMode mode, UnitStyle style) {
    const auto base = style.system == UnitSystem::SI ? std::uint64_t{1000} : std::uint64_t{1024};
    const auto &labels = style.system == UnitSystem::SI
                             ? kSiLabels
                             : (style.system == UnitSystem::IEC ? kIecLabels : kTraditionalLabels);
    std::uint32_t power = 0;
    if (mode == UnitMode::Auto) {
        while (power < 6 && bytes >= scale(power + 1, base)) {
            ++power;
        }
    } else {
        power = static_cast<std::uint32_t>(mode) - 1;
        if (power > 6) {
            throw std::invalid_argument("unsupported unit mode");
        }
    }
    if (power == 0) {
        return std::to_string(bytes) + " B";
    }

    const auto divisor = scale(power, base);
    auto whole = bytes / divisor;
    const auto remainder = bytes % divisor;
    auto tenth = (remainder * 10 + divisor / 2) / divisor;
    if (tenth == 10) {
        ++whole;
        tenth = 0;
    }
    const auto maximum = std::numeric_limits<std::uint64_t>::max();
    const auto fractional_bytes = (divisor / 10) * tenth + ((divisor % 10) * tenth + 5) / 10;
    if (whole > maximum / divisor || fractional_bytes > maximum - whole * divisor) {
        return std::to_string(bytes) + " B";
    }
    return std::to_string(whole) + style.decimal_separator + static_cast<char>('0' + tenth) + " " +
           std::string(labels[power]);
}

std::uint64_t parse_size(std::string_view text, UnitStyle style) {
    text = trim(text);
    if (text.empty() || text.front() == '-') {
        throw std::invalid_argument("size must be non-negative");
    }

    std::size_t offset = 0;
    std::uint64_t whole = 0;
    bool has_digit = false;
    while (offset < text.size() && text[offset] >= '0' && text[offset] <= '9') {
        has_digit = true;
        const auto digit = static_cast<std::uint64_t>(text[offset] - '0');
        if (whole > (std::numeric_limits<std::uint64_t>::max() - digit) / 10) {
            throw std::out_of_range("size overflows 64 bits");
        }
        whole = whole * 10 + digit;
        ++offset;
    }

    std::uint64_t fraction = 0;
    std::uint64_t fraction_scale = 1;
    if (offset < text.size() && text[offset] == style.decimal_separator) {
        ++offset;
        while (offset < text.size() && text[offset] >= '0' && text[offset] <= '9') {
            has_digit = true;
            if (fraction_scale >= 1'000'000'000) {
                throw std::invalid_argument("too many fractional digits");
            }
            fraction = fraction * 10 + static_cast<std::uint64_t>(text[offset] - '0');
            fraction_scale *= 10;
            ++offset;
        }
    }
    if (!has_digit) {
        throw std::invalid_argument("size has no digits");
    }

    const auto suffix = trim(text.substr(offset));
    std::uint32_t power = 0;
    bool binary_suffix = false;
    if (!suffix.empty()) {
        if (suffix.size() == 1 && ascii_upper(suffix.front()) == 'B') {
            power = 0;
        } else {
            constexpr std::string_view prefixes = "KMGTPE";
            const auto found = prefixes.find(ascii_upper(suffix.front()));
            if (found == std::string_view::npos) {
                throw std::invalid_argument("unknown size unit");
            }
            power = static_cast<std::uint32_t>(found + 1);
            std::size_t suffix_offset = 1;
            if (suffix_offset < suffix.size() && ascii_upper(suffix[suffix_offset]) == 'I') {
                binary_suffix = true;
                ++suffix_offset;
            }
            if (suffix_offset < suffix.size() && ascii_upper(suffix[suffix_offset]) == 'B') {
                ++suffix_offset;
            }
            if (suffix_offset != suffix.size()) {
                throw std::invalid_argument("unknown size unit");
            }
        }
    }

    const auto base =
        binary_suffix || style.system != UnitSystem::SI ? std::uint64_t{1024} : std::uint64_t{1000};
    const auto multiplier = scale(power, base);
    const auto maximum = std::numeric_limits<std::uint64_t>::max();
    if (whole > maximum / multiplier) {
        throw std::out_of_range("size overflows 64 bits");
    }
    const auto whole_bytes = whole * multiplier;
    const auto fraction_bytes =
        (multiplier / fraction_scale) * fraction +
        ((multiplier % fraction_scale) * fraction + fraction_scale / 2) / fraction_scale;
    if (fraction_bytes > maximum - whole_bytes) {
        throw std::out_of_range("size overflows 64 bits");
    }
    return whole_bytes + fraction_bytes;
}

} // namespace dafree
