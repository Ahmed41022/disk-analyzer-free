#pragma once

#include "dafree/model.hpp"

#include <array>
#include <cstdint>
#include <optional>
#include <span>
#include <unordered_map>
#include <vector>

namespace dafree {

inline constexpr std::uint8_t kTreemapDefaultDepth = 12;
inline constexpr std::uint32_t kTreemapDefaultBudget = 50'000;
inline constexpr std::size_t kTreemapClasses = 16, kTreemapDirectoryColors = 8;

/// Limits and spacing in device pixels for a squarified treemap.
struct TreemapOptions {
    std::uint8_t max_depth = kTreemapDefaultDepth;
    float min_px = 3, padding = 1, header_px = 0;
    std::uint32_t max_rects = kTreemapDefaultBudget;
};

/// Flags distinguish directory rectangles and aggregated small-item groups.
enum TmFlags : std::uint8_t { kTmOther = 1u << 0, kTmDirectory = 1u << 1 };

/// One device-pixel rectangle; OTHER has node=kNone and a separate item count.
struct TmRect {
    float x = 0, y = 0, w = 0, h = 0;
    std::uint32_t node = kNone;
    std::uint8_t depth = 0, cls = 0, flags = 0, pad = 0;
};
// Fixed binary record shared with the read-only NumPy structured view.
// NOLINTNEXTLINE(cppcoreguidelines-avoid-magic-numbers)
static_assert(sizeof(TmRect) == 24);

/// Packed colors are 0xRRGGBBAA, independent of host byte order.
struct Palette {
    std::array<std::uint32_t, kTreemapClasses> by_class{};
    std::array<std::uint32_t, kTreemapDirectoryColors> dir_by_depth{};
    std::uint32_t background = 0, border = 0;
};

/// Immutable layout owning its rectangles, hierarchy and 32-pixel spatial index.
class TreemapLayout {
  public:
    /// Return owned storage; retain this layout alive and unmoved while borrowing it.
    [[nodiscard]] auto rects() const noexcept -> std::span<const TmRect>;
    /// Return the smallest containing real node, or no node outside the layout.
    [[nodiscard]] auto hit_test(float x, float y) const -> std::optional<std::uint32_t>;
    /// Return the number of siblings represented by an OTHER rectangle.
    [[nodiscard]] auto small_items(std::size_t index) const -> std::uint32_t;
    /// Return the requested layout width, including an empty rectangle budget.
    [[nodiscard]] auto width() const noexcept -> float;
    /// Return the requested layout height, including an empty rectangle budget.
    [[nodiscard]] auto height() const noexcept -> float;

  private:
    friend auto treemap_layout(const Tree &, NodeId, float, float, const TreemapOptions &)
        -> TreemapLayout;
    friend auto treemap_render(const TreemapLayout &, int, int, const Palette &, bool)
        -> std::vector<std::uint8_t>;
    void build_index();

    float width_ = 0, height_ = 0;
    std::vector<TmRect> rects_;
    std::vector<std::uint32_t> parents_;
    std::vector<std::uint32_t> small_counts_;
    std::unordered_map<std::uint64_t, std::vector<std::uint32_t>> cells_;
    std::vector<std::uint32_t> large_;
};

/// Layout positive-size, non-duplicate children; invalid geometry throws invalid_argument.
[[nodiscard]] auto treemap_layout(const Tree &, NodeId root, float w, float h,
                                  const TreemapOptions &) -> TreemapLayout;
/// Rasterize once per visible pixel to RGBA8888, clipping to the requested image.
[[nodiscard]] auto treemap_render(const TreemapLayout &, int w, int h, const Palette &,
                                  bool cushion) -> std::vector<std::uint8_t>;

} // namespace dafree
