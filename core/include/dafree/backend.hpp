#pragma once

#include "dafree/platform.hpp"

#include <chrono>
#include <memory>
#include <unordered_map>
#include <vector>

namespace dafree {

/// Transport used to access filesystem entries.
enum class BackendKind : std::uint8_t { Local, Sftp };

/// Optional directory hints, reserved for scan-owned traversal metadata.
struct DirHint {};

struct ScanOptions;
class FastScanSink;

/// Non-recursive filesystem operations consumed by the scan engine.
class FsBackend {
  public:
    virtual ~FsBackend() = default;
    /// Return the transport represented by this backend.
    [[nodiscard]] virtual BackendKind kind() const = 0;
    /// Read root metadata without following a final link; throw IoError on failure.
    virtual RawEntry stat_root(std::string_view path) = 0;
    /// Enumerate direct children, preserving native names and not following links.
    virtual DirListing read_dir(std::string_view dir, const DirHint &hint) = 0;
    /// Return volume properties if the backend can supply them.
    virtual std::optional<VolumeInfo> volume_info(std::string_view path) = 0;
    /// Attempt the optional fast scan protocol; false means unsupported.
    virtual bool fast_scan(std::string_view, const ScanOptions &, FastScanSink &) { return false; }
    /// Resolve an owner using an optional identity hint.
    virtual std::optional<std::pair<OwnerKey, std::string>> resolve_owner(std::string_view path,
                                                                          const OwnerKey *hint) = 0;
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
};

/// Thread-safe in-memory local filesystem with injected failures and call counters.
class MockBackend final : public FsBackend {
  public:
    /// Validate and index an immutable filesystem description.
    explicit MockBackend(MockSpec spec);
    ~MockBackend() override;
    /// Report local semantics without accessing the real filesystem.
    [[nodiscard]] BackendKind kind() const override;
    /// Read synthetic metadata or throw an injected error.
    RawEntry stat_root(std::string_view path) override;
    /// Return synthetic direct children and deterministic per-entry issues.
    DirListing read_dir(std::string_view dir, const DirHint &hint) override;
    /// Return the optional synthetic volume information.
    std::optional<VolumeInfo> volume_info(std::string_view path) override;
    /// Resolve a supplied UID through the synthetic owner table, with numeric fallback.
    std::optional<std::pair<OwnerKey, std::string>> resolve_owner(std::string_view path,
                                                                  const OwnerKey *hint) override;
    /// Count all attempted directory reads, including failed reads.
    [[nodiscard]] std::uint64_t read_dir_calls() const noexcept;
    /// Count all attempted owner resolutions.
    [[nodiscard]] std::uint64_t owner_resolution_calls() const noexcept;

  private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

/// Create a backend over the host filesystem.
std::shared_ptr<FsBackend> make_local_backend();
/// Create an in-memory backend from the supplied test description.
std::shared_ptr<FsBackend> make_mock_backend(MockSpec spec);

} // namespace dafree
