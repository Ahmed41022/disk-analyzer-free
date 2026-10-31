#include "../src/scan/work_queue.hpp"
#include "dafree/scan.hpp"

#include <doctest/doctest.h>

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
