#include "dafree/mft.hpp"

#include "../src/testing/counting_alloc.hpp"

#include <doctest/doctest.h>

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <initializer_list>
#include <limits>
#include <span>
#include <string>
#include <string_view>
#include <variant>
#include <vector>

namespace {

using Bytes = std::vector<std::byte>;
constexpr std::size_t attrs_offset = 0x50;
constexpr std::uint64_t unix_epoch = UINT64_C(116444736000000000);

void put(std::span<std::byte> bytes, std::size_t offset, std::uint64_t value, std::size_t width) {
    REQUIRE(offset <= bytes.size());
    REQUIRE(width <= bytes.size() - offset);
    REQUIRE(width <= sizeof(value));
    for (std::size_t index = 0; index < width; ++index)
        bytes[offset + index] = static_cast<std::byte>((value >> (index * 8)) & 0xffu);
}

std::size_t round8(std::size_t length) { return (length + 7) & ~std::size_t{7}; }

void put_name(std::span<std::byte> bytes, std::size_t offset, std::u16string_view name) {
    for (std::size_t index = 0; index < name.size(); ++index)
        put(bytes, offset + index * 2, name[index], 2);
}

Bytes resident(std::uint32_t type, const Bytes &payload = {}, std::u16string_view name = {},
               std::uint16_t flags = 0) {
    REQUIRE(name.size() <= 255);
    const auto value_offset = round8(24 + name.size() * 2);
    Bytes result(round8(value_offset + payload.size()));
    put(result, 0, type, 4);
    put(result, 4, result.size(), 4);
    put(result, 9, name.size(), 1);
    put(result, 10, name.empty() ? 0 : 24, 2);
    put(result, 12, flags, 2);
    put(result, 16, payload.size(), 4);
    put(result, 20, value_offset, 2);
    put_name(result, 24, name);
    std::copy(payload.begin(), payload.end(),
              result.begin() + static_cast<std::ptrdiff_t>(value_offset));
    return result;
}

Bytes nonresident(std::uint16_t flags = 0, bool extended = false, std::u16string_view name = {},
                  std::uint64_t lowest_vcn = 0) {
    REQUIRE(name.size() <= 255);
    const std::size_t header = extended ? 72 : 64;
    const auto maps = round8(header + name.size() * 2);
    Bytes result(round8(maps + 4));
    put(result, 0, 0x80, 4);
    put(result, 4, result.size(), 4);
    put(result, 8, 1, 1);
    put(result, 9, name.size(), 1);
    put(result, 10, name.empty() ? 0 : header, 2);
    put(result, 12, flags, 2);
    put(result, 16, lowest_vcn, 8);
    put(result, 24, lowest_vcn + 2, 8);
    put(result, 32, maps, 2);
    put(result, 40, 16384, 8);
    put(result, 48, 100000, 8);
    put(result, 56, 99999, 8);
    if (extended)
        put(result, 64, 4096, 8);
    put_name(result, header, name);
    // Encoded runs are borrowed, not decoded by the attribute iterator.
    put(result, maps, 0x11, 1);
    put(result, maps + 1, 3, 1);
    put(result, maps + 2, 0x7f, 1);
    return result;
}

Bytes record(std::initializer_list<Bytes> attributes, bool terminator = true) {
    Bytes result(4096);
    result[0] = std::byte{0x46};
    result[1] = std::byte{0x49};
    result[2] = std::byte{0x4c};
    result[3] = std::byte{0x45};
    put(result, 4, 0x30, 2);
    put(result, 6, 9, 2);
    put(result, 0x14, attrs_offset, 2);
    put(result, 0x16, 1, 2);
    put(result, 0x1c, result.size(), 4);
    std::size_t used = attrs_offset;
    for (const auto &attribute : attributes) {
        REQUIRE(attribute.size() <= result.size() - used);
        std::copy(attribute.begin(), attribute.end(),
                  result.begin() + static_cast<std::ptrdiff_t>(used));
        used += attribute.size();
    }
    if (terminator) {
        put(result, used, 0xffffffffu, 4);
        used += 4;
    }
    put(result, 0x18, used, 4);
    return result;
}

Bytes filename(std::uint8_t name_space, std::u16string_view name) {
    Bytes value(66 + name.size() * 2);
    put(value, 0, UINT64_C(0xabcd0123456789ef), 8);
    put(value, 64, name.size(), 1);
    put(value, 65, name_space, 1);
    put_name(value, 66, name);
    return resident(0x30, value);
}

template <typename T> T next_as(dafree::AttrIterator &iterator) {
    const auto parsed = iterator.next();
    REQUIRE(parsed.has_value());
    REQUIRE(parsed.value().has_value());
    REQUIRE(std::holds_alternative<T>(*parsed.value()));
    return std::get<T>(*parsed.value());
}

void at_end(dafree::AttrIterator &iterator) {
    for (int repeat = 0; repeat < 2; ++repeat) {
        const auto parsed = iterator.next();
        REQUIRE(parsed.has_value());
        CHECK_FALSE(parsed.value().has_value());
    }
}

void error_is(std::span<const std::byte> bytes,
              dafree::MftError expected = dafree::MftError::OutOfBounds) {
    dafree::AttrIterator iterator(bytes);
    for (int repeat = 0; repeat < 2; ++repeat) {
        const auto parsed = iterator.next();
        REQUIRE_FALSE(parsed.has_value());
        CHECK(parsed.error() == expected);
    }
}

} // namespace

TEST_CASE("std_info_times") {
    Bytes info(48);
    put(info, 0, 0, 8);
    put(info, 8, UINT64_C(125911584000000000), 8);
    put(info, 16, std::numeric_limits<std::uint64_t>::max(), 8);
    put(info, 24, unix_epoch + 1, 8);
    put(info, 32, 0xdeadbeefu, 4);
    const auto bytes = record({resident(0x10, info)});
    dafree::AttrIterator iterator(bytes);
    const auto parsed = next_as<dafree::StdInfo>(iterator);
    CHECK(parsed.created == INT64_C(-11644473600));
    CHECK(parsed.modified == 946684800);
    CHECK(parsed.accessed == 0);
    CHECK(parsed.file_attributes == 0xdeadbeefu);
    at_end(iterator);
}

TEST_CASE("filename_namespaces") {
    const std::u16string name = {u'A', u'\0', char16_t{0xd800}, char16_t{0xdc00}, char16_t{0xdfff}};
    for (const auto name_space : std::array<std::uint8_t, 5>{0, 1, 2, 3, 0xff}) {
        const auto bytes = record({filename(name_space, name)});
        dafree::AttrIterator iterator(bytes);
        const auto parsed = next_as<dafree::FileNameAttr>(iterator);
        CHECK(parsed.parent_ref == UINT64_C(0xabcd0123456789ef));
        CHECK(parsed.name_space == name_space);
        CHECK(parsed.name == name);
        CHECK(reinterpret_cast<std::uintptr_t>(parsed.name.data()) % alignof(char16_t) == 0);
        at_end(iterator);
    }
}

TEST_CASE("data_resident_size") {
    const Bytes content = {std::byte{1}, std::byte{2}, std::byte{3}};
    const auto bytes = record({resident(0x80, content, {}, 0x4000), resident(0x80)});
    dafree::AttrIterator iterator(bytes);
    const auto first = next_as<dafree::DataAttr>(iterator);
    CHECK(first.name.empty());
    CHECK(first.resident);
    CHECK(first.size == content.size());
    CHECK(first.alloc == 0);
    CHECK(first.lowest_vcn == 0);
    CHECK(first.runlist.empty());
    CHECK(first.flags == 0x4000);
    const auto empty = next_as<dafree::DataAttr>(iterator);
    CHECK(empty.size == 0);
    CHECK(empty.alloc == 0);
    CHECK(empty.resident);
    at_end(iterator);
}

TEST_CASE("data_nonresident_sparse_alloc") {
    for (const auto flags : std::array<std::uint16_t, 5>{0, 1, 3, 0x8000, 0x8001}) {
        for (const auto extended : {false, true}) {
            for (const auto name : {std::u16string_view{}, std::u16string_view{u"ads"}}) {
                const auto attribute = nonresident(flags, extended, name, 7);
                const auto bytes = record({attribute});
                dafree::AttrIterator iterator(bytes);
                const auto parsed = next_as<dafree::DataAttr>(iterator);
                CHECK_FALSE(parsed.resident);
                CHECK(parsed.name == name);
                CHECK(parsed.size == 100000);
                CHECK(parsed.alloc == (flags != 0 && extended ? 4096 : 16384));
                CHECK(parsed.lowest_vcn == 7);
                CHECK(parsed.flags == flags);
                REQUIRE(parsed.runlist.size() >= 4);
                CHECK(parsed.runlist[0] == std::byte{0x11});
                CHECK(parsed.runlist[1] == std::byte{3});
                CHECK(parsed.runlist[2] == std::byte{0x7f});
                CHECK(parsed.runlist[3] == std::byte{0});
                CHECK(parsed.runlist.data() >= bytes.data() + attrs_offset);
                CHECK(parsed.runlist.data() + parsed.runlist.size() <=
                      bytes.data() + attrs_offset + attribute.size());
                at_end(iterator);
            }
        }
    }
}

TEST_CASE("named_stream_detected") {
    const std::u16string name = {u'x', u':', char16_t{0xd800}, u'\0', u'z'};
    for (const auto is_resident : {false, true}) {
        const auto bytes =
            record({is_resident ? resident(0x80, Bytes(5), name) : nonresident(0, false, name)});
        dafree::AttrIterator iterator(bytes);
        const auto parsed = next_as<dafree::DataAttr>(iterator);
        CHECK(parsed.name == name);
        CHECK(parsed.resident == is_resident);
        CHECK(reinterpret_cast<std::uintptr_t>(parsed.name.data()) % alignof(char16_t) == 0);
    }
}

TEST_CASE("filetime_table") {
    struct Example {
        std::uint64_t ticks;
        std::int64_t seconds;
    };
    constexpr std::array examples = {
        Example{0, INT64_C(-11644473600)},
        Example{1, INT64_C(-11644473600)},
        Example{unix_epoch - 10000001, -2},
        Example{unix_epoch - 10000000, -1},
        Example{unix_epoch - 1, -1},
        Example{unix_epoch, 0},
        Example{unix_epoch + 1, 0},
        Example{unix_epoch + 9999999, 0},
        Example{unix_epoch + 10000000, 1},
        Example{UINT64_C(125911584000000000), 946684800},
        Example{UINT64_C(133485408000000000), 1704067200},
        Example{std::numeric_limits<std::uint64_t>::max(), INT64_C(1833029933770)},
    };
    for (const auto &example : examples) {
        CAPTURE(example.ticks);
        CHECK(dafree::filetime_to_unix(example.ticks) == example.seconds);
    }
}

TEST_CASE("mft_attributes_stop_at_marker_or_used_boundary") {
    for (const auto terminator : {false, true}) {
        const auto empty = record({}, terminator);
        dafree::AttrIterator empty_iterator(empty);
        at_end(empty_iterator);
        auto bytes = record({resident(0x80)}, terminator);
        // Valid-looking attributes past bytes_used must remain invisible.
        const auto extra = resident(0x80, Bytes(16));
        std::copy(extra.begin(), extra.end(), bytes.begin() + 256);
        dafree::AttrIterator iterator(bytes);
        CHECK(next_as<dafree::DataAttr>(iterator).size == 0);
        at_end(iterator);
    }
    auto bytes = record({}, true);
    put(bytes, 0x18, attrs_offset + 8, 4);
    put(bytes, attrs_offset + 4, 0, 4);
    dafree::AttrIterator iterator(bytes);
    at_end(iterator);
}

TEST_CASE("mft_attribute_markers_and_unknown_types") {
    const auto bytes = record({resident(0x20), resident(0xc0), resident(0x12345678)});
    dafree::AttrIterator iterator(bytes);
    next_as<dafree::AttrListMarker>(iterator);
    next_as<dafree::ReparseMarker>(iterator);
    CHECK(next_as<dafree::OtherAttr>(iterator).type == 0x12345678);
    at_end(iterator);
}

TEST_CASE("mft_attribute_names_accept_unaligned_record_storage") {
    const std::u16string name(255, char16_t{0xd812});
    for (const auto offset : std::array<std::size_t, 4>{0, 1, 2, 3}) {
        for (const auto is_filename : {false, true}) {
            const auto original =
                record({is_filename ? filename(1, name) : resident(0x80, {}, name)});
            Bytes storage(original.size() + offset);
            std::copy(original.begin(), original.end(),
                      storage.begin() + static_cast<std::ptrdiff_t>(offset));
            const auto bytes = std::span<const std::byte>(storage).subspan(offset);
            dafree::AttrIterator iterator(bytes);
            if (is_filename) {
                const auto parsed = next_as<dafree::FileNameAttr>(iterator);
                CHECK(parsed.name == name);
                CHECK(reinterpret_cast<std::uintptr_t>(parsed.name.data()) % alignof(char16_t) ==
                      0);
            } else {
                const auto parsed = next_as<dafree::DataAttr>(iterator);
                CHECK(parsed.name == name);
                CHECK(reinterpret_cast<std::uintptr_t>(parsed.name.data()) % alignof(char16_t) ==
                      0);
            }
            at_end(iterator);
        }
    }
}

TEST_CASE("mft_attribute_truncations_and_invalid_lengths_are_sticky_errors") {
    const auto attribute = resident(0x80, Bytes(16));
    const auto original = record({attribute});
    for (std::size_t size = 0; size < original.size(); ++size)
        error_is(std::span<const std::byte>(original).first(size));
    for (std::size_t size = 1; size < attribute.size(); ++size) {
        auto bytes = original;
        put(bytes, 0x18, attrs_offset + size, 4);
        error_is(bytes);
    }
    for (const auto length : std::array<std::uint32_t, 8>{0, 1, 8, 16, 20, 25, 4096, 0xffffffff}) {
        auto bytes = original;
        put(bytes, attrs_offset + 4, length, 4);
        error_is(bytes);
    }
    auto bytes = original;
    bytes[0] = std::byte{0};
    error_is(bytes, dafree::MftError::BadSignature);
}

TEST_CASE("mft_attribute_value_name_and_runlist_ranges_are_checked") {
    const auto original = record({resident(0x80, Bytes(8), u"ads")});
    for (const auto field : {std::size_t{10}, std::size_t{20}}) {
        for (const auto offset : std::array<std::uint16_t, 4>{0, 16, 23, 0xffff}) {
            auto bytes = original;
            put(bytes, attrs_offset + field, offset, 2);
            error_is(bytes);
        }
    }
    auto bytes = original;
    put(bytes, attrs_offset + 9, 255, 1);
    error_is(bytes);
    bytes = original;
    put(bytes, attrs_offset + 16, 0xffffffff, 4);
    error_is(bytes);
    bytes = original;
    put(bytes, attrs_offset + 20, 24, 2);
    error_is(bytes); // Payload overlaps the nonempty name.

    const auto nonresident_record = record({nonresident()});
    for (const auto offset : std::array<std::uint16_t, 4>{0, 32, 72, 0xffff}) {
        bytes = nonresident_record;
        put(bytes, attrs_offset + 32, offset, 2);
        error_is(bytes);
    }
    bytes = record({nonresident(0x8000, true, u"ads")});
    put(bytes, attrs_offset + 10, 65, 2);
    error_is(bytes); // Named text must start on a code-unit boundary.

    // NameOffset is undefined for unnamed streams, including a maximal sentinel.
    bytes = record({resident(0x80), nonresident()});
    put(bytes, attrs_offset + 10, 0xffff, 2);
    put(bytes, attrs_offset + 24 + 10, 0xffff, 2);
    dafree::AttrIterator iterator(bytes);
    CHECK(next_as<dafree::DataAttr>(iterator).name.empty());
    CHECK(next_as<dafree::DataAttr>(iterator).name.empty());
    at_end(iterator);
}

TEST_CASE("mft_attribute_known_payloads_and_forms_are_validated") {
    error_is(record({resident(0x10, Bytes(47))}));
    error_is(record({resident(0x30, Bytes(65))}));
    auto value = Bytes(66);
    put(value, 64, 255, 1);
    error_is(record({resident(0x30, value)}));
    for (const auto form : std::array<std::uint8_t, 2>{2, 0xff}) {
        auto bytes = record({resident(0x80)});
        put(bytes, attrs_offset + 8, form, 1);
        error_is(bytes, dafree::MftError::Unsupported);
    }
    for (const auto type : {0x10u, 0x30u}) {
        auto bytes = record({nonresident()});
        put(bytes, attrs_offset, type, 4);
        error_is(bytes, dafree::MftError::Unsupported);
    }
}

TEST_CASE("mft_attribute_iteration_does_not_allocate") {
    const std::u16string name(255, char16_t{0xd812});
    const auto bytes = record(
        {filename(1, name), resident(0x80, Bytes(8), name), nonresident(0x8000, true, name)});
    const auto before = dafree::testing::allocations().calls;
    dafree::AttrIterator iterator(bytes);
    const auto first = iterator.next();
    const bool filename_ok = first.has_value() && first.value().has_value() &&
                             std::holds_alternative<dafree::FileNameAttr>(*first.value()) &&
                             std::get<dafree::FileNameAttr>(*first.value()).name == name;
    const auto second = iterator.next();
    const bool resident_ok = second.has_value() && second.value().has_value() &&
                             std::holds_alternative<dafree::DataAttr>(*second.value()) &&
                             std::get<dafree::DataAttr>(*second.value()).resident &&
                             std::get<dafree::DataAttr>(*second.value()).name == name &&
                             std::get<dafree::DataAttr>(*second.value()).size == 8;
    const auto third = iterator.next();
    const bool nonresident_ok = third.has_value() && third.value().has_value() &&
                                std::holds_alternative<dafree::DataAttr>(*third.value()) &&
                                !std::get<dafree::DataAttr>(*third.value()).resident &&
                                std::get<dafree::DataAttr>(*third.value()).name == name &&
                                std::get<dafree::DataAttr>(*third.value()).alloc == 4096;
    const auto end = iterator.next();
    const bool ended = end.has_value() && !end.value().has_value();
    const auto after = dafree::testing::allocations().calls;
    // Keep doctest bookkeeping outside the measured construction/iteration region.
    CHECK(filename_ok);
    CHECK(resident_ok);
    CHECK(nonresident_ok);
    CHECK(ended);
    CHECK(after == before);
}
