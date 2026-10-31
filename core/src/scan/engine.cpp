#include "dafree/scan.hpp"
#include "glob.hpp"
#include "work_queue.hpp"

#include <algorithm>
#include <atomic>
#include <condition_variable>
#include <deque>
#include <exception>
#include <limits>
#include <mutex>
#include <thread>

namespace dafree {
namespace {

using Clock = std::chrono::steady_clock;

std::string normalize_target(std::string_view input) {
    if (input.empty() || input.find('\0') != std::string_view::npos)
        throw ScanError(ScanError::Code::InvalidTarget, "empty target or embedded NUL");
    std::string path(input);
    const bool windows = platform::windows_paths();
    if (windows) {
        std::replace(path.begin(), path.end(), '\\', '/');
        if (path.starts_with("//?/UNC/"))
            path = "//" + path.substr(8);
        else if (path.starts_with("//?/"))
            path.erase(0, 4);
    }
    const bool drive = windows && path.size() >= 3 &&
                       ((path[0] >= 'A' && path[0] <= 'Z') || (path[0] >= 'a' && path[0] <= 'z')) &&
                       path[1] == ':' && path[2] == '/';
    const bool unc = windows && path.starts_with("//");
    if (windows ? !(drive || unc) : !path.starts_with('/'))
        throw ScanError(ScanError::Code::InvalidTarget, "scan targets must be absolute");
    std::size_t offset = drive ? 3 : (unc ? 2 : 1);
    std::string result = path.substr(0, offset);
    std::vector<std::string_view> components;
    while (offset < path.size()) {
        const auto end = path.find('/', offset);
        const auto stop = end == std::string::npos ? path.size() : end;
        const std::string_view part(path.data() + offset, stop - offset);
        if (part == "..") {
            if (components.size() > (unc ? 2u : 0u))
                components.pop_back();
        } else if (!part.empty() && part != ".")
            components.push_back(part);
        offset = stop + 1;
    }
    if (unc && components.size() < 2)
        throw ScanError(ScanError::Code::InvalidTarget, "UNC target requires a server and share");
    for (const auto part : components) {
        if (!result.ends_with('/'))
            result.push_back('/');
        result.append(part);
    }
    if (windows)
        std::replace(result.begin(), result.end(), '/', '\\');
    return result;
}

bool path_under(std::string_view path, std::string_view prefix) {
    std::size_t a = 0, b = 0;
    while (b < prefix.size()) {
        if (a == path.size())
            return false;
        auto left = detail::next_codepoint(path, a);
        auto right = detail::next_codepoint(prefix, b);
        if (platform::case_insensitive_paths()) {
            left = detail::fold_codepoint(left);
            right = detail::fold_codepoint(right);
        }
        if (left != right)
            return false;
    }
    const auto separator = platform::windows_paths() ? '\\' : '/';
    return a == path.size() || prefix.back() == separator || path[a] == separator;
}

bool is_directory(const RawEntry &entry) {
    return entry.kind == EntryKind::Dir || entry.kind == EntryKind::MountPoint;
}

std::uint16_t flags_for(const RawEntry &entry) {
    unsigned flags = 0;
    if (is_directory(entry))
        flags |= kDir;
    if (entry.kind == EntryKind::Symlink)
        flags |= kSymlink;
    if (entry.kind == EntryKind::Junction || entry.kind == EntryKind::OtherReparse)
        flags |= kReparse;
    if (entry.kind == EntryKind::MountPoint)
        flags |= kMountPoint;
    if (entry.hidden)
        flags |= kHidden;
    if (entry.system)
        flags |= kSystem;
    if (entry.sparse)
        flags |= kSparse;
    if (entry.compressed)
        flags |= kCompressed;
    if (entry.cloud)
        flags |= kCloudPlaceholder;
    if (entry.access_denied)
        flags |= kAccessDenied;
    return static_cast<std::uint16_t>(flags);
}

std::uint32_t node_time(std::optional<std::int64_t> timestamp) {
    if (!timestamp || *timestamp <= 0)
        return 0;
    return static_cast<std::uint32_t>(std::min<std::uint64_t>(
        static_cast<std::uint64_t>(*timestamp), std::numeric_limits<std::uint32_t>::max()));
}

void add_saturated(std::atomic<std::uint64_t> &counter, std::uint64_t amount) {
    auto old = counter.load(std::memory_order_relaxed);
    for (;;) {
        const auto limit = std::numeric_limits<std::uint64_t>::max();
        const auto next = amount > limit - old ? limit : old + amount;
        if (counter.compare_exchange_weak(old, next, std::memory_order_relaxed))
            break;
    }
}

std::int64_t unix_now() {
    return std::chrono::duration_cast<std::chrono::seconds>(
               std::chrono::system_clock::now().time_since_epoch())
        .count();
}

struct Prepared {
    ScanOptions options;
    std::vector<RawEntry> roots;
    std::vector<CompiledExcludes> excludes;
    std::vector<VolumeInfo> volumes;
};

Prepared prepare(ScanOptions options, FsBackend &backend) {
    if (options.targets.empty())
        throw ScanError(ScanError::Code::EmptyTargets, "at least one scan target is required");
    if (options.mode == ScanMode::Mft)
        throw ScanError(ScanError::Code::UnsupportedMode, "MFT scanning is not available yet");
    std::vector<std::string> targets;
    for (const auto &input : options.targets) {
        auto path = normalize_target(input);
        bool duplicate = false;
        for (const auto &existing : targets) {
            const bool a = path_under(path, existing), b = path_under(existing, path);
            if (a && b) {
                duplicate = true;
                break;
            }
            if (a || b)
                throw ScanError(ScanError::Code::OverlappingTargets, "scan targets overlap");
        }
        if (!duplicate)
            targets.push_back(std::move(path));
    }
    options.targets = std::move(targets);
    Prepared prepared;
    bool network = false, rotational = false;
    for (const auto &path : options.targets) {
        prepared.roots.push_back(backend.stat_root(path));
        prepared.excludes.push_back(CompiledExcludes::compile(options.exclude, path));
        if (auto volume = backend.volume_info(path)) {
            network = network || volume->is_network;
            rotational = rotational || volume->is_rotational.value_or(false);
            prepared.volumes.push_back(std::move(*volume));
        }
    }
    if (options.threads == 0) {
        const unsigned cpus = std::max(1u, std::thread::hardware_concurrency());
        options.threads = network ? 16u : (rotational ? 2u : std::min(cpus, 16u) * 2u);
    }
    prepared.options = std::move(options);
    return prepared;
}

} // namespace

class ScanEngine {
  public:
    ScanEngine(ScanOptions options, std::shared_ptr<FsBackend> backend)
        : backend_(std::move(backend)), input_(prepare(std::move(options), *backend_)),
          builder_(input_.options.targets),
          results_(4u * static_cast<std::size_t>(input_.options.threads)),
          remaining_(input_.options.threads), started_(Clock::now()),
          last_snapshot_(started_ - std::chrono::seconds(1)), last_progress_(started_),
          started_at_(unix_now()), identity_(platform::system_identity()) {
        backend_mode_ =
            backend_->kind() == BackendKind::Sftp ? ScanModeUsed::Sftp : ScanModeUsed::Walk;
        current_ = input_.options.targets.front();
        for (std::size_t index = 0; index < input_.roots.size(); ++index) {
            const auto id = static_cast<NodeId>(index + 1);
            const auto &entry = input_.roots[index];
            auto &node = builder_.tree_.nodes_[id];
            node.flags = flags_for(entry);
            node.size = entry.size;
            node.alloc = entry.alloc;
            node.mtime = node_time(entry.mtime);
            node.btime = node_time(entry.btime);
            node.atime = node_time(entry.atime);
            node.ext_id =
                builder_.tree_.exts_.intern(builder_.tree_.name_bytes(id), is_directory(entry));
            if (entry.owner && input_.options.owner != OwnerMode::Off)
                node.owner = builder_.tree_.owners_.intern(*entry.owner, {});
            count(entry);
            if (is_directory(entry)) {
                jobs_.push({id, input_.options.targets[index], index, entry.dev});
                ++pending_;
            }
        }
        input_.roots.clear();
        input_.roots.shrink_to_fit();
        for (const auto &volume : input_.volumes) {
            if (volume.is_network)
                notices_.push_back({Notice::NetworkVolume, volume.mount});
            if (volume.is_rotational.value_or(false))
                notices_.push_back({Notice::RotationalDisk, volume.mount});
        }
        if (pending_ == 0)
            jobs_.close();
    }

    ~ScanEngine() {
        cancel();
        join();
    }

    void start() {
        try {
            workers_.reserve(input_.options.threads);
            for (unsigned index = 0; index < input_.options.threads; ++index)
                workers_.emplace_back([this] { run_worker(); });
            coordinator_ = std::thread([this] { run_builder(); });
        } catch (...) {
            cancel();
            results_.close(true);
            for (auto &worker : workers_)
                if (worker.joinable())
                    worker.join();
            throw;
        }
    }

    ScanProgress progress() const {
        ScanProgress value;
        value.files = files_.load(std::memory_order_relaxed);
        value.dirs = dirs_.load(std::memory_order_relaxed);
        value.bytes = bytes_.load(std::memory_order_relaxed);
        value.alloc = alloc_.load(std::memory_order_relaxed);
        value.issues = issue_count_.load(std::memory_order_relaxed);
        value.state = phase_.load(std::memory_order_acquire);
        value.mode = backend_mode_;
        value.elapsed_ms =
            terminal(value.state) ? elapsed_.load(std::memory_order_relaxed) : elapsed_now();
        {
            std::lock_guard lock(progress_mutex_);
            value.current = current_;
        }
        return value;
    }

    void pause() {
        std::lock_guard lock(gate_mutex_);
        if (phase_.load() == ScanState::Running) {
            paused_ = true;
            phase_.store(ScanState::Paused);
        }
    }
    void resume() {
        {
            std::lock_guard lock(gate_mutex_);
            paused_ = false;
            if (phase_.load() == ScanState::Paused)
                phase_.store(ScanState::Running);
        }
        gate_.notify_all();
    }
    void cancel() {
        cancelled_.store(true, std::memory_order_release);
        jobs_.close(true);
        gate_.notify_all();
    }
    bool wait(std::chrono::milliseconds timeout) {
        std::unique_lock lock(done_mutex_);
        return done_.wait_for(lock, timeout, [&] { return finished_; });
    }
    ScanResult take_result() {
        {
            std::lock_guard lock(done_mutex_);
            if (!finished_)
                throw ScanError(ScanError::Code::NotFinished, "scan is not finished");
        }
        join();
        std::lock_guard lock(done_mutex_);
        if (failure_)
            std::rethrow_exception(failure_);
        if (taken_)
            throw ScanError(ScanError::Code::AlreadyTaken, "scan result was already consumed");
        taken_ = true;
        return std::move(*result_);
    }
    std::vector<ScanIssue> drain_issues(std::size_t max) {
        std::lock_guard lock(issue_mutex_);
        std::vector<ScanIssue> drained;
        drained.reserve(std::min(max, issues_.size()));
        while (!issues_.empty() && drained.size() < max) {
            drained.push_back(std::move(issues_.front()));
            issues_.pop_front();
        }
        return drained;
    }
    std::vector<Notice> drain_notices() {
        std::lock_guard lock(notice_mutex_);
        std::vector<Notice> drained;
        drained.reserve(notices_.size());
        while (!notices_.empty()) {
            drained.push_back(std::move(notices_.front()));
            notices_.pop_front();
        }
        return drained;
    }
    std::shared_ptr<const Tree> partial_tree() const {
        snapshot_requested_.store(true, std::memory_order_release);
        std::lock_guard lock(snapshot_mutex_);
        return snapshot_;
    }

  private:
    struct Job {
        NodeId dir;
        std::string path;
        std::size_t root;
        std::uint64_t dev;
    };
    struct DirResult {
        Job job;
        DirListing listing;
        std::optional<ScanIssue> error;
    };

    static bool terminal(ScanState state) {
        return state == ScanState::Done || state == ScanState::Cancelled ||
               state == ScanState::Failed;
    }
    std::uint64_t elapsed_now() const {
        return static_cast<std::uint64_t>(
            std::chrono::duration_cast<std::chrono::milliseconds>(Clock::now() - started_).count());
    }
    void join() {
        std::lock_guard lock(join_mutex_);
        if (coordinator_.joinable())
            coordinator_.join();
        for (auto &worker : workers_)
            if (worker.joinable())
                worker.join();
    }
    void fail(std::exception_ptr failure) {
        {
            std::lock_guard lock(failure_mutex_);
            if (!failure_)
                failure_ = std::move(failure);
        }
        cancel();
    }
    void run_worker() noexcept {
        try {
            while (auto job = jobs_.pop()) {
                {
                    std::unique_lock lock(gate_mutex_);
                    gate_.wait(lock, [&] {
                        return !paused_ || cancelled_.load(std::memory_order_acquire);
                    });
                }
                if (cancelled_.load(std::memory_order_acquire))
                    break;
                DirResult result{std::move(*job), {}, {}};
                try {
                    result.listing = backend_->read_dir(result.job.path, {});
                } catch (const IoError &error) {
                    result.error = ScanIssue{result.job.path, error.kind(), error.what()};
                }
                if (!results_.push(std::move(result)))
                    break;
            }
        } catch (...) {
            fail(std::current_exception());
        }
        if (remaining_.fetch_sub(1, std::memory_order_acq_rel) == 1)
            results_.close();
    }
    void count(const RawEntry &entry) {
        if (is_directory(entry))
            add_saturated(dirs_, 1);
        else {
            add_saturated(files_, 1);
            add_saturated(bytes_, entry.size);
            add_saturated(alloc_, entry.alloc);
        }
    }
    void issue(ScanIssue value) {
        ++issue_summary_.total;
        auto index = static_cast<std::size_t>(value.kind);
        if (index >= issue_summary_.counts.size())
            index = static_cast<std::size_t>(IssueKind::Other);
        ++issue_summary_.counts[index];
        if (issue_summary_.first.size() < 1000)
            issue_summary_.first.push_back(value);
        issue_count_.store(issue_summary_.total, std::memory_order_relaxed);
        std::lock_guard lock(issue_mutex_);
        if (issues_.size() < 100000)
            issues_.push_back(std::move(value));
        else
            ++issue_summary_.overflow;
    }
    void consume(DirResult result) {
        const auto &job = result.job;
        if (result.error) {
            builder_.mark(job.dir, static_cast<std::uint16_t>(
                                       kPartial | (result.error->kind == IssueKind::AccessDenied
                                                       ? kAccessDenied
                                                       : kError)));
            issue(std::move(*result.error));
            builder_.add_children(job.dir, {});
        } else {
            for (auto &value : result.listing.issues)
                issue(std::move(value));
            if (result.listing.partial)
                builder_.mark(job.dir, kPartial);
            std::vector<TreeBuilder::NewNode> nodes;
            struct Child {
                std::size_t index;
                std::string path;
                std::uint64_t dev;
            };
            std::vector<Child> children;
            nodes.reserve(result.listing.entries.size());
            const auto &root = input_.options.targets[job.root];
            std::string relative = job.path.substr(root.size());
            const char native_separator = platform::windows_paths() ? '\\' : '/';
            while (!relative.empty() && relative.front() == native_separator)
                relative.erase(0, 1);
            if (!relative.empty())
                relative.push_back('/');
            const auto base = relative.size();
            for (const auto &entry : result.listing.entries) {
                if (cancelled_.load(std::memory_order_acquire)) {
                    builder_.mark(job.dir, kPartial);
                    break;
                }
                relative.resize(base);
                relative.append(entry.name);
                if (input_.excludes[job.root].excluded(relative, entry.name, entry))
                    continue;
                nodes.push_back(
                    {entry.name, flags_for(entry), entry.size, entry.alloc, node_time(entry.mtime),
                     node_time(entry.btime), node_time(entry.atime),
                     input_.options.owner == OwnerMode::Off ? std::nullopt : entry.owner});
                count(entry);
                if (is_directory(entry)) {
                    std::string path = job.path;
                    const char separator = platform::windows_paths() ? '\\' : '/';
                    if (!path.ends_with(separator))
                        path.push_back(separator);
                    path.append(entry.name);
                    children.push_back({nodes.size() - 1, std::move(path), entry.dev});
                }
            }
            const auto range = builder_.add_children(job.dir, nodes);
            for (auto &child : children) {
                if (!cancelled_.load(std::memory_order_acquire) &&
                    jobs_.push({range.first + static_cast<NodeId>(child.index),
                                std::move(child.path), job.root, child.dev}))
                    ++pending_;
            }
        }
        if (--pending_ == 0)
            jobs_.close();
        const auto now = Clock::now();
        if (now - last_progress_ >=
            std::chrono::milliseconds(input_.options.progress_interval_ms)) {
            std::lock_guard lock(progress_mutex_);
            current_ = job.path;
            last_progress_ = now;
        }
    }
    ScanMeta metadata() const {
        ScanMeta meta;
        meta.started_at = started_at_;
        meta.finished_at = unix_now();
        meta.mode = backend_mode_;
        meta.options = input_.options;
        meta.host = identity_.first;
        meta.os = identity_.second;
        meta.app_version = DAFREE_VERSION;
        meta.volumes = input_.volumes;
        meta.issues = issue_summary_;
        meta.cancelled = cancelled_.load(std::memory_order_acquire);
        return meta;
    }
    std::shared_ptr<const Tree> clone_tree() {
        auto copy = std::make_shared<Tree>();
        const auto &source = builder_.tree_;
        copy->roots_ = source.roots_;
        copy->root_paths_ = source.root_paths_;
        copy->exts_ = source.exts_;
        copy->owners_ = source.owners_;
        copy->meta_ = metadata();
        for (NodeId id = 0; id < source.size(); ++id) {
            auto node = source.nodes_[id];
            const auto name = source.name_bytes(id);
            const auto stored = copy->names_.push(name);
            node.name_off = stored.first;
            node.name_len = stored.second;
            copy->nodes_.push_back(node);
            copy->counts_.push_back(source.counts_[id]);
        }
        return copy;
    }
    void maybe_snapshot() {
        if (!snapshot_requested_.load(std::memory_order_acquire) ||
            Clock::now() - last_snapshot_ < std::chrono::seconds(1) || slow_aggregate_)
            return;
        snapshot_requested_.store(false, std::memory_order_release);
        const auto start = Clock::now();
        builder_.aggregate_partial();
        slow_aggregate_ = Clock::now() - start > std::chrono::milliseconds(200);
        auto copy = clone_tree();
        {
            std::lock_guard lock(snapshot_mutex_);
            snapshot_ = std::move(copy);
        }
        last_snapshot_ = Clock::now();
    }
    void run_builder() noexcept {
        try {
            while (!results_.drained()) {
                if (auto result = results_.pop_for(std::chrono::milliseconds(20)))
                    consume(std::move(*result));
                maybe_snapshot();
            }
            for (auto &worker : workers_)
                if (worker.joinable())
                    worker.join();
            {
                std::lock_guard lock(failure_mutex_);
                if (failure_)
                    std::rethrow_exception(failure_);
            }
            phase_.store(ScanState::Finalizing, std::memory_order_release);
            if (cancelled_.load(std::memory_order_acquire)) {
                for (NodeId id = 1; id < builder_.tree_.size(); ++id)
                    if ((builder_.tree_.nodes_[id].flags & kDir) != 0 && !builder_.populated_[id])
                        builder_.mark(id, kPartial);
            }
            auto tree = std::make_shared<Tree>(std::move(builder_).finish(metadata()));
            const auto counts = tree->counts(kRoot);
            ScanSummary summary{
                counts.files,  counts.dirs,    tree->node(kRoot).size, tree->node(kRoot).alloc,
                elapsed_now(), issue_summary_, tree->meta().cancelled};
            files_.store(summary.files);
            dirs_.store(summary.dirs);
            bytes_.store(summary.bytes);
            alloc_.store(summary.alloc);
            elapsed_.store(summary.elapsed_ms);
            {
                std::lock_guard lock(snapshot_mutex_);
                snapshot_ = tree;
            }
            result_ = ScanResult{std::move(tree), std::move(summary)};
            backend_.reset();
            input_.excludes.clear();
            phase_.store(result_->summary.cancelled ? ScanState::Cancelled : ScanState::Done,
                         std::memory_order_release);
        } catch (...) {
            fail(std::current_exception());
            results_.close(true);
            for (auto &worker : workers_)
                if (worker.joinable())
                    worker.join();
            elapsed_.store(elapsed_now());
            phase_.store(ScanState::Failed, std::memory_order_release);
        }
        {
            std::lock_guard lock(done_mutex_);
            finished_ = true;
        }
        done_.notify_all();
    }

    std::shared_ptr<FsBackend> backend_;
    Prepared input_;
    TreeBuilder builder_;
    detail::WorkQueue<Job> jobs_;
    detail::WorkQueue<DirResult> results_;
    std::vector<std::thread> workers_;
    std::thread coordinator_;
    std::atomic<unsigned> remaining_;
    std::size_t pending_ = 0;
    std::atomic<bool> cancelled_{false};
    bool paused_ = false;
    std::mutex gate_mutex_, join_mutex_, done_mutex_, failure_mutex_, issue_mutex_, notice_mutex_;
    mutable std::mutex progress_mutex_, snapshot_mutex_;
    std::condition_variable gate_, done_;
    bool finished_ = false, taken_ = false;
    std::optional<ScanResult> result_;
    std::exception_ptr failure_;
    std::deque<ScanIssue> issues_;
    std::deque<Notice> notices_;
    IssueSummary issue_summary_;
    std::atomic<ScanState> phase_{ScanState::Running};
    std::atomic<std::uint64_t> files_{0}, dirs_{0}, bytes_{0}, alloc_{0}, issue_count_{0},
        elapsed_{0};
    ScanModeUsed backend_mode_ = ScanModeUsed::Walk;
    std::string current_;
    mutable std::atomic<bool> snapshot_requested_{false};
    std::shared_ptr<const Tree> snapshot_;
    Clock::time_point started_, last_snapshot_, last_progress_;
    std::int64_t started_at_;
    std::pair<std::string, std::string> identity_;
    bool slow_aggregate_ = false;
};

ScanHandle::~ScanHandle() = default;
ScanHandle::ScanHandle(ScanHandle &&) noexcept = default;
ScanHandle &ScanHandle::operator=(ScanHandle &&) noexcept = default;
ScanEngine &ScanHandle::engine() const {
    if (!engine_)
        throw ScanError(ScanError::Code::InvalidHandle, "scan handle was moved");
    return *engine_;
}
ScanProgress ScanHandle::progress() const { return engine().progress(); }
std::vector<ScanIssue> ScanHandle::drain_issues(std::size_t max) {
    return engine().drain_issues(max);
}
std::vector<Notice> ScanHandle::drain_notices() { return engine().drain_notices(); }
void ScanHandle::pause() { engine().pause(); }
void ScanHandle::resume() { engine().resume(); }
void ScanHandle::cancel() { engine().cancel(); }
bool ScanHandle::wait(std::chrono::milliseconds timeout) { return engine().wait(timeout); }
std::shared_ptr<const Tree> ScanHandle::partial_tree() const { return engine().partial_tree(); }
ScanResult ScanHandle::take_result() { return engine().take_result(); }

ScanHandle start_scan(ScanOptions options, std::shared_ptr<FsBackend> backend) {
    if (!backend)
        backend = make_local_backend();
    auto engine = std::make_shared<ScanEngine>(std::move(options), std::move(backend));
    engine->start();
    return ScanHandle(std::move(engine));
}

} // namespace dafree
