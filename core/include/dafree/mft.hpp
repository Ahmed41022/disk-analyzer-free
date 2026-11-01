#pragma once

#include "dafree/error.hpp"

#include <array>
#include <cstddef>
#include <cstdint>
#include <span>

namespace dafree {

/// Decoded NTFS v3 file-record metadata; integers are host-endian values.
struct RecordHeader {
    std::array<char, 4> signature;
    std::uint16_t usa_offset, usa_count;
    std::uint64_t lsn;
    std::uint16_t sequence, link_count, attrs_offset;
    /// Bit 0 means in use and bit 1 means directory; preserve every other bit.
    std::uint16_t flags;
    std::uint32_t bytes_used, bytes_allocated;
    std::uint64_t base_record;
};

/// A malformed record, invalid update sequence, or unsupported parser input.
enum class MftError { BadSignature, BadFixup, OutOfBounds, Unsupported };

/// Decode a complete NTFS v3 record header without reading outside its span.
///
/// The fixed prefix includes the unexposed next-attribute-id storage (42 bytes).
/// The aligned USA must follow that prefix and precede the first aligned attribute;
/// both must fit bytes_used <= bytes_allocated <= rec.size(). Unknown flags remain
/// intact. Sector geometry and update-sequence values are checked by apply_fixups.
Expected<RecordHeader, MftError> parse_header(std::span<const std::byte> rec);

/// Verify every sector's update-sequence value, then restore its saved trailer.
///
/// The declared bytes_allocated must equal rec.size(), and USA count must equal
/// rec.size() / sector_size + 1. Invalid inputs return an error without partially
/// restoring the record.
Expected<void, MftError> apply_fixups(std::span<std::byte> rec, std::size_t sector_size);

} // namespace dafree
