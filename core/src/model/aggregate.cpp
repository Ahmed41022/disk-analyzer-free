#include "dafree/model.hpp"

#include <algorithm>
#include <limits>
#include <stdexcept>

namespace dafree {
namespace {

template <typename T> T saturating_add(T left, T right) noexcept {
    const auto maximum = std::numeric_limits<T>::max();
    return right > maximum - left ? maximum : static_cast<T>(left + right);
}

template <typename T> T saturating_subtract(T left, T right) noexcept {
    return right > left ? 0 : static_cast<T>(left - right);
}

Counts contribution(std::uint16_t flags, Counts below) noexcept {
    if ((flags & kExcluded) != 0) {
        return {};
    }
    if ((flags & kDir) != 0) {
        return {below.files, saturating_add(std::uint32_t{1}, below.dirs)};
    }
    return {1, 0};
}

void recompute_directory(SegVector<Node> &nodes, SegVector<Counts> &counts, NodeId dir) {
    auto &directory = nodes[dir];
    directory.size = 0;
    directory.alloc = 0;
    counts[dir] = {};
    if (directory.child_count == 0) {
        return;
    }
    const auto end = directory.first_child + directory.child_count;
    for (auto child_id = directory.first_child; child_id < end; ++child_id) {
        const auto &child = nodes[child_id];
        if ((child.flags & (kHardlinkDup | kExcluded)) == 0) {
            directory.size = saturating_add(directory.size, child.size);
            directory.alloc = saturating_add(directory.alloc, child.alloc);
        }
        const auto child_counts = contribution(child.flags, counts[child_id]);
        counts[dir].files = saturating_add(counts[dir].files, child_counts.files);
        counts[dir].dirs = saturating_add(counts[dir].dirs, child_counts.dirs);
    }
}

} // namespace

void aggregate(SegVector<Node> &nodes, SegVector<Counts> &counts) {
    if (nodes.size() != counts.size()) {
        throw std::invalid_argument("node and count arrays must have equal sizes");
    }
    for (NodeId id = 0; id < nodes.size(); ++id) {
        if ((nodes[id].flags & kDir) != 0) {
            nodes[id].size = 0;
            nodes[id].alloc = 0;
        }
        counts[id] = {};
    }
    for (NodeId next = nodes.size(); next > 1; --next) {
        const auto id = next - 1;
        const auto child = nodes[id];
        if (child.parent >= id) {
            throw std::invalid_argument("tree nodes must have an earlier parent");
        }
        auto &parent = nodes[child.parent];
        if ((child.flags & (kHardlinkDup | kExcluded)) == 0) {
            parent.size = saturating_add(parent.size, child.size);
            parent.alloc = saturating_add(parent.alloc, child.alloc);
        }
        const auto child_counts = contribution(child.flags, counts[id]);
        counts[child.parent].files = saturating_add(counts[child.parent].files, child_counts.files);
        counts[child.parent].dirs = saturating_add(counts[child.parent].dirs, child_counts.dirs);
    }
}

void Tree::mark_deleted(NodeId id) {
    if (id == kRoot) {
        throw std::invalid_argument("the synthetic root cannot be deleted");
    }
    if (id >= nodes_.size()) {
        throw std::out_of_range("tree node ID is out of range");
    }
    auto &deleted = nodes_[id];
    if ((deleted.flags & kExcluded) != 0) {
        return;
    }

    Node old_child = deleted;
    auto old_child_counts = counts_[id];
    deleted.flags = static_cast<std::uint16_t>(deleted.flags | kExcluded);
    Node new_child = deleted;
    auto new_child_counts = counts_[id];

    while (old_child.parent != kNone) {
        const auto parent_id = old_child.parent;
        if (parent_id >= nodes_.size()) {
            throw std::logic_error("tree node has an invalid parent");
        }
        auto &parent = nodes_[parent_id];
        if ((parent.flags & kDir) == 0) {
            throw std::logic_error("tree parent is not a directory");
        }
        const Node old_parent = parent;
        const auto old_parent_counts = counts_[parent_id];

        if (parent.size == std::numeric_limits<std::uint64_t>::max() ||
            parent.alloc == std::numeric_limits<std::uint64_t>::max()) {
            recompute_directory(nodes_, counts_, parent_id);
        } else {
            if ((old_child.flags & (kHardlinkDup | kExcluded)) == 0) {
                parent.size = saturating_subtract(parent.size, old_child.size);
                parent.alloc = saturating_subtract(parent.alloc, old_child.alloc);
            }
            if ((new_child.flags & (kHardlinkDup | kExcluded)) == 0) {
                parent.size = saturating_add(parent.size, new_child.size);
                parent.alloc = saturating_add(parent.alloc, new_child.alloc);
            }

            const auto old_contribution = contribution(old_child.flags, old_child_counts);
            const auto new_contribution = contribution(new_child.flags, new_child_counts);
            counts_[parent_id].files = saturating_add(
                saturating_subtract(counts_[parent_id].files, old_contribution.files),
                new_contribution.files);
            counts_[parent_id].dirs =
                saturating_add(saturating_subtract(counts_[parent_id].dirs, old_contribution.dirs),
                               new_contribution.dirs);
        }

        old_child = old_parent;
        old_child_counts = old_parent_counts;
        new_child = parent;
        new_child_counts = counts_[parent_id];
        if ((parent.flags & kExcluded) != 0) {
            break;
        }
    }
}

} // namespace dafree
