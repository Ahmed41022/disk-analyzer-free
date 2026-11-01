#include "dafree/mft.hpp"

#include "../src/testing/counting_alloc.hpp"

#include <doctest/doctest.h>

#include <array>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <optional>
#include <span>
#include <vector>

namespace {

using Bytes = std::vector<std::uint8_t>;
using Runs = std::vector<dafree::Run>;
constexpr auto maximum_lcn = std::numeric_limits<std::int64_t>::max();
constexpr auto maximum_clusters = std::numeric_limits<std::uint64_t>::max();

std::span<const std::byte> as_bytes(std::span<const std::uint8_t> bytes) {
    return std::as_bytes(bytes);
}

void check_runs(const Runs &actual, const Runs &expected) {
    REQUIRE(actual.size() == expected.size());
    for (std::size_t index = 0; index < expected.size(); ++index) {
        CAPTURE(index);
        CHECK(actual[index].lcn == expected[index].lcn);
        CHECK(actual[index].clusters == expected[index].clusters);
    }
}

// This encoder is test-only. Literal byte vectors below establish its independent oracle.
std::uint8_t unsigned_width(std::uint64_t value) {
    std::uint8_t width = 1;
    while ((value >>= 8) != 0)
        ++width;
    return width;
}

std::uint8_t signed_width(std::int64_t value) {
    std::uint8_t width = 1;
    while (width < 8) {
        const auto boundary = std::int64_t{1} << (width * 8 - 1);
        if (value >= -boundary && value < boundary)
            break;
        ++width;
    }
    return width;
}

void append_low(Bytes &bytes, std::uint64_t value, std::uint8_t width) {
    for (std::uint8_t index = 0; index < width; ++index) {
        bytes.push_back(static_cast<std::uint8_t>(value & 0xffu));
        value >>= 8;
    }
}

Bytes encode(const Runs &runs) {
    Bytes bytes;
    std::int64_t previous = 0;
    for (const auto &run : runs) {
        const auto length_width = unsigned_width(run.clusters);
        const auto delta = run.lcn ? *run.lcn - previous : 0;
        const std::uint8_t offset_width = run.lcn ? signed_width(delta) : std::uint8_t{0};
        bytes.push_back(static_cast<std::uint8_t>((offset_width << 4) | length_width));
        append_low(bytes, run.clusters, length_width);
        append_low(bytes, static_cast<std::uint64_t>(delta), offset_width);
        if (run.lcn)
            previous = *run.lcn;
    }
    bytes.push_back(0);
    return bytes;
}

std::uint64_t random_word(std::uint64_t &state) {
    state ^= state << 13;
    state ^= state >> 7;
    state ^= state << 17;
    return state;
}

// Measure only the standard result-container construction/move path. In MSVC
// Debug, even an empty vector allocates checked-iterator proxies on this path.
// This reference contains no decoder, reserve, element buffer or parsing work.
dafree::Expected<Runs, dafree::MftError> empty_run_container() {
    Runs runs;
    return runs;
}

} // namespace

TEST_CASE("runlist_table") {
    struct Example {
        Bytes bytes;
        Runs runs;
    };
    const std::array examples = {
        Example{{0}, {}},
        Example{{0, 0xff, 0x99}, {}},
        Example{{0x01, 5, 0}, {{std::nullopt, 5}}},
        Example{{0x11, 1, 0, 0}, {{0, 1}}},
        Example{{0x11, 3, 0x7f, 0}, {{127, 3}}},
        Example{{0x11, 4, 10, 0x11, 2, 0xfd, 0}, {{10, 4}, {7, 2}}},
        Example{{0x11, 3, 10, 0x11, 2, 0, 0}, {{10, 3}, {10, 2}}},
        Example{{0x11, 3, 10, 0x01, 2, 0x11, 1, 0xfe, 0}, {{10, 3}, {std::nullopt, 2}, {8, 1}}},
        Example{{0x12, 0x34, 0x12, 1, 0}, {{1, UINT64_C(0x1234)}}},
        Example{{0x13, 0x56, 0x34, 0x12, 2, 0}, {{2, UINT64_C(0x123456)}}},
        Example{{0x14, 0xef, 0xcd, 0xab, 0x89, 3, 0}, {{3, UINT64_C(0x89abcdef)}}},
        Example{{0x15, 5, 4, 3, 2, 1, 4, 0}, {{4, UINT64_C(0x0102030405)}}},
        Example{{0x16, 6, 5, 4, 3, 2, 1, 5, 0}, {{5, UINT64_C(0x010203040506)}}},
        Example{{0x17, 7, 6, 5, 4, 3, 2, 1, 6, 0}, {{6, UINT64_C(0x01020304050607)}}},
        Example{{0x18, 8, 7, 6, 5, 4, 3, 2, 1, 7, 0}, {{7, UINT64_C(0x0102030405060708)}}},
        Example{{0x08, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0},
                {{std::nullopt, maximum_clusters}}},
        Example{{0x81, 1, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0x7f, 0}, {{maximum_lcn, 1}}},
        Example{{0x81, 1, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0x7f, 0x81,
                 1,    1, 0,    0,    0,    0,    0,    0,    0x80, 0},
                {{maximum_lcn, 1}, {0, 1}}},
        Example{{0x01, 1, 0x01, 2, 0}, {{std::nullopt, 1}, {std::nullopt, 2}}},
        Example{{0x08, 0xfe, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0x01, 1, 0},
                {{std::nullopt, maximum_clusters - 1}, {std::nullopt, 1}}},
        // A decoder has no volume geometry: a physical start is checked, not its end.
        Example{{0x88, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff,
                 0xff, 0xff, 0x7f, 0},
                {{maximum_lcn, maximum_clusters}}},
    };
    for (std::size_t index = 0; index < examples.size(); ++index) {
        CAPTURE(index);
        const auto decoded = dafree::decode_runlist(as_bytes(examples[index].bytes));
        REQUIRE(decoded.has_value());
        check_runs(decoded.value(), examples[index].runs);
    }
}

TEST_CASE("runlist_sign_extension_all_eight_widths") {
    for (std::uint8_t width = 1; width <= 8; ++width) {
        CAPTURE(width);
        const auto header = static_cast<std::uint8_t>((width << 4) | 1);
        // 0x40 followed by sign-bit-set 0xC0 in the highest encoded byte gives +X,-X.
        Bytes bytes{header, 1};
        bytes.insert(bytes.end(), static_cast<std::size_t>(width - 1), 0);
        bytes.push_back(0x40);
        bytes.push_back(header);
        bytes.push_back(2);
        bytes.insert(bytes.end(), static_cast<std::size_t>(width - 1), 0);
        bytes.push_back(0xc0);
        bytes.push_back(0);
        const auto decoded = dafree::decode_runlist(as_bytes(bytes));
        REQUIRE(decoded.has_value());
        check_runs(decoded.value(), {{std::int64_t{1} << (width * 8 - 2), 1}, {0, 2}});

        // -1 must sign-extend even when deliberately stored in a nonminimal width.
        bytes = {0x11, 1, 1, header, 2};
        bytes.insert(bytes.end(), width, 0xff);
        bytes.push_back(0);
        const auto negative_one = dafree::decode_runlist(as_bytes(bytes));
        REQUIRE(negative_one.has_value());
        check_runs(negative_one.value(), {{1, 1}, {0, 2}});
    }
}

TEST_CASE("encode_decode_roundtrip") {
    for (std::uint64_t seed = 1; seed <= 1000; ++seed) {
        CAPTURE(seed);
        std::uint64_t state = seed * UINT64_C(0x9e3779b97f4a7c15);
        Runs expected;
        const auto count = 8 + seed % 25;
        for (std::uint64_t index = 0; index < count; ++index) {
            const auto width = 1 + (index + seed) % 8;
            const auto high = std::uint64_t{1} << ((width - 1) * 8);
            const auto clusters = high | (random_word(state) & (high - 1));
            std::optional<std::int64_t> lcn;
            if (index == 0)
                lcn = 1000;
            else if (index == 1 || index == 3)
                lcn = 10; // A negative delta, then sparse, then a zero delta.
            else if (index != 2 && random_word(state) % 4 != 0) {
                const auto mask = (std::uint64_t{1} << (width * 8 - 1)) - 1;
                lcn = static_cast<std::int64_t>(random_word(state) & mask);
            }
            expected.push_back({lcn, clusters});
        }
        const auto encoded = encode(expected);
        const auto decoded = dafree::decode_runlist(as_bytes(encoded));
        REQUIRE(decoded.has_value());
        check_runs(decoded.value(), expected);
    }
}

TEST_CASE("runlist_malformed_encodings_and_arithmetic_errors") {
    const std::array examples = {
        Bytes{},
        Bytes{0x10, 1, 0},
        Bytes{0x09, 1, 0},
        Bytes{0x91, 1, 0},
        Bytes{0xf8, 1, 0},
        Bytes{0x01},
        Bytes{0x11, 1},
        Bytes{0x11, 1, 1},
        Bytes{0x01, 0, 0},
        Bytes{0x11, 0, 0, 0},
        Bytes{0x11, 1, 0xff, 0},
        Bytes{0x81, 1, 0, 0, 0, 0, 0, 0, 0, 0x80, 0},
        Bytes{0x81, 1, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0x7f, 0x11, 1, 1, 0},
        Bytes{0x08, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0xff, 0x01, 1, 0},
    };
    for (std::size_t index = 0; index < examples.size(); ++index) {
        CAPTURE(index);
        const auto before = dafree::testing::allocations().calls;
        const auto decoded = dafree::decode_runlist(as_bytes(examples[index]));
        const auto after = dafree::testing::allocations().calls;
        REQUIRE_FALSE(decoded.has_value());
        CHECK(decoded.error() == dafree::MftError::OutOfBounds);
        CHECK(after == before);
    }
    const Bytes complete = {0x88, 1, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0, 0, 0, 0, 0};
    for (std::size_t length = 0; length < complete.size(); ++length) {
        CAPTURE(length);
        const auto decoded = dafree::decode_runlist(as_bytes(complete).first(length));
        REQUIRE_FALSE(decoded.has_value());
        CHECK(decoded.error() == dafree::MftError::OutOfBounds);
    }
}

TEST_CASE("runlist_valid_output_allocates_once_and_empty_output_never_allocates") {
    const auto reference_before = dafree::testing::allocations().calls;
    const auto reference = empty_run_container();
    const auto container_calls = dafree::testing::allocations().calls - reference_before;
    REQUIRE(reference.has_value());
    CHECK(reference.value().capacity() == 0);
    INFO("standard result-container bookkeeping allocations: ", container_calls);

    constexpr std::array<std::uint8_t, 1> empty{0};
    const auto empty_before = dafree::testing::allocations().calls;
    const auto empty_result = dafree::decode_runlist(as_bytes(empty));
    const auto empty_after = dafree::testing::allocations().calls;
    REQUIRE(empty_result.has_value());
    CHECK(empty_result.value().empty());
    CHECK(empty_result.value().capacity() == 0);
    CHECK(empty_after - empty_before == container_calls);

    constexpr std::array<std::uint8_t, 9> bytes{0x11, 3, 10, 0x01, 2, 0x11, 1, 0xfe, 0};
    const auto before = dafree::testing::allocations().calls;
    const auto decoded = dafree::decode_runlist(as_bytes(bytes));
    const auto after = dafree::testing::allocations().calls;
    REQUIRE(decoded.has_value());
    CHECK(after - before == container_calls + 1);
    CHECK(decoded.value().capacity() == decoded.value().size());
    check_runs(decoded.value(), {{10, 3}, {std::nullopt, 2}, {8, 1}});
}

TEST_CASE("runlist_output_over_64mib_is_rejected_before_allocation") {
    constexpr std::size_t max_output_bytes = 64u * 1024u * 1024u;
    constexpr auto count = max_output_bytes / sizeof(dafree::Run) + 1;
    Bytes bytes(count * 2 + 1);
    for (std::size_t index = 0; index < count; ++index) {
        bytes[index * 2] = 0x01;
        bytes[index * 2 + 1] = 1;
    }
    const auto before = dafree::testing::allocations().calls;
    const auto decoded = dafree::decode_runlist(as_bytes(bytes));
    const auto after = dafree::testing::allocations().calls;
    REQUIRE_FALSE(decoded.has_value());
    CHECK(decoded.error() == dafree::MftError::Unsupported);
    CHECK(after == before);
}
