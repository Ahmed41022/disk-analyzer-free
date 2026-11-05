#pragma once

#include "dafree/mft.hpp"

#include <cstddef>
#include <cstdint>
#include <span>

namespace dafree::mft_detail {

/// Bounds-checked byte decoding that accepts spans at any address alignment.
class ByteReader {
  public:
    /// Borrow an immutable record buffer without changing its contents.
    explicit ByteReader(std::span<const std::byte> data) noexcept : data_(data) {}

    /// Return a subrange only when both its starting offset and length fit.
    [[nodiscard]] Expected<std::span<const std::byte>, MftError>
    bytes(std::size_t offset, std::size_t count) const noexcept {
        if (offset > data_.size() || count > data_.size() - offset)
            return MftError::OutOfBounds;
        return data_.subspan(offset, count);
    }

    /// Read one unsigned byte without an unchecked subscript.
    [[nodiscard]] Expected<std::uint8_t, MftError> read_u8(std::size_t offset) const noexcept {
        return read_integer<std::uint8_t>(offset);
    }

    /// Decode an unsigned little-endian word without an aligned pointer cast.
    [[nodiscard]] Expected<std::uint16_t, MftError> read_u16(std::size_t offset) const noexcept {
        return read_integer<std::uint16_t>(offset);
    }

    /// Decode an unsigned little-endian double word.
    [[nodiscard]] Expected<std::uint32_t, MftError> read_u32(std::size_t offset) const noexcept {
        return read_integer<std::uint32_t>(offset);
    }

    /// Decode an unsigned little-endian quad word.
    [[nodiscard]] Expected<std::uint64_t, MftError> read_u64(std::size_t offset) const noexcept {
        return read_integer<std::uint64_t>(offset);
    }

  private:
    template <typename T>
    [[nodiscard]] Expected<T, MftError> read_integer(std::size_t offset) const noexcept {
        const auto source = bytes(offset, sizeof(T));
        if (!source.has_value())
            return source.error();
        std::uint64_t value = 0;
        for (std::size_t index = 0; index < sizeof(T); ++index)
            value |= std::uint64_t{std::to_integer<std::uint8_t>(source.value()[index])}
                     << (index * 8);
        return static_cast<T>(value);
    }

    std::span<const std::byte> data_;
};

} // namespace dafree::mft_detail
