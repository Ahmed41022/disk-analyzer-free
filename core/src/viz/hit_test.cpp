#include "dafree/treemap.hpp"

#include <cmath>
#include <limits>

namespace dafree {
namespace {

constexpr float kCellSize = 32;
constexpr std::uint64_t kMaxCellsPerRect = 64;
constexpr auto kCellShift = std::numeric_limits<std::uint32_t>::digits;

auto cell(float value) -> std::uint32_t {
    return static_cast<std::uint32_t>(std::floor(value / kCellSize));
}
auto key(std::uint32_t x, std::uint32_t y) -> std::uint64_t {
    return (static_cast<std::uint64_t>(y) << kCellShift) | x;
}

} // namespace

void TreemapLayout::build_index() {
    for (std::size_t index = 0; index < rects_.size(); ++index) {
        const auto &rect = rects_[index];
        if (rect.flags & kTmOther || rect.w <= 0 || rect.h <= 0)
            continue;
        const auto left = cell(rect.x), top = cell(rect.y);
        const auto right = cell(rect.x + rect.w), bottom = cell(rect.y + rect.h);
        const auto count = (std::uint64_t{right} - left + 1) * (std::uint64_t{bottom} - top + 1);
        if (count > kMaxCellsPerRect) {
            // Broad ancestors need one candidate, not millions of repeated cell entries.
            large_.push_back(static_cast<std::uint32_t>(index));
            continue;
        }
        for (auto y = top; y <= bottom; ++y)
            for (auto x = left; x <= right; ++x)
                cells_[key(x, y)].push_back(static_cast<std::uint32_t>(index));
    }
}

auto TreemapLayout::hit_test(float x, float y) const -> std::optional<std::uint32_t> {
    if (!std::isfinite(x) || !std::isfinite(y) || x < 0 || y < 0 || x >= width_ || y >= height_)
        return std::nullopt;
    std::optional<std::uint32_t> found;
    auto best = std::numeric_limits<double>::infinity();
    std::uint8_t depth = 0;
    const auto consider = [&](std::uint32_t index) {
        const auto &rect = rects_[index];
        if (x < rect.x || y < rect.y || x >= rect.x + rect.w || y >= rect.y + rect.h)
            return;
        const auto area = double{rect.w} * rect.h;
        if (area < best || (area == best && rect.depth >= depth)) {
            best = area;
            depth = rect.depth;
            found = rect.node;
        }
    };
    for (const auto index : large_)
        consider(index);
    const auto entry = cells_.find(key(cell(x), cell(y)));
    if (entry != cells_.end())
        for (const auto index : entry->second)
            consider(index);
    return found;
}

} // namespace dafree
