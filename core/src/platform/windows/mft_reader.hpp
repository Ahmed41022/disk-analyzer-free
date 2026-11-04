#pragma once

#include "dafree/mft.hpp"

#include <functional>

namespace dafree {

/// Expected failures opening a local raw NTFS volume.
enum class MftOpenError { NotElevated, NotNtfs, AccessDenied, Io };

/// Read-only view of the MFT stream mapped through its physical extents.
class VolumeReader {
  public:
    /// Open a local NTFS volume and validate its MFT geometry and stream mapping.
    static Expected<VolumeReader, MftOpenError> open(std::wstring_view volume_root);
    VolumeReader(VolumeReader &&) noexcept;
    VolumeReader &operator=(VolumeReader &&) noexcept;
    ~VolumeReader();

    /// Number of complete records in the valid MFT data range.
    std::uint64_t record_count() const;
    /// Bytes per MFT record.
    std::size_t record_size() const;
    /// Bytes per logical volume sector.
    std::size_t sector_size() const;

    /// Read consecutive records in aligned chunks. Returning false stops the reader.
    /// The callback borrows mutable storage only for the duration of the call.
    void read_chunks(std::size_t chunk_bytes,
                     const std::function<bool(std::uint64_t, std::span<std::byte>)> &callback);

  private:
    struct Impl;
    explicit VolumeReader(std::unique_ptr<Impl> impl);
    std::unique_ptr<Impl> impl_;
};

} // namespace dafree
