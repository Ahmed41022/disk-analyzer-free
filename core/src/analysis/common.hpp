#pragma once

#include "dafree/analysis.hpp"

#include <limits>

namespace dafree::analysis_detail {

inline bool visible_scope(const Tree &tree, NodeId scope) {
    while (scope != kRoot) {
        const auto &node = tree.node(scope);
        if ((node.flags & kExcluded) != 0)
            return false;
        scope = node.parent;
    }
    return true;
}

template <class Stat> void add_file(Stat &stat, const Node &node) {
    const auto sum = [](std::uint64_t a, std::uint64_t b) {
        const auto max = std::numeric_limits<std::uint64_t>::max();
        return b > max - a ? max : a + b;
    };
    ++stat.files;
    stat.size = sum(stat.size, node.size);
    stat.alloc = sum(stat.alloc, node.alloc);
}

template <class Visit> void for_each_node(const Tree &tree, NodeId scope, Visit &&visit) {
    auto id = scope;
    for (;;) {
        if ((tree.node(id).flags & kExcluded) == 0) {
            if (id != kRoot && (tree.node(id).flags & kHardlinkDup) == 0)
                visit(id);
            const auto [first, end] = tree.children(id);
            if (first != end) {
                id = first;
                continue;
            }
        }
        while (id != scope) {
            const auto parent = tree.node(id).parent;
            if (id + 1 < tree.children(parent).second) {
                ++id;
                break;
            }
            id = parent;
        }
        if (id == scope)
            return;
    }
}

} // namespace dafree::analysis_detail
