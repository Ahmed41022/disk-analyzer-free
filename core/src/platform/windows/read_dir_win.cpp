#include "internal.hpp"

#include <array>
#include <cstddef>
#include <cstring>
#include <type_traits>

namespace dafree::platform {

static detail::UniqueHandle open_metadata(const std::wstring &path, DWORD access, bool follow) {
    return detail::UniqueHandle(::CreateFileW(
        path.c_str(), access, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr,
        OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS | (follow ? 0u : FILE_FLAG_OPEN_REPARSE_POINT),
        nullptr));
}

static DWORD reparse_tag(const std::wstring &path) {
    WIN32_FIND_DATAW data{};
    HANDLE find = ::FindFirstFileW(path.c_str(), &data);
    if (find == INVALID_HANDLE_VALUE)
        return 0;
    ::FindClose(find);
    return data.dwReserved0;
}

template <class Record>
static void append_records(DirListing &listing, const std::array<std::byte, 64 * 1024> &buffer,
                           const std::wstring &directory, std::uint64_t serial) {
    std::size_t offset = 0;
    for (;;) {
        if (offset + offsetof(Record, FileName) > buffer.size())
            throw Error("invalid Windows directory record");
        const auto *record = reinterpret_cast<const Record *>(buffer.data() + offset);
        const std::size_t name_bytes = record->FileNameLength;
        if (name_bytes % sizeof(wchar_t) != 0 ||
            name_bytes > buffer.size() - offset - offsetof(Record, FileName))
            throw Error("invalid Windows directory name");
        const std::wstring_view name(record->FileName, name_bytes / sizeof(wchar_t));
        if (name != L"." && name != L"..") {
            RawEntry entry;
            entry.name = detail::to_wtf8(name);
            entry.size = record->EndOfFile.QuadPart > 0
                             ? static_cast<std::uint64_t>(record->EndOfFile.QuadPart)
                             : 0;
            entry.alloc = record->AllocationSize.QuadPart > 0
                              ? static_cast<std::uint64_t>(record->AllocationSize.QuadPart)
                              : 0;
            entry.mtime = detail::unix_time(record->LastWriteTime.QuadPart);
            entry.btime = detail::unix_time(record->CreationTime.QuadPart);
            entry.atime = detail::unix_time(record->LastAccessTime.QuadPart);
            entry.dev = serial;
            DWORD tag = 0;
            std::wstring path;
            if ((record->FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0) {
                path = directory + L"\\" + std::wstring(name);
            }
            if constexpr (std::is_same_v<Record, FILE_ID_EXTD_DIR_INFO>) {
                std::memcpy(&entry.ino_lo, record->FileId.Identifier, 8);
                std::memcpy(&entry.ino_hi, record->FileId.Identifier + 8, 8);
                tag = record->ReparsePointTag;
            } else {
                entry.ino_lo = static_cast<std::uint64_t>(record->FileId.QuadPart);
                if (!path.empty())
                    tag = reparse_tag(path);
            }
            detail::set_attributes(entry, record->FileAttributes, tag, path);
            listing.entries.push_back(std::move(entry));
        }
        if (record->NextEntryOffset == 0)
            break;
        if (record->NextEntryOffset < offsetof(Record, FileName) + name_bytes ||
            record->NextEntryOffset % 8 != 0 || record->NextEntryOffset > buffer.size() - offset)
            throw Error("invalid Windows directory offset");
        offset += record->NextEntryOffset;
    }
}

DirListing read_dir(std::string_view path) {
    const auto native = detail::native_path(path);
    auto handle = open_metadata(native, FILE_LIST_DIRECTORY | FILE_READ_ATTRIBUTES, false);
    if (handle.get() == INVALID_HANDLE_VALUE)
        detail::fail(path, ::GetLastError());
    FILE_ATTRIBUTE_TAG_INFO attributes{};
    if (!::GetFileInformationByHandleEx(handle.get(), FileAttributeTagInfo, &attributes,
                                        sizeof(attributes)))
        detail::fail(path, ::GetLastError());
    if ((attributes.FileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) != 0)
        throw IoError(std::string(path), IssueKind::Io, "directory is a reparse point");
    const auto serial = detail::volume_serial(handle.get(), path);
    alignas(8) std::array<std::byte, 64 * 1024> buffer{};
    DirListing listing;
    bool extended = true, first = true;
    for (;;) {
        const auto info = extended
                              ? (first ? FileIdExtdDirectoryRestartInfo : FileIdExtdDirectoryInfo)
                              : (first ? FileIdBothDirectoryRestartInfo : FileIdBothDirectoryInfo);
        if (!::GetFileInformationByHandleEx(handle.get(), info, buffer.data(),
                                            static_cast<DWORD>(buffer.size()))) {
            const DWORD code = ::GetLastError();
            if (code == ERROR_NO_MORE_FILES)
                break;
            if (extended && first &&
                (code == ERROR_INVALID_PARAMETER || code == ERROR_NOT_SUPPORTED ||
                 code == ERROR_INVALID_FUNCTION)) {
                extended = false;
                continue;
            }
            if (first)
                detail::fail(path, code);
            listing.partial = true;
            listing.issues.push_back(
                {std::string(path), IssueKind::Io, "Windows error " + std::to_string(code)});
            break;
        }
        if (extended)
            append_records<FILE_ID_EXTD_DIR_INFO>(listing, buffer, native, serial);
        else
            append_records<FILE_ID_BOTH_DIR_INFO>(listing, buffer, native, serial);
        first = false;
    }
    return listing;
}

static RawEntry stat_path(std::string_view path, bool follow) {
    const auto native = detail::native_path(path);
    auto handle = open_metadata(native, FILE_READ_ATTRIBUTES, follow);
    if (handle.get() == INVALID_HANDLE_VALUE)
        detail::fail(path, ::GetLastError());
    FILE_BASIC_INFO basic{};
    FILE_STANDARD_INFO standard{};
    FILE_ATTRIBUTE_TAG_INFO tag{};
    if (!::GetFileInformationByHandleEx(handle.get(), FileBasicInfo, &basic, sizeof(basic)) ||
        !::GetFileInformationByHandleEx(handle.get(), FileStandardInfo, &standard,
                                        sizeof(standard)) ||
        !::GetFileInformationByHandleEx(handle.get(), FileAttributeTagInfo, &tag, sizeof(tag)))
        detail::fail(path, ::GetLastError());
    RawEntry entry;
    const auto separator = native.find_last_of(L"\\/");
    entry.name = detail::to_wtf8(separator == std::wstring::npos
                                     ? std::wstring_view(native)
                                     : std::wstring_view(native).substr(separator + 1));
    entry.size = standard.EndOfFile.QuadPart > 0
                     ? static_cast<std::uint64_t>(standard.EndOfFile.QuadPart)
                     : 0;
    entry.alloc = standard.AllocationSize.QuadPart > 0
                      ? static_cast<std::uint64_t>(standard.AllocationSize.QuadPart)
                      : 0;
    entry.nlink = standard.NumberOfLinks;
    entry.mtime = detail::unix_time(basic.LastWriteTime.QuadPart);
    entry.btime = detail::unix_time(basic.CreationTime.QuadPart);
    entry.atime = detail::unix_time(basic.LastAccessTime.QuadPart);
    entry.dev = detail::volume_serial(handle.get(), path);
    FILE_ID_INFO id{};
    if (::GetFileInformationByHandleEx(handle.get(), FileIdInfo, &id, sizeof(id))) {
        std::memcpy(&entry.ino_lo, id.FileId.Identifier, 8);
        std::memcpy(&entry.ino_hi, id.FileId.Identifier + 8, 8);
    } else {
        BY_HANDLE_FILE_INFORMATION legacy{};
        if (!::GetFileInformationByHandle(handle.get(), &legacy))
            detail::fail(path, ::GetLastError());
        entry.ino_lo =
            (static_cast<std::uint64_t>(legacy.nFileIndexHigh) << 32u) | legacy.nFileIndexLow;
    }
    detail::set_attributes(entry, basic.FileAttributes, tag.ReparseTag, native);
    return entry;
}

RawEntry stat_nofollow(std::string_view path) { return stat_path(path, false); }
RawEntry stat_follow(std::string_view path) {
    const auto entry = stat_path(path, false);
    if (entry.cloud || (entry.kind != EntryKind::Symlink && entry.kind != EntryKind::Junction &&
                        entry.kind != EntryKind::MountPoint))
        return entry;
    return stat_path(path, true);
}

} // namespace dafree::platform
