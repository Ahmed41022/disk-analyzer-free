#pragma once

#include <cstdint>
#include <string>
#include <string_view>

namespace dafree {

/// Select an automatic scale, bytes, or a fixed power from kilo to exa.
enum class UnitMode : std::uint8_t { Auto, Bytes, Kilo, Mega, Giga, Tera, Peta, Exa };

/// Choose the base and labels used for size formatting.
enum class UnitSystem : std::uint8_t { Traditional, IEC, SI };

/// Formatting rules supplied by the caller, including its locale decimal separator.
struct UnitStyle {
    UnitSystem system = UnitSystem::Traditional;
    char decimal_separator = '.';

    /// Construct a unit style with its base and decimal separator.
    UnitStyle(UnitSystem chosen_system = UnitSystem::Traditional, char separator = '.')
        : system(chosen_system), decimal_separator(separator) {}
};

/// Format a byte count using one decimal for scaled values.
[[nodiscard]] std::string format_size(std::uint64_t bytes, UnitMode mode = UnitMode::Auto,
                                      UnitStyle style = {});

/// Parse a byte count with an optional K/M/G/T/P/E suffix, rejecting overflow.
[[nodiscard]] std::uint64_t parse_size(std::string_view text, UnitStyle style = {});

} // namespace dafree
