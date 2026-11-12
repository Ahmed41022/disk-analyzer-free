#include "common.hpp"

#include "../view/view_internal.hpp"

#include <algorithm>
#include <limits>
#include <unordered_set>

namespace dafree {

auto child_chart_data(const Tree &tree, NodeId scope, ChildChartField field, std::size_t top)
    -> std::vector<ChildChartRow> {
    if (!analysis_detail::visible_scope(tree, scope))
        return {};

    const auto [first, end] = tree.children(scope);
    const auto get_value = [&](NodeId id) -> std::uint64_t {
        const auto &node = tree.node(id);
        switch (field) {
        case ChildChartField::Size:
            return node.size;
        case ChildChartField::Alloc:
            return node.alloc;
        case ChildChartField::Files:
            return (node.flags & kDir) != 0 ? tree.counts(id).files : 1;
        }
        throw std::invalid_argument("unknown child chart field");
    };
    const auto better = [&](const ChildChartRow &left, const ChildChartRow &right) {
        if (left.value != right.value)
            return left.value > right.value;
        const auto name =
            detail::natural_compare(tree.name_bytes(left.node), tree.name_bytes(right.node));
        return name != 0 ? name < 0 : left.node < right.node;
    };

    // Keep only the best `top` rows while walking siblings; memory is bounded by the result.
    std::vector<ChildChartRow> result;
    result.reserve(std::min<std::size_t>(top, end - first) + 1);
    for (auto id = first; id < end; ++id) {
        const auto &node = tree.node(id);
        if ((node.flags & (kExcluded | kHardlinkDup)) != 0 || top == 0)
            continue;
        const auto value = get_value(id);
        if (value == 0)
            continue;
        const ChildChartRow candidate{id, value, false};
        if (result.size() < top) {
            result.push_back(candidate);
            std::push_heap(result.begin(), result.end(), better);
        } else if (better(candidate, result.front())) {
            std::pop_heap(result.begin(), result.end(), better);
            result.back() = candidate;
            std::push_heap(result.begin(), result.end(), better);
        }
    }
    std::sort_heap(result.begin(), result.end(), better);

    // A second linear pass computes the saturated remainder without storing all siblings.
    std::unordered_set<NodeId> selected;
    selected.reserve(result.size());
    for (const auto &row : result)
        selected.insert(row.node);
    std::uint64_t remainder = 0;
    for (auto id = first; id < end; ++id) {
        const auto &node = tree.node(id);
        if ((node.flags & (kExcluded | kHardlinkDup)) != 0 || selected.contains(id))
            continue;
        const auto value = get_value(id);
        if (value != 0) {
            remainder = value > std::numeric_limits<std::uint64_t>::max() - remainder
                            ? std::numeric_limits<std::uint64_t>::max()
                            : remainder + value;
        }
    }
    if (remainder != 0)
        result.push_back({kNone, remainder, true});
    return result;
}

} // namespace dafree
