#include <ostream>

#include "dafree/units.hpp"

#include <doctest/doctest.h>

#include <cstdint>
#include <limits>
#include <random>
#include <stdexcept>
#include <string>

TEST_CASE("format_table") {
    using dafree::format_size;
    CHECK(format_size(0) == "0 B");
    CHECK(format_size(1023) == "1023 B");
    CHECK(format_size(1024) == "1.0 KB");
    CHECK(format_size(1536) == "1.5 KB");
    CHECK(format_size(1024, dafree::UnitMode::Auto, {dafree::UnitSystem::IEC, '.'}) == "1.0 KiB");
    CHECK(format_size(1000, dafree::UnitMode::Auto, {dafree::UnitSystem::SI, '.'}) == "1.0 kB");
    CHECK(format_size(1500, dafree::UnitMode::Auto, {dafree::UnitSystem::SI, ','}) == "1,5 kB");
    CHECK(format_size(512, dafree::UnitMode::Kilo) == "0.5 KB");
}

TEST_CASE("parse_table") {
    using dafree::parse_size;
    CHECK(parse_size("1.5GB") == 1'610'612'736);
    CHECK(parse_size("1.5gb") == 1'610'612'736);
    CHECK(parse_size("500 MiB") == 524'288'000);
    CHECK(parse_size("10k") == 10'240);
    CHECK(parse_size("1.5 GB", {dafree::UnitSystem::SI, '.'}) == 1'500'000'000);
    CHECK(parse_size("1,5 kB", {dafree::UnitSystem::SI, ','}) == 1500);
    CHECK(parse_size("18446744073709551615 B") == std::numeric_limits<std::uint64_t>::max());
    CHECK_THROWS_AS((void)parse_size("-1 GB"), std::invalid_argument);
    CHECK_THROWS_AS((void)parse_size("18446744073709551616 B"), std::out_of_range);
    CHECK_THROWS_AS((void)parse_size("18446744073709551615 EB"), std::out_of_range);
    CHECK_THROWS_AS((void)parse_size("1.2.3 MB"), std::invalid_argument);
}

TEST_CASE("parse_format_roundtrip_within_rounding") {
    std::mt19937_64 random{0xDAFEE123u};
    for (int index = 0; index < 10'000; ++index) {
        const auto value = random();
        const auto rendered = dafree::format_size(value);
        const auto parsed = dafree::parse_size(rendered);
        const auto difference = value > parsed ? value - parsed : parsed - value;
        std::uint64_t divisor = 1;
        while (divisor <= value / 1024 && divisor <= (std::uint64_t{1} << 50)) {
            divisor *= 1024;
        }
        CHECK(difference <= divisor / 20 + 1);
    }
}
