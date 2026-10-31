#include "dafree/platform.hpp"

#include <algorithm>
#include <cstdint>
#include <limits>
#include <string>
#include <sys/mount.h>
#include <utility>
#include <vector>

namespace dafree::platform {

std::uint64_t volume_bytes(std::uint64_t blocks, std::uint64_t fragment_size) noexcept;

std::optional<VolumeInfo> volume_info(std::string_view path) {
    const std::string owned(path);
    struct statfs fs{};
    if (::statfs(owned.c_str(), &fs) != 0)
        return std::nullopt;
    VolumeInfo info;
    info.mount = fs.f_mntonname;
    info.fs_type = fs.f_fstypename;
    info.total = volume_bytes(fs.f_blocks, static_cast<std::uint64_t>(fs.f_bsize));
    info.free = volume_bytes(fs.f_bavail, static_cast<std::uint64_t>(fs.f_bsize));
    info.cluster_size = static_cast<std::uint32_t>(std::min<std::uint64_t>(
        static_cast<std::uint64_t>(fs.f_bsize), std::numeric_limits<std::uint32_t>::max()));
    info.serial = static_cast<std::uint32_t>(fs.f_fsid.val[0]);
    info.is_network = info.fs_type == "smbfs" || info.fs_type == "nfs" || info.fs_type == "afpfs" ||
                      info.fs_type == "webdav";
    return info;
}

std::vector<VolumeInfo> list_volumes() {
    struct statfs *mounts = nullptr;
    const int count = ::getmntinfo(&mounts, MNT_NOWAIT);
    std::vector<VolumeInfo> volumes;
    for (int index = 0; index < count; ++index) {
        if (auto info = volume_info(mounts[index].f_mntonname))
            volumes.push_back(std::move(*info));
    }
    return volumes;
}

} // namespace dafree::platform
