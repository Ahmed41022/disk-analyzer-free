#pragma once

#include "dafree/backend.hpp"

#include <chrono>

namespace dafree {

/// An invalid exclusion pattern, with the original input for diagnostics.
class ExcludeError : public Error {
  public:
    /// Construct an exclusion syntax error.
    ExcludeError(std::string input, const std::string &message)
        : Error(message), pattern(std::move(input)) {}
    const std::string pattern;
};

/// Immutable exclusions compiled once for a scan root.
class CompiledExcludes {
  public:
    /// Validate patterns and resolve excluded paths relative to the root.
    static CompiledExcludes compile(const ExcludeRules &rules, std::string_view root);
    /// Test a root-relative path and native entry name without filesystem access.
    [[nodiscard]] bool excluded(std::string_view rel_path, std::string_view name,
                                const RawEntry &entry) const;

  private:
    struct Impl;
    explicit CompiledExcludes(std::shared_ptr<const Impl> impl) : impl_(std::move(impl)) {}
    std::shared_ptr<const Impl> impl_;
};

/// Invalid scan input or misuse of a scan handle.
class ScanError : public Error {
  public:
    enum class Code {
        EmptyTargets,
        InvalidTarget,
        OverlappingTargets,
        UnsupportedMode,
        NotFinished,
        AlreadyTaken,
        InvalidHandle
    };
    /// Construct an error with a stable category.
    ScanError(Code code, const std::string &message) : Error(message), code_(code) {}
    /// Return the error category.
    [[nodiscard]] Code code() const noexcept { return code_; }

  private:
    Code code_;
};

/// Final entry and byte totals, with elapsed time and recoverable issues.
struct ScanSummary {
    std::uint64_t files = 0, dirs = 0, bytes = 0, alloc = 0, elapsed_ms = 0;
    IssueSummary issues;
    bool cancelled = false;
};

/// Immutable scan output and its summary.
struct ScanResult {
    std::shared_ptr<const Tree> tree;
    ScanSummary summary;
};

class ScanEngine;

/// Thread-safe control and snapshots for one asynchronous scan.
class ScanHandle {
  public:
    /// Cancel and join unfinished work before releasing its resources.
    ~ScanHandle();
    ScanHandle(const ScanHandle &) = delete;
    ScanHandle &operator=(const ScanHandle &) = delete;
    /// Transfer ownership of a running scan.
    ScanHandle(ScanHandle &&) noexcept;
    /// Cancel existing work and take ownership of another scan.
    ScanHandle &operator=(ScanHandle &&) noexcept;
    /// Return a progress snapshot without waiting for I/O.
    [[nodiscard]] ScanProgress progress() const;
    /// Remove up to max live diagnostics from the bounded issue queue.
    std::vector<ScanIssue> drain_issues(std::size_t max = 1000);
    /// Remove all currently queued policy notices.
    std::vector<Notice> drain_notices();
    /// Stop workers between directory reads.
    void pause();
    /// Resume workers after a pause.
    void resume();
    /// Request cancellation and wake paused or idle workers.
    void cancel();
    /// Wait up to the supplied duration for all scan threads to finish.
    bool wait(std::chrono::milliseconds timeout);
    /// Request a throttled snapshot and return the latest available immutable tree.
    [[nodiscard]] std::shared_ptr<const Tree> partial_tree() const;
    /// Consume the final result once; throw if unfinished, failed, or already consumed.
    ScanResult take_result();

  private:
    friend ScanHandle start_scan(ScanOptions, std::shared_ptr<FsBackend>);
    explicit ScanHandle(std::shared_ptr<ScanEngine> engine) : engine_(std::move(engine)) {}
    [[nodiscard]] ScanEngine &engine() const;
    std::shared_ptr<ScanEngine> engine_;
};

/// Validate targets and begin a scan using the supplied or local backend.
ScanHandle start_scan(ScanOptions options, std::shared_ptr<FsBackend> backend = nullptr);

} // namespace dafree
