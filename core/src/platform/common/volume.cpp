#include <cstdint>
#include <limits>

namespace dafree::platform {

std::uint64_t volume_bytes(std::uint64_t blocks, std::uint64_t fragment_size) noexcept {
    if (fragment_size != 0 && blocks > std::numeric_limits<std::uint64_t>::max() / fragment_size)
        return std::numeric_limits<std::uint64_t>::max();
    return blocks * fragment_size;
}

} // namespace dafree::platform
