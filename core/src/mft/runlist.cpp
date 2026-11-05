#include "dafree/mft.hpp"

#include "byte_reader.hpp"

#include <limits>
#include <vector>

namespace dafree {
namespace {

Expected<std::uint64_t, MftError> read_unsigned(const mft_detail::ByteReader &reader,
                                                std::size_t offset, std::size_t width) {
    const auto bytes = reader.bytes(offset, width);
    if (!bytes.has_value())
        return bytes.error();
    std::uint64_t value = 0;
    for (std::size_t index = 0; index < width; ++index)
        value |= std::uint64_t{std::to_integer<std::uint8_t>(bytes.value()[index])} << (index * 8);
    return value;
}

std::int64_t signed_delta(std::uint64_t encoded, std::size_t width) {
    const auto bits = width * 8;
    constexpr auto maximum = std::numeric_limits<std::uint64_t>::max();
    if (bits < 64 && (encoded & (std::uint64_t{1} << (bits - 1))) != 0)
        encoded |= maximum << bits;
    if (encoded <= static_cast<std::uint64_t>(std::numeric_limits<std::int64_t>::max()))
        return static_cast<std::int64_t>(encoded);
    // For a negative two's-complement value, this difference always fits int64_t.
    // Subtracting it from -1 also represents INT64_MIN without negating that value.
    return -1 - static_cast<std::int64_t>(maximum - encoded);
}

Expected<std::size_t, MftError> decode_pass(std::span<const std::byte> bytes,
                                            std::vector<Run> *output) {
    const mft_detail::ByteReader reader(bytes);
    std::size_t position = 0, count = 0;
    std::uint64_t vcn = 0;
    std::int64_t previous_lcn = 0;
    for (;;) {
        const auto header = reader.read_u8(position);
        if (!header.has_value())
            return header.error();
        ++position;
        if (header.value() == 0)
            return count;
        const auto length_width = static_cast<std::size_t>(header.value() & 0x0f);
        const auto offset_width = static_cast<std::size_t>(header.value() >> 4);
        if (length_width == 0 || length_width > 8 || offset_width > 8)
            return MftError::OutOfBounds;
        const auto clusters = read_unsigned(reader, position, length_width);
        if (!clusters.has_value())
            return clusters.error();
        position += length_width;
        if (clusters.value() == 0 ||
            clusters.value() > std::numeric_limits<std::uint64_t>::max() - vcn)
            return MftError::OutOfBounds;
        vcn += clusters.value();

        std::optional<std::int64_t> lcn;
        if (offset_width != 0) {
            const auto encoded = read_unsigned(reader, position, offset_width);
            if (!encoded.has_value())
                return encoded.error();
            position += offset_width;
            const auto delta = signed_delta(encoded.value(), offset_width);
            if ((delta >= 0 && delta > std::numeric_limits<std::int64_t>::max() - previous_lcn) ||
                (delta < 0 && delta < -previous_lcn))
                return MftError::OutOfBounds;
            previous_lcn += delta;
            lcn = previous_lcn;
        }
        if (output != nullptr)
            output->push_back(Run{lcn, clusters.value()});
        ++count;
    }
}

} // namespace

Expected<std::vector<Run>, MftError> decode_runlist(std::span<const std::byte> bytes) {
    const auto count = decode_pass(bytes, nullptr);
    if (!count.has_value())
        return count.error();
    constexpr std::size_t maximum_output_bytes = 64 * 1024 * 1024;
    if (count.value() > maximum_output_bytes / sizeof(Run))
        return MftError::Unsupported;
    std::vector<Run> runs;
    if (count.value() != 0)
        runs.reserve(count.value());
    const auto decoded = decode_pass(bytes, &runs);
    if (!decoded.has_value())
        return decoded.error();
    return runs;
}

} // namespace dafree
