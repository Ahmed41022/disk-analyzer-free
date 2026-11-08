#pragma once

#include "dafree/error.hpp"
#include "dafree/scan_types.hpp"

#include <array>
#include <cstddef>
#include <cstdint>
#include <memory>
#include <optional>
#include <span>
#include <string>
#include <string_view>
#include <variant>
#include <vector>

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
// Preserve the established public/native enum representation.
// NOLINTNEXTLINE(performance-enum-size)
enum class MftError { BadSignature, BadFixup, OutOfBounds, Unsupported };

/// Decode a complete NTFS v3 record header without reading outside its span.
///
/// The fixed prefix includes the unexposed next-attribute-id storage (42 bytes).
/// The aligned USA must follow that prefix and precede the first aligned attribute;
/// both must fit bytes_used <= bytes_allocated <= rec.size(). Unknown flags remain
/// intact. Sector geometry and update-sequence values are checked by apply_fixups.
auto parse_header(std::span<const std::byte> rec) -> Expected<RecordHeader, MftError>;

/// Verify every sector's update-sequence value, then restore its saved trailer.
///
/// The declared bytes_allocated must equal rec.size(), and USA count must equal
/// rec.size() / sector_size + 1. Invalid inputs return an error without partially
/// restoring the record.
auto apply_fixups(std::span<std::byte> rec, std::size_t sector_size) -> Expected<void, MftError>;

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
    auto next() -> Expected<std::optional<Attr>, MftError>;

  private:
    auto read_name(std::span<const std::byte> chars) -> Expected<std::u16string_view, MftError>;

    std::span<const std::byte> record_;
    std::size_t position_ = 0, end_ = 0;
    std::optional<MftError> error_;
    // NTFS filename attributes contain at most 255 UTF-16 code units.
    // NOLINTNEXTLINE(cppcoreguidelines-avoid-magic-numbers)
    std::array<char16_t, 255> name_storage_;
};

/// Convert unsigned 100 ns ticks since 1601 to Unix seconds, flooring subsecond times.
auto filetime_to_unix(std::uint64_t filetime) -> std::int64_t;

/// A cluster extent; no LCN denotes a sparse run, and clusters is nonzero.
struct Run {
    std::optional<std::int64_t> lcn;
    std::uint64_t clusters = 0;
};

/// Decode zero-terminated mapping pairs with checked lengths, deltas and VCN totals.
///
/// Sparse runs do not change the previous physical LCN; physical cluster zero is
/// valid. Malformed/overflowing encodings return OutOfBounds. Output above 64 MiB
/// returns Unsupported before allocation; valid output uses one exact reservation.
/// Standard-library checked-iterator bookkeeping is separate from run storage.
auto decode_runlist(std::span<const std::byte> bytes) -> Expected<std::vector<Run>, MftError>;

class Tree;
namespace mft_detail {
struct IndexData;
}

/// Retain parsed, owned MFT summaries independently of source chunks and ingest order.
class MftIndex {
  public:
    /// Create an empty sparse index; record numbers never determine allocation size.
    MftIndex();
    /// Release all retained summaries.
    ~MftIndex();
    MftIndex(const MftIndex &) = delete;
    auto operator=(const MftIndex &) -> MftIndex & = delete;
    /// Transfer the retained summaries.
    MftIndex(MftIndex &&) noexcept;
    /// Replace summaries with those owned by another index.
    auto operator=(MftIndex &&) noexcept -> MftIndex &;
    /// Verify/restore a raw record and copy only retained attributes; failures are issues.
    void ingest(std::uint64_t record_no, std::span<std::byte> rec, std::size_t sector);
    /// Combine independent parser batches; duplicates become conflicts rather than overwrite.
    void merge(MftIndex &&other);

  private:
    friend auto build_tree_from_mft(const MftIndex &, std::string_view,
                                    std::optional<std::string_view>, const ScanOptions &,
                                    IssueSink &) -> Tree;
    std::unique_ptr<mft_detail::IndexData> data_;
};

/// Encode UTF-16 losslessly, combining valid pairs and preserving lone surrogates.
auto utf16_to_wtf8(std::u16string_view input) -> std::string;

/// Build a breadth-first tree rooted at record 5 or a selected relative/absolute subtree.
///
/// Input and output retain native names. NTFS lookup is case/separator insensitive on
/// every OS. No filesystem calls or reparse traversal occur. Issues are counted in the
/// tree metadata, with the first 1,000 retained and every issue delivered to a nonempty sink.
auto build_tree_from_mft(const MftIndex &, std::string_view root_path,
                         std::optional<std::string_view> subtree, const ScanOptions &, IssueSink &)
    -> Tree;

} // namespace dafree
