#include "dafree/platform.hpp"

#include <doctest/doctest.h>

#include <cerrno>
#include <cstdint>
#include <cstdlib>
#include <fcntl.h>
#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <sys/stat.h>
#include <unistd.h>
#include <vector>

namespace {

class TempDir {
  public:
    TempDir() {
        std::string pattern =
            (std::filesystem::temp_directory_path() / "dafree-posix-XXXXXX").string();
        std::vector<char> buffer(pattern.begin(), pattern.end());
        buffer.push_back('\0');
        const char *created = ::mkdtemp(buffer.data());
        if (created == nullptr)
            throw std::runtime_error("mkdtemp failed");
        path_ = created;
    }
    ~TempDir() {
        std::error_code ignored;
        std::filesystem::remove_all(path_, ignored);
    }
    TempDir(const TempDir &) = delete;
    TempDir &operator=(const TempDir &) = delete;
    [[nodiscard]] const std::string &path() const noexcept { return path_; }

  private:
    std::string path_;
};

const dafree::RawEntry *find_entry(const dafree::DirListing &listing, std::string_view name) {
    for (const auto &entry : listing.entries) {
        if (entry.name == name)
            return &entry;
    }
    return nullptr;
}

} // namespace

TEST_CASE("lists_files_with_sizes") {
    TempDir temp;
    std::ofstream(temp.path() + "/five.bin", std::ios::binary) << "12345";
    REQUIRE(::mkdir((temp.path() + "/sub").c_str(), 0700) == 0);
    const auto listing = dafree::platform::read_dir(temp.path());
    CHECK_FALSE(listing.partial);
    REQUIRE(listing.entries.size() == 2);
    const auto *file = find_entry(listing, "five.bin");
    const auto *sub = find_entry(listing, "sub");
    REQUIRE(file != nullptr);
    REQUIRE(sub != nullptr);
    CHECK(file->kind == dafree::EntryKind::File);
    CHECK(file->size == 5);
    CHECK(sub->kind == dafree::EntryKind::Dir);
}

TEST_CASE("sparse_alloc_less_than_size") {
    TempDir temp;
    const std::string path = temp.path() + "/sparse.bin";
    const int fd = ::open(path.c_str(), O_WRONLY | O_CREAT | O_EXCL, 0600);
    REQUIRE(fd >= 0);
    REQUIRE(::ftruncate(fd, 1024 * 1024 * 1024) == 0);
    ::close(fd);
    const auto entry = dafree::platform::stat_nofollow(path);
    CHECK(entry.size == 1024u * 1024u * 1024u);
    CHECK(entry.alloc < entry.size);
}

TEST_CASE("symlink_not_followed") {
    TempDir temp;
    REQUIRE(::mkdir((temp.path() + "/target").c_str(), 0700) == 0);
    REQUIRE(::symlink("target", (temp.path() + "/link").c_str()) == 0);
    const auto listing = dafree::platform::read_dir(temp.path());
    const auto *link = find_entry(listing, "link");
    REQUIRE(link != nullptr);
    CHECK(link->kind == dafree::EntryKind::Symlink);
    CHECK(dafree::platform::stat_follow(temp.path() + "/link").kind == dafree::EntryKind::Dir);
}

TEST_CASE("access_denied_dir_reports_issue") {
    if (::geteuid() == 0) {
        MESSAGE("Access-denial test requires a non-root user");
        return;
    }
    TempDir temp;
    const std::string denied = temp.path() + "/denied";
    REQUIRE(::mkdir(denied.c_str(), 0700) == 0);
    REQUIRE(::chmod(denied.c_str(), 0) == 0);
    bool access_denied = false;
    try {
        (void)dafree::platform::read_dir(denied);
    } catch (const dafree::IoError &error) {
        access_denied = error.kind() == dafree::IssueKind::AccessDenied;
    }
    ::chmod(denied.c_str(), 0700);
    CHECK(access_denied);
}

TEST_CASE("deep_path_beyond_path_max") {
#ifdef __linux__
    TempDir temp;
    std::string path = temp.path();
    std::vector<int> descriptors;
    std::vector<std::string> components;
    descriptors.push_back(::open(path.c_str(), O_RDONLY | O_DIRECTORY));
    REQUIRE(descriptors.back() >= 0);
    for (unsigned index = 0; index < 300; ++index) {
        const std::string component = "level-" + std::to_string(index) + "-xxxxxx";
        REQUIRE(::mkdirat(descriptors.back(), component.c_str(), 0700) == 0);
        const int next = ::openat(descriptors.back(), component.c_str(), O_RDONLY | O_DIRECTORY);
        REQUIRE(next >= 0);
        descriptors.push_back(next);
        components.push_back(component);
        path += "/" + component;
    }
    CHECK(path.size() > 4200);
    const int file = ::openat(descriptors.back(), "leaf", O_WRONLY | O_CREAT | O_EXCL, 0600);
    REQUIRE(file >= 0);
    ::close(file);
    const auto listing = dafree::platform::read_dir(path);
    const auto *leaf = find_entry(listing, "leaf");
    REQUIRE(leaf != nullptr);
    CHECK(leaf->kind == dafree::EntryKind::File);
    CHECK(leaf->size == 0);
    REQUIRE(::unlinkat(descriptors.back(), "leaf", 0) == 0);
    for (std::size_t index = components.size(); index > 0; --index) {
        ::close(descriptors[index]);
        REQUIRE(::unlinkat(descriptors[index - 1], components[index - 1].c_str(), AT_REMOVEDIR) ==
                0);
    }
    ::close(descriptors[0]);
#endif
}

TEST_CASE("btime_optional_no_crash") {
    TempDir temp;
    const auto entry = dafree::platform::stat_nofollow(temp.path());
    const bool directory =
        entry.kind == dafree::EntryKind::Dir || entry.kind == dafree::EntryKind::MountPoint;
    CHECK(directory);
    CHECK(entry.mtime.has_value());
    (void)entry.btime;
}

TEST_CASE("posix_volume_and_owner_metadata") {
    TempDir temp;
    const auto volume = dafree::platform::volume_info(temp.path());
    REQUIRE(volume.has_value());
    CHECK(volume->total >= volume->free);
    CHECK(volume->cluster_size > 0);
    const auto owner = dafree::platform::owner_of(temp.path());
    REQUIRE(owner.has_value());
    CHECK(owner->first.uid == static_cast<std::uint32_t>(::getuid()));
    CHECK_FALSE(owner->second.empty());
}
