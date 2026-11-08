#include "dafree/platform.hpp"
#include "fd.hpp"

#include <algorithm>
#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <limits>
#include <string>
#include <sys/stat.h>
#include <unistd.h>

namespace dafree::platform {

constexpr std::uint64_t kStatBlockBytes = 512;

auto open_parent_directory(std::string_view path) -> int;
#ifdef __linux__
auto statx_entry_at(int dirfd, const char *name, bool follow, RawEntry &entry) -> int;
#endif

auto issue_kind(int code) noexcept -> IssueKind {
    switch (code) {
    case EACCES:
    case EPERM:
        return IssueKind::AccessDenied;
    case ENOENT:
    case ENOTDIR:
        return IssueKind::NotFound;
    case ENAMETOOLONG:
        return IssueKind::PathTooLong;
    default:
        return IssueKind::Io;
    }
}

auto kind_from_mode(mode_t mode) noexcept -> EntryKind {
    if (S_ISREG(mode))
        return EntryKind::File;
    if (S_ISDIR(mode))
        return EntryKind::Dir;
    if (S_ISLNK(mode))
        return EntryKind::Symlink;
    return EntryKind::Other;
}

auto raw_from_stat(std::string_view name, const struct stat &metadata) -> RawEntry {
    RawEntry entry;
    entry.name = name;
    entry.kind = kind_from_mode(metadata.st_mode);
    entry.size = metadata.st_size > 0 ? static_cast<std::uint64_t>(metadata.st_size) : 0;
    entry.alloc = metadata.st_blocks > 0
                      ? static_cast<std::uint64_t>(metadata.st_blocks) * kStatBlockBytes
                      : 0;
    entry.mtime = static_cast<std::int64_t>(metadata.st_mtime);
    entry.atime = static_cast<std::int64_t>(metadata.st_atime);
#ifdef __APPLE__
    entry.btime = static_cast<std::int64_t>(metadata.st_birthtime);
#endif
    entry.dev = static_cast<std::uint64_t>(metadata.st_dev);
    entry.ino_lo = static_cast<std::uint64_t>(metadata.st_ino);
    entry.nlink = static_cast<std::uint32_t>(std::min<std::uint64_t>(
        static_cast<std::uint64_t>(metadata.st_nlink), std::numeric_limits<std::uint32_t>::max()));
    entry.hidden = !name.empty() && name.front() == '.';
#ifdef __APPLE__
    entry.hidden = entry.hidden || (metadata.st_flags & UF_HIDDEN) != 0;
#endif
    entry.sparse = entry.kind == EntryKind::File && entry.alloc < entry.size;
    entry.owner = OwnerKey::posix_uid(static_cast<std::uint32_t>(metadata.st_uid));
    return entry;
}

auto stat_entry_at(int dirfd, const char *name, bool follow, RawEntry &entry) -> int {
#ifdef __linux__
    const int statx_result = statx_entry_at(dirfd, name, follow, entry);
    if (statx_result != ENOSYS)
        return statx_result;
#endif
    struct stat metadata{};
    if (::fstatat(dirfd, name, &metadata, follow ? 0 : AT_SYMLINK_NOFOLLOW) != 0)
        return errno;
    entry = raw_from_stat(name, metadata);
    return 0;
}

static auto stat_path(std::string_view input, bool follow) -> RawEntry {
    if (input.empty())
        throw IoError("", IssueKind::NotFound, "empty path");
    std::string path(input);
    while (path.size() > 1 && path.back() == '/')
        path.pop_back();
    const auto separator = path.find_last_of('/');
    const std::string parent =
        separator == std::string::npos ? "." : (separator == 0 ? "/" : path.substr(0, separator));
    const std::string name =
        separator == std::string::npos
            ? path
            : (separator + 1 == path.size() ? "." : path.substr(separator + 1));
    const int dirfd = open_parent_directory(parent);
    if (dirfd < 0) {
        const int code = errno;
        throw IoError(path, issue_kind(code), std::strerror(code));
    }
    detail::UniqueFd guard(dirfd);
    RawEntry entry;
    const int code = stat_entry_at(guard.get(), name.c_str(), follow, entry);
    if (code != 0)
        throw IoError(path, issue_kind(code), std::strerror(code));
    return entry;
}

auto stat_nofollow(std::string_view path) -> RawEntry { return stat_path(path, false); }

auto stat_follow(std::string_view path) -> RawEntry { return stat_path(path, true); }

} // namespace dafree::platform
