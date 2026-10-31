#include "dafree/platform.hpp"

#include <array>
#include <cerrno>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <optional>
#include <string>
#include <sys/attr.h>
#include <sys/stat.h>
#include <sys/vnode.h>
#include <unistd.h>

namespace dafree::platform {

IssueKind issue_kind(int code) noexcept;
void add_entry(DirListing &listing, int fd, std::string_view dir, const char *name,
               unsigned char dtype);

template <class T>
static bool take(const char *record, std::size_t length, std::size_t &cursor, T &value) {
    if (cursor > length || sizeof(T) > length - cursor)
        return false;
    std::memcpy(&value, record + cursor, sizeof(T));
    cursor += sizeof(T);
    return true;
}

static bool parse_metadata(const char *record, std::size_t length, std::size_t cursor,
                           const attribute_set_t &returned, const char *name, RawEntry &entry) {
    entry.name = name;
    entry.hidden = entry.name.front() == '.';
    dev_t device = 0;
    fsobj_type_t type = VNON;
    std::uint64_t file_id = 0;
    if ((returned.commonattr & ATTR_CMN_DEVID) == 0 ||
        (returned.commonattr & ATTR_CMN_OBJTYPE) == 0 ||
        (returned.commonattr & ATTR_CMN_FILEID) == 0)
        return false;
    if (!take(record, length, cursor, device) || !take(record, length, cursor, type))
        return false;
    entry.dev = static_cast<std::uint64_t>(device);
    switch (type) {
    case VREG:
        entry.kind = EntryKind::File;
        break;
    case VDIR:
        entry.kind = EntryKind::Dir;
        break;
    case VLNK:
        entry.kind = EntryKind::Symlink;
        break;
    default:
        entry.kind = EntryKind::Other;
        break;
    }
    struct timespec timestamp{};
    if ((returned.commonattr & ATTR_CMN_CRTIME) != 0) {
        if (!take(record, length, cursor, timestamp))
            return false;
        entry.btime = timestamp.tv_sec;
    }
    if ((returned.commonattr & ATTR_CMN_MODTIME) != 0) {
        if (!take(record, length, cursor, timestamp))
            return false;
        entry.mtime = timestamp.tv_sec;
    }
    if ((returned.commonattr & ATTR_CMN_ACCTIME) != 0) {
        if (!take(record, length, cursor, timestamp))
            return false;
        entry.atime = timestamp.tv_sec;
    }
    if ((returned.commonattr & ATTR_CMN_OWNERID) != 0) {
        uid_t uid = 0;
        if (!take(record, length, cursor, uid))
            return false;
        entry.owner = OwnerKey::posix_uid(static_cast<std::uint32_t>(uid));
    }
    if ((returned.commonattr & ATTR_CMN_FLAGS) != 0) {
        std::uint32_t flags = 0;
        if (!take(record, length, cursor, flags))
            return false;
        entry.hidden = entry.hidden || (flags & UF_HIDDEN) != 0;
#ifdef UF_COMPRESSED
        entry.compressed = (flags & UF_COMPRESSED) != 0;
#endif
    }
    if (!take(record, length, cursor, file_id))
        return false;
    entry.ino_lo = file_id;
    if (entry.kind == EntryKind::Dir) {
        if ((returned.dirattr & ATTR_DIR_LINKCOUNT) != 0 &&
            !take(record, length, cursor, entry.nlink))
            return false;
        if ((returned.dirattr & ATTR_DIR_MOUNTSTATUS) != 0) {
            std::uint32_t mount_status = 0;
            if (!take(record, length, cursor, mount_status))
                return false;
            if ((mount_status & DIR_MNTSTATUS_MNTPOINT) != 0)
                entry.kind = EntryKind::MountPoint;
        }
        std::int64_t allocation = 0, data = 0;
        if ((returned.dirattr & ATTR_DIR_ALLOCSIZE) != 0) {
            if (!take(record, length, cursor, allocation))
                return false;
            entry.alloc = allocation > 0 ? static_cast<std::uint64_t>(allocation) : 0;
        }
        if ((returned.dirattr & ATTR_DIR_DATALENGTH) != 0) {
            if (!take(record, length, cursor, data))
                return false;
            entry.size = data > 0 ? static_cast<std::uint64_t>(data) : 0;
        }
    } else if (entry.kind == EntryKind::File) {
        if ((returned.fileattr & ATTR_FILE_LINKCOUNT) == 0 ||
            (returned.fileattr & ATTR_FILE_DATALENGTH) == 0 ||
            (returned.fileattr & ATTR_FILE_DATAALLOCSIZE) == 0)
            return false;
        std::int64_t data = 0, allocation = 0;
        if (!take(record, length, cursor, entry.nlink) || !take(record, length, cursor, data) ||
            !take(record, length, cursor, allocation))
            return false;
        entry.size = data > 0 ? static_cast<std::uint64_t>(data) : 0;
        entry.alloc = allocation > 0 ? static_cast<std::uint64_t>(allocation) : 0;
        entry.sparse = entry.alloc < entry.size;
    } else {
        return false;
    }
    return true;
}

std::optional<DirListing> list_getattrlistbulk(int fd, std::string_view path) {
    struct attrlist attributes{};
    attributes.bitmapcount = ATTR_BIT_MAP_COUNT;
    attributes.commonattr = ATTR_CMN_RETURNED_ATTRS | ATTR_CMN_NAME | ATTR_CMN_DEVID |
                            ATTR_CMN_OBJTYPE | ATTR_CMN_CRTIME | ATTR_CMN_MODTIME |
                            ATTR_CMN_ACCTIME | ATTR_CMN_OWNERID | ATTR_CMN_FLAGS | ATTR_CMN_FILEID;
    attributes.dirattr =
        ATTR_DIR_LINKCOUNT | ATTR_DIR_MOUNTSTATUS | ATTR_DIR_ALLOCSIZE | ATTR_DIR_DATALENGTH;
    attributes.fileattr = ATTR_FILE_LINKCOUNT | ATTR_FILE_DATALENGTH | ATTR_FILE_DATAALLOCSIZE;
    alignas(8) std::array<char, 64 * 1024> buffer{};
    DirListing listing;
    for (;;) {
        const int count = ::getattrlistbulk(fd, &attributes, buffer.data(), buffer.size(), 0);
        if (count == 0)
            return listing;
        if (count < 0) {
            if (listing.entries.empty())
                return std::nullopt;
            const int code = errno;
            listing.issues.push_back({std::string(path), issue_kind(code), std::strerror(code)});
            listing.partial = true;
            return listing;
        }
        std::size_t offset = 0;
        for (int index = 0; index < count; ++index) {
            if (offset + sizeof(std::uint32_t) > buffer.size()) {
                listing.issues.push_back(
                    {std::string(path), IssueKind::Io, "invalid getattrlistbulk record offset"});
                listing.partial = true;
                return listing;
            }
            std::uint32_t record_length = 0;
            std::memcpy(&record_length, buffer.data() + offset, sizeof(record_length));
            if (record_length <
                    sizeof(record_length) + sizeof(attribute_set_t) + sizeof(attrreference_t) ||
                offset + record_length > buffer.size()) {
                listing.issues.push_back(
                    {std::string(path), IssueKind::Io, "invalid getattrlistbulk record"});
                listing.partial = true;
                return listing;
            }
            attribute_set_t returned{};
            std::memcpy(&returned, buffer.data() + offset + sizeof(record_length),
                        sizeof(returned));
            if ((returned.commonattr & ATTR_CMN_NAME) == 0) {
                listing.issues.push_back(
                    {std::string(path), IssueKind::Io, "getattrlistbulk omitted entry name"});
                listing.partial = true;
                return listing;
            }
            const std::size_t base = sizeof(record_length) + sizeof(returned);
            attrreference_t reference{};
            std::memcpy(&reference, buffer.data() + offset + base, sizeof(reference));
            if (reference.attr_dataoffset < 0) {
                listing.issues.push_back(
                    {std::string(path), IssueKind::Io, "invalid getattrlistbulk name offset"});
                listing.partial = true;
                return listing;
            }
            const auto data = base + static_cast<std::size_t>(reference.attr_dataoffset);
            if (data >= record_length || reference.attr_length > record_length - data) {
                listing.issues.push_back(
                    {std::string(path), IssueKind::Io, "invalid getattrlistbulk name"});
                listing.partial = true;
                return listing;
            }
            const char *name = buffer.data() + offset + data;
            if (std::memchr(name, '\0', reference.attr_length) == nullptr) {
                listing.issues.push_back(
                    {std::string(path), IssueKind::Io, "unterminated getattrlistbulk name"});
                listing.partial = true;
                return listing;
            }
            RawEntry entry;
            if (parse_metadata(buffer.data() + offset, record_length, base + sizeof(reference),
                               returned, name, entry)) {
                listing.entries.push_back(std::move(entry));
            } else {
                add_entry(listing, fd, path, name, 0);
            }
            offset += record_length;
        }
    }
}

} // namespace dafree::platform
