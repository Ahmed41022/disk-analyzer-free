#include "dafree/treemap.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace dafree {
namespace {

constexpr std::size_t kChannels = 4;
constexpr auto kByteBits = std::numeric_limits<std::uint8_t>::digits;
constexpr double kCushionHeight = 0.15;
constexpr double kDepthAttenuation = 0.65;
constexpr double kAmbient = 0.35;
constexpr double kPixelCenter = 0.5;
constexpr double kLightX = 1, kLightY = 2, kLightZ = 10;
constexpr auto kColorMax = std::numeric_limits<std::uint8_t>::max();

struct Surface {
    double xx = 0, x = 0, yy = 0, y = 0;
};

// Quadratic ridge derivatives and diffuse lighting, implemented from the method in
// van Wijk & van de Wetering (1999): https://vanwijk.win.tue.nl/ctm.pdf

auto pixel_bound(double value, int limit) -> int {
    return static_cast<int>(
        std::clamp(std::ceil(value - kPixelCenter), 0.0, static_cast<double>(limit)));
}

auto unpack(std::uint32_t color) -> std::array<std::uint8_t, kChannels> {
    std::array<std::uint8_t, kChannels> bytes{};
    for (std::size_t channel = 0; channel < bytes.size(); ++channel) {
        const auto shift = (kChannels - 1 - channel) * kByteBits;
        bytes.at(channel) = static_cast<std::uint8_t>((color >> shift) & kColorMax);
    }
    return bytes;
}

} // namespace

auto treemap_render(const TreemapLayout &layout, int w, int h, const Palette &palette, bool cushion)
    -> std::vector<std::uint8_t> {
    if (w < 0 || h < 0)
        throw std::invalid_argument("treemap image dimensions must be nonnegative");
    const auto width = static_cast<std::size_t>(w), height = static_cast<std::size_t>(h);
    const auto max_bytes = std::vector<std::uint8_t>{}.max_size();
    if (height && width > max_bytes / kChannels / height)
        throw std::length_error("treemap image dimensions exceed buffer capacity");
    const auto pixels = width * height;
    std::vector<std::uint8_t> output(pixels * kChannels);
    if (!pixels)
        return output;
    std::vector<std::uint32_t> owners(pixels, kNone);
    std::vector<Surface> surfaces(layout.rects_.size());
    std::vector<std::array<std::uint8_t, kChannels>> colors;
    colors.reserve(layout.rects_.size());
    const auto background = unpack(palette.background), border = unpack(palette.border);
    for (std::size_t index = 0; index < layout.rects_.size(); ++index) {
        const auto &rect = layout.rects_[index];
        const auto color = rect.flags & kTmDirectory
                               ? palette.dir_by_depth.at(rect.depth % palette.dir_by_depth.size())
                               : palette.by_class.at(rect.cls);
        colors.push_back(unpack(color));
        if (cushion && rect.w > 0 && rect.h > 0) {
            const auto parent = layout.parents_[index];
            auto surface = parent == kNone ? Surface{} : surfaces[parent];
            const auto elevation =
                kCushionHeight * std::min(rect.w, rect.h) * std::pow(kDepthAttenuation, rect.depth);
            const auto ridge_x = 4 * elevation / (double{rect.w} * rect.w);
            const auto ridge_y = 4 * elevation / (double{rect.h} * rect.h);
            surface.xx -= 2 * ridge_x;
            surface.x += ridge_x * (2 * double{rect.x} + rect.w);
            surface.yy -= 2 * ridge_y;
            surface.y += ridge_y * (2 * double{rect.y} + rect.h);
            surfaces[index] = surface;
        }
        const auto left = pixel_bound(rect.x, w), top = pixel_bound(rect.y, h);
        const auto right = pixel_bound(rect.x + rect.w, w);
        const auto bottom = pixel_bound(rect.y + rect.h, h);
        for (auto y = top; y < bottom; ++y) {
            const auto row = static_cast<std::size_t>(y) * width;
            std::fill(
                owners.begin() + static_cast<std::ptrdiff_t>(row + static_cast<std::size_t>(left)),
                owners.begin() + static_cast<std::ptrdiff_t>(row + static_cast<std::size_t>(right)),
                static_cast<std::uint32_t>(index));
        }
    }
    const auto light_norm = std::sqrt(kLightX * kLightX + kLightY * kLightY + kLightZ * kLightZ);
    // Determine visible ownership first: ancestors are never shaded again under their children.
    for (std::size_t y = 0; y < height; ++y) {
        for (std::size_t x = 0; x < width; ++x) {
            const auto pixel = y * width + x;
            const auto owner = owners[pixel];
            auto color = background;
            if (owner != kNone) {
                const auto &rect = layout.rects_[owner];
                const auto px = static_cast<double>(x) + kPixelCenter;
                const auto py = static_cast<double>(y) + kPixelCenter;
                const bool edge =
                    rect.w >= 3 && rect.h >= 3 &&
                    (px - rect.x < 1 || py - rect.y < 1 || double{rect.x} + rect.w - px <= 1 ||
                     double{rect.y} + rect.h - py <= 1);
                color = edge ? border : colors[owner];
                if (cushion && !edge) {
                    const auto &surface = surfaces[owner];
                    const auto dx = surface.xx * px + surface.x;
                    const auto dy = surface.yy * py + surface.y;
                    const auto diffuse =
                        std::max(0.0, (kLightZ - kLightX * dx - kLightY * dy) /
                                          (light_norm * std::sqrt(dx * dx + dy * dy + 1)));
                    const auto intensity = std::min(1.0, kAmbient + (1 - kAmbient) * diffuse);
                    // Nonnegative channels round identically by adding half before truncation.
                    for (std::size_t channel = 0; channel + 1 < kChannels; ++channel)
                        color.at(channel) =
                            static_cast<std::uint8_t>(color.at(channel) * intensity + kPixelCenter);
                }
            }
            for (std::size_t channel = 0; channel < kChannels; ++channel)
                output[pixel * kChannels + channel] = color.at(channel);
        }
    }
    return output;
}

} // namespace dafree
