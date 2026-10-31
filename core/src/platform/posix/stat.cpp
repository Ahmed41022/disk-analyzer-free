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

namespace dafree {

IoError::IoError(std::string path, IssueKind kind, std::string message)
    : Error(message), path_(std::move(path)), kind_(kind) {}

namespace platform {

int open_directory(std::string_view path);
#ifdef __linux__
int statx_entry_at(int dirfd, const char *name, bool follow, RawEntry &entry);
#endif

IssueKind issue_kind(int code) noexcept {
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

EntryKind kind_from_mode(mode_t mode) noexcept {
    if (S_ISREG(mode))
        return EntryKind::File;
    if (S_ISDIR(mode))
        return EntryKind::Dir;
    if (S_ISLNK(mode))
        return EntryKind::Symlink;
    return EntryKind::Other;
}

RawEntry raw_from_stat(std::string_view name, const struct stat &metadata) {
    RawEntry entry;
    entry.name = name;
    entry.kind = kind_from_mode(metadata.st_mode);
    entry.size = metadata.st_size > 0 ? static_cast<std::uint64_t>(metadata.st_size) : 0;
    entry.alloc =
        metadata.st_blocks > 0 ? static_cast<std::uint64_t>(metadata.st_blocks) * 512u : 0;
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

int stat_entry_at(int dirfd, const char *name, bool follow, RawEntry &entry) {
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

static RawEntry stat_path(std::string_view input, bool follow) {
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
    const int dirfd = open_directory(parent);
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

RawEntry stat_nofollow(std::string_view path) { return stat_path(path, false); }

RawEntry stat_follow(std::string_view path) { return stat_path(path, true); }

} // namespace platform
} // namespace dafree
