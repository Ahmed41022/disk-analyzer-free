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

using VolumeInfo = dafree::VolumeInfo;

/// Return the host name and operating system name for scan provenance.
std::pair<std::string, std::string> system_identity();

/// Report the native separator convention for portable scanner path handling.
constexpr bool windows_paths() noexcept {
#ifdef _WIN32
    return true;
#else
    return false;
#endif
}

/// Report the planned platform path case policy.
constexpr bool case_insensitive_paths() noexcept {
#if defined(_WIN32) || defined(__APPLE__)
    return true;
#else
    return false;
#endif
}

/// Convert an absolute Windows drive or UNC path to verbatim form.
std::string to_verbatim(std::string_view path);

/// List direct children without following symbolic links.
DirListing read_dir(std::string_view dir);
/// List direct children while explicitly following the final directory link.
DirListing read_dir_follow(std::string_view dir);
/// Read metadata for a path without following its final symbolic link.
RawEntry stat_nofollow(std::string_view path);
/// Read metadata for the final target of a symbolic link.
RawEntry stat_follow(std::string_view path);
/// Read the volume containing a path when available.
std::optional<VolumeInfo> volume_info(std::string_view path);
/// List mounted volumes for drive and mount selection.
std::vector<VolumeInfo> list_volumes();
#ifdef _WIN32
/// Return the process peak working set in bytes, or no value if unavailable.
std::optional<std::uint64_t> peak_rss();
#endif
/// Read an owner identity and its display name.
std::optional<std::pair<OwnerKey, std::string>> owner_of(std::string_view path);
/// Open the native Windows property sheet for an absolute path, or return false.
bool show_properties(std::string_view path);
#ifdef _WIN32
/// Count SID-to-account cache hits for test verification.
std::uint64_t sid_cache_hits();
#endif
/// Resolve a POSIX user ID to a display name.
std::optional<std::string> name_for_uid(std::uint32_t uid);
/// Report whether the process has elevated privileges.
bool is_elevated();
/// Quote arguments (excluding argv[0]) for a Windows command line.
std::wstring quote_windows_args(std::span<const std::wstring> args);
/// Relaunch the current executable with explicit native arguments and request elevation.
/// Throws Cancelled if the request is declined and Unsupported on POSIX.
void relaunch_elevated(std::span<const std::string> args);

} // namespace platform
} // namespace dafree
