#pragma once

#include <array>
#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace dafree {

/// Requested scanning strategy.
enum class ScanMode { Auto, Walk, Mft };
/// Owner lookup policy.
enum class OwnerMode { Off, Lazy, Eager };
/// Logical-byte accounting for additional hard links.
enum class HardlinkMode { Dedup, CountAll };
/// Strategy actually used for a scan.
enum class ScanModeUsed { Walk, Mft, Sftp };
/// Observable scan lifecycle.
enum class ScanState : std::uint8_t { Running, Paused, Finalizing, Done, Cancelled, Failed };

/// Entries removed from both the scan tree and its totals.
struct ExcludeRules {
    std::vector<std::string> paths;
    std::vector<std::string> globs;
    bool hidden = false;
    bool system = false;
};

/// Inputs and policies retained with the resulting tree.
struct ScanOptions {
    std::vector<std::string> targets;
    ScanMode mode = ScanMode::Auto;
    unsigned threads = 0;
    bool follow_symlinks = false, cross_filesystems = false;
    ExcludeRules exclude;
    OwnerMode owner = OwnerMode::Lazy;
    HardlinkMode hardlinks = HardlinkMode::Dedup;
    bool include_ads = false, show_ntfs_metafiles = true;
    std::uint32_t progress_interval_ms = 250;
};

/// Reason a filesystem entry could not be enumerated completely.
enum class IssueKind : std::uint8_t {
    AccessDenied,
    NotFound,
    PathTooLong,
    InvalidName,
    Io,
    Timeout,
    SymlinkLoop,
    Orphaned,
    Changed,
    Other
};

/// A recoverable issue tied to a native path.
struct ScanIssue {
    std::string path;
    IssueKind kind = IssueKind::Other;
    std::string message;
};

/// All issue counts and the first 1,000 diagnostics, independent of live draining.
struct IssueSummary {
    std::array<std::uint64_t, 10> counts{};
    std::vector<ScanIssue> first;
    std::uint64_t total = 0, overflow = 0;
};

/// Free space and scan-relevant properties of one volume.
struct VolumeInfo {
    std::string mount, fs_type, label;
    std::uint64_t serial = 0, total = 0, free = 0;
    std::uint32_t cluster_size = 0;
    bool is_network = false, is_removable = false, supports_mft = false;
    std::optional<bool> is_rotational;
};

/// Provenance, effective options, and diagnostics associated with a tree.
struct ScanMeta {
    std::int64_t started_at = 0, finished_at = 0;
    ScanModeUsed mode = ScanModeUsed::Walk;
    ScanOptions options;
    std::string host, os, app_version;
    std::vector<VolumeInfo> volumes;
    IssueSummary issues;
    bool cancelled = false;
};

/// A non-blocking progress snapshot.
struct ScanProgress {
    std::uint64_t files = 0, dirs = 0, bytes = 0, alloc = 0, issues = 0;
    std::string current;
    std::uint64_t elapsed_ms = 0;
    ScanState state = ScanState::Running;
    std::optional<std::uint64_t> est_total;
    ScanModeUsed mode = ScanModeUsed::Walk;
};

/// Informational scan policy or volume notices.
struct Notice {
    enum Kind { FastModeUnavailable, NetworkVolume, RotationalDisk, HardlinkDedupDisabled } kind;
    std::string detail;
};

} // namespace dafree
