#include "dafree/model.hpp"

#include <limits>
#include <stdexcept>

namespace dafree {
namespace {

Node make_node(NodeId parent, std::uint16_t flags, std::uint32_t name_offset,
               std::uint16_t name_length) {
    Node node;
    node.parent = parent;
    node.flags = flags;
    node.name_off = name_offset;
    node.name_len = name_length;
    return node;
}

} // namespace

TreeBuilder::TreeBuilder(std::vector<std::string> root_paths) {
    Node synthetic;
    synthetic.flags = static_cast<std::uint16_t>(kDir | kSynthetic);
    tree_.nodes_.push_back(synthetic);
    tree_.counts_.push_back({});
    populated_.push_back(false);
    tree_.root_paths_ = std::move(root_paths);

    if (tree_.root_paths_.size() > std::numeric_limits<std::uint32_t>::max()) {
        throw CapacityError();
    }
    tree_.roots_.reserve(tree_.root_paths_.size());
    std::vector<NewNode> roots;
    roots.reserve(tree_.root_paths_.size());
    for (const auto &path : tree_.root_paths_) {
        roots.push_back({path, static_cast<std::uint16_t>(kDir), 0, 0, 0, 0, 0, std::nullopt});
    }
    const auto [first, last] = add_children(kRoot, roots);
    for (auto id = first; id < last; ++id) {
        tree_.roots_.push_back(id);
    }
}

std::pair<NodeId, NodeId> TreeBuilder::add_children(NodeId dir, std::span<const NewNode> entries) {
    if (dir >= tree_.nodes_.size()) {
        throw std::out_of_range("tree node ID is out of range");
    }
    if ((tree_.nodes_[dir].flags & kDir) == 0) {
        throw std::invalid_argument("children can only be added to a directory");
    }
    if (populated_[dir]) {
        throw AlreadyPopulated();
    }
    if (entries.size() >
        static_cast<std::size_t>(std::numeric_limits<std::uint32_t>::max() - tree_.nodes_.size())) {
        throw CapacityError();
    }
    populated_[dir] = true;
    const auto first = tree_.nodes_.size();
    // Let vector grow geometrically; reserving each small batch repeatedly copies its bits.
    for (const auto &entry : entries) {
        const auto [offset, length] = tree_.names_.push(entry.name);
        auto child = make_node(dir, entry.flags, offset, length);
        child.size = entry.size;
        child.alloc = entry.alloc;
        child.mtime = entry.mtime;
        child.btime = entry.btime;
        child.atime = entry.atime;
        child.ext_id = tree_.exts_.intern(entry.name, (entry.flags & kDir) != 0);
        if (entry.owner) {
            child.owner = tree_.owners_.intern(*entry.owner, {});
        }
        tree_.nodes_.push_back(child);
        tree_.counts_.push_back({});
        populated_.push_back(false);
    }
    const auto last = tree_.nodes_.size();
    tree_.nodes_[dir].first_child = first == last ? kNone : first;
    tree_.nodes_[dir].child_count = last - first;
    return {first, last};
}

void TreeBuilder::mark(NodeId id, std::uint16_t flags) {
    if (id >= tree_.nodes_.size()) {
        throw std::out_of_range("tree node ID is out of range");
    }
    tree_.nodes_[id].flags = static_cast<std::uint16_t>(tree_.nodes_[id].flags | flags);
}

void TreeBuilder::aggregate_partial() { aggregate(tree_.nodes_, tree_.counts_); }

Tree TreeBuilder::finish(ScanMeta meta) && {
    aggregate(tree_.nodes_, tree_.counts_);
    tree_.meta_ = std::move(meta);
    tree_.nodes_.shrink_last();
    tree_.counts_.shrink_last();
    return std::move(tree_);
}

} // namespace dafree
