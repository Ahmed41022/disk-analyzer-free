#include "dafree/mft.hpp"

#include <doctest/doctest.h>

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <limits>
#include <span>
#include <string_view>
#include <vector>

namespace {

std::vector<std::byte> golden(std::string_view name) {
    const auto path = std::filesystem::path(DAFREE_SOURCE_DIR) / "core/tests/golden/mft" / name;
    std::ifstream input(path, std::ios::binary);
    REQUIRE(input.good());
    const std::vector<char> bytes((std::istreambuf_iterator<char>(input)),
                                  std::istreambuf_iterator<char>());
    REQUIRE_FALSE(input.bad());
    std::vector<std::byte> result;
    result.reserve(bytes.size());
    for (const auto value : bytes)
        result.push_back(static_cast<std::byte>(static_cast<unsigned char>(value)));
    return result;
}

void put16(std::span<std::byte> bytes, std::size_t offset, std::uint16_t value) {
    REQUIRE(offset <= bytes.size());
    REQUIRE(bytes.size() - offset >= 2);
    bytes[offset] = static_cast<std::byte>(value & 0xffu);
    bytes[offset + 1] = static_cast<std::byte>(value >> 8u);
}

void put32(std::span<std::byte> bytes, std::size_t offset, std::uint32_t value) {
    REQUIRE(offset <= bytes.size());
    REQUIRE(bytes.size() - offset >= 4);
    for (unsigned index = 0; index < 4; ++index)
        bytes[offset + index] = static_cast<std::byte>((value >> (index * 8u)) & 0xffu);
}

void check_fixup_error(std::vector<std::byte> record, std::size_t sector_size,
                       dafree::MftError error) {
    const auto original = record;
    const auto result = dafree::apply_fixups(record, sector_size);
    REQUIRE_FALSE(result.has_value());
    CHECK(result.error() == error);
    CHECK(record == original);
}

} // namespace

TEST_CASE("golden_header") {
    const auto record = golden("file_1024.bin");
    const auto result = dafree::parse_header(record);
    REQUIRE(result.has_value());
    const auto &header = result.value();
    CHECK((header.signature == std::array<char, 4>{'F', 'I', 'L', 'E'}));
    CHECK(header.usa_offset == 0x30);
    CHECK(header.usa_count == 3);
    CHECK(header.lsn == UINT64_C(0x0102030405060708));
    CHECK(header.sequence == 0x1234);
    CHECK(header.link_count == 0x2345);
    CHECK(header.attrs_offset == 0x38);
    CHECK(header.flags == 1);
    CHECK(header.bytes_used == 0x40);
    CHECK(header.bytes_allocated == 1024);
    CHECK(header.base_record == UINT64_C(0xfedcba9876543210));

    const auto directory = dafree::parse_header(golden("directory_2048.bin"));
    REQUIRE(directory.has_value());
    CHECK(directory.value().flags == 3);
    CHECK(directory.value().usa_count == 5);
    CHECK(directory.value().attrs_offset == 0x40);
    CHECK(directory.value().bytes_used == 0x48);
    CHECK(directory.value().bytes_allocated == 2048);

    const auto legacy = dafree::parse_header(golden("ntfs30_1024.bin"));
    REQUIRE(legacy.has_value());
    CHECK(legacy.value().usa_offset == 0x2a);
    CHECK(legacy.value().attrs_offset == 0x30);
    CHECK(legacy.value().bytes_used == 0x38);
}

TEST_CASE("fixup_restores_bytes") {
    for (const auto name : {"file_1024.bin", "directory_2048.bin", "ntfs30_1024.bin"}) {
        CAPTURE(name);
        auto record = golden(name);
        auto expected = record;
        for (std::size_t sector = 0; sector < record.size() / 512; ++sector)
            put16(expected, (sector + 1) * 512 - 2, static_cast<std::uint16_t>(0xb000 + sector));
        const auto result = dafree::apply_fixups(record, 512);
        REQUIRE(result.has_value());
        CHECK(record == expected);
        // Applying an already-restored record again must detect the missing sequence stamp.
        check_fixup_error(record, 512, dafree::MftError::BadFixup);
    }
}

TEST_CASE("fixup_mismatch_errors") {
    for (std::size_t sector = 0; sector < 4; ++sector) {
        auto record = golden("directory_2048.bin");
        put16(record, (sector + 1) * 512 - 2, 0x1234);
        CAPTURE(sector);
        check_fixup_error(record, 512, dafree::MftError::BadFixup);
    }
    for (const auto count : {std::uint16_t{1}, std::uint16_t{2}, std::uint16_t{4}}) {
        auto record = golden("file_1024.bin");
        put16(record, 6, count);
        CAPTURE(count);
        check_fixup_error(record, 512, dafree::MftError::BadFixup);
    }
}

TEST_CASE("truncated_record_errors_not_crashes") {
    const auto complete = golden("file_1024.bin");
    for (std::size_t length = 0; length < complete.size(); ++length) {
        CAPTURE(length);
        auto prefix = std::vector<std::byte>(
            complete.begin(), complete.begin() + static_cast<std::ptrdiff_t>(length));
        const auto header = dafree::parse_header(prefix);
        REQUIRE_FALSE(header.has_value());
        CHECK(header.error() == dafree::MftError::OutOfBounds);
        check_fixup_error(prefix, 512, dafree::MftError::OutOfBounds);
    }
}

TEST_CASE("mft_record_unaligned_span") {
    const auto complete = golden("file_1024.bin");
    std::vector<std::byte> storage(complete.size() + 1);
    std::copy(complete.begin(), complete.end(), storage.begin() + 1);
    const std::span record(storage.data() + 1, complete.size());
    const auto header = dafree::parse_header(record);
    REQUIRE(header.has_value());
    CHECK(header.value().lsn == UINT64_C(0x0102030405060708));
    CHECK(header.value().base_record == UINT64_C(0xfedcba9876543210));
    const auto fixed = dafree::apply_fixups(record, 512);
    REQUIRE(fixed.has_value());
    auto expected = complete;
    put16(expected, 510, 0xb000);
    put16(expected, 1022, 0xb001);
    CHECK(std::equal(record.begin(), record.end(), expected.begin(), expected.end()));
}

TEST_CASE("mft_bad_signatures") {
    for (const auto signature : {std::array{'B', 'A', 'A', 'D'}, std::array{'F', 'I', 'L', '\0'},
                                 std::array{'f', 'i', 'l', 'e'}}) {
        auto record = golden("file_1024.bin");
        for (std::size_t index = 0; index < signature.size(); ++index)
            record[index] = static_cast<std::byte>(signature[index]);
        const auto parsed = dafree::parse_header(record);
        REQUIRE_FALSE(parsed.has_value());
        CHECK(parsed.error() == dafree::MftError::BadSignature);
        check_fixup_error(record, 512, dafree::MftError::BadSignature);
    }
}

TEST_CASE("mft_fixup_geometry_and_usa_bounds") {
    for (const auto sector : {std::size_t{0}, std::size_t{1}, std::size_t{3}, std::size_t{513},
                              std::numeric_limits<std::size_t>::max()}) {
        CAPTURE(sector);
        check_fixup_error(golden("file_1024.bin"), sector, dafree::MftError::Unsupported);
    }
    check_fixup_error(golden("file_1024.bin"), 2048, dafree::MftError::OutOfBounds);
    check_fixup_error({}, 512, dafree::MftError::OutOfBounds);
    for (const auto offset : {std::uint16_t{0}, std::uint16_t{0x28}, std::uint16_t{0x2b},
                              std::uint16_t{1022}, std::uint16_t{0xfffe}}) {
        auto record = golden("file_1024.bin");
        put16(record, 4, offset);
        CAPTURE(offset);
        check_fixup_error(record, 512, dafree::MftError::OutOfBounds);
    }
    auto no_array = golden("file_1024.bin");
    put16(no_array, 6, 0);
    check_fixup_error(no_array, 512, dafree::MftError::OutOfBounds);

    auto overlaps_tail = golden("file_1024.bin");
    put16(overlaps_tail, 4, 510);
    put16(overlaps_tail, 0x14, 520);
    put32(overlaps_tail, 0x18, 528);
    check_fixup_error(overlaps_tail, 512, dafree::MftError::OutOfBounds);
}

TEST_CASE("mft_usa_can_end_at_first_trailer_boundary") {
    auto record = golden("file_1024.bin");
    put16(record, 4, 504);
    put16(record, 0x14, 512);
    put32(record, 0x18, 520);
    put16(record, 504, 0xa55a);
    put16(record, 506, 0xb000);
    put16(record, 508, 0xb001);
    auto expected = record;
    put16(expected, 510, 0xb000);
    put16(expected, 1022, 0xb001);
    REQUIRE(dafree::parse_header(record).has_value());
    REQUIRE(dafree::apply_fixups(record, 512).has_value());
    CHECK(record == expected);
}

TEST_CASE("mft_header_layout_bounds") {
    struct Change {
        std::size_t offset;
        std::uint32_t value;
        bool word;
    };
    for (const auto change :
         {Change{0x14, 0x37, true}, Change{0x14, 0x30, true}, Change{0x14, 0x48, true},
          Change{0x18, 41, false}, Change{0x18, 1025, false}, Change{0x1c, 63, false},
          Change{0x1c, 1025, false}}) {
        auto record = golden("file_1024.bin");
        if (change.word)
            put16(record, change.offset, static_cast<std::uint16_t>(change.value));
        else
            put32(record, change.offset, change.value);
        CAPTURE(change.offset);
        CAPTURE(change.value);
        const auto parsed = dafree::parse_header(record);
        REQUIRE_FALSE(parsed.has_value());
        CHECK(parsed.error() == dafree::MftError::OutOfBounds);
        check_fixup_error(record, 512, dafree::MftError::OutOfBounds);
    }
}

TEST_CASE("mft_header_preserves_uninterpreted_values") {
    auto record = golden("file_1024.bin");
    put16(record, 0x10, 0);
    put16(record, 0x12, 0);
    put16(record, 0x16, 0xffff);
    put32(record, 0x18, 0x38); // Empty attribute boundary is still structurally readable.
    const auto parsed = dafree::parse_header(record);
    REQUIRE(parsed.has_value());
    CHECK(parsed.value().sequence == 0);
    CHECK(parsed.value().link_count == 0);
    CHECK(parsed.value().flags == 0xffff);
    REQUIRE(dafree::apply_fixups(record, 512).has_value());

    record = golden("file_1024.bin");
    record.resize(1056);
    const auto larger_span = dafree::parse_header(record);
    REQUIRE(larger_span.has_value());
    CHECK(larger_span.value().bytes_allocated == 1024);
    check_fixup_error(record, 512, dafree::MftError::OutOfBounds);
}

TEST_CASE("mft_fixup_rejects_supplied_span_beyond_declared_record") {
    auto record = golden("file_1024.bin");
    record.resize(2048);
    put16(record, 6, 5);
    put16(record, 0x14, 0x40);
    put32(record, 0x18, 0x48);
    for (std::size_t sector = 0; sector < 4; ++sector) {
        put16(record, 0x30 + (sector + 1) * 2, static_cast<std::uint16_t>(0xb000 + sector));
        put16(record, (sector + 1) * 512 - 2, 0xa55a);
    }
    const auto header = dafree::parse_header(record);
    REQUIRE(header.has_value());
    CHECK(header.value().bytes_allocated == 1024);
    CHECK(header.value().usa_count == 5);
    check_fixup_error(record, 512, dafree::MftError::OutOfBounds);
}
