#include "dafree/backend.hpp"

#include <doctest/doctest.h>

#include <algorithm>
#include <chrono>
#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <thread>

namespace {

dafree::RawEntry entry(dafree::EntryKind kind, std::uint64_t size = 0) {
    dafree::RawEntry value;
    value.kind = kind;
    value.size = size;
    value.alloc = size;
    value.dev = 1;
    return value;
}

dafree::MockSpec sample() {
    return {{{"/mock", entry(dafree::EntryKind::Dir)},
             {"/mock/alpha", entry(dafree::EntryKind::File, 10)},
             {"/mock/sub", entry(dafree::EntryKind::Dir)},
             {"/mock/sub/beta", entry(dafree::EntryKind::File, 20)}},
            {},
            {},
            {},
            {},
            {}};
}

class TempDir {
  public:
    TempDir() {
        const auto stamp = std::chrono::steady_clock::now().time_since_epoch().count();
        for (unsigned retry = 0; retry < 100; ++retry) {
            root = std::filesystem::temp_directory_path() /
                   ("dafree-backend-" + std::to_string(stamp) + "-" + std::to_string(retry));
            if (std::filesystem::create_directory(root))
                return;
        }
        throw std::runtime_error("temporary directory creation failed");
    }
    ~TempDir() {
        std::error_code ignored;
        std::filesystem::remove_all(root, ignored);
    }
    TempDir(const TempDir &) = delete;
    TempDir &operator=(const TempDir &) = delete;
    std::filesystem::path root;
};

std::string native_path(const std::filesystem::path &path) {
    const auto bytes = path.u8string();
    return {reinterpret_cast<const char *>(bytes.data()), bytes.size()};
}

} // namespace

TEST_CASE("local_followed_metadata_and_owner_lookup_contract") {
    TempDir temporary;
    const auto file = temporary.root / "owned";
    {
        std::ofstream output(file);
        output << "content";
    }
    auto backend = dafree::make_local_backend();
    const auto path = native_path(file);
    CHECK(backend->stat_follow(path).kind == dafree::EntryKind::File);
    const auto listing = backend->read_dir(native_path(temporary.root), dafree::DirHint{true});
    REQUIRE(listing.entries.size() == 1);
#ifndef _WIN32
    REQUIRE(listing.entries[0].owner.has_value());
    const auto hint = *listing.entries[0].owner;
    const auto from_hint = backend->resolve_owner(path, &hint);
    const auto from_path = backend->resolve_owner(path, nullptr);
    REQUIRE(from_hint.has_value());
    REQUIRE(from_path.has_value());
    CHECK(from_hint->first == from_path->first);
    CHECK(from_hint->second == from_path->second);
    CHECK_FALSE(from_hint->second.empty());
    CHECK_FALSE(
        backend->resolve_owner(native_path(temporary.root / "missing"), nullptr).has_value());
#else
    CHECK_FALSE(backend->resolve_owner(path, nullptr).has_value());
#endif
}

TEST_CASE("mock_serves_tree") {
    auto spec = sample();
    dafree::VolumeInfo volume;
    volume.total = 1000;
    volume.free = 500;
    spec.volume = volume;
    auto backend = dafree::make_mock_backend(std::move(spec));
    CHECK(backend->kind() == dafree::BackendKind::Local);
    CHECK(backend->stat_root("/mock").kind == dafree::EntryKind::Dir);
    const auto listing = backend->read_dir("/mock", {});
    CHECK_FALSE(listing.partial);
    REQUIRE(listing.entries.size() == 2);
    CHECK(listing.entries[0].name == "alpha");
    CHECK(listing.entries[0].size == 10);
    CHECK(listing.entries[1].name == "sub");
    const auto nested = backend->read_dir("/mock/sub/", {});
    REQUIRE(nested.entries.size() == 1);
    CHECK(nested.entries[0].name == "beta");
    CHECK(nested.entries[0].size == 20);
    REQUIRE(backend->volume_info("/mock").has_value());
    CHECK(backend->volume_info("/mock")->free == 500);
    CHECK_THROWS_AS(backend->stat_root("/missing"), dafree::IoError);
    CHECK_THROWS_AS(backend->read_dir("/mock/alpha", {}), dafree::IoError);
}

TEST_CASE("mock_injects_errors") {
    auto spec = sample();
    spec.errors["/mock/sub"] = dafree::IssueKind::AccessDenied;
    spec.errors["/mock/alpha"] = dafree::IssueKind::Io;
    dafree::MockBackend backend(std::move(spec));
    bool denied = false;
    try {
        (void)backend.read_dir("/mock/sub", {});
    } catch (const dafree::IoError &error) {
        denied = error.kind() == dafree::IssueKind::AccessDenied;
    }
    CHECK(denied);
    const auto listing = backend.read_dir("/mock", {});
    REQUIRE(listing.entries.size() == 1);
    CHECK(listing.entries[0].name == "sub");
    CHECK(listing.partial);
    REQUIRE(listing.issues.size() == 1);
    CHECK(listing.issues[0].kind == dafree::IssueKind::Io);
    CHECK(backend.read_dir_calls() == 2);

    auto vanishing = sample();
    vanishing.vanish_after_listing.push_back("/mock/alpha");
    dafree::MockBackend vanish_backend(std::move(vanishing));
    CHECK(vanish_backend.stat_root("/mock/alpha").size == 10);
    const auto changed = vanish_backend.read_dir("/mock", {});
    CHECK(changed.partial);
    REQUIRE(changed.issues.size() == 1);
    CHECK(changed.issues[0].kind == dafree::IssueKind::NotFound);
    CHECK_THROWS_AS(vanish_backend.stat_root("/mock/alpha"), dafree::IoError);

    auto metadata = sample();
    metadata.errors["/mock/alpha"] = dafree::IssueKind::AccessDenied;
    dafree::MockBackend denied_metadata(std::move(metadata));
    const auto partial = denied_metadata.read_dir("/mock", {});
    REQUIRE(partial.entries.size() == 2);
    CHECK(partial.entries[0].access_denied);
    CHECK(partial.entries[0].size == 0);
}

TEST_CASE("local_matches_platform_read_dir") {
    TempDir temp;
    std::ofstream(temp.root / "alpha", std::ios::binary) << "12345";
    REQUIRE(std::filesystem::create_directory(temp.root / "sub"));
    const auto path = native_path(temp.root);
    auto backend = dafree::make_local_backend();
    auto actual = backend->read_dir(path, {});
    auto expected = dafree::platform::read_dir(path);
    const auto by_name = [](const auto &left, const auto &right) { return left.name < right.name; };
    std::sort(actual.entries.begin(), actual.entries.end(), by_name);
    std::sort(expected.entries.begin(), expected.entries.end(), by_name);
    REQUIRE(actual.entries.size() == expected.entries.size());
    for (std::size_t index = 0; index < actual.entries.size(); ++index) {
        const auto &left = actual.entries[index];
        const auto &right = expected.entries[index];
        CHECK(left.name == right.name);
        CHECK(left.kind == right.kind);
        CHECK(left.size == right.size);
        CHECK(left.alloc == right.alloc);
        CHECK(left.dev == right.dev);
        CHECK(left.ino_lo == right.ino_lo);
        CHECK(left.ino_hi == right.ino_hi);
    }
    CHECK(backend->stat_root(path).kind == dafree::EntryKind::Dir);
    CHECK(backend->volume_info(path).has_value());
}

TEST_CASE("mock_delay_counters_and_owners") {
    auto spec = sample();
    spec.delay = std::chrono::milliseconds(10);
    spec.entries[1].entry.owner = dafree::OwnerKey::posix_uid(42);
    spec.owner_names[42] = "test-user";
    dafree::MockBackend backend(std::move(spec));
    const auto start = std::chrono::steady_clock::now();
    (void)backend.read_dir("/mock", {});
    CHECK(std::chrono::steady_clock::now() - start >= std::chrono::milliseconds(10));
    const auto owner = backend.resolve_owner("/mock/alpha", nullptr);
    REQUIRE(owner.has_value());
    CHECK(owner->second == "test-user");
    const auto unknown = dafree::OwnerKey::posix_uid(99999);
    CHECK(backend.resolve_owner("/mock/alpha", &unknown)->second == "99999");
    CHECK(backend.owner_resolution_calls() == 2);
    {
        std::vector<std::thread> threads;
        for (unsigned worker = 0; worker < 4; ++worker) {
            threads.emplace_back([&backend] {
                for (unsigned call = 0; call < 4; ++call)
                    (void)backend.read_dir("/mock", {});
            });
        }
        for (auto &thread : threads)
            thread.join();
    }
    CHECK(backend.read_dir_calls() == 17);
}

TEST_CASE("mock_delay_never_returns_before_minimum") {
    for (const auto delay : {std::chrono::milliseconds(1), std::chrono::milliseconds(2),
                             std::chrono::milliseconds(10), std::chrono::milliseconds(25)}) {
        auto spec = sample();
        spec.delay = delay;
        dafree::MockBackend backend(std::move(spec));
        CAPTURE(delay.count());
        for (unsigned phase = 0; phase < 4; ++phase) {
            CAPTURE(phase);
            const auto start = std::chrono::steady_clock::now();
            (void)backend.read_dir("/mock", {});
            CHECK(std::chrono::steady_clock::now() - start >= delay);
        }
    }
}
