#pragma once

#include "dafree/model.hpp"

#include <cstdint>
#include <optional>
#include <span>
#include <string>
#include <string_view>
#include <utility>
#include <vector>

namespace dafree {

/// File kind returned by a filesystem backend without following links.
enum class EntryKind : std::uint8_t {
    File,
    Dir,
    Symlink,
    Junction,
    MountPoint,
    OtherReparse,
    Other
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

/// An unrecoverable filesystem operation failure.
class IoError : public Error {
  public:
    /// Construct an error for a path and a classified OS failure.
    IoError(std::string path, IssueKind kind, std::string message)
        : Error(message), path_(std::move(path)), kind_(kind) {}
    /// Return the path whose operation failed.
    [[nodiscard]] const std::string &path() const noexcept { return path_; }
    /// Return the classified reason.
    [[nodiscard]] IssueKind kind() const noexcept { return kind_; }

  private:
    std::string path_;
    IssueKind kind_;
};

/// Native metadata for one directory entry.
struct RawEntry {
    std::string name;
    EntryKind kind = EntryKind::Other;
    std::uint64_t size = 0, alloc = 0;
    std::optional<std::int64_t> mtime, btime, atime;
    std::uint64_t dev = 0;
    std::uint64_t ino_lo = 0, ino_hi = 0;
    std::uint32_t nlink = 0;
    bool hidden = false, system = false, sparse = false, compressed = false, cloud = false;
    bool access_denied = false;
    std::optional<OwnerKey> owner;
};

/// One non-recursive directory listing and its recoverable issues.
struct DirListing {
    std::vector<RawEntry> entries;
    bool partial = false;
    std::vector<ScanIssue> issues;
};

namespace platform {

/// Convert an absolute Windows drive or UNC path to verbatim form.
std::string to_verbatim(std::string_view path);

/// Free and total space and scan-relevant properties of one volume.
struct VolumeInfo {
    std::string mount, fs_type, label;
    std::uint64_t serial = 0, total = 0, free = 0;
    std::uint32_t cluster_size = 0;
    bool is_network = false, is_removable = false, supports_mft = false;
    std::optional<bool> is_rotational;
};

/// List direct children without following symbolic links.
DirListing read_dir(std::string_view dir);
/// Read metadata for a path without following its final symbolic link.
RawEntry stat_nofollow(std::string_view path);
/// Read metadata for the final target of a symbolic link.
RawEntry stat_follow(std::string_view path);
/// Read the volume containing a path when available.
std::optional<VolumeInfo> volume_info(std::string_view path);
/// List mounted volumes for drive and mount selection.
std::vector<VolumeInfo> list_volumes();
/// Read an owner identity and its display name.
std::optional<std::pair<OwnerKey, std::string>> owner_of(std::string_view path);
/// Resolve a POSIX user ID to a display name.
std::optional<std::string> name_for_uid(std::uint32_t uid);
/// Report whether the process has elevated privileges.
bool is_elevated();
/// Relaunch with elevated privileges, or throw when unsupported.
void relaunch_elevated(std::span<const std::string> args);

} // namespace platform
} // namespace dafree
