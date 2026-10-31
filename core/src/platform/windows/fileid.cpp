#include "internal.hpp"

#include <array>
#include <cstring>
#include <limits>
#include <stdexcept>
#include <winioctl.h>

namespace dafree::platform {

std::pair<std::string, std::string> system_identity() {
    std::array<wchar_t, MAX_COMPUTERNAME_LENGTH + 1> host{};
    DWORD size = static_cast<DWORD>(host.size());
    if (!::GetComputerNameW(host.data(), &size))
        return {"unknown", "Windows"};
    return {detail::to_wtf8(std::wstring_view(host.data(), size)), "Windows"};
}

namespace detail {

std::wstring from_wtf8(std::string_view input) {
    std::wstring output;
    output.reserve(input.size());
    for (std::size_t index = 0; index < input.size();) {
        const auto first = static_cast<unsigned char>(input[index++]);
        unsigned value = first;
        unsigned continuation = 0;
        unsigned minimum = 0;
        if (first >= 0xF0 && first <= 0xF4) {
            value = first & 7u;
            continuation = 3;
            minimum = 0x10000;
        } else if (first >= 0xE0 && first <= 0xEF) {
            value = first & 15u;
            continuation = 2;
            minimum = 0x800;
        } else if (first >= 0xC2 && first <= 0xDF) {
            value = first & 31u;
            continuation = 1;
            minimum = 0x80;
        } else if (first >= 0x80)
            throw std::invalid_argument("invalid WTF-8 path");
        for (unsigned part = 0; part < continuation; ++part) {
            if (index == input.size())
                throw std::invalid_argument("truncated WTF-8 path");
            const auto next = static_cast<unsigned char>(input[index++]);
            if ((next & 0xC0u) != 0x80u)
                throw std::invalid_argument("invalid WTF-8 continuation");
            value = (value << 6u) | (next & 0x3Fu);
        }
        if (value < minimum || value > 0x10FFFFu || value == 0)
            throw std::invalid_argument("invalid WTF-8 code point");
        if (value <= 0xFFFFu)
            output.push_back(static_cast<wchar_t>(value));
        else {
            value -= 0x10000u;
            output.push_back(static_cast<wchar_t>(0xD800u + (value >> 10u)));
            output.push_back(static_cast<wchar_t>(0xDC00u + (value & 0x3FFu)));
        }
    }
    return output;
}

std::string to_wtf8(std::wstring_view input) {
    std::string output;
    output.reserve(input.size());
    for (std::size_t index = 0; index < input.size(); ++index) {
        unsigned value = static_cast<unsigned>(input[index]);
        if (value >= 0xD800u && value <= 0xDBFFu && index + 1 < input.size()) {
            const unsigned low = static_cast<unsigned>(input[index + 1]);
            if (low >= 0xDC00u && low <= 0xDFFFu) {
                value = 0x10000u + ((value - 0xD800u) << 10u) + low - 0xDC00u;
                ++index;
            }
        }
        if (value < 0x80u)
            output.push_back(static_cast<char>(value));
        else if (value < 0x800u) {
            output.push_back(static_cast<char>(0xC0u | (value >> 6u)));
            output.push_back(static_cast<char>(0x80u | (value & 0x3Fu)));
        } else if (value < 0x10000u) {
            output.push_back(static_cast<char>(0xE0u | (value >> 12u)));
            output.push_back(static_cast<char>(0x80u | ((value >> 6u) & 0x3Fu)));
            output.push_back(static_cast<char>(0x80u | (value & 0x3Fu)));
        } else {
            output.push_back(static_cast<char>(0xF0u | (value >> 18u)));
            output.push_back(static_cast<char>(0x80u | ((value >> 12u) & 0x3Fu)));
            output.push_back(static_cast<char>(0x80u | ((value >> 6u) & 0x3Fu)));
            output.push_back(static_cast<char>(0x80u | (value & 0x3Fu)));
        }
    }
    return output;
}

std::wstring native_path(std::string_view input) {
    const auto wide = from_wtf8(input);
    if (input.starts_with("\\\\?\\"))
        return wide;
    const DWORD length = ::GetFullPathNameW(wide.c_str(), 0, nullptr, nullptr);
    if (length == 0)
        fail(input, ::GetLastError());
    std::wstring absolute(length, L'\0');
    const DWORD written = ::GetFullPathNameW(wide.c_str(), length, absolute.data(), nullptr);
    if (written == 0 || written >= length)
        fail(input, ::GetLastError());
    absolute.resize(written);
    return from_wtf8(to_verbatim(to_wtf8(absolute)));
}

[[noreturn]] void fail(std::string_view path, DWORD code) {
    IssueKind kind = IssueKind::Io;
    if (code == ERROR_ACCESS_DENIED || code == ERROR_PRIVILEGE_NOT_HELD)
        kind = IssueKind::AccessDenied;
    else if (code == ERROR_FILE_NOT_FOUND || code == ERROR_PATH_NOT_FOUND)
        kind = IssueKind::NotFound;
    else if (code == ERROR_FILENAME_EXCED_RANGE)
        kind = IssueKind::PathTooLong;
    throw IoError(std::string(path), kind, "Windows error " + std::to_string(code));
}

std::uint64_t volume_serial(HANDLE handle, std::string_view path) {
    FILE_ID_INFO identity{};
    if (::GetFileInformationByHandleEx(handle, FileIdInfo, &identity, sizeof(identity)))
        return identity.VolumeSerialNumber;
    BY_HANDLE_FILE_INFORMATION legacy{};
    if (!::GetFileInformationByHandle(handle, &legacy))
        fail(path, ::GetLastError());
    return legacy.dwVolumeSerialNumber;
}

std::optional<std::int64_t> unix_time(LONGLONG ticks) {
    if (ticks == 0)
        return std::nullopt;
    return ticks / 10'000'000 - 11'644'473'600LL;
}

static bool volume_mount(std::wstring_view path) {
    const std::wstring owned(path);
    UniqueHandle handle(::CreateFileW(
        owned.c_str(), 0, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr,
        OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, nullptr));
    if (handle.get() == INVALID_HANDLE_VALUE)
        return false;
    alignas(8) std::array<std::byte, MAXIMUM_REPARSE_DATA_BUFFER_SIZE> buffer{};
    DWORD returned = 0;
    if (!::DeviceIoControl(handle.get(), FSCTL_GET_REPARSE_POINT, nullptr, 0, buffer.data(),
                           static_cast<DWORD>(buffer.size()), &returned, nullptr) ||
        returned < 16)
        return false;
    USHORT offset = 0, length = 0;
    std::memcpy(&offset, buffer.data() + 8, sizeof(offset));
    std::memcpy(&length, buffer.data() + 10, sizeof(length));
    if (16u + offset + length > returned || length % sizeof(wchar_t) != 0)
        return false;
    const std::wstring_view target(reinterpret_cast<const wchar_t *>(buffer.data() + 16 + offset),
                                   length / sizeof(wchar_t));
    return target.starts_with(L"\\??\\Volume{");
}

void set_attributes(RawEntry &entry, DWORD attributes, DWORD tag, std::wstring_view path) {
    entry.hidden = (attributes & FILE_ATTRIBUTE_HIDDEN) != 0;
    entry.system = (attributes & FILE_ATTRIBUTE_SYSTEM) != 0;
    entry.sparse = (attributes & FILE_ATTRIBUTE_SPARSE_FILE) != 0;
    entry.compressed = (attributes & FILE_ATTRIBUTE_COMPRESSED) != 0;
    entry.cloud =
        (attributes & (FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS)) != 0 ||
        (tag & ~IO_REPARSE_TAG_CLOUD_MASK) == IO_REPARSE_TAG_CLOUD;
    entry.kind = (attributes & FILE_ATTRIBUTE_DIRECTORY) != 0 ? EntryKind::Dir : EntryKind::File;
    if ((attributes & FILE_ATTRIBUTE_REPARSE_POINT) == 0)
        return;
    if (entry.cloud)
        entry.kind = EntryKind::File;
    else if (tag == IO_REPARSE_TAG_SYMLINK)
        entry.kind = EntryKind::Symlink;
    else if (tag == IO_REPARSE_TAG_MOUNT_POINT)
        entry.kind = volume_mount(path) ? EntryKind::MountPoint : EntryKind::Junction;
    else
        entry.kind = EntryKind::OtherReparse;
}

} // namespace detail
} // namespace dafree::platform
