#include "common.hpp"

#include "../view/view_internal.hpp"

#include <algorithm>
#include <future>
#include <thread>

namespace dafree {
namespace {

template <class Value> int compare(Value left, Value right) {
    return (left > right) - (left < right);
}

long double parent_fraction(const Tree &tree, const Node &node) {
    const auto size = node.parent == kNone ? 0 : tree.node(node.parent).size;
    return size == 0 ? 0 : static_cast<long double>(node.size) / static_cast<long double>(size);
}

// Rank across directories without changing the sibling-sort hot path.
int compare_rank(const Tree &tree, NodeId left, NodeId right, SortKey key) {
    const auto &a = tree.node(left);
    const auto &b = tree.node(right);
    switch (key) {
    case SortKey::Name:
        return detail::natural_compare(tree.name_bytes(left), tree.name_bytes(right));
    case SortKey::Size:
        return compare(a.size, b.size);
    case SortKey::Alloc:
        return compare(a.alloc, b.alloc);
    case SortKey::PctParent:
        return compare(parent_fraction(tree, a), parent_fraction(tree, b));
    case SortKey::Files:
        return compare(tree.counts(left).files, tree.counts(right).files);
    case SortKey::Dirs:
        return compare(tree.counts(left).dirs, tree.counts(right).dirs);
    case SortKey::Mtime:
        return compare(a.mtime, b.mtime);
    case SortKey::Owner:
        return detail::natural_compare(tree.owner_name(left).value_or(""),
                                       tree.owner_name(right).value_or(""));
    case SortKey::Ext:
        return detail::natural_compare(tree.ext(left).value_or(""), tree.ext(right).value_or(""));
    }
    throw std::invalid_argument("unknown ranking key");
}

bool candidate(const Tree &tree, NodeId id, TopKind kind, bool leaf_only) {
    const auto &node = tree.node(id);
    const bool dir = (node.flags & kDir) != 0;
    if (dir != (kind == TopKind::Dirs))
        return false;
    if (!dir || !leaf_only)
        return true;

    // Round the one-percent threshold up without overflowing a byte count.
    const auto threshold = node.size / 100 + (node.size % 100 != 0);
    const auto [first, end] = tree.children(id);
    for (auto child = first; child < end; ++child) {
        const auto &entry = tree.node(child);
        if ((entry.flags & (kDir | kExcluded | kHardlinkDup)) == kDir && entry.size >= threshold)
            return false;
    }
    return true;
}

template <class Better>
void offer(std::vector<NodeId> &heap, NodeId id, std::size_t n, const Better &better) {
    if (heap.size() < n) {
        heap.push_back(id);
        std::push_heap(heap.begin(), heap.end(), better);
    } else if (better(id, heap.front())) {
        std::pop_heap(heap.begin(), heap.end(), better);
        heap.back() = id;
        std::push_heap(heap.begin(), heap.end(), better);
    }
}

} // namespace

std::vector<NodeId> top_n(const Tree &tree, NodeId scope, TopKind kind, std::size_t n, SortKey by,
                          bool leaf_only) {
    if (n == 0 || !analysis_detail::visible_scope(tree, scope))
        return {};
    const auto better = [&](NodeId left, NodeId right) {
        const auto primary = compare_rank(tree, left, right, by);
        if (primary != 0)
            return primary > 0;
        const auto name = detail::natural_compare(tree.name_bytes(left), tree.name_bytes(right));
        return name != 0 ? name < 0 : left < right;
    };
    const auto add = [&](std::vector<NodeId> &heap, NodeId id) {
        if (candidate(tree, id, kind, leaf_only))
            offer(heap, id, n, better);
    };

    std::vector<NodeId> heap;
    if (tree.size() < 16'384) {
        analysis_detail::for_each_node(tree, scope, [&](NodeId id) { add(heap, id); });
    } else {
        auto root = scope;
        while (true) {
            const auto &node = tree.node(root);
            if ((node.flags & kExcluded) != 0)
                break;
            if (root != kRoot && (node.flags & kHardlinkDup) == 0)
                add(heap, root);
            const auto [first, end] = tree.children(root);
            if (end - first == 1) {
                root = first;
                continue;
            }
            const auto worker_count =
                std::min({8u, std::max(1u, std::thread::hardware_concurrency()), end - first});
            std::vector<std::future<std::vector<NodeId>>> workers;
            workers.reserve(worker_count);
            for (unsigned worker = 0; worker < worker_count; ++worker) {
                const auto length = static_cast<std::uint64_t>(end - first);
                const auto begin = first + static_cast<NodeId>(length * worker / worker_count);
                const auto stop = first + static_cast<NodeId>(length * (worker + 1) / worker_count);
                workers.push_back(std::async(std::launch::async, [&, begin, stop] {
                    std::vector<NodeId> local;
                    for (auto id = begin; id < stop; ++id)
                        analysis_detail::for_each_node(tree, id,
                                                       [&](NodeId item) { add(local, item); });
                    return local;
                }));
            }
            for (auto &worker : workers)
                for (const auto id : worker.get())
                    offer(heap, id, n, better);
            break;
        }
    }
    std::sort_heap(heap.begin(), heap.end(), better);
    return heap;
}

} // namespace dafree
