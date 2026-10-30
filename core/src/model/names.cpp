#include "dafree/model.hpp"

#include <cstring>
#include <limits>
#include <stdexcept>

namespace dafree {
namespace {

constexpr std::size_t kChunkSize = 1024 * 1024;

} // namespace

std::pair<std::uint32_t, std::uint16_t> NameArena::push(std::string_view native_bytes) {
    if (native_bytes.size() > std::numeric_limits<std::uint16_t>::max()) {
        throw NameTooLong();
    }
    if (chunks_.empty()) {
        chunks_.push_back({std::make_unique_for_overwrite<char[]>(kChunkSize), 0});
    }

    auto *chunk = &chunks_.back();
    if (kChunkSize - chunk->used < native_bytes.size()) {
        const auto chunk_index = chunks_.size();
        if (chunk_index > std::numeric_limits<std::uint32_t>::max() / kChunkSize) {
            throw CapacityError();
        }
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

std::string_view NameArena::get(std::uint32_t offset, std::uint16_t length) const {
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

std::size_t NameArena::heap_bytes() const noexcept { return chunks_.size() * kChunkSize; }

} // namespace dafree
