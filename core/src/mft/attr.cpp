#include "dafree/mft.hpp"

#include "byte_reader.hpp"

#include <algorithm>
#include <bit>
#include <cstring>
#include <utility>

namespace dafree {
namespace {

struct AttributeRecord {
    std::uint32_t type;
    std::uint16_t flags;
    bool resident;
    std::span<const std::byte> bytes, name, value, runlist;
    std::uint64_t size = 0, alloc = 0, lowest_vcn = 0;
};

Expected<AttributeRecord, MftError> read_attribute(std::span<const std::byte> remaining,
                                                   std::uint32_t type) {
    const mft_detail::ByteReader outer(remaining);
    const auto length = outer.read_u32(4);
    if (!length.has_value() || length.value() < 16 || length.value() % 8 != 0)
        return MftError::OutOfBounds;
    const auto bytes = outer.bytes(0, length.value());
    if (!bytes.has_value())
        return bytes.error();
    const mft_detail::ByteReader reader(bytes.value());
    const auto form = reader.read_u8(8);
    const auto name_length = reader.read_u8(9);
    const auto name_offset = reader.read_u16(10);
    const auto flags = reader.read_u16(12);
    if (!form.has_value() || !name_length.has_value() || !name_offset.has_value() ||
        !flags.has_value())
        return MftError::OutOfBounds;
    if (form.value() > 1)
        return MftError::Unsupported;
    const bool resident = form.value() == 0;
    const std::size_t minimum_header = resident ? 24 : 64;
    if (!reader.bytes(0, minimum_header).has_value())
        return MftError::OutOfBounds;

    AttributeRecord result{type, flags.value(), resident, bytes.value(), {}, {}, {}};
    std::size_t name_end = minimum_header;
    if (name_length.value() != 0) {
        if (name_offset.value() < minimum_header || name_offset.value() % 2 != 0)
            return MftError::OutOfBounds;
        const auto name =
            reader.bytes(name_offset.value(), static_cast<std::size_t>(name_length.value()) * 2);
        if (!name.has_value())
            return name.error();
        result.name = name.value();
        name_end = static_cast<std::size_t>(name_offset.value()) + result.name.size();
    }
    // NameOffset is undefined for unnamed attributes; never use it in that case.
    if (resident) {
        const auto value_length = reader.read_u32(16);
        const auto value_offset = reader.read_u16(20);
        if (!value_length.has_value() || !value_offset.has_value() ||
            value_offset.value() < name_end)
            return MftError::OutOfBounds;
        const auto value = reader.bytes(value_offset.value(), value_length.value());
        if (!value.has_value())
            return value.error();
        result.value = value.value();
        result.size = value_length.value();
        return result;
    }

    const auto lowest = reader.read_u64(16);
    const auto mapping_offset = reader.read_u16(32);
    const auto allocated = reader.read_u64(40);
    const auto size = reader.read_u64(48);
    if (!lowest.has_value() || !mapping_offset.has_value() || !allocated.has_value() ||
        !size.has_value() || mapping_offset.value() < name_end ||
        mapping_offset.value() >= result.bytes.size())
        return MftError::OutOfBounds;
    const auto runlist =
        reader.bytes(mapping_offset.value(), result.bytes.size() - mapping_offset.value());
    if (!runlist.has_value())
        return runlist.error();
    result.lowest_vcn = lowest.value();
    result.alloc = allocated.value();
    result.size = size.value();
    result.runlist = runlist.value();
    const auto header_end = result.name.empty()
                                ? static_cast<std::size_t>(mapping_offset.value())
                                : std::min(static_cast<std::size_t>(name_offset.value()),
                                           static_cast<std::size_t>(mapping_offset.value()));
    // The optional word must belong to the header, not a stream name or run bytes.
    constexpr std::uint16_t compressed_or_sparse = 0x80ff;
    if ((result.flags & compressed_or_sparse) != 0 && header_end >= 0x48) {
        const auto total_allocated = reader.read_u64(0x40);
        if (!total_allocated.has_value())
            return total_allocated.error();
        result.alloc = total_allocated.value();
    }
    return result;
}

} // namespace

AttrIterator::AttrIterator(std::span<const std::byte> rec) : record_(rec) {
    const auto header = parse_header(rec);
    if (!header.has_value()) {
        error_ = header.error();
        return;
    }
    position_ = header.value().attrs_offset;
    end_ = header.value().bytes_used;
}

Expected<std::u16string_view, MftError> AttrIterator::read_name(std::span<const std::byte> chars) {
    static_assert(sizeof(char16_t) == 2);
    if (chars.size() % 2 != 0 || chars.size() / 2 > name_storage_.size())
        return MftError::OutOfBounds;
    if (chars.empty())
        return std::u16string_view{};
    if constexpr (std::endian::native == std::endian::little) {
        std::memcpy(name_storage_.data(), chars.data(), chars.size());
    } else {
        const mft_detail::ByteReader reader(chars);
        for (std::size_t index = 0; index < chars.size() / 2; ++index) {
            const auto code_unit = reader.read_u16(index * 2);
            if (!code_unit.has_value())
                return code_unit.error();
            name_storage_[index] = static_cast<char16_t>(code_unit.value());
        }
    }
    return std::u16string_view(name_storage_.data(), chars.size() / 2);
}

Expected<std::optional<Attr>, MftError> AttrIterator::next() {
    if (error_.has_value())
        return error_.value();
    if (position_ == end_)
        return std::optional<Attr>{};
    const mft_detail::ByteReader reader(record_);
    const auto remaining = reader.bytes(position_, end_ - position_);
    if (!remaining.has_value()) {
        error_ = remaining.error();
        return error_.value();
    }
    const auto type = mft_detail::ByteReader(remaining.value()).read_u32(0);
    if (!type.has_value()) {
        error_ = type.error();
        return error_.value();
    }
    if (type.value() == 0xffffffffu) {
        position_ = end_;
        return std::optional<Attr>{};
    }
    const auto parsed = read_attribute(remaining.value(), type.value());
    if (!parsed.has_value()) {
        error_ = parsed.error();
        return error_.value();
    }
    const auto &attribute = parsed.value();
    const auto decode = [this, &attribute]() -> Expected<Attr, MftError> {
        if (attribute.type == 0x10) {
            if (!attribute.resident)
                return MftError::Unsupported;
            const mft_detail::ByteReader value(attribute.value);
            if (!value.bytes(0, 48).has_value())
                return MftError::OutOfBounds;
            const auto created = value.read_u64(0);
            const auto modified = value.read_u64(8);
            const auto accessed = value.read_u64(24);
            const auto attributes = value.read_u32(32);
            if (!created.has_value() || !modified.has_value() || !accessed.has_value() ||
                !attributes.has_value())
                return MftError::OutOfBounds;
            return Attr{StdInfo{filetime_to_unix(created.value()),
                                filetime_to_unix(modified.value()),
                                filetime_to_unix(accessed.value()), attributes.value()}};
        }
        if (attribute.type == 0x30) {
            if (!attribute.resident)
                return MftError::Unsupported;
            const mft_detail::ByteReader value(attribute.value);
            if (!value.bytes(0, 66).has_value())
                return MftError::OutOfBounds;
            const auto parent = value.read_u64(0);
            const auto length = value.read_u8(64);
            const auto name_space = value.read_u8(65);
            if (!parent.has_value() || !length.has_value() || !name_space.has_value())
                return MftError::OutOfBounds;
            const auto raw_name = value.bytes(66, static_cast<std::size_t>(length.value()) * 2);
            if (!raw_name.has_value())
                return raw_name.error();
            const auto name = read_name(raw_name.value());
            if (!name.has_value())
                return name.error();
            return Attr{FileNameAttr{parent.value(), name_space.value(), name.value()}};
        }
        if (attribute.type == 0x80) {
            const auto name = read_name(attribute.name);
            if (!name.has_value())
                return name.error();
            return Attr{DataAttr{name.value(), attribute.resident, attribute.size, attribute.alloc,
                                 attribute.lowest_vcn, attribute.runlist, attribute.flags}};
        }
        if (attribute.type == 0x20)
            return Attr{AttrListMarker{}};
        if (attribute.type == 0xc0)
            return Attr{ReparseMarker{}};
        return Attr{OtherAttr{attribute.type}};
    };
    auto result = decode();
    if (!result.has_value()) {
        error_ = result.error();
        return error_.value();
    }
    position_ += attribute.bytes.size();
    return std::optional<Attr>{std::move(result.value())};
}

std::int64_t filetime_to_unix(std::uint64_t filetime) {
    constexpr std::uint64_t ticks_per_second = 10'000'000;
    constexpr std::int64_t epoch_offset = 11'644'473'600;
    return static_cast<std::int64_t>(filetime / ticks_per_second) - epoch_offset;
}

} // namespace dafree
