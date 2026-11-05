#include "dafree/mft.hpp"

#include "byte_reader.hpp"

namespace dafree {

/// Validate the complete update-sequence array and all trailers before restoring bytes.
Expected<void, MftError> apply_fixups(std::span<std::byte> rec, std::size_t sector_size) {
    if (sector_size < sizeof(std::uint16_t) || (sector_size & (sector_size - 1)) != 0)
        return MftError::Unsupported;
    if (rec.empty() || rec.size() % sector_size != 0)
        return MftError::OutOfBounds;

    const auto parsed = parse_header(rec);
    if (!parsed.has_value())
        return parsed.error();
    const auto &header = parsed.value();
    if (header.bytes_allocated != rec.size())
        return MftError::OutOfBounds;
    const auto sectors = rec.size() / sector_size;
    if (static_cast<std::size_t>(header.usa_count) != sectors + 1)
        return MftError::BadFixup;

    const auto usa_offset = static_cast<std::size_t>(header.usa_offset);
    const auto usa_bytes = static_cast<std::size_t>(header.usa_count) * sizeof(std::uint16_t);
    const auto first_trailer = sector_size - sizeof(std::uint16_t);
    // Restoring a trailer must never overwrite the USA that supplies later words.
    if (usa_offset > first_trailer || usa_bytes > first_trailer - usa_offset)
        return MftError::OutOfBounds;

    const mft_detail::ByteReader reader(rec);
    const auto array = reader.bytes(usa_offset, usa_bytes);
    if (!array.has_value())
        return array.error();
    const auto sequence = reader.read_u16(usa_offset);
    if (!sequence.has_value())
        return sequence.error();
    for (std::size_t sector = 0; sector < sectors; ++sector) {
        const auto trailer = (sector + 1) * sector_size - sizeof(std::uint16_t);
        const auto actual = reader.read_u16(trailer);
        if (!actual.has_value())
            return actual.error();
        if (actual.value() != sequence.value())
            return MftError::BadFixup;
    }

    // All ranges are validated and the USA is disjoint from every write, so these
    // bounded rereads cannot fail or change as earlier trailers are restored.
    for (std::size_t sector = 0; sector < sectors; ++sector) {
        const auto saved = reader.read_u16(usa_offset + (sector + 1) * sizeof(std::uint16_t));
        const auto trailer = (sector + 1) * sector_size - sizeof(std::uint16_t);
        rec[trailer] = static_cast<std::byte>(saved.value() & 0xffu);
        rec[trailer + 1] = static_cast<std::byte>(saved.value() >> 8);
    }
    return {};
}

} // namespace dafree
