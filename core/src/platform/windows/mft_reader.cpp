#include "mft_reader.hpp"
#include "internal.hpp"

#include "../../mft/byte_reader.hpp"

#include <algorithm>
#include <bit>
#include <limits>
#include <malloc.h>
#include <winioctl.h>

namespace dafree {
namespace {

constexpr auto max_offset = static_cast<std::uint64_t>(std::numeric_limits<LONGLONG>::max());
constexpr std::uint64_t ref_mask = (std::uint64_t{1} << 48) - 1;
constexpr std::size_t max_list_bytes = 8 * 1024 * 1024;

struct Extent {
    std::uint64_t start, end, physical;
};

struct AlignedFree {
    void operator()(std::byte *memory) const noexcept { _aligned_free(memory); }
};

using Buffer = std::unique_ptr<std::byte, AlignedFree>;

Buffer allocate(std::size_t bytes, std::size_t sector) {
    Buffer memory(
        static_cast<std::byte *>(_aligned_malloc(bytes, std::max(sector, std::size_t{4096}))));
    if (!memory)
        throw std::bad_alloc();
    return memory;
}

bool read_at(HANDLE handle, std::uint64_t offset, std::span<std::byte> output) {
    LARGE_INTEGER where{};
    where.QuadPart = static_cast<LONGLONG>(offset);
    DWORD received = 0;
    const auto requested = static_cast<DWORD>(output.size());
    return output.size() <= std::numeric_limits<DWORD>::max() &&
           ::SetFilePointerEx(handle, where, nullptr, FILE_BEGIN) &&
           ::ReadFile(handle, output.data(), requested, &received, nullptr) &&
           received == requested;
}

bool append_runs(std::vector<Extent> &mapping, std::span<const std::byte> encoded,
                 std::uint64_t vcn, std::uint64_t cluster, std::uint64_t volume_bytes) {
    const auto decoded = decode_runlist(encoded);
    if (!decoded.has_value() || vcn > max_offset / cluster)
        return false;
    auto end = mapping.empty() ? 0 : mapping.back().end;
    if (vcn * cluster != end)
        return false;
    for (const auto &run : decoded.value()) {
        if (!run.lcn || *run.lcn < 0 || run.clusters > (max_offset - end) / cluster ||
            static_cast<std::uint64_t>(*run.lcn) > volume_bytes / cluster)
            return false;
        const auto offset = static_cast<std::uint64_t>(*run.lcn) * cluster;
        const auto length = run.clusters * cluster;
        if (length > volume_bytes - offset)
            return false;
        mapping.push_back({end, end + length, offset});
        end += length;
    }
    return !decoded.value().empty();
}

bool read_stream(HANDLE handle, std::span<const Extent> mapping, std::uint64_t offset,
                 std::span<std::byte> output) {
    auto extent = std::upper_bound(mapping.begin(), mapping.end(), offset,
                                   [](auto at, const Extent &entry) { return at < entry.end; });
    while (!output.empty() && extent != mapping.end() && offset >= extent->start) {
        const auto take =
            static_cast<std::size_t>(std::min<std::uint64_t>(extent->end - offset, output.size()));
        if (!read_at(handle, extent->physical + offset - extent->start, output.first(take)))
            return false;
        output = output.subspan(take);
        offset += take;
        ++extent;
    }
    return output.empty();
}

bool add_record_runs(std::span<const std::byte> record, std::uint64_t vcn,
                     std::vector<Extent> &mapping, std::uint64_t cluster,
                     std::uint64_t volume_bytes) {
    AttrIterator attributes(record);
    for (;;) {
        auto item = attributes.next();
        if (!item.has_value() || !item.value())
            return false;
        const auto *data = std::get_if<DataAttr>(&*item.value());
        if (data && !data->resident && data->name.empty() && data->lowest_vcn == vcn)
            return append_runs(mapping, data->runlist, vcn, cluster, volume_bytes);
    }
}

std::optional<std::vector<std::byte>>
read_attribute_list(HANDLE handle, std::span<const std::byte> record, const RecordHeader &header,
                    std::uint64_t cluster, std::uint64_t volume_bytes, std::size_t sector) {
    using mft_detail::ByteReader;
    auto rest = record.first(header.bytes_used).subspan(header.attrs_offset);
    while (rest.size() >= 8) {
        const ByteReader bytes(rest);
        const auto type = bytes.read_u32(0).value();
        const auto length = bytes.read_u32(4).value();
        if (type == 0xffffffff || length < 24 || length > rest.size())
            return std::nullopt;
        if (type != 0x20) {
            rest = rest.subspan(length);
            continue;
        }
        const ByteReader attr(rest.first(length));
        if (attr.read_u8(8).value() == 0) {
            const auto value = attr.bytes(attr.read_u16(20).value(), attr.read_u32(16).value());
            if (!value.has_value())
                return std::nullopt;
            return std::vector<std::byte>(value.value().begin(), value.value().end());
        }
        if (length < 64 || attr.read_u64(16).value() != 0)
            return std::nullopt;
        const auto size = attr.read_u64(48).value();
        const auto runs = attr.read_u16(32).value();
        if (size == 0 || size > max_list_bytes || runs < 64 || runs >= length)
            return std::nullopt;
        std::vector<Extent> extents;
        if (!append_runs(extents, rest.subspan(runs, length - runs), 0, cluster, volume_bytes))
            return std::nullopt;
        const auto aligned = static_cast<std::size_t>((size + sector - 1) / sector * sector);
        auto memory = allocate(aligned, sector);
        if (!read_stream(handle, extents, 0, {memory.get(), aligned}))
            return std::nullopt;
        return std::vector<std::byte>(memory.get(), memory.get() + size);
    }
    return std::nullopt;
}

bool complete_mapping(HANDLE handle, std::span<std::byte> record, const RecordHeader &base,
                      std::vector<Extent> &mapping, std::uint64_t bytes, std::uint64_t cluster,
                      std::uint64_t volume_bytes, std::size_t sector) {
    if (mapping.back().end >= bytes)
        return true;
    auto list = read_attribute_list(handle, record, base, cluster, volume_bytes, sector);
    if (!list)
        return false;
    std::vector<std::pair<std::uint64_t, std::uint64_t>> segments;
    std::span<const std::byte> remaining(*list);
    while (!remaining.empty()) {
        using mft_detail::ByteReader;
        if (remaining.size() < 26)
            return false;
        const ByteReader entry(remaining);
        const auto length = entry.read_u16(4).value();
        if (length < 26 || length > remaining.size())
            return false;
        if (entry.read_u32(0).value() == 0x80 && entry.read_u8(6).value() == 0)
            segments.emplace_back(entry.read_u64(8).value(), entry.read_u64(16).value());
        remaining = remaining.subspan(length);
    }
    std::ranges::sort(segments);
    for (const auto &[vcn, reference] : segments) {
        if (vcn == 0)
            continue;
        const auto id = reference & ref_mask;
        if (id == 0 || id >= bytes / record.size() ||
            !read_stream(handle, mapping, id * record.size(), record) ||
            !apply_fixups(record, sector).has_value())
            return false;
        const auto header = parse_header(record);
        if (!header.has_value() || (header.value().flags & 1) == 0 ||
            header.value().sequence != reference >> 48 ||
            header.value().base_record != (std::uint64_t{base.sequence} << 48) ||
            !add_record_runs(record, vcn, mapping, cluster, volume_bytes))
            return false;
        if (mapping.back().end >= bytes)
            return true;
    }
    return false;
}

} // namespace

struct VolumeReader::Impl {
    explicit Impl(const std::wstring &device)
        : handle(::CreateFileW(device.c_str(), GENERIC_READ,
                               FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE, nullptr,
                               OPEN_EXISTING, 0, nullptr)) {}

    platform::detail::UniqueHandle handle;
    std::vector<Extent> mapping;
    std::uint64_t bytes = 0;
    std::size_t record = 0, sector = 0;
};

VolumeReader::VolumeReader(std::unique_ptr<Impl> impl) : impl_(std::move(impl)) {}
VolumeReader::VolumeReader(VolumeReader &&) noexcept = default;
VolumeReader &VolumeReader::operator=(VolumeReader &&) noexcept = default;
VolumeReader::~VolumeReader() = default;

Expected<VolumeReader, MftOpenError> VolumeReader::open(std::wstring_view volume_root) {
    // A restricted token can retain its elevation type after disabling Administrators.
    alignas(DWORD) std::array<std::byte, SECURITY_MAX_SID_SIZE> administrators{};
    auto sid_size = static_cast<DWORD>(administrators.size());
    BOOL member = FALSE;
    if (!::CreateWellKnownSid(WinBuiltinAdministratorsSid, nullptr, administrators.data(),
                              &sid_size) ||
        !::CheckTokenMembership(nullptr, administrators.data(), &member))
        return MftOpenError::Io;
    if (!member || !platform::is_elevated())
        return MftOpenError::NotElevated;
    std::wstring mount(volume_root);
    if (!mount.ends_with(L'\\'))
        mount.push_back(L'\\');
    std::array<wchar_t, 64> volume{};
    if (!::GetVolumeNameForVolumeMountPointW(mount.c_str(), volume.data(),
                                             static_cast<DWORD>(volume.size())))
        return MftOpenError::NotNtfs;
    std::wstring device(volume.data());
    if (!device.ends_with(L'\\'))
        return MftOpenError::Io;
    device.pop_back();
    auto impl = std::make_unique<Impl>(device);
    const auto handle = impl->handle.get();
    if (handle == INVALID_HANDLE_VALUE)
        return ::GetLastError() == ERROR_ACCESS_DENIED ? MftOpenError::AccessDenied
                                                       : MftOpenError::Io;

    NTFS_VOLUME_DATA_BUFFER info{};
    DWORD returned = 0;
    if (!::DeviceIoControl(handle, FSCTL_GET_NTFS_VOLUME_DATA, nullptr, 0, &info,
                           static_cast<DWORD>(sizeof(info)), &returned, nullptr)) {
        const auto error = ::GetLastError();
        return error == ERROR_INVALID_FUNCTION || error == ERROR_NOT_SUPPORTED
                   ? MftOpenError::NotNtfs
                   : MftOpenError::Io;
    }
    if (returned < sizeof(info) || !std::has_single_bit(info.BytesPerSector) ||
        !std::has_single_bit(info.BytesPerCluster) || info.BytesPerCluster < info.BytesPerSector ||
        !std::has_single_bit(info.BytesPerFileRecordSegment) ||
        info.BytesPerFileRecordSegment < info.BytesPerSector ||
        info.BytesPerFileRecordSegment > max_list_bytes || info.NumberSectors.QuadPart <= 0 ||
        info.MftValidDataLength.QuadPart < static_cast<LONGLONG>(info.BytesPerFileRecordSegment) ||
        info.MftStartLcn.QuadPart < 0)
        return MftOpenError::Io;

    const auto sectors = static_cast<std::uint64_t>(info.NumberSectors.QuadPart);
    const auto first_lcn = static_cast<std::uint64_t>(info.MftStartLcn.QuadPart);
    const auto cluster = std::uint64_t{info.BytesPerCluster};
    if (sectors > max_offset / info.BytesPerSector)
        return MftOpenError::Io;
    const auto volume_bytes = sectors * info.BytesPerSector;
    if (first_lcn > volume_bytes / cluster)
        return MftOpenError::Io;
    impl->record = info.BytesPerFileRecordSegment;
    impl->sector = info.BytesPerSector;
    impl->bytes = static_cast<std::uint64_t>(info.MftValidDataLength.QuadPart);
    if (impl->bytes % impl->record != 0 || impl->bytes > volume_bytes ||
        impl->record > volume_bytes - first_lcn * cluster)
        return MftOpenError::Io;

    auto memory = allocate(impl->record, impl->sector);
    const std::span<std::byte> record(memory.get(), impl->record);
    if (!read_at(handle, first_lcn * cluster, record) ||
        !apply_fixups(record, impl->sector).has_value())
        return MftOpenError::Io;
    const auto header = parse_header(record);
    if (!header.has_value() || (header.value().flags & 1) == 0 || header.value().base_record != 0 ||
        !add_record_runs(record, 0, impl->mapping, cluster, volume_bytes) ||
        impl->mapping.front().physical != first_lcn * cluster ||
        !complete_mapping(handle, record, header.value(), impl->mapping, impl->bytes, cluster,
                          volume_bytes, impl->sector))
        return MftOpenError::Io;
    return VolumeReader(std::move(impl));
}

std::uint64_t VolumeReader::record_count() const { return impl_->bytes / impl_->record; }
std::size_t VolumeReader::record_size() const { return impl_->record; }
std::size_t VolumeReader::sector_size() const { return impl_->sector; }

void VolumeReader::read_chunks(
    std::size_t chunk_bytes,
    const std::function<bool(std::uint64_t, std::span<std::byte>)> &callback) {
    if (chunk_bytes < impl_->record || chunk_bytes > std::numeric_limits<DWORD>::max())
        throw std::invalid_argument("invalid MFT chunk size");
    chunk_bytes -= chunk_bytes % impl_->record;
    auto memory = allocate(chunk_bytes, impl_->sector);
    for (std::uint64_t offset = 0; offset < impl_->bytes;) {
        const auto count =
            static_cast<std::size_t>(std::min<std::uint64_t>(chunk_bytes, impl_->bytes - offset));
        const std::span<std::byte> chunk(memory.get(), count);
        if (!read_stream(impl_->handle.get(), impl_->mapping, offset, chunk))
            throw Error("failed to read MFT stream");
        if (!callback(offset / impl_->record, chunk))
            return;
        offset += count;
    }
}

} // namespace dafree
