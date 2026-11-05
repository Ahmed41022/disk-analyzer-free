#include "dafree/mft.hpp"

#include "byte_reader.hpp"

namespace dafree {

Expected<RecordHeader, MftError> parse_header(std::span<const std::byte> rec) {
    constexpr std::size_t fixed_header_size = 0x2a;
    const mft_detail::ByteReader reader(rec);
    const auto signature = reader.bytes(0, 4);
    if (!signature.has_value())
        return signature.error();

    RecordHeader header{};
    for (std::size_t index = 0; index < header.signature.size(); ++index)
        header.signature[index] =
            static_cast<char>(std::to_integer<unsigned char>(signature.value()[index]));
    if (header.signature != std::array<char, 4>{'F', 'I', 'L', 'E'})
        return MftError::BadSignature;

    // Reading the complete fixed prefix also covers its unexposed final word.
    if (!reader.bytes(0, fixed_header_size).has_value())
        return MftError::OutOfBounds;
    const auto usa_offset = reader.read_u16(0x04);
    const auto usa_count = reader.read_u16(0x06);
    const auto lsn = reader.read_u64(0x08);
    const auto sequence = reader.read_u16(0x10);
    const auto link_count = reader.read_u16(0x12);
    const auto attrs_offset = reader.read_u16(0x14);
    const auto flags = reader.read_u16(0x16);
    const auto bytes_used = reader.read_u32(0x18);
    const auto bytes_allocated = reader.read_u32(0x1c);
    const auto base_record = reader.read_u64(0x20);
    if (!usa_offset.has_value() || !usa_count.has_value() || !lsn.has_value() ||
        !sequence.has_value() || !link_count.has_value() || !attrs_offset.has_value() ||
        !flags.has_value() || !bytes_used.has_value() || !bytes_allocated.has_value() ||
        !base_record.has_value())
        return MftError::OutOfBounds;

    header.usa_offset = usa_offset.value();
    header.usa_count = usa_count.value();
    header.lsn = lsn.value();
    header.sequence = sequence.value();
    header.link_count = link_count.value();
    header.attrs_offset = attrs_offset.value();
    header.flags = flags.value();
    header.bytes_used = bytes_used.value();
    header.bytes_allocated = bytes_allocated.value();
    header.base_record = base_record.value();

    if (header.bytes_used < fixed_header_size || header.bytes_used > header.bytes_allocated ||
        header.bytes_allocated > rec.size() || header.usa_offset < fixed_header_size ||
        header.usa_offset % 2 != 0 || header.usa_count == 0 ||
        header.usa_offset > header.bytes_used ||
        static_cast<std::size_t>(header.usa_count) >
            (header.bytes_used - header.usa_offset) / sizeof(std::uint16_t))
        return MftError::OutOfBounds;
    const auto usa_end = static_cast<std::size_t>(header.usa_offset) +
                         static_cast<std::size_t>(header.usa_count) * sizeof(std::uint16_t);
    if (header.attrs_offset < usa_end || header.attrs_offset > header.bytes_used ||
        header.attrs_offset % 8 != 0)
        return MftError::OutOfBounds;
    return header;
}

} // namespace dafree
