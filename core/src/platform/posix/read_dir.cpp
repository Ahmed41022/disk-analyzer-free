#include "dafree/platform.hpp"
#include "fd.hpp"

#include <array>
#include <cerrno>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <dirent.h>
#include <fcntl.h>
#include <memory>
#include <optional>
#include <string>
#include <sys/types.h>
#ifdef __linux__
#include <sys/syscall.h>
#endif
#include <unistd.h>

namespace dafree::platform {

IssueKind issue_kind(int code) noexcept;
int stat_entry_at(int dirfd, const char *name, bool follow, RawEntry &entry);
#ifdef __APPLE__
std::optional<DirListing> list_getattrlistbulk(int fd, std::string_view path);
#endif

int open_directory(std::string_view path) {
    if (path.empty()) {
        errno = ENOENT;
        return -1;
    }
    const std::string owned(path);
    const int direct = ::open(owned.c_str(), O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (direct >= 0 || errno != ENAMETOOLONG)
        return direct;

    const bool absolute = path.front() == '/';
    int current = ::open(absolute ? "/" : ".", O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    if (current < 0)
        return -1;
    detail::UniqueFd guard(current);
    std::size_t begin = 0;
    while (begin < path.size()) {
        while (begin < path.size() && path[begin] == '/')
            ++begin;
        if (begin == path.size())
            break;
        const std::size_t end = path.find('/', begin);
        const std::size_t stop = end == std::string_view::npos ? path.size() : end;
        const std::string component(path.substr(begin, stop - begin));
        std::size_t next_component = stop;
        while (next_component < path.size() && path[next_component] == '/')
            ++next_component;
        const bool final = next_component == path.size();
        const int next = ::openat(current, component.c_str(),
                                  O_RDONLY | O_DIRECTORY | O_CLOEXEC | (final ? O_NOFOLLOW : 0));
        const int saved = errno;
        guard.reset(next);
        if (next < 0) {
            errno = saved;
            return -1;
        }
        current = next;
        begin = next_component;
    }
    return guard.release();
}

static EntryKind kind_from_dtype(unsigned char type) noexcept {
    switch (type) {
    case DT_REG:
        return EntryKind::File;
    case DT_DIR:
        return EntryKind::Dir;
    case DT_LNK:
        return EntryKind::Symlink;
    default:
        return EntryKind::Other;
    }
}

void add_entry(DirListing &listing, int fd, std::string_view dir, const char *name,
               unsigned char dtype) {
    if (std::strcmp(name, ".") == 0 || std::strcmp(name, "..") == 0)
        return;
    RawEntry entry;
    const int code = stat_entry_at(fd, name, false, entry);
    if (code == 0) {
        listing.entries.push_back(std::move(entry));
        return;
    }
    std::string path(dir);
    if (path.empty() || path.back() != '/')
        path.push_back('/');
    path.append(name);
    listing.issues.push_back({path, issue_kind(code), std::strerror(code)});
    listing.partial = true;
    if (code == EACCES || code == EPERM) {
        entry.name = name;
        entry.kind = kind_from_dtype(dtype);
        entry.hidden = entry.name.front() == '.';
        entry.access_denied = true;
        listing.entries.push_back(std::move(entry));
    }
}

static DirListing list_readdir(int fd, std::string_view path) {
    DirListing listing;
    DIR *stream = ::fdopendir(fd);
    if (stream == nullptr) {
        const int code = errno;
        ::close(fd);
        throw IoError(std::string(path), issue_kind(code), std::strerror(code));
    }
    const auto close_stream = [](DIR *directory) { ::closedir(directory); };
    std::unique_ptr<DIR, decltype(close_stream)> guard(stream, close_stream);
    for (;;) {
        errno = 0;
        dirent *item = ::readdir(stream);
        if (item == nullptr) {
            if (errno != 0) {
                const int code = errno;
                listing.issues.push_back(
                    {std::string(path), issue_kind(code), std::strerror(code)});
                listing.partial = true;
            }
            break;
        }
        add_entry(listing, fd, path, item->d_name, item->d_type);
    }
    return listing;
}

#ifdef __linux__
static DirListing list_getdents(int fd, std::string_view path) {
    detail::UniqueFd guard(fd);
    DirListing listing;
    alignas(8) std::array<char, 64 * 1024> buffer{};
    for (;;) {
        const long bytes = ::syscall(SYS_getdents64, fd, buffer.data(), buffer.size());
        if (bytes == 0)
            break;
        if (bytes < 0) {
            const int code = errno;
            if (code == ENOSYS)
                return list_readdir(guard.release(), path);
            listing.issues.push_back({std::string(path), issue_kind(code), std::strerror(code)});
            listing.partial = true;
            break;
        }
        const std::size_t length = static_cast<std::size_t>(bytes);
        std::size_t offset = 0;
        while (offset + 19u <= length) {
            std::uint16_t record_length = 0;
            std::memcpy(&record_length, buffer.data() + offset + 16u, sizeof(record_length));
            if (record_length < 20u || offset + record_length > length)
                break;
            const unsigned char dtype = static_cast<unsigned char>(buffer[offset + 18u]);
            const char *name = buffer.data() + offset + 19u;
            if (std::memchr(name, '\0', record_length - 19u) == nullptr)
                break;
            add_entry(listing, fd, path, name, dtype);
            offset += record_length;
        }
        if (offset != length) {
            listing.issues.push_back(
                {std::string(path), IssueKind::Io, "invalid getdents64 record"});
            listing.partial = true;
            break;
        }
    }
    return listing;
}
#endif

DirListing read_dir(std::string_view path) {
    const int fd = open_directory(path);
    if (fd < 0) {
        const int code = errno;
        throw IoError(std::string(path), issue_kind(code), std::strerror(code));
    }
    detail::UniqueFd guard(fd);
#ifdef __linux__
    return list_getdents(guard.release(), path);
#else
#ifdef __APPLE__
    if (auto bulk = list_getattrlistbulk(fd, path)) {
        return std::move(*bulk);
    }
    guard.reset(-1);
    const int fallback = open_directory(path);
    if (fallback < 0) {
        const int code = errno;
        throw IoError(std::string(path), issue_kind(code), std::strerror(code));
    }
    return list_readdir(fallback, path);
#endif
#ifndef __APPLE__
    return list_readdir(guard.release(), path);
#endif
#endif
}

} // namespace dafree::platform
