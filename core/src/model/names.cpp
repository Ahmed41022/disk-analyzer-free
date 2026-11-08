#include "dafree/model.hpp"

#include <cstring>
#include <limits>
#include <stdexcept>

namespace dafree {
namespace {

constexpr std::size_t kChunkSize = std::size_t{1024} * 1024;

} // namespace

auto NameArena::push(std::string_view native_bytes) -> std::pair<std::uint32_t, std::uint16_t> {
    if (native_bytes.size() > std::numeric_limits<std::uint16_t>::max()) {
        throw NameTooLong();
    }
    if (chunks_.empty()) {
        // Arena chunks are owning dynamic arrays whose addresses must remain stable.
        // NOLINTNEXTLINE(cppcoreguidelines-avoid-c-arrays,modernize-avoid-c-arrays)
        chunks_.push_back({std::make_unique_for_overwrite<char[]>(kChunkSize), 0});
    }

    auto *chunk = &chunks_.back();
    if (kChunkSize - chunk->used < native_bytes.size()) {
        const auto chunk_index = chunks_.size();
        if (chunk_index > std::numeric_limits<std::uint32_t>::max() / kChunkSize) {
            throw CapacityError();
        }
        // Arena chunks are owning dynamic arrays whose addresses must remain stable.
        // NOLINTNEXTLINE(cppcoreguidelines-avoid-c-arrays,modernize-avoid-c-arrays)
        chunks_.push_back({std::make_unique_for_overwrite<char[]>(kChunkSize), 0});
        chunk = &chunks_.back();
    }

    const auto chunk_index = chunks_.size() - 1;
    const auto absolute_offset = chunk_index * kChunkSize + chunk->used;
    if (absolute_offset > std::numeric_limits<std::uint32_t>::max()) {
        throw CapacityError();
    }
    const auto offset = static_cast<std::uint32_t>(absolute_offset);
    const auto length = static_cast<std::uint16_t>(native_bytes.size());
    if (!native_bytes.empty()) {
        std::memcpy(chunk->data.get() + chunk->used, native_bytes.data(), native_bytes.size());
        chunk->used += native_bytes.size();
    }
    return {offset, length};
}

// The arena interface specifies a 32-bit offset and 16-bit length.
// NOLINTNEXTLINE(bugprone-easily-swappable-parameters)
auto NameArena::get(std::uint32_t offset, std::uint16_t length) const -> std::string_view {
    if (length == 0) {
        return {};
    }
    const auto chunk_index = static_cast<std::size_t>(offset) / kChunkSize;
    const auto local_offset = static_cast<std::size_t>(offset) % kChunkSize;
    if (chunk_index >= chunks_.size() || local_offset + length > chunks_[chunk_index].used) {
        throw std::out_of_range("name arena range is not populated");
    }
    return {chunks_[chunk_index].data.get() + local_offset, length};
}

auto NameArena::heap_bytes() const noexcept -> std::size_t { return chunks_.size() * kChunkSize; }

} // namespace dafree
