#include "internal.hpp"

#include <array>
#include <cwchar>
#include <winioctl.h>

namespace dafree::platform {

std::optional<VolumeInfo> volume_info(std::string_view path) {
    const auto native = detail::native_path(path);
    std::wstring mount(32768, L'\0');
    if (!::GetVolumePathNameW(native.c_str(), mount.data(), static_cast<DWORD>(mount.size())))
        return std::nullopt;
    mount.resize(std::wcslen(mount.c_str()));
    mount = detail::native_path(detail::to_wtf8(mount));
    std::array<wchar_t, 261> label{}, filesystem{};
    DWORD serial = 0, maximum_component = 0, flags = 0;
    if (!::GetVolumeInformationW(mount.c_str(), label.data(), static_cast<DWORD>(label.size()),
                                 &serial, &maximum_component, &flags, filesystem.data(),
                                 static_cast<DWORD>(filesystem.size())))
        return std::nullopt;
    ULARGE_INTEGER available{}, total{}, free{};
    if (!::GetDiskFreeSpaceExW(mount.c_str(), &available, &total, &free))
        return std::nullopt;
    DWORD sectors = 0, bytes = 0, free_clusters = 0, clusters = 0;
    if (!::GetDiskFreeSpaceW(mount.c_str(), &sectors, &bytes, &free_clusters, &clusters))
        return std::nullopt;
    VolumeInfo info;
    info.mount = detail::to_wtf8(mount);
    info.fs_type = detail::to_wtf8(filesystem.data());
    info.label = detail::to_wtf8(label.data());
    info.serial = serial;
    detail::UniqueHandle directory(::CreateFileW(
        mount.c_str(), FILE_READ_ATTRIBUTES, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        nullptr, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS, nullptr));
    if (directory.get() != INVALID_HANDLE_VALUE)
        info.serial = detail::volume_serial(directory.get(), path);
    info.total = total.QuadPart;
    info.free = available.QuadPart;
    info.cluster_size = sectors * bytes;
    const UINT type = ::GetDriveTypeW(mount.c_str());
    info.is_network = type == DRIVE_REMOTE;
    info.is_removable = type == DRIVE_REMOVABLE;
    info.supports_mft = !info.is_network && info.fs_type == "NTFS";
    if (!info.is_network && mount.starts_with(L"\\\\?\\") && mount.size() >= 6 &&
        mount[5] == L':') {
        const std::wstring device = L"\\\\.\\" + mount.substr(4, 2);
        detail::UniqueHandle handle(::CreateFileW(device.c_str(), 0,
                                                  FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr,
                                                  OPEN_EXISTING, 0, nullptr));
        STORAGE_PROPERTY_QUERY query{};
        query.PropertyId = StorageDeviceSeekPenaltyProperty;
        query.QueryType = PropertyStandardQuery;
        DEVICE_SEEK_PENALTY_DESCRIPTOR descriptor{};
        DWORD returned = 0;
        if (handle.get() != INVALID_HANDLE_VALUE &&
            ::DeviceIoControl(handle.get(), IOCTL_STORAGE_QUERY_PROPERTY, &query, sizeof(query),
                              &descriptor, sizeof(descriptor), &returned, nullptr))
            info.is_rotational = descriptor.IncursSeekPenalty != 0;
    }
    return info;
}

std::vector<VolumeInfo> list_volumes() {
    struct RestoreErrorMode {
        DWORD previous;
        bool changed;
        ~RestoreErrorMode() {
            if (changed)
                ::SetThreadErrorMode(previous, nullptr);
        }
    };
    const DWORD previous_mode = ::GetThreadErrorMode();
    const RestoreErrorMode restore{
        previous_mode,
        ::SetThreadErrorMode(previous_mode | SEM_FAILCRITICALERRORS, nullptr) != FALSE};
    // Capacity probes of empty removable drives must report failure, not show an OS dialog.
    const DWORD length = ::GetLogicalDriveStringsW(0, nullptr);
    if (length == 0)
        return {};
    std::wstring drives(length + 1, L'\0');
    if (::GetLogicalDriveStringsW(static_cast<DWORD>(drives.size()), drives.data()) == 0)
        return {};
    std::vector<VolumeInfo> volumes;
    for (const wchar_t *drive = drives.data(); *drive != L'\0'; drive += std::wcslen(drive) + 1) {
        if (auto info = volume_info(detail::to_wtf8(drive)))
            volumes.push_back(std::move(*info));
    }
    return volumes;
}

} // namespace dafree::platform
