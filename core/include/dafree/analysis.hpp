#pragma once

#include "dafree/model.hpp"

#include <cstdint>
#include <optional>
#include <span>
#include <string>
#include <string_view>
#include <vector>

namespace dafree {

enum class SortKey : std::uint8_t;

/// Timestamp selected by filters and age analysis.
// Preserve the established public/native enum representation.
// NOLINTNEXTLINE(performance-enum-size)
enum class TimeField { Modified, Created, Accessed };

/// Stable extension category IDs shared by analysis and view rows.
enum class ExtCategory : std::uint8_t {
    Image,
    Video,
    Audio,
    Archive,
    Document,
    Code,
    Executable,
    DiskImage,
    System,
    Other
};

/// Candidate kind for a largest-items report.
// Preserve the established public/native enum representation.
// NOLINTNEXTLINE(performance-enum-size)
enum class TopKind { Files, Dirs };

/// Rank at most n matching nodes within scope, with stable ties.
auto top_n(const Tree &, NodeId scope, TopKind, std::size_t n, SortKey by, bool leaf_only = false)
    -> std::vector<NodeId>;

/// Counts and byte totals for an extension, or the empty extension group.
struct ExtStat {
    std::string ext;
    std::uint64_t files = 0, size = 0, alloc = 0;
    ExtCategory category = ExtCategory::Other;
};

/// Classify a normalized extension without a leading dot.
auto classify_extension(std::string_view ext) noexcept -> ExtCategory;

/// Return file totals grouped by extension, ordered by descending logical size.
auto ext_breakdown(const Tree &, NodeId scope) -> std::vector<ExtStat>;

/// Age interval with an exclusive upper bound, or an unbounded final interval.
struct AgeBucket {
    std::string label;
    std::optional<std::uint64_t> max_age_secs;
};

/// Counts and byte totals for an age interval.
struct AgeStat {
    std::size_t bucket = 0;
    std::uint64_t files = 0, size = 0, alloc = 0;
};

/// Partition files by timestamp, appending a bucket for missing values.
auto age_histogram(const Tree &, NodeId scope, TimeField, std::span<const AgeBucket>,
                   std::uint32_t now) -> std::vector<AgeStat>;

} // namespace dafree
