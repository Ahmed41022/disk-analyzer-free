#include "dafree/platform.hpp"

#include <algorithm>
#include <cstdint>
#include <fstream>
#include <limits>
#include <sstream>
#include <string>
#include <sys/stat.h>
#include <sys/statvfs.h>
#include <sys/sysmacros.h>
#include <utility>
#include <vector>

namespace dafree::platform {

std::uint64_t volume_bytes(std::uint64_t blocks, std::uint64_t fragment_size) noexcept;

struct MountRow {
    std::string path;
    std::string fs_type;
};

static std::string unescape_mount(std::string_view input) {
    std::string output;
    output.reserve(input.size());
    for (std::size_t index = 0; index < input.size(); ++index) {
        if (input[index] == '\\' && index + 3u < input.size() && input[index + 1u] >= '0' &&
            input[index + 1u] <= '7' && input[index + 2u] >= '0' && input[index + 2u] <= '7' &&
            input[index + 3u] >= '0' && input[index + 3u] <= '7') {
            const unsigned value = static_cast<unsigned>(input[index + 1u] - '0') * 64u +
                                   static_cast<unsigned>(input[index + 2u] - '0') * 8u +
                                   static_cast<unsigned>(input[index + 3u] - '0');
            output.push_back(static_cast<char>(value));
            index += 3u;
        } else {
            output.push_back(input[index]);
        }
    }
    return output;
}

static std::vector<MountRow> mount_rows() {
    std::ifstream input("/proc/self/mountinfo");
    std::vector<MountRow> rows;
    std::string line;
    while (std::getline(input, line)) {
        const std::size_t separator = line.find(" - ");
        if (separator == std::string::npos)
            continue;
        std::istringstream before(line.substr(0, separator));
        std::string id, parent, device, root, mount;
        if (!(before >> id >> parent >> device >> root >> mount))
            continue;
        std::istringstream after(line.substr(separator + 3u));
        std::string fs_type;
        if (!(after >> fs_type))
            continue;
        rows.push_back({unescape_mount(mount), fs_type});
    }
    return rows;
}

static bool contains_path(std::string_view path, std::string_view mount) {
    return mount == "/" ||
           (path.starts_with(mount) && (path.size() == mount.size() || path[mount.size()] == '/'));
}

static std::optional<bool> sysfs_flag(unsigned major_id, unsigned minor_id,
                                      std::string_view filename) {
    const std::string base =
        "/sys/dev/block/" + std::to_string(major_id) + ":" + std::to_string(minor_id);
    for (const std::string &candidate :
         {base + "/" + std::string(filename), base + "/../" + std::string(filename)}) {
        std::ifstream input(candidate);
        int value = 0;
        if (input >> value)
            return value != 0;
    }
    return std::nullopt;
}

std::optional<VolumeInfo> volume_info(std::string_view path) {
    const std::string owned(path);
    struct statvfs fs{};
    struct stat metadata{};
    if (::statvfs(owned.c_str(), &fs) != 0 || ::stat(owned.c_str(), &metadata) != 0)
        return std::nullopt;

    VolumeInfo info;
    const auto rows = mount_rows();
    for (const MountRow &row : rows) {
        if (contains_path(path, row.path) && row.path.size() > info.mount.size()) {
            info.mount = row.path;
            info.fs_type = row.fs_type;
        }
    }
    if (info.mount.empty())
        info.mount = "/";
    const std::uint64_t fragment = fs.f_frsize != 0 ? fs.f_frsize : fs.f_bsize;
    info.total = volume_bytes(fs.f_blocks, fragment);
    info.free = volume_bytes(fs.f_bavail, fragment);
    info.cluster_size = static_cast<std::uint32_t>(
        std::min<std::uint64_t>(fragment, std::numeric_limits<std::uint32_t>::max()));
    info.serial = static_cast<std::uint64_t>(metadata.st_dev);
    info.is_network = info.fs_type == "nfs" || info.fs_type == "cifs" || info.fs_type == "smb3" ||
                      info.fs_type == "fuse.sshfs";
    info.is_removable =
        sysfs_flag(major(metadata.st_dev), minor(metadata.st_dev), "removable").value_or(false);
    info.is_rotational =
        sysfs_flag(major(metadata.st_dev), minor(metadata.st_dev), "queue/rotational");
    return info;
}

std::vector<VolumeInfo> list_volumes() {
    std::vector<VolumeInfo> volumes;
    for (const MountRow &row : mount_rows()) {
        if (auto info = volume_info(row.path))
            volumes.push_back(std::move(*info));
    }
    return volumes;
}

} // namespace dafree::platform
