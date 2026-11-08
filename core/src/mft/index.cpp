#include "dafree/mft.hpp"

#include "byte_reader.hpp"
#include "index.hpp"

#include <utility>

namespace dafree::mft_detail {

// NOLINTBEGIN(cppcoreguidelines-avoid-magic-numbers) -- UTF-8/WTF-8 bit and surrogate encoding.
void append_utf8(std::string &output, char32_t value) {
    if (value <= 0x7f) {
        output.push_back(static_cast<char>(value));
    } else if (value <= 0x7ff) {
        output.push_back(static_cast<char>(0xc0 | (value >> 6)));
        output.push_back(static_cast<char>(0x80 | (value & 0x3f)));
    } else if (value <= 0xffff) {
        output.push_back(static_cast<char>(0xe0 | (value >> 12)));
        output.push_back(static_cast<char>(0x80 | ((value >> 6) & 0x3f)));
        output.push_back(static_cast<char>(0x80 | (value & 0x3f)));
    } else {
        output.push_back(static_cast<char>(0xf0 | (value >> 18)));
        output.push_back(static_cast<char>(0x80 | ((value >> 12) & 0x3f)));
        output.push_back(static_cast<char>(0x80 | ((value >> 6) & 0x3f)));
        output.push_back(static_cast<char>(0x80 | (value & 0x3f)));
    }
}

} // namespace dafree::mft_detail

namespace dafree {
namespace {

void insert_record(mft_detail::IndexData &data, std::uint64_t number,
                   mft_detail::IndexedRecord &&record) {
    const auto [found, inserted] = data.records.try_emplace(number, std::move(record));
    if (!inserted) {
        found->second = {};
        found->second.duplicate = true;
    }
}

} // namespace

auto utf16_to_wtf8(std::u16string_view input) -> std::string {
    std::string output;
    output.reserve(input.size());
    for (std::size_t index = 0; index < input.size(); ++index) {
        char32_t value = input[index];
        if (value >= 0xd800 && value <= 0xdbff && index + 1 < input.size()) {
            const char32_t next = input[index + 1];
            if (next >= 0xdc00 && next <= 0xdfff) {
                value = 0x10000 + ((value - 0xd800) << 10) + next - 0xdc00;
                ++index;
            }
        }
        mft_detail::append_utf8(output, value);
    }
    return output;
}
// NOLINTEND(cppcoreguidelines-avoid-magic-numbers)

MftIndex::MftIndex() : data_(std::make_unique<mft_detail::IndexData>()) {}
MftIndex::~MftIndex() = default;
MftIndex::MftIndex(MftIndex &&) noexcept = default;
auto MftIndex::operator=(MftIndex &&) noexcept -> MftIndex & = default;

void MftIndex::ingest(std::uint64_t record_no, std::span<std::byte> rec, std::size_t sector) {
    const auto signature = mft_detail::ByteReader(rec).bytes(0, 4);
    if (!signature.has_value())
        return;
    const auto magic = signature.value();
    const bool file = magic[0] == std::byte{'F'} && magic[1] == std::byte{'I'} &&
                      magic[2] == std::byte{'L'} && magic[3] == std::byte{'E'};
    const bool bad = magic[0] == std::byte{'B'} && magic[1] == std::byte{'A'} &&
                     magic[2] == std::byte{'A'} && magic[3] == std::byte{'D'};
    if (!file && !bad)
        return;
    if (!data_)
        data_ = std::make_unique<mft_detail::IndexData>();
    mft_detail::IndexedRecord record;
    if (bad) {
        record.error = MftError::BadSignature;
        insert_record(*data_, record_no, std::move(record));
        return;
    }
    const auto fixed = apply_fixups(rec, sector);
    if (!fixed.has_value()) {
        record.error = fixed.error();
        insert_record(*data_, record_no, std::move(record));
        return;
    }
    const auto header = parse_header(rec);
    if (!header.has_value()) {
        record.error = header.error();
        insert_record(*data_, record_no, std::move(record));
        return;
    }
    record.header = header.value();
    if ((record.header.flags & 1) == 0)
        return;
    {
        AttrIterator iterator(rec);
        for (;;) {
            const auto attribute = iterator.next();
            if (!attribute.has_value()) {
                record.error = attribute.error();
                record.names.clear();
                record.streams.clear();
                record.standard.reset();
                break;
            }
            if (!attribute.value())
                break;
            const auto &value = attribute.value().value();
            if (const auto *standard = std::get_if<StdInfo>(&value))
                record.standard = *standard;
            else if (const auto *name = std::get_if<FileNameAttr>(&value))
                record.names.push_back(
                    {name->parent_ref, name->name_space, utf16_to_wtf8(name->name)});
            else if (const auto *data = std::get_if<DataAttr>(&value)) {
                if (data->lowest_vcn == 0)
                    record.streams.push_back({utf16_to_wtf8(data->name), data->size, data->alloc});
            } else if (std::holds_alternative<ReparseMarker>(value))
                record.reparse = true;
        }
    }
    insert_record(*data_, record_no, std::move(record));
}

// Records are moved individually, preserving a usable empty source index.
// NOLINTNEXTLINE(cppcoreguidelines-rvalue-reference-param-not-moved)
void MftIndex::merge(MftIndex &&other) {
    if (this == &other || !other.data_)
        return;
    if (!data_)
        data_ = std::make_unique<mft_detail::IndexData>();
    for (auto &[number, record] : other.data_->records)
        insert_record(*data_, number, std::move(record));
    other.data_->records.clear();
}

} // namespace dafree
