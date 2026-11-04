#include "mft_driver.hpp"

#include "../platform/windows/internal.hpp"
#include "../platform/windows/mft_reader.hpp"
#include "dafree/scan.hpp"
#include "work_queue.hpp"

#include <algorithm>
#include <exception>
#include <thread>

namespace dafree::detail {
namespace {

struct Chunk {
    std::uint64_t first;
    std::vector<std::byte> data;
};

std::string_view open_reason(MftOpenError error) {
    switch (error) {
    case MftOpenError::NotElevated:
        return "the process is not elevated";
    case MftOpenError::NotNtfs:
        return "the target is not a supported local NTFS volume";
    case MftOpenError::AccessDenied:
        return "access to the volume was denied";
    case MftOpenError::Io:
        return "could not read or map the MFT";
    }
    return "could not open the volume";
}

} // namespace

std::optional<Tree> scan_mft(std::string_view volume_root, std::string_view target,
                             const ScanOptions &options, const std::function<bool()> &checkpoint,
                             const std::function<void(std::uint64_t)> &estimate) {
    if (!checkpoint())
        return std::nullopt;
    auto opened = VolumeReader::open(platform::detail::from_wtf8(volume_root));
    if (!opened.has_value())
        throw ScanError(ScanError::Code::UnsupportedMode, std::string(open_reason(opened.error())));
    auto reader = std::move(opened.value());
    estimate(reader.record_count());

    const auto count = std::clamp(options.threads, 1u, 8u);
    const auto record_size = reader.record_size(), sector_size = reader.sector_size();
    WorkQueue<Chunk> queue(4);
    std::vector<MftIndex> indices(count);
    std::vector<std::jthread> parsers;
    parsers.reserve(count);
    std::mutex failure_mutex;
    std::exception_ptr failure;
    try {
        for (unsigned worker = 0; worker < count; ++worker) {
            parsers.emplace_back([&, worker] {
                try {
                    auto &index = indices[worker];
                    while (auto chunk = queue.pop()) {
                        std::span<std::byte> records(chunk->data);
                        for (std::size_t offset = 0; offset < records.size(); offset += record_size)
                            index.ingest(chunk->first + offset / record_size,
                                         records.subspan(offset, record_size), sector_size);
                    }
                } catch (...) {
                    {
                        std::lock_guard lock(failure_mutex);
                        if (!failure)
                            failure = std::current_exception();
                    }
                    queue.close(true);
                }
            });
        }
        constexpr std::size_t chunk_size = 8 * 1024 * 1024;
        reader.read_chunks(chunk_size, [&](auto first, std::span<std::byte> data) {
            return checkpoint() && queue.push({first, {data.begin(), data.end()}});
        });
    } catch (...) {
        std::lock_guard lock(failure_mutex);
        if (!failure)
            failure = std::current_exception();
    }

    const bool running = checkpoint();
    queue.close(!running);
    parsers.clear();
    if (failure)
        std::rethrow_exception(failure);
    if (!running || !checkpoint())
        return std::nullopt;

    auto index = std::move(indices.front());
    for (unsigned worker = 1; worker < count; ++worker)
        index.merge(std::move(indices[worker]));
    IssueSink sink;
    return build_tree_from_mft(index, volume_root, target, options, sink);
}

} // namespace dafree::detail
