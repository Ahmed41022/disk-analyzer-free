#include "../src/platform/windows/internal.hpp"
#include "dafree/platform.hpp"

#include <doctest/doctest.h>

#include <array>
#include <cstring>
#include <stdexcept>
#include <vector>
#include <winioctl.h>

namespace {

namespace detail = dafree::platform::detail;

void cleanup_temp(const std::wstring &path) noexcept {
    WIN32_FIND_DATAW data{};
    const HANDLE search = ::FindFirstFileW((path + L"\\*").c_str(), &data);
    if (search != INVALID_HANDLE_VALUE) {
        do {
            const std::wstring_view name(data.cFileName);
            if (name == L"." || name == L"..")
                continue;
            const auto child = path + L"\\" + std::wstring(name);
            if ((data.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) != 0) {
                if ((data.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT) == 0)
                    cleanup_temp(child);
                else
                    ::RemoveDirectoryW(child.c_str());
            } else {
                ::DeleteFileW(child.c_str());
            }
        } while (::FindNextFileW(search, &data));
        ::FindClose(search);
    }
    ::RemoveDirectoryW(path.c_str());
}

class TempDir {
  public:
    TempDir() {
        std::array<wchar_t, MAX_PATH + 1> base{}, unique{};
        if (::GetTempPathW(static_cast<DWORD>(base.size()), base.data()) == 0 ||
            ::GetTempFileNameW(base.data(), L"daf", 0, unique.data()) == 0)
            throw std::runtime_error("temporary directory name failed");
        if (!::DeleteFileW(unique.data()) || !::CreateDirectoryW(unique.data(), nullptr))
            throw std::runtime_error("temporary directory creation failed");
        root = detail::native_path(detail::to_wtf8(unique.data()));
    }
    ~TempDir() { cleanup_temp(root); }
    TempDir(const TempDir &) = delete;
    TempDir &operator=(const TempDir &) = delete;
    std::wstring root;
};

void write_file(const std::wstring &path, std::string_view bytes) {
    detail::UniqueHandle file(::CreateFileW(path.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_NEW,
                                            FILE_ATTRIBUTE_NORMAL, nullptr));
    REQUIRE(file.get() != INVALID_HANDLE_VALUE);
    DWORD written = 0;
    REQUIRE(
        ::WriteFile(file.get(), bytes.data(), static_cast<DWORD>(bytes.size()), &written, nullptr));
    REQUIRE(written == bytes.size());
}

const dafree::RawEntry *find(const dafree::DirListing &listing, std::string_view name) {
    for (const auto &entry : listing.entries)
        if (entry.name == name)
            return &entry;
    return nullptr;
}

void make_junction(const std::wstring &path, const std::wstring &target) {
    REQUIRE(::CreateDirectoryW(path.c_str(), nullptr));
    const std::wstring substitute = L"\\??\\" + target.substr(4);
    const std::wstring print = target.substr(4);
    const auto substitute_bytes = static_cast<USHORT>(substitute.size() * sizeof(wchar_t));
    const auto print_bytes = static_cast<USHORT>(print.size() * sizeof(wchar_t));
    const USHORT print_offset = static_cast<USHORT>(substitute_bytes + sizeof(wchar_t));
    const USHORT data_length =
        static_cast<USHORT>(8 + print_offset + print_bytes + sizeof(wchar_t));
    alignas(8) std::array<std::byte, MAXIMUM_REPARSE_DATA_BUFFER_SIZE> buffer{};
    const DWORD tag = IO_REPARSE_TAG_MOUNT_POINT;
    const USHORT zero = 0;
    std::memcpy(buffer.data(), &tag, sizeof(tag));
    std::memcpy(buffer.data() + 4, &data_length, sizeof(data_length));
    std::memcpy(buffer.data() + 8, &zero, sizeof(zero));
    std::memcpy(buffer.data() + 10, &substitute_bytes, sizeof(substitute_bytes));
    std::memcpy(buffer.data() + 12, &print_offset, sizeof(print_offset));
    std::memcpy(buffer.data() + 14, &print_bytes, sizeof(print_bytes));
    std::memcpy(buffer.data() + 16, substitute.data(), substitute_bytes);
    std::memcpy(buffer.data() + 16 + print_offset, print.data(), print_bytes);
    detail::UniqueHandle handle(
        ::CreateFileW(path.c_str(), GENERIC_WRITE, 0, nullptr, OPEN_EXISTING,
                      FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, nullptr));
    REQUIRE(handle.get() != INVALID_HANDLE_VALUE);
    DWORD returned = 0;
    REQUIRE(::DeviceIoControl(handle.get(), FSCTL_SET_REPARSE_POINT, buffer.data(),
                              static_cast<DWORD>(8u + data_length), nullptr, 0, &returned,
                              nullptr));
}

} // namespace

TEST_CASE("lists_files_with_sizes") {
    TempDir temp;
    write_file(temp.root + L"\\five.bin", "12345");
    REQUIRE(::CreateDirectoryW((temp.root + L"\\sub").c_str(), nullptr));
    const auto listing = dafree::platform::read_dir(detail::to_wtf8(temp.root));
    CHECK_FALSE(listing.partial);
    REQUIRE(listing.entries.size() == 2);
    const auto *file = find(listing, "five.bin");
    REQUIRE(file != nullptr);
    CHECK(file->size == 5);
    CHECK(file->kind == dafree::EntryKind::File);
    const auto stat = dafree::platform::stat_nofollow(detail::to_wtf8(temp.root + L"\\five.bin"));
    CHECK(file->dev == stat.dev);
    CHECK(file->ino_lo == stat.ino_lo);
    CHECK(file->ino_hi == stat.ino_hi);
}

TEST_CASE("junction_detected_not_followed") {
    TempDir temp;
    const auto target = temp.root + L"\\target";
    REQUIRE(::CreateDirectoryW(target.c_str(), nullptr));
    write_file(target + L"\\child", "123");
    const auto junction = temp.root + L"\\junction";
    make_junction(junction, target);
    const auto listing = dafree::platform::read_dir(detail::to_wtf8(temp.root));
    const auto *entry = find(listing, "junction");
    REQUIRE(entry != nullptr);
    CHECK(entry->kind == dafree::EntryKind::Junction);
    CHECK_THROWS_AS(dafree::platform::read_dir(detail::to_wtf8(junction)), dafree::IoError);
    CHECK(dafree::platform::stat_follow(detail::to_wtf8(junction)).kind == dafree::EntryKind::Dir);
    const auto followed = dafree::platform::read_dir_follow(detail::to_wtf8(junction));
    REQUIRE(followed.entries.size() == 1);
    CHECK(followed.entries[0].size == 3);
}

TEST_CASE("long_path_over_260") {
    TempDir temp;
    std::wstring path = temp.root;
    for (int index = 0; index < 16; ++index) {
        path += L"\\segment-abcdefghijklmnop";
        REQUIRE(::CreateDirectoryW(path.c_str(), nullptr));
    }
    REQUIRE(path.size() > 400);
    write_file(path + L"\\leaf", "data");
    const auto listing = dafree::platform::read_dir(detail::to_wtf8(path));
    const auto *leaf = find(listing, "leaf");
    REQUIRE(leaf != nullptr);
    CHECK(leaf->size == 4);
}

TEST_CASE("hidden_system_attrs") {
    TempDir temp;
    const auto path = temp.root + L"\\hidden";
    write_file(path, "data");
    REQUIRE(::SetFileAttributesW(path.c_str(), FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_SYSTEM));
    const auto listing = dafree::platform::read_dir(detail::to_wtf8(temp.root));
    const auto *hidden = find(listing, "hidden");
    REQUIRE(hidden != nullptr);
    CHECK(hidden->hidden);
    CHECK(hidden->system);
}

TEST_CASE("windows_native_names_and_volume") {
    TempDir temp;
    std::wstring name = L"emoji-\U0001F600-";
    name.push_back(static_cast<wchar_t>(0xD800));
    write_file(temp.root + L"\\" + name, "data");
    CHECK(detail::from_wtf8(detail::to_wtf8(name)) == name);
    const auto listing = dafree::platform::read_dir(detail::to_wtf8(temp.root));
    REQUIRE(listing.entries.size() == 1);
    CHECK(detail::from_wtf8(listing.entries.front().name) == name);
    const auto volume = dafree::platform::volume_info(detail::to_wtf8(temp.root));
    REQUIRE(volume.has_value());
    CHECK(volume->total >= volume->free);
    CHECK(volume->cluster_size > 0);
}

TEST_CASE("windows_multiple_directory_batches") {
    TempDir temp;
    constexpr unsigned count = 1200;
    for (unsigned index = 0; index < count; ++index)
        write_file(temp.root + L"\\entry-" + std::to_wstring(index), "");
    const auto listing = dafree::platform::read_dir(detail::to_wtf8(temp.root));
    CHECK_FALSE(listing.partial);
    CHECK(listing.entries.size() == count);
    for (unsigned index = 0; index < count; ++index)
        CHECK(find(listing, "entry-" + std::to_string(index)) != nullptr);
}

TEST_CASE("windows_cloud_tags_remain_unopened_files") {
    for (DWORD index = 0; index < 16; ++index) {
        dafree::RawEntry entry;
        detail::set_attributes(entry, FILE_ATTRIBUTE_REPARSE_POINT,
                               IO_REPARSE_TAG_CLOUD | (index << 12u), L"");
        CHECK(entry.kind == dafree::EntryKind::File);
        CHECK(entry.cloud);
    }
}
