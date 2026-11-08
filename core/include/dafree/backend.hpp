#pragma once

#include "dafree/platform.hpp"

#include <chrono>
#include <memory>
#include <unordered_map>
#include <vector>

namespace dafree {

/// Transport used to access filesystem entries.
enum class BackendKind : std::uint8_t { Local, Sftp };

/// Explicit traversal policy for the final directory component.
struct DirHint {
    bool follow_symlinks = false;
};

struct ScanOptions;
class FastScanSink;

/// Non-recursive filesystem operations consumed by the scan engine.
// Stateless abstract interface: virtual destruction does not change copy semantics.
// NOLINTNEXTLINE(cppcoreguidelines-special-member-functions)
class FsBackend {
  public:
    virtual ~FsBackend() = default;
    /// Return the transport represented by this backend.
    [[nodiscard]] virtual auto kind() const -> BackendKind = 0;
    /// Read root metadata without following a final link; throw IoError on failure.
    virtual auto stat_root(std::string_view path) -> RawEntry = 0;
    /// Read a followed target when supported; default backends retain no-follow behavior.
    virtual auto stat_follow(std::string_view path) -> RawEntry { return stat_root(path); }
    /// Enumerate direct children; follow the final directory only when explicitly hinted.
    virtual auto read_dir(std::string_view dir, const DirHint &hint) -> DirListing = 0;
    /// Return volume properties if the backend can supply them.
    virtual auto volume_info(std::string_view path) -> std::optional<VolumeInfo> = 0;
    /// Return whether this backend can use the host Windows NTFS reader.
    [[nodiscard]] virtual auto supports_local_mft() const noexcept -> bool { return false; }
    /// Attempt the optional fast scan protocol; false means unsupported.
    virtual auto fast_scan(std::string_view, const ScanOptions &, FastScanSink &) -> bool {
        return false;
    }
    /// Return whether owner metadata can be read lazily by path without an identity hint.
    [[nodiscard]] virtual auto can_resolve_owner_by_path() const noexcept -> bool { return false; }
    /// Resolve an owner using an optional identity hint.
    virtual auto resolve_owner(std::string_view path, const OwnerKey *hint)
        -> std::optional<std::pair<OwnerKey, std::string>> = 0;
};

/// One native-path entry in an in-memory filesystem description.
struct MockEntry {
    std::string path;
    RawEntry entry;
};

/// Deterministic filesystem input and failures for scanner tests.
struct MockSpec {
    std::vector<MockEntry> entries;
    std::unordered_map<std::string, IssueKind> errors;
    std::vector<std::string> vanish_after_listing;
    std::chrono::milliseconds delay{0};
    std::optional<VolumeInfo> volume;
    std::unordered_map<std::uint32_t, std::string> owner_names;
    std::unordered_map<std::string, std::string> symlink_targets{};
};

/// Thread-safe in-memory local filesystem with injected failures and call counters.
class MockBackend final : public FsBackend {
  public:
    /// Validate and index an immutable filesystem description.
    explicit MockBackend(MockSpec spec);
    ~MockBackend() override;
    /// Backends retain one immutable implementation and cannot be copied or moved.
    MockBackend(const MockBackend &) = delete;
    auto operator=(const MockBackend &) -> MockBackend & = delete;
    MockBackend(MockBackend &&) = delete;
    auto operator=(MockBackend &&) -> MockBackend & = delete;
    /// Report local semantics without accessing the real filesystem.
    [[nodiscard]] auto kind() const -> BackendKind override;
    /// Read synthetic metadata or throw an injected error.
    auto stat_root(std::string_view path) -> RawEntry override;
    /// Resolve synthetic aliases while rejecting loops in the alias chain.
    auto stat_follow(std::string_view path) -> RawEntry override;
    /// Return synthetic direct children and deterministic per-entry issues.
    auto read_dir(std::string_view dir, const DirHint &hint) -> DirListing override;
    /// Return the optional synthetic volume information.
    auto volume_info(std::string_view path) -> std::optional<VolumeInfo> override;
    /// Resolve a supplied UID through the synthetic owner table, with numeric fallback.
    auto resolve_owner(std::string_view path, const OwnerKey *hint)
        -> std::optional<std::pair<OwnerKey, std::string>> override;
    /// Count all attempted directory reads, including failed reads.
    [[nodiscard]] auto read_dir_calls() const noexcept -> std::uint64_t;
    /// Count all attempted owner resolutions.
    [[nodiscard]] auto owner_resolution_calls() const noexcept -> std::uint64_t;

  private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

/// Create a backend over the host filesystem.
auto make_local_backend() -> std::shared_ptr<FsBackend>;
/// Create an in-memory backend from the supplied test description.
auto make_mock_backend(MockSpec spec) -> std::shared_ptr<FsBackend>;

} // namespace dafree
