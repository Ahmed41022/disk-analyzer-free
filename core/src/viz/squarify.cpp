#include "dafree/analysis.hpp"
#include "dafree/treemap.hpp"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>

namespace dafree {
namespace {

struct Item {
    NodeId node = kNone;
    double weight = 0;
    std::uint32_t count = 0;
    std::uint64_t bytes = 0;
    bool overflow = false;
};

constexpr auto kLarger = [](const Item &left, const Item &right) {
    if (left.overflow != right.overflow)
        return left.overflow;
    return left.bytes != right.bytes ? left.bytes > right.bytes : left.node < right.node;
};

struct Box {
    double x = 0, y = 0, w = 0, h = 0;
};

struct Row {
    double sum = 0, smallest = 0, largest = 0;
};

using Classes = std::unordered_map<std::uint32_t, std::uint8_t>;

enum class Rounding : std::uint8_t { Up, Down };

auto edge(double value, Rounding direction) -> float {
    const auto rounded = static_cast<float>(value);
    if (direction == Rounding::Up && double{rounded} < value)
        return std::nextafter(rounded, std::numeric_limits<float>::infinity());
    if (direction == Rounding::Down && double{rounded} > value)
        return std::nextafter(rounded, -std::numeric_limits<float>::infinity());
    return rounded;
}

auto worst(const Row &row, double side) -> double {
    const auto squared_sum = row.sum * row.sum;
    const auto squared_side = side * side;
    return std::max(squared_side * row.largest / squared_sum,
                    squared_sum / (squared_side * row.smallest));
}

auto children(const Tree &tree, NodeId parent, const Box &box, const TreemapOptions &options,
              std::size_t budget) -> std::vector<Item> {
    const auto area = box.w * box.h;
    const auto min_area = double{options.min_px} * options.min_px;
    std::vector<Item> result;
    const auto [first, end] = tree.children(parent);
    double total = 0;
    for (auto id = first; id < end; ++id) {
        const auto &node = tree.node(id);
        if (node.size && !(node.flags & kHardlinkDup)) {
            result.push_back({id, static_cast<double>(node.size), 0, node.size});
            total += static_cast<double>(node.size);
        }
    }
    std::sort(result.begin(), result.end(), kLarger);
    Item other;
    const auto retained = std::min(budget, result.size());
    std::size_t keep = 0;
    while (keep < retained && result[keep].weight / total * area >= min_area)
        ++keep;
    // Reserve one slot for all omitted siblings, preserving their combined area.
    if (keep < result.size() && keep == budget)
        --keep;
    for (auto index = keep; index < result.size(); ++index) {
        other.weight += result[index].weight;
        const auto bytes = result[index].bytes;
        if (bytes > std::numeric_limits<std::uint64_t>::max() - other.bytes) {
            other.bytes = std::numeric_limits<std::uint64_t>::max();
            other.overflow = true;
        } else {
            other.bytes += bytes;
        }
        ++other.count;
    }
    result.resize(keep);
    if (other.count) {
        const auto position = std::lower_bound(result.begin(), result.end(), other, kLarger);
        result.insert(position, other);
    }
    return result;
}

auto rectangle(const Tree &tree, const Item &item, const Box &box, std::uint8_t depth,
               Classes &classes) -> TmRect {
    // Round inward at the binary record boundary: float conversion cannot make
    // siblings overlap or let a child escape its parent's interior.
    const auto right = edge(box.x + box.w, Rounding::Down);
    const auto bottom = edge(box.y + box.h, Rounding::Down);
    const auto left = std::min(right, edge(box.x, Rounding::Up));
    const auto top = std::min(bottom, edge(box.y, Rounding::Up));
    TmRect result{left,
                  top,
                  edge(std::max(0.0, double{right} - left), Rounding::Down),
                  edge(std::max(0.0, double{bottom} - top), Rounding::Down),
                  item.node,
                  depth};
    if (item.node == kNone) {
        result.flags = kTmOther;
        result.cls = static_cast<std::uint8_t>(ExtCategory::Other);
    } else if (tree.node(item.node).flags & kDir) {
        result.flags = kTmDirectory;
        result.cls = static_cast<std::uint8_t>(depth % kTreemapDirectoryColors);
    } else {
        const auto ext_id = tree.node(item.node).ext_id;
        const auto [entry, added] = classes.try_emplace(ext_id, 0);
        if (added)
            entry->second = static_cast<std::uint8_t>(
                classify_extension(tree.ext(item.node).value_or(std::string_view{})));
        result.cls = entry->second;
    }
    return result;
}

// Original implementation of the row aspect-ratio criterion described in:
// Bruls, Huizing & van Wijk, Squarified Treemaps (2000), section 3.
// https://www.win.tue.nl/~vanwijk/stm.pdf
auto squarify(const Tree &tree, std::span<const Item> items, Box box, std::uint8_t depth,
              Classes &classes) -> std::vector<TmRect> {
    std::vector<TmRect> result;
    result.reserve(items.size());
    // Tail sums avoid catastrophic subtraction when a huge file precedes tiny ones.
    std::vector<double> remaining(items.size() + 1, 0);
    for (auto index = items.size(); index > 0; --index)
        remaining[index - 1] = remaining[index] + items[index - 1].weight;
    std::size_t begin = 0;
    while (begin < items.size() && box.w > 0 && box.h > 0) {
        const auto scale = box.w * box.h / remaining[begin];
        const auto side = std::min(box.w, box.h);
        auto end = begin + 1;
        auto sum = items[begin].weight * scale;
        const auto largest = sum;
        auto score = worst({sum, sum, sum}, side);
        while (end < items.size()) {
            const auto area = items[end].weight * scale;
            const auto next = worst({sum + area, area, largest}, side);
            if (next > score)
                break;
            sum += area;
            score = next;
            ++end;
        }
        const bool vertical = box.w >= box.h;
        const auto thickness = end == items.size() ? (vertical ? box.w : box.h) : sum / side;
        const auto origin = vertical ? box.y : box.x;
        const auto limit = origin + side;
        auto cursor = origin;
        for (auto index = begin; index < end; ++index) {
            const auto &item = items[index];
            const auto next = index + 1 == end
                                  ? limit
                                  : std::min(limit, cursor + item.weight * scale / thickness);
            const Box child = vertical ? Box{box.x, cursor, thickness, next - cursor}
                                       : Box{cursor, box.y, next - cursor, thickness};
            result.push_back(rectangle(tree, item, child, depth, classes));
            cursor = next;
        }
        if (vertical) {
            box.x += thickness;
            box.w = std::max(0.0, box.w - thickness);
        } else {
            box.y += thickness;
            box.h = std::max(0.0, box.h - thickness);
        }
        begin = end;
    }
    // A dominant uint64-sized item can exhaust double-precision remaining space.
    // Retain the remaining IDs/counts as zero-area records rather than losing them.
    for (; begin < items.size(); ++begin)
        result.push_back(rectangle(tree, items[begin], {box.x, box.y, 0, 0}, depth, classes));
    return result;
}

} // namespace

auto treemap_layout(const Tree &tree, NodeId root, float w, float h, const TreemapOptions &options)
    -> TreemapLayout {
    const auto valid = [](float value) { return std::isfinite(value) && value >= 0; };
    const auto max_dimension = static_cast<double>(std::numeric_limits<int>::max());
    if (!valid(w) || !valid(h) || static_cast<double>(w) > max_dimension ||
        static_cast<double>(h) > max_dimension || !valid(options.min_px) ||
        !valid(options.padding) || !valid(options.header_px))
        throw std::invalid_argument("treemap geometry must be finite, nonnegative device pixels");
    const auto &node = tree.node(root); // Validate even an empty output request.
    TreemapLayout layout;
    layout.width_ = w;
    layout.height_ = h;
    if (w == 0 || h == 0 || options.max_rects == 0)
        return layout;
    const auto capacity = std::min(tree.size(), options.max_rects);
    layout.rects_.reserve(capacity);
    layout.parents_.reserve(capacity);
    layout.small_counts_.reserve(capacity);
    Classes classes;
    layout.rects_.push_back(
        rectangle(tree, {root, static_cast<double>(node.size), 0}, {0, 0, w, h}, 0, classes));
    layout.parents_.push_back(kNone);
    layout.small_counts_.push_back(0);
    const auto min_area = static_cast<double>(options.min_px) * options.min_px;
    // Appending children before visiting them makes both traversal and budgeting BFS.
    for (std::size_t index = 0; index < layout.rects_.size(); ++index) {
        const auto parent = layout.rects_[index];
        if (!(parent.flags & kTmDirectory) || parent.depth >= options.max_depth ||
            layout.rects_.size() >= options.max_rects)
            continue;
        const auto header = parent.depth ? static_cast<double>(options.header_px) : 0.0;
        const Box inner{parent.x + static_cast<double>(options.padding),
                        parent.y + static_cast<double>(options.padding) + header,
                        std::max(0.0, parent.w - 2.0 * options.padding),
                        std::max(0.0, parent.h - 2.0 * options.padding - header)};
        const auto area = inner.w * inner.h;
        if (area <= 0 || area < min_area)
            continue;
        const auto items =
            children(tree, parent.node, inner, options, options.max_rects - layout.rects_.size());
        const auto placed =
            squarify(tree, items, inner, static_cast<std::uint8_t>(parent.depth + 1), classes);
        for (std::size_t child = 0; child < placed.size(); ++child) {
            layout.rects_.push_back(placed[child]);
            layout.parents_.push_back(static_cast<std::uint32_t>(index));
            layout.small_counts_.push_back(items[child].count);
        }
    }
    layout.build_index();
    return layout;
}

auto TreemapLayout::rects() const noexcept -> std::span<const TmRect> { return rects_; }
auto TreemapLayout::small_items(std::size_t index) const -> std::uint32_t {
    return small_counts_.at(index);
}
auto TreemapLayout::width() const noexcept -> float { return width_; }
auto TreemapLayout::height() const noexcept -> float { return height_; }

} // namespace dafree
