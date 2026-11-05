// Capture one verified, test-owned NTFS record for the cross-platform golden tests.
#include "../src/platform/windows/internal.hpp"
#include "../src/platform/windows/mft_reader.hpp"

#include "dafree/mft.hpp"

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <iostream>
#include <iterator>
#include <span>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace {

constexpr wchar_t fixture_name[] = L"dafree-captured-mft-fixture.bin";
constexpr std::array<unsigned char, 32> fixture_data = {
    0x44, 0x41, 0x46, 0x52, 0x45, 0x45, 0x2d, 0x4d, 0x46, 0x54, 0x2d, 0x47, 0x4f, 0x4c, 0x44, 0x45,
    0x4e, 0x2d, 0x46, 0x49, 0x58, 0x54, 0x55, 0x52, 0x45, 0x2d, 0x56, 0x31, 0x00, 0x7f, 0x81, 0xff};

struct Handle {
    HANDLE value = INVALID_HANDLE_VALUE;
    ~Handle() {
        if (value != INVALID_HANDLE_VALUE)
            CloseHandle(value);
    }
    Handle(const Handle &) = delete;
    Handle &operator=(const Handle &) = delete;
    Handle() = default;
    explicit Handle(HANDLE handle) : value(handle) {}
};

std::uint16_t u16(std::span<const std::byte> b, std::size_t p) {
    return static_cast<std::uint16_t>(std::to_integer<unsigned char>(b[p]) |
                                      (std::to_integer<unsigned char>(b[p + 1]) << 8));
}
std::uint32_t u32(std::span<const std::byte> b, std::size_t p) {
    return static_cast<std::uint32_t>(u16(b, p)) |
           (static_cast<std::uint32_t>(u16(b, p + 2)) << 16);
}
std::uint64_t u64(std::span<const std::byte> b, std::size_t p) {
    return static_cast<std::uint64_t>(u32(b, p)) |
           (static_cast<std::uint64_t>(u32(b, p + 4)) << 32);
}

bool matches_fixture(std::span<const std::byte> raw, std::uint64_t expected_parent,
                     std::uint16_t expected_sequence, std::vector<std::uint16_t> &saved) {
    auto fixed = std::vector<std::byte>(raw.begin(), raw.end());
    const auto header = dafree::parse_header(fixed);
    if (!header.has_value() || header.value().sequence != expected_sequence ||
        (header.value().flags & 1) == 0 || (header.value().flags & 2) != 0 ||
        header.value().base_record != 0 || !dafree::apply_fixups(fixed, 512).has_value())
        return false;
    const auto parsed = dafree::parse_header(fixed);
    if (!parsed.has_value() || parsed.value().bytes_allocated != raw.size())
        return false;

    bool name_ok = false, data_ok = false;
    auto at = static_cast<std::size_t>(parsed.value().attrs_offset);
    while (at + 8 <= parsed.value().bytes_used) {
        const auto type = u32(fixed, at);
        if (type == 0xffffffffu)
            break;
        const auto length = u32(fixed, at + 4);
        if (length < 16 || length % 8 != 0 || length > parsed.value().bytes_used - at)
            return false;
        const auto form = std::to_integer<unsigned char>(fixed[at + 8]);
        const auto name_length = std::to_integer<unsigned char>(fixed[at + 9]);
        if (type == 0x30 && form == 0 && length >= 24) {
            const auto value_length = u32(fixed, at + 16);
            const auto value_offset = u16(fixed, at + 20);
            if (value_offset < 24 || value_offset > length ||
                value_length > length - value_offset || value_length < 66)
                return false;
            const auto value = at + value_offset;
            const auto parent = u64(fixed, value);
            const auto chars = std::to_integer<unsigned char>(fixed[value + 64]);
            const auto name_space = std::to_integer<unsigned char>(fixed[value + 65]);
            if (parent == expected_parent && chars == std::size(fixture_name) - 1 &&
                name_space <= 3 && value_length >= 66u + static_cast<std::uint32_t>(chars) * 2u) {
                bool equal = true;
                for (std::size_t i = 0; i < chars; ++i)
                    equal &= u16(fixed, value + 66 + i * 2) == fixture_name[i];
                name_ok |= equal;
            }
        }
        if (type == 0x80 && name_length == 0 && form == 0 && length >= 24) {
            const auto value_length = u32(fixed, at + 16);
            const auto value_offset = u16(fixed, at + 20);
            if (value_length == fixture_data.size() && value_offset >= 24 &&
                value_offset <= length && value_length <= length - value_offset) {
                bool equal = true;
                for (std::size_t i = 0; i < fixture_data.size(); ++i)
                    equal &= std::to_integer<unsigned char>(fixed[at + value_offset + i]) ==
                             fixture_data[i];
                data_ok |= equal;
            }
        }
        at += length;
    }
    if (!name_ok || !data_ok)
        return false;

    const auto usa_offset = parsed.value().usa_offset;
    const auto usa_count = parsed.value().usa_count;
    saved.clear();
    for (std::size_t i = 1; i < usa_count; ++i)
        saved.push_back(u16(raw, usa_offset + i * 2));
    return true;
}

void write_new(const std::filesystem::path &path, std::span<const std::byte> bytes) {
    Handle output(CreateFileW(path.c_str(), GENERIC_WRITE, 0, nullptr, CREATE_NEW,
                              FILE_ATTRIBUTE_NORMAL | FILE_FLAG_OPEN_REPARSE_POINT, nullptr));
    if (output.value == INVALID_HANDLE_VALUE)
        throw std::runtime_error("output exists or cannot be created");
    std::size_t offset = 0;
    while (offset < bytes.size()) {
        const auto remaining = std::min<std::size_t>(bytes.size() - offset, MAXDWORD);
        DWORD written = 0;
        if (!WriteFile(output.value, bytes.data() + offset, static_cast<DWORD>(remaining), &written,
                       nullptr) ||
            written != remaining)
            throw std::runtime_error("failed writing output");
        offset += written;
    }
    if (!FlushFileBuffers(output.value))
        throw std::runtime_error("failed flushing output");
}

void write_json(const std::filesystem::path &path, std::span<const std::byte> raw,
                const std::vector<std::uint16_t> &saved, std::size_t sector) {
    const auto header = dafree::parse_header(raw);
    if (!header.has_value())
        throw std::runtime_error("captured header failed parsing");
    const auto &h = header.value();
    std::ostringstream out;
    out << "{\n  \"provenance\": \"Captured from this helper's test-created file. Unused tail "
           "bytes and their saved USA words were zeroed, retaining USA-protected sector stamps. "
           "Used bytes and their saved sector words were preserved.\",\n"
        << "  \"record_size\": " << raw.size() << ",\n  \"sector_size\": " << sector
        << ",\n  \"usa_number\": " << u16(raw, h.usa_offset) << ",\n  \"saved_sector_words\": [";
    for (std::size_t i = 0; i < saved.size(); ++i)
        out << (i ? ", " : "") << saved[i];
    out << "],\n  \"header\": {\n    \"signature\": \"FILE\",\n    \"usa_offset\": " << h.usa_offset
        << ",\n    \"usa_count\": " << h.usa_count << ",\n    \"lsn\": " << h.lsn
        << ",\n    \"sequence\": " << h.sequence << ",\n    \"link_count\": " << h.link_count
        << ",\n    \"attrs_offset\": " << h.attrs_offset << ",\n    \"flags\": " << h.flags
        << ",\n    \"bytes_used\": " << h.bytes_used
        << ",\n    \"bytes_allocated\": " << h.bytes_allocated
        << ",\n    \"base_record\": " << h.base_record << "\n  }\n}\n";
    const auto text = out.str();
    write_new(path, {reinterpret_cast<const std::byte *>(text.data()), text.size()});
}

} // namespace

/// Capture a verified fixture record into an explicitly supplied test-owned directory.
int wmain(int argc, wchar_t **argv) {
    try {
        if (argc != 2)
            throw std::runtime_error("usage: dafree_capture_mft <existing-temp-root>");
        const auto root = std::filesystem::absolute(argv[1]).lexically_normal();
        auto prefix = root.root_path();
        for (const auto &part : root.relative_path()) {
            prefix /= part;
            Handle component(CreateFileW(
                prefix.c_str(), FILE_READ_ATTRIBUTES,
                FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr, OPEN_EXISTING,
                FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, nullptr));
            BY_HANDLE_FILE_INFORMATION component_info{};
            if (component.value == INVALID_HANDLE_VALUE ||
                !GetFileInformationByHandle(component.value, &component_info) ||
                (component_info.dwFileAttributes &
                 (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT)) !=
                    FILE_ATTRIBUTE_DIRECTORY)
                throw std::runtime_error(
                    "capture root path contains a non-directory or reparse point");
        }
        Handle directory(CreateFileW(
            root.c_str(), FILE_READ_ATTRIBUTES,
            FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr, OPEN_EXISTING,
            FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT, nullptr));
        if (directory.value == INVALID_HANDLE_VALUE)
            throw std::runtime_error("cannot open capture root");
        BY_HANDLE_FILE_INFORMATION root_info{};
        if (!GetFileInformationByHandle(directory.value, &root_info) ||
            (root_info.dwFileAttributes &
             (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT)) != FILE_ATTRIBUTE_DIRECTORY)
            throw std::runtime_error("capture root must be a real directory, not a reparse point");

        const auto file_path = root / fixture_name;
        Handle file(CreateFileW(file_path.c_str(), GENERIC_READ | GENERIC_WRITE, 0, nullptr,
                                CREATE_NEW, FILE_ATTRIBUTE_TEMPORARY | FILE_FLAG_OPEN_REPARSE_POINT,
                                nullptr));
        if (file.value == INVALID_HANDLE_VALUE)
            throw std::runtime_error("fixture already exists or cannot be created");
        DWORD written = 0;
        if (!WriteFile(file.value, fixture_data.data(), static_cast<DWORD>(fixture_data.size()),
                       &written, nullptr) ||
            written != fixture_data.size() || !FlushFileBuffers(file.value))
            throw std::runtime_error("could not write and flush fixture");
        BY_HANDLE_FILE_INFORMATION file_info{};
        if (!GetFileInformationByHandle(file.value, &file_info))
            throw std::runtime_error("cannot get fixture file ID");
        const auto file_reference =
            (static_cast<std::uint64_t>(file_info.nFileIndexHigh) << 32) | file_info.nFileIndexLow;
        const auto record_no = file_reference & ((std::uint64_t{1} << 48) - 1);
        const auto parent_ref =
            (static_cast<std::uint64_t>(root_info.nFileIndexHigh) << 32) | root_info.nFileIndexLow;
        const auto volume = root.root_path().wstring();
        auto reader = dafree::VolumeReader::open(volume);
        if (!reader.has_value())
            throw std::runtime_error("cannot open elevated NTFS volume reader");
        if (reader.value().sector_size() != 512 || record_no >= reader.value().record_count())
            throw std::runtime_error("unsupported sector size or fixture record number");

        std::vector<std::byte> captured;
        std::vector<std::uint16_t> saved;
        const auto size = reader.value().record_size();
        reader.value().read_chunks(
            8 * 1024 * 1024, [&](std::uint64_t first, std::span<std::byte> chunk) {
                if (record_no < first || record_no - first >= chunk.size() / size)
                    return true;
                const auto offset = static_cast<std::size_t>(record_no - first) * size;
                const auto raw = std::span<const std::byte>(chunk).subspan(offset, size);
                if (!matches_fixture(raw, parent_ref,
                                     static_cast<std::uint16_t>(file_reference >> 48), saved))
                    throw std::runtime_error(
                        "record ID matched, but record contents did not match fixture");
                captured.assign(raw.begin(), raw.end());
                return false;
            });
        if (captured.empty())
            throw std::runtime_error("fixture record was not found");

        // Scrub unused allocated tail bytes; retain only used bytes and USA-protected sector
        // stamps.
        const auto header = dafree::parse_header(captured);
        if (!header.has_value())
            throw std::runtime_error("captured header failed parsing");
        const auto used = header.value().bytes_used;
        std::fill(captured.begin() + used, captured.end(), std::byte{0});
        const auto usa_offset = header.value().usa_offset;
        for (std::size_t index = 1; index < header.value().usa_count; ++index) {
            const auto tail = index * 512 - 2;
            if (tail >= used) {
                // Scrub saved tail bytes too: fixup will restore zeros, never stale slack.
                captured[usa_offset + index * 2] = std::byte{0};
                captured[usa_offset + index * 2 + 1] = std::byte{0};
                captured[tail] = static_cast<std::byte>(u16(captured, usa_offset) & 0xff);
                captured[tail + 1] = static_cast<std::byte>(u16(captured, usa_offset) >> 8);
            }
        }
        saved.clear();
        for (std::size_t index = 1; index < header.value().usa_count; ++index)
            saved.push_back(u16(captured, usa_offset + index * 2));

        const auto bin_path = root / L"captured_file.bin";
        const auto json_path = root / L"captured_file.json";
        write_new(bin_path, captured);
        write_json(json_path, captured, saved, reader.value().sector_size());
        std::wcout << bin_path.wstring() << L"\n" << json_path.wstring() << L"\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << "capture failed: " << error.what() << '\n';
        return 1;
    }
}
