#pragma once

#include "dafree/error.hpp"

#include <array>
#include <cstddef>
#include <cstdint>
#include <optional>
#include <span>
#include <string_view>
#include <variant>

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

/// Standard-information times in Unix seconds, with raw NTFS file attributes.
struct StdInfo {
    std::int64_t created, modified, accessed;
    std::uint32_t file_attributes;
};

/// One filename and its full parent reference; name storage belongs to the iterator.
struct FileNameAttr {
    std::uint64_t parent_ref;
    std::uint8_t name_space;
    std::u16string_view name;
};

/// A data stream's sizes and borrowed encoded runs; resident streams allocate no clusters.
struct DataAttr {
    std::u16string_view name;
    bool resident;
    std::uint64_t size, alloc, lowest_vcn;
    std::span<const std::byte> runlist;
    std::uint16_t flags;
};

/// An attribute list is present; resolving its extents belongs to volume reading.
struct AttrListMarker {};
/// A reparse attribute is present; this parser never follows its target.
struct ReparseMarker {};
/// An unhandled attribute type, retained without interpreting its payload.
struct OtherAttr {
    std::uint32_t type;
};

/// The attribute forms needed by the MFT index, without disk I/O.
using Attr =
    std::variant<StdInfo, FileNameAttr, DataAttr, AttrListMarker, ReparseMarker, OtherAttr>;

/// Iterate an already fixed-up record, bounded by its declared used bytes.
///
/// The caller retains the record for this iterator and any returned runlist spans.
/// Name views borrow aligned iterator storage and expire on the next next() call
/// or iterator destruction. Copying code units also avoids byte-buffer aliasing.
class AttrIterator {
  public:
    /// Validate the header and borrow the record; errors are returned by next().
    explicit AttrIterator(std::span<const std::byte> rec);
    /// Return one attribute, end at the marker/used boundary, or a sticky typed error.
    Expected<std::optional<Attr>, MftError> next();

  private:
    Expected<std::u16string_view, MftError> read_name(std::span<const std::byte> chars);

    std::span<const std::byte> record_;
    std::size_t position_ = 0, end_ = 0;
    std::optional<MftError> error_;
    std::array<char16_t, 255> name_storage_;
};

/// Convert unsigned 100 ns ticks since 1601 to Unix seconds, flooring subsecond times.
std::int64_t filetime_to_unix(std::uint64_t filetime);

} // namespace dafree
