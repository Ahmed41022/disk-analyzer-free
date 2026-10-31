#include "../src/scan/work_queue.hpp"
#include "dafree/scan.hpp"

#include <doctest/doctest.h>

#include <atomic>
#include <chrono>
#include <future>
#include <thread>

namespace {

using namespace std::chrono_literals;

std::string root_path() { return dafree::platform::windows_paths() ? "C:/mock" : "/mock"; }

dafree::RawEntry entry(dafree::EntryKind kind, std::uint64_t size = 0) {
    dafree::RawEntry value;
    value.kind = kind;
    value.size = value.alloc = size;
    value.mtime = 123;
    return value;
}

dafree::MockSpec sample() {
    const auto root = root_path();
    dafree::MockSpec spec;
    spec.entries = {{root, entry(dafree::EntryKind::Dir)},
                    {root + "/alpha", entry(dafree::EntryKind::File, 10)},
                    {root + "/sub", entry(dafree::EntryKind::Dir)},
                    {root + "/sub/beta", entry(dafree::EntryKind::File, 20)}};
    return spec;
}

dafree::MockSpec broad(unsigned directories, std::chrono::milliseconds delay) {
    dafree::MockSpec spec;
    const auto root = root_path();
    spec.entries.push_back({root, entry(dafree::EntryKind::Dir)});
    for (unsigned index = 0; index < directories; ++index) {
        const auto path = root + "/dir-" + std::to_string(index);
        spec.entries.push_back({path, entry(dafree::EntryKind::Dir)});
        spec.entries.push_back({path + "/file", entry(dafree::EntryKind::File, 10)});
    }
    spec.delay = delay;
    return spec;
}

dafree::ScanOptions options() {
    dafree::ScanOptions opts;
    opts.targets = {root_path()};
    opts.threads = 2;
    return opts;
}

template <class Predicate> bool until(Predicate predicate, std::chrono::milliseconds timeout = 3s) {
    const auto deadline = std::chrono::steady_clock::now() + timeout;
    while (!predicate()) {
        if (std::chrono::steady_clock::now() >= deadline)
            return false;
        std::this_thread::sleep_for(1ms);
    }
    return true;
}

} // namespace

TEST_CASE("owner_resolution_parallel_readers") {
    auto spec = sample();
    for (std::size_t i = 0; i < spec.entries.size(); ++i)
        spec.entries[i].entry.owner =
            dafree::OwnerKey::posix_uid(static_cast<std::uint32_t>(100 + i));
    spec.delay = 10ms;
    auto backend = std::make_shared<dafree::MockBackend>(std::move(spec));
    auto scan = dafree::start_scan(options(), backend);
    REQUIRE(scan.wait(5s));
    auto result = scan.take_result();
    dafree::TreeHandle tree(result.tree);
    std::vector<dafree::NodeId> ids;
    for (dafree::NodeId id = 1; id < result.tree->size(); ++id)
        ids.push_back(id);
    std::atomic<bool> stop{false}, inconsistent{false};
    std::atomic<unsigned> reads{0};
    std::promise<void> ready;
    auto started = ready.get_future();
    std::thread reader([&] {
        ready.set_value();
        while (!stop.load()) {
            tree.read([&](const dafree::Tree &value) {
                unsigned resolved = 0;
                for (const auto id : ids) {
                    const auto owner = value.owner_name(id);
                    if (owner && !owner->empty())
                        ++resolved;
                }
                if (resolved != 0 && resolved != ids.size())
                    inconsistent.store(true);
                reads.fetch_add(1);
            });
        }
    });
    started.wait();
    try {
        auto other =
            std::async(std::launch::async, [&] { dafree::resolve_owners(tree, ids, *backend); });
        dafree::resolve_owners(tree, ids, *backend);
        other.get();
    } catch (...) {
        stop.store(true);
        reader.join();
        throw;
    }
    stop.store(true);
    reader.join();
    CHECK(reads.load() > 0);
    CHECK_FALSE(inconsistent.load());
    CHECK(backend->owner_resolution_calls() == ids.size());
    for (const auto id : ids)
        CHECK(tree.read([&](const dafree::Tree &value) { return !value.owner_name(id)->empty(); }));
    CHECK_THROWS_AS(dafree::resolve_owners(tree, std::array<dafree::NodeId, 1>{999}, *backend),
                    std::out_of_range);
}

TEST_CASE("engine_cancel_skips_eager_owner_lookups") {
    auto spec = broad(20, 10ms);
    for (auto &item : spec.entries)
        item.entry.owner = dafree::OwnerKey::posix_uid(42);
    auto backend = std::make_shared<dafree::MockBackend>(std::move(spec));
    auto opts = options();
    opts.owner = dafree::OwnerMode::Eager;
    auto handle = dafree::start_scan(std::move(opts), backend);
    handle.cancel();
    REQUIRE(handle.wait(5s));
    CHECK(handle.take_result().summary.cancelled);
    CHECK(backend->owner_resolution_calls() == 0);
}

TEST_CASE("scan_mock_matches_expected") {
    auto handle = dafree::start_scan(options(), dafree::make_mock_backend(sample()));
    REQUIRE(handle.wait(5s));
    auto result = handle.take_result();
    REQUIRE(result.tree != nullptr);
    CHECK(result.tree->size() == 5);
    const auto root = result.tree->roots()[0];
    CHECK(result.tree->node(root).size == 30);
    CHECK(result.tree->counts(root).files == 2);
    CHECK(result.tree->counts(root).dirs == 1);
    CHECK(result.summary.bytes == 30);
    CHECK(result.summary.files == 2);
    CHECK(result.summary.dirs == 2);
    CHECK(handle.progress().state == dafree::ScanState::Done);
    for (dafree::NodeId id = 1; id < result.tree->size(); ++id) {
        CHECK(result.tree->node(id).parent < id);
        const auto range = result.tree->children(result.tree->node(id).parent);
        CHECK(id >= range.first);
        CHECK(id < range.second);
    }
    CHECK(result.tree->meta().started_at > 0);
    CHECK(result.tree->meta().finished_at >= result.tree->meta().started_at);
    CHECK_FALSE(result.tree->meta().host.empty());
    CHECK_FALSE(result.tree->meta().os.empty());
    CHECK_THROWS_AS(handle.take_result(), dafree::ScanError);

    auto excluded_options = options();
    excluded_options.exclude.globs = {"sub"};
    auto excluded = dafree::start_scan(excluded_options, dafree::make_mock_backend(sample()));
    REQUIRE(excluded.wait(5s));
    const auto filtered = excluded.take_result();
    CHECK(filtered.tree->size() == 3);
    CHECK(filtered.summary.bytes == 10);
}

TEST_CASE("cancel_marks_partial_and_returns_tree") {
    auto backend = std::make_shared<dafree::MockBackend>(broad(40, 10ms));
    auto handle = dafree::start_scan(options(), backend);
    REQUIRE(until([&] { return backend->read_dir_calls() >= 2; }));
    handle.cancel();
    REQUIRE(handle.wait(5s));
    const auto result = handle.take_result();
    CHECK(result.summary.cancelled);
    CHECK(result.tree->meta().cancelled);
    CHECK(handle.progress().state == dafree::ScanState::Cancelled);
    bool partial = false;
    for (dafree::NodeId id = 1; id < result.tree->size(); ++id)
        partial = partial || (result.tree->node(id).flags & dafree::kPartial) != 0;
    CHECK(partial);
}

TEST_CASE("pause_stops_new_reads") {
    auto backend = std::make_shared<dafree::MockBackend>(broad(60, 10ms));
    auto handle = dafree::start_scan(options(), backend);
    REQUIRE(until([&] { return backend->read_dir_calls() >= 3; }));
    handle.pause();
    CHECK(handle.progress().state == dafree::ScanState::Paused);
    std::this_thread::sleep_for(50ms);
    const auto settled = backend->read_dir_calls();
    std::this_thread::sleep_for(50ms);
    CHECK(backend->read_dir_calls() == settled);
    handle.resume();
    REQUIRE(handle.wait(5s));
    CHECK(handle.take_result().summary.files == 60);
}

TEST_CASE("read_dir_error_marks_access_denied") {
    auto spec = sample();
    spec.errors[root_path() + "/sub"] = dafree::IssueKind::AccessDenied;
    auto handle = dafree::start_scan(options(), dafree::make_mock_backend(std::move(spec)));
    REQUIRE(handle.wait(5s));
    const auto result = handle.take_result();
    const auto denied = result.tree->find_path(root_path() + "/sub");
    REQUIRE(denied.has_value());
    CHECK((result.tree->node(*denied).flags & dafree::kAccessDenied) != 0);
    CHECK(result.summary.bytes == 10);
    CHECK(result.summary.issues.total == 1);
    const auto issues = handle.drain_issues();
    REQUIRE(issues.size() == 1);
    CHECK(issues[0].kind == dafree::IssueKind::AccessDenied);
    CHECK(handle.drain_issues().empty());
}

TEST_CASE("overlapping_targets_rejected") {
    auto opts = options();
    opts.targets.push_back(root_path() + "/sub");
    bool overlap = false;
    try {
        (void)dafree::start_scan(opts, dafree::make_mock_backend(sample()));
    } catch (const dafree::ScanError &error) {
        overlap = error.code() == dafree::ScanError::Code::OverlappingTargets;
    }
    CHECK(overlap);
    opts.targets.clear();
    CHECK_THROWS_AS(dafree::start_scan(opts, dafree::make_mock_backend(sample())),
                    dafree::ScanError);
    opts.targets = {"relative"};
    CHECK_THROWS_AS(dafree::start_scan(opts, dafree::make_mock_backend(sample())),
                    dafree::ScanError);
}

TEST_CASE("multiple_targets_share_root") {
    auto opts = options();
    opts.targets = {root_path() + "/sub", root_path() + "/alpha", root_path() + "/sub/."};
    auto handle = dafree::start_scan(opts, dafree::make_mock_backend(sample()));
    REQUIRE(handle.wait(5s));
    const auto result = handle.take_result();
    REQUIRE(result.tree->roots().size() == 2);
    CHECK(result.tree->node(dafree::kRoot).flags == (dafree::kDir | dafree::kSynthetic));
    CHECK(result.tree->node(dafree::kRoot).size == 30);
    CHECK(result.tree->meta().options.targets.size() == 2);
    CHECK(result.tree->parent(result.tree->roots()[0]) == dafree::kRoot);
    CHECK(result.tree->parent(result.tree->roots()[1]) == dafree::kRoot);
}

TEST_CASE("issue_queue_overflow_counted") {
    constexpr unsigned issue_count = 100005;
    dafree::MockSpec spec;
    const auto root = root_path();
    spec.entries.reserve(issue_count + 1);
    spec.entries.push_back({root, entry(dafree::EntryKind::Dir)});
    for (unsigned index = 0; index < issue_count; ++index) {
        const auto path = root + "/file-" + std::to_string(index);
        spec.entries.push_back({path, entry(dafree::EntryKind::File)});
        spec.errors[path] = dafree::IssueKind::Io;
    }
    auto handle = dafree::start_scan(options(), dafree::make_mock_backend(std::move(spec)));
    REQUIRE(handle.wait(10s));
    const auto result = handle.take_result();
    CHECK(result.summary.issues.total == issue_count);
    CHECK(result.summary.issues.overflow == 5);
    CHECK(result.summary.issues.first.size() == 1000);
    CHECK(result.tree->meta().issues.counts[static_cast<std::size_t>(dafree::IssueKind::Io)] ==
          issue_count);
    CHECK(handle.progress().issues == issue_count);
    CHECK(handle.drain_issues(100001).size() == 100000);
    CHECK(handle.drain_issues().empty());
}

TEST_CASE("partial_snapshots_remain_immutable") {
    auto opts = options();
    opts.threads = 1;
    auto handle = dafree::start_scan(opts, dafree::make_mock_backend(broad(30, 20ms)));
    handle.pause();
    std::shared_ptr<const dafree::Tree> snapshot;
    REQUIRE(until([&] {
        snapshot = handle.partial_tree();
        return snapshot != nullptr;
    }));
    const auto size = snapshot->size();
    handle.resume();
    REQUIRE(handle.wait(5s));
    const auto result = handle.take_result();
    CHECK(snapshot->size() == size);
    CHECK(result.tree->size() > size);
    CHECK(handle.partial_tree() == result.tree);
}

TEST_CASE("bounded_result_queue_applies_backpressure") {
    dafree::detail::WorkQueue<int> queue(1);
    REQUIRE(queue.push(1));
    std::promise<void> started;
    std::promise<bool> finished;
    auto done = finished.get_future();
    std::thread producer([&] {
        started.set_value();
        finished.set_value(queue.push(2));
    });
    started.get_future().wait();
    CHECK(done.wait_for(20ms) == std::future_status::timeout);
    CHECK(queue.pop() == 1);
    CHECK(done.get());
    producer.join();
    queue.close();
    CHECK(queue.pop() == 2);
    CHECK_FALSE(queue.pop().has_value());
    CHECK_FALSE(queue.push(3));
}

TEST_CASE("engine_hardlinks_dedup_and_count_all") {
    dafree::MockSpec spec;
    const auto root = root_path();
    spec.entries.push_back({root, entry(dafree::EntryKind::Dir)});
    for (unsigned index = 0; index < 3; ++index) {
        auto file = entry(dafree::EntryKind::File, 10 * 1024 * 1024);
        file.dev = 1;
        file.ino_lo = 77;
        file.nlink = 3;
        spec.entries.push_back({root + "/link-" + std::to_string(index), file});
    }
    for (const auto mode : {dafree::HardlinkMode::Dedup, dafree::HardlinkMode::CountAll}) {
        auto opts = options();
        opts.hardlinks = mode;
        auto handle = dafree::start_scan(opts, dafree::make_mock_backend(spec));
        REQUIRE(handle.wait(5s));
        const auto result = handle.take_result();
        CHECK(result.summary.files == 3);
        CHECK(result.summary.bytes ==
              (mode == dafree::HardlinkMode::Dedup ? 10u : 30u) * 1024u * 1024u);
        unsigned duplicates = 0;
        for (dafree::NodeId id = 2; id < result.tree->size(); ++id) {
            duplicates += (result.tree->node(id).flags & dafree::kHardlinkDup) != 0 ? 1u : 0u;
            CHECK(result.tree->node(id).size == 10u * 1024u * 1024u);
        }
        CHECK(duplicates == (mode == dafree::HardlinkMode::Dedup ? 2u : 0u));
    }
}

TEST_CASE("engine_hardlink_identity_and_platform_policy") {
    dafree::MockSpec spec;
    const auto root = root_path();
    spec.entries.push_back({root, entry(dafree::EntryKind::Dir)});
    for (unsigned index = 0; index < 3; ++index) {
        auto file = entry(dafree::EntryKind::File, 1);
        file.dev = index == 2 ? 2 : 1;
        file.ino_lo = 10;
        file.ino_hi = index == 1 ? 1 : 0;
        file.nlink = 2;
        spec.entries.push_back({root + "/file-" + std::to_string(index), file});
    }
    auto handle = dafree::start_scan(options(), dafree::make_mock_backend(spec));
    REQUIRE(handle.wait(5s));
    CHECK(handle.take_result().summary.bytes == 3);
    spec.entries[2].entry = spec.entries[3].entry = spec.entries[1].entry;
    for (auto &item : spec.entries)
        item.entry.nlink = 1;
    auto policy = dafree::start_scan(options(), dafree::make_mock_backend(spec));
    REQUIRE(policy.wait(5s));
    CHECK(policy.take_result().summary.bytes == (dafree::platform::windows_paths() ? 1u : 3u));
}

TEST_CASE("engine_symlink_loop_and_default_policy") {
    const auto root = root_path();
    dafree::MockSpec spec;
    spec.entries = {{root, entry(dafree::EntryKind::Dir)},
                    {root + "/child", entry(dafree::EntryKind::Dir)},
                    {root + "/child/back", entry(dafree::EntryKind::Symlink, 99)}};
    spec.symlink_targets[root + "/child/back"] = root;
    for (const bool follow : {false, true}) {
        auto opts = options();
        opts.follow_symlinks = follow;
        auto backend = std::make_shared<dafree::MockBackend>(spec);
        auto handle = dafree::start_scan(opts, backend);
        REQUIRE(handle.wait(5s));
        const auto result = handle.take_result();
        CHECK(result.summary.bytes == 0);
        CHECK(backend->read_dir_calls() == 2);
        const auto back = result.tree->find_path(root + "/child/back");
        REQUIRE(back.has_value());
        CHECK((result.tree->node(*back).flags & dafree::kSymlink) != 0);
        CHECK(result.summary.files == (follow ? 0u : 1u));
        CHECK(result.summary.dirs == (follow ? 3u : 2u));
        CHECK(result.summary.issues
                  .counts[static_cast<std::size_t>(dafree::IssueKind::SymlinkLoop)] ==
              (follow ? 1u : 0u));
    }
}

TEST_CASE("engine_follows_directory_alias_only_when_enabled") {
    const auto root = root_path();
    const std::string outside = root + "-outside";
    for (const auto kind : {dafree::EntryKind::Symlink, dafree::EntryKind::Junction}) {
        dafree::MockSpec spec;
        spec.entries = {{root, entry(dafree::EntryKind::Dir)},
                        {root + "/alias", entry(kind, 50)},
                        {outside, entry(dafree::EntryKind::Dir)},
                        {outside + "/file", entry(dafree::EntryKind::File, 17)}};
        spec.symlink_targets[root + "/alias"] = outside;
        for (const bool follow : {false, true}) {
            auto opts = options();
            opts.follow_symlinks = follow;
            auto handle = dafree::start_scan(opts, dafree::make_mock_backend(spec));
            REQUIRE(handle.wait(5s));
            const auto result = handle.take_result();
            CHECK(result.summary.bytes == (follow ? 17u : 0u));
            CHECK(result.tree->find_path(root + "/alias/file").has_value() == follow);
        }
    }
}

TEST_CASE("engine_mount_boundaries_follow_option") {
    const auto root = root_path();
    dafree::MockSpec spec;
    auto mount = entry(dafree::EntryKind::MountPoint);
    mount.dev = 2;
    auto file = entry(dafree::EntryKind::File, 7);
    file.dev = 2;
    spec.entries = {{root, entry(dafree::EntryKind::Dir)},
                    {root + "/mount", mount},
                    {root + "/mount/file", file}};
    for (const bool cross : {false, true}) {
        auto opts = options();
        opts.cross_filesystems = cross;
        auto backend = std::make_shared<dafree::MockBackend>(spec);
        auto handle = dafree::start_scan(opts, backend);
        REQUIRE(handle.wait(5s));
        const auto result = handle.take_result();
        CHECK(result.summary.bytes == (cross ? 7u : 0u));
        CHECK(backend->read_dir_calls() == (cross ? 2u : 1u));
        const auto mounted = result.tree->find_path(root + "/mount");
        REQUIRE(mounted.has_value());
        CHECK((result.tree->node(*mounted).flags & dafree::kMountPoint) != 0);
    }
}

TEST_CASE("engine_cloud_metadata_is_not_followed") {
    auto spec = sample();
    spec.entries[1].entry.cloud = true;
    spec.symlink_targets[root_path() + "/alpha"] = root_path() + "/missing";
    auto opts = options();
    opts.follow_symlinks = true;
    auto handle = dafree::start_scan(opts, dafree::make_mock_backend(std::move(spec)));
    REQUIRE(handle.wait(5s));
    const auto result = handle.take_result();
    CHECK(result.summary.bytes == 30);
    CHECK(result.summary.issues.total == 0);
    const auto cloud = result.tree->find_path(root_path() + "/alpha");
    REQUIRE(cloud.has_value());
    CHECK((result.tree->node(*cloud).flags & dafree::kCloudPlaceholder) != 0);
}

TEST_CASE("engine_explicit_link_root") {
    const auto root = root_path();
    const auto outside = root + "-outside";
    dafree::MockSpec spec;
    spec.entries = {{root, entry(dafree::EntryKind::Symlink, 50)},
                    {outside, entry(dafree::EntryKind::Dir)},
                    {outside + "/file", entry(dafree::EntryKind::File, 17)}};
    spec.symlink_targets[root] = outside;
    for (const bool follow : {false, true}) {
        auto opts = options();
        opts.follow_symlinks = follow;
        auto handle = dafree::start_scan(opts, dafree::make_mock_backend(spec));
        REQUIRE(handle.wait(5s));
        const auto result = handle.take_result();
        CHECK(result.summary.bytes == (follow ? 17u : 0u));
        CHECK(result.tree->find_path(root + "/file").has_value() == follow);
    }
    spec.entries[0].entry.kind = dafree::EntryKind::MountPoint;
    auto mounted = dafree::start_scan(options(), dafree::make_mock_backend(spec));
    REQUIRE(mounted.wait(5s));
    CHECK(mounted.take_result().summary.bytes == 17);
}

TEST_CASE("engine_symlink_chain_loop") {
    const auto root = root_path();
    dafree::MockSpec spec;
    spec.entries = {{root, entry(dafree::EntryKind::Dir)},
                    {root + "/alias", entry(dafree::EntryKind::Symlink, 50)}};
    spec.symlink_targets[root + "/alias"] = root + "/alias/sub";
    auto opts = options();
    opts.follow_symlinks = true;
    auto handle = dafree::start_scan(opts, dafree::make_mock_backend(spec));
    REQUIRE(handle.wait(5s));
    const auto result = handle.take_result();
    CHECK(result.summary.bytes == 0);
    CHECK(result.summary.issues.counts[static_cast<std::size_t>(dafree::IssueKind::SymlinkLoop)] ==
          1);
}
