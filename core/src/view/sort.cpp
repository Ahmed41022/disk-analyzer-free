#include "view_internal.hpp"

#include <algorithm>

namespace dafree::detail {
namespace {

template <class T> int compare(T left, T right) {
    return left < right ? -1 : (left > right ? 1 : 0);
}

int primary(const Tree &tree, NodeId left, NodeId right, SortKey key) {
    const auto &a = tree.node(left);
    const auto &b = tree.node(right);
    switch (key) {
    case SortKey::Name:
        return natural_compare(tree.name_bytes(left), tree.name_bytes(right));
    case SortKey::Size:
        return compare(a.size, b.size);
    case SortKey::PctParent:
        return a.parent != kNone && tree.node(a.parent).size != 0 ? compare(a.size, b.size) : 0;
    case SortKey::Alloc:
        return compare(a.alloc, b.alloc);
    case SortKey::Files:
        return compare(tree.counts(left).files, tree.counts(right).files);
    case SortKey::Dirs:
        return compare(tree.counts(left).dirs, tree.counts(right).dirs);
    case SortKey::Mtime:
        return compare(a.mtime, b.mtime);
    case SortKey::Owner:
        return natural_compare(tree.owner_name(left).value_or(""),
                               tree.owner_name(right).value_or(""));
    case SortKey::Ext:
        return natural_compare(tree.ext(left).value_or(""), tree.ext(right).value_or(""));
    }
    throw std::invalid_argument("unknown sort key");
}

} // namespace

void sort_children(const Tree &tree, std::vector<NodeId> &ids, const ViewOptions &options) {
    const auto less = [&](NodeId left, NodeId right) {
        if (options.dirs_first) {
            const bool a_dir = (tree.node(left).flags & kDir) != 0;
            const bool b_dir = (tree.node(right).flags & kDir) != 0;
            if (a_dir != b_dir)
                return a_dir;
        }
        const int value = primary(tree, left, right, options.sort);
        if (value != 0)
            return options.descending ? value > 0 : value < 0;
        const int name = natural_compare(tree.name_bytes(left), tree.name_bytes(right));
        return name != 0 ? name < 0 : left < right;
    };
    if (!std::is_sorted(ids.begin(), ids.end(), less))
        std::sort(ids.begin(), ids.end(), less);
}

} // namespace dafree::detail
