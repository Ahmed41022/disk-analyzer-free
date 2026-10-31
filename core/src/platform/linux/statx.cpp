#include "dafree/platform.hpp"
#include "statx_compat.hpp"

#include <algorithm>
#include <cerrno>
#include <cstdint>
#include <fcntl.h>
#include <limits>
#include <linux/stat.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/sysmacros.h>
#include <unistd.h>

namespace dafree::platform {

#ifdef STATX_ATTR_MOUNT_ROOT
static_assert(detail::kStatxMountRoot == STATX_ATTR_MOUNT_ROOT);
#endif

EntryKind kind_from_mode(mode_t mode) noexcept;

int statx_entry_at(int dirfd, const char *name, bool follow, RawEntry &entry) {
    struct statx metadata{};
    const int flags = follow ? 0 : AT_SYMLINK_NOFOLLOW;
    if (::syscall(SYS_statx, dirfd, name, flags, STATX_BASIC_STATS | STATX_BTIME, &metadata) != 0)
        return errno;

    entry.name = name;
    entry.kind = kind_from_mode(metadata.stx_mode);
    if (entry.kind == EntryKind::Dir &&
        detail::statx_is_mount_root(metadata.stx_attributes, metadata.stx_attributes_mask))
        entry.kind = EntryKind::MountPoint;
    entry.size = metadata.stx_size;
    entry.alloc = metadata.stx_blocks * 512u;
    entry.mtime = metadata.stx_mtime.tv_sec;
    entry.atime = metadata.stx_atime.tv_sec;
    if ((metadata.stx_mask & STATX_BTIME) != 0)
        entry.btime = metadata.stx_btime.tv_sec;
    entry.dev = static_cast<std::uint64_t>(makedev(metadata.stx_dev_major, metadata.stx_dev_minor));
    entry.ino_lo = metadata.stx_ino;
    entry.nlink =
        std::min<std::uint32_t>(metadata.stx_nlink, std::numeric_limits<std::uint32_t>::max());
    entry.hidden = !entry.name.empty() && entry.name.front() == '.';
    entry.sparse = entry.kind == EntryKind::File && entry.alloc < entry.size;
    entry.compressed = (metadata.stx_attributes & STATX_ATTR_COMPRESSED) != 0;
    entry.owner = OwnerKey::posix_uid(metadata.stx_uid);
    return 0;
}

} // namespace dafree::platform
