#include "dafree/scan.hpp"
#include "view_internal.hpp"

#include <algorithm>
#include <array>
#include <limits>
#include <utility>

namespace dafree::detail {

struct VisibleRows::Storage {
    static constexpr std::size_t capacity = 512;
    struct Block {
        NodeId id;
        std::uint32_t priority, total = 0;
        Block *left = nullptr, *right = nullptr, *parent = nullptr;
        Block *previous = nullptr, *next = nullptr;
        std::vector<RowRef> rows;
    };
    Block *root = nullptr;
    std::vector<std::unique_ptr<Block>> blocks;
    std::vector<NodeId> free_ids, location;
    std::uint32_t random = 0x7F4A7C15;

    explicit Storage(std::uint32_t nodes) : location(nodes, kNone) {}
    static std::uint32_t count(const Block *node) { return node ? node->total : 0; }
    static void update(Block *node) {
        node->total =
            count(node->left) + count(node->right) + static_cast<std::uint32_t>(node->rows.size());
        if (node->left)
            node->left->parent = node;
        if (node->right)
            node->right->parent = node;
    }
    static void update_up(Block *node) {
        while (node) {
            update(node);
            node = node->parent;
        }
    }
    static Block *first(Block *node) {
        if (node)
            while (node->left)
                node = node->left;
        return node;
    }
    static Block *last(Block *node) {
        if (node)
            while (node->right)
                node = node->right;
        return node;
    }
    static void join_links(Block *left, Block *right) {
        if (left)
            left->next = right;
        if (right)
            right->previous = left;
    }
    Block *make(std::span<const RowRef> rows) {
        NodeId id;
        if (free_ids.empty()) {
            id = static_cast<NodeId>(blocks.size());
            blocks.push_back(nullptr);
        } else {
            id = free_ids.back();
            free_ids.pop_back();
        }
        random ^= random << 13;
        random ^= random >> 17;
        random ^= random << 5;
        auto block = std::make_unique<Block>();
        block->id = id;
        block->priority = random;
        block->rows.reserve(capacity);
        block->rows.assign(rows.begin(), rows.end());
        for (const auto &row : rows)
            location.at(row.id) = id;
        update(block.get());
        blocks[id] = std::move(block);
        return blocks[id].get();
    }
    static Block *merge(Block *left, Block *right) {
        if (!left || !right) {
            auto *result = left ? left : right;
            if (result)
                result->parent = nullptr;
            return result;
        }
        Block *result;
        if (left->priority < right->priority) {
            left->right = merge(left->right, right);
            result = left;
        } else {
            right->left = merge(left, right->left);
            result = right;
        }
        update(result);
        result->parent = nullptr;
        return result;
    }
    std::pair<Block *, Block *> split(Block *node, std::uint32_t at) {
        if (!node)
            return {nullptr, nullptr};
        const auto before = count(node->left);
        const auto after = before + static_cast<std::uint32_t>(node->rows.size());
        if (at < before) {
            auto [left, remainder] = split(node->left, at);
            node->left = remainder;
            update(node);
            node->parent = nullptr;
            return {left, node};
        }
        if (at > after) {
            auto [remainder, right] = split(node->right, at - after);
            node->right = remainder;
            update(node);
            node->parent = nullptr;
            return {node, right};
        }
        if (at == before) {
            auto *left = node->left;
            node->left = nullptr;
            update(node);
            node->parent = nullptr;
            if (left)
                left->parent = nullptr;
            return {left, node};
        }
        if (at == after) {
            auto *right = node->right;
            node->right = nullptr;
            update(node);
            node->parent = nullptr;
            if (right)
                right->parent = nullptr;
            return {node, right};
        }
        const auto offset = at - before;
        auto *suffix = make(std::span(node->rows).subspan(offset));
        node->rows.resize(offset);
        join_links(suffix, node->next);
        join_links(node, suffix);
        auto *right = node->right;
        node->right = nullptr;
        update(node);
        node->parent = nullptr;
        return {node, merge(suffix, right)};
    }
    std::pair<Block *, std::uint32_t> find(std::uint32_t at) const {
        auto *node = root;
        while (node) {
            const auto before = count(node->left);
            if (at < before) {
                node = node->left;
            } else if (at < before + node->rows.size()) {
                return {node, at - before};
            } else {
                at -= before + static_cast<std::uint32_t>(node->rows.size());
                node = node->right;
            }
        }
        throw std::out_of_range("visible row index is out of range");
    }
};

VisibleRows::VisibleRows(std::uint32_t nodes) : storage_(std::make_unique<Storage>(nodes)) {}
VisibleRows::~VisibleRows() = default;
VisibleRows::VisibleRows(VisibleRows &&) noexcept = default;
VisibleRows &VisibleRows::operator=(VisibleRows &&) noexcept = default;
std::uint32_t VisibleRows::size() const { return Storage::count(storage_->root); }

std::optional<std::uint32_t> VisibleRows::index_of(NodeId id) const {
    if (id >= storage_->location.size() || storage_->location[id] == kNone)
        return std::nullopt;
    auto *block = storage_->blocks[storage_->location[id]].get();
    const auto found = std::find_if(block->rows.begin(), block->rows.end(),
                                    [id](const RowRef &row) { return row.id == id; });
    if (found == block->rows.end())
        throw std::logic_error("visible row location is inconsistent");
    auto index =
        Storage::count(block->left) + static_cast<std::uint32_t>(found - block->rows.begin());
    for (auto *parent = block->parent; parent; block = parent, parent = parent->parent)
        if (parent->right == block)
            index += Storage::count(parent->left) + static_cast<std::uint32_t>(parent->rows.size());
    return index;
}

RowRef VisibleRows::at(std::uint32_t index) const {
    const auto [block, offset] = storage_->find(index);
    return block->rows[offset];
}

void VisibleRows::visit(std::uint32_t start, std::uint32_t count,
                        const std::function<bool(const RowRef &)> &function) const {
    if (start >= size() || count == 0)
        return;
    auto [block, offset] = storage_->find(start);
    auto remaining = std::min(count, size() - start);
    while (remaining != 0) {
        const auto available = static_cast<std::uint32_t>(block->rows.size()) - offset;
        const auto take = std::min(remaining, available);
        for (std::uint32_t index = 0; index < take; ++index)
            if (!function(block->rows[offset + index]))
                return;
        remaining -= take;
        block = block->next;
        offset = 0;
    }
}

void VisibleRows::insert(std::uint32_t at, std::span<const RowRef> rows) {
    if (at > size())
        throw std::out_of_range("visible insertion index is out of range");
    if (rows.empty())
        return;
    auto &s = *storage_;
    Storage::Block *existing = nullptr;
    std::uint32_t offset = 0;
    if (at < size())
        std::tie(existing, offset) = s.find(at);
    else if (s.root) {
        existing = Storage::last(s.root);
        offset = static_cast<std::uint32_t>(existing->rows.size());
    }
    if (existing && existing->rows.size() + rows.size() <= Storage::capacity) {
        existing->rows.insert(existing->rows.begin() + offset, rows.begin(), rows.end());
        for (const auto &row : rows)
            s.location.at(row.id) = existing->id;
        Storage::update_up(existing);
        return;
    }
    auto [left, right] = s.split(s.root, at);
    auto *previous = Storage::last(left);
    auto *right_first = Storage::first(right);
    const auto prefix =
        previous ? std::min(rows.size(), Storage::capacity - previous->rows.size()) : 0;
    if (prefix != 0) {
        previous->rows.insert(previous->rows.end(), rows.begin(),
                              rows.begin() + static_cast<std::ptrdiff_t>(prefix));
        for (const auto &row : rows.first(prefix))
            s.location.at(row.id) = previous->id;
        Storage::update_up(previous);
        rows = rows.subspan(prefix);
    }
    Storage::Block *middle = nullptr;
    while (!rows.empty()) {
        const auto take = std::min(rows.size(), Storage::capacity);
        auto *block = s.make(rows.first(take));
        Storage::join_links(previous, block);
        previous = block;
        middle = Storage::merge(middle, block);
        rows = rows.subspan(take);
    }
    Storage::join_links(previous, right_first);
    s.root = Storage::merge(Storage::merge(left, middle), right);
}

void VisibleRows::erase(std::uint32_t at, std::uint32_t count) {
    if (at > size() || count > size() - at)
        throw std::out_of_range("visible erase range is out of range");
    if (count == 0)
        return;
    auto &s = *storage_;
    auto [left, remainder] = s.split(s.root, at);
    auto [removed, right] = s.split(remainder, count);
    auto *left_last = Storage::last(left);
    auto *right_first = Storage::first(right);
    auto *cursor = Storage::first(removed);
    Storage::join_links(left_last, right_first);
    while (cursor != right_first && cursor) {
        auto *next = cursor->next;
        const auto id = cursor->id;
        for (const auto &row : cursor->rows)
            s.location[row.id] = kNone;
        s.blocks[id].reset();
        s.free_ids.push_back(id);
        cursor = next;
    }
    s.root = Storage::merge(left, right);
}

} // namespace dafree::detail

namespace dafree {

struct TreeView::Impl {
    struct SortEntry {
        std::uint64_t key;
        std::vector<NodeId> ids;
    };
    std::shared_ptr<TreeHandle> handle;
    std::shared_ptr<FsBackend> backend;
    mutable std::mutex mutex;
    ViewOptions options;
    detail::Visibility visibility;
    std::vector<bool> expanded;
    detail::VisibleRows visible;
    std::list<SortEntry> cache;
    std::unordered_map<std::uint64_t, std::list<SortEntry>::iterator> cached;

    Impl(std::shared_ptr<TreeHandle> tree, std::shared_ptr<FsBackend> context, ViewOptions opts)
        : handle(std::move(tree)), backend(std::move(context)), visible(0) {
        expanded.resize(node_count());
        handle->read([&](const Tree &source) {
            for (const auto id : source.roots())
                expanded[id] = (source.node(id).flags & kDir) != 0;
        });
        set(std::move(opts));
    }
    std::uint32_t node_count() const {
        if (!handle)
            throw std::invalid_argument("view requires a tree handle");
        return handle->read([](const Tree &tree) { return tree.size(); });
    }
    bool eligible(const Tree &tree, NodeId id, const ViewOptions &opts,
                  const detail::Visibility &filter) const {
        const auto &node = tree.node(id);
        return (node.flags & kExcluded) == 0 && (opts.show_files || (node.flags & kDir) != 0) &&
               (!filter.filtered || filter.eligible.get(id));
    }
    bool children(const Tree &tree, NodeId id) const {
        if ((tree.node(id).flags & kDir) == 0)
            return false;
        if (visibility.filtered)
            return visibility.has_children.get(id);
        const auto counts = tree.counts(id);
        return counts.dirs != 0 || (options.show_files && counts.files != 0);
    }
    void resolve(std::span<const NodeId> ids, bool required = false) {
        const bool missing = handle->read([&](const Tree &tree) {
            return std::any_of(ids.begin(), ids.end(), [&](NodeId id) {
                const auto name = tree.owner_name(id);
                return tree.node(id).owner != 0 && (!name || name->empty());
            });
        });
        if (!missing)
            return;
        if (backend) {
            resolve_owners(*handle, ids, *backend);
            for (auto entry = cache.begin(); entry != cache.end();) {
                if (((entry->key >> 1) & 0x7Fu) == static_cast<unsigned>(SortKey::Owner)) {
                    cached.erase(entry->key);
                    entry = cache.erase(entry);
                } else {
                    ++entry;
                }
            }
        } else if (required) {
            throw std::invalid_argument("lazy owner lookup requires a tree handle and backend");
        }
    }
    const std::vector<NodeId> &sorted(const Tree &tree, NodeId parent, const ViewOptions &opts,
                                      const detail::Visibility &filter) {
        const auto key = (static_cast<std::uint64_t>(parent) << 8) |
                         (static_cast<std::uint64_t>(opts.sort) << 1) |
                         static_cast<unsigned>(opts.descending);
        if (const auto found = cached.find(key); found != cached.end()) {
            cache.splice(cache.begin(), cache, found->second);
            return found->second->ids;
        }
        std::vector<NodeId> ids;
        const auto [begin, end] = tree.children(parent);
        const auto counts = tree.counts(parent);
        const auto possible =
            opts.show_files ? std::uint64_t{counts.files} + counts.dirs : counts.dirs;
        const bool empty = filter.filtered ? !filter.has_children.get(parent) : possible == 0;
        if (!empty) {
            ids.reserve(filter.filtered ? std::min(end - begin, 1024u)
                                        : static_cast<std::size_t>(
                                              std::min<std::uint64_t>(end - begin, possible)));
            for (auto id = begin; id < end; ++id)
                if (eligible(tree, id, opts, filter))
                    ids.push_back(id);
        }
        detail::sort_children(tree, ids, opts);
        cache.push_front({key, std::move(ids)});
        cached.emplace(key, cache.begin());
        if (cache.size() > 256) {
            cached.erase(cache.back().key);
            cache.pop_back();
        }
        return cache.front().ids;
    }
    void clear_cache() {
        cached.clear();
        cache.clear();
    }

    void resolve_sort_owners(NodeId parent, const ViewOptions &opts,
                             const detail::Visibility &filter) {
        if (opts.sort != SortKey::Owner || !backend)
            return;
        std::vector<NodeId> ids;
        handle->read([&](const Tree &tree) {
            std::vector<NodeId> pending{parent};
            while (!pending.empty()) {
                const auto directory = pending.back();
                pending.pop_back();
                const auto [begin, end] = tree.children(directory);
                for (auto id = begin; id < end; ++id) {
                    if (!eligible(tree, id, opts, filter))
                        continue;
                    ids.push_back(id);
                    if ((tree.node(id).flags & kDir) != 0 && expanded[id])
                        pending.push_back(id);
                }
            }
        });
        resolve(ids);
    }
    std::vector<detail::RowRef> descendants(const Tree &tree, NodeId parent, std::uint32_t depth,
                                            const ViewOptions &opts,
                                            const detail::Visibility &filter) {
        std::vector<detail::RowRef> result;
        struct Frame {
            std::vector<NodeId> ids;
            std::size_t next;
            std::uint32_t depth;
        };
        // Each active sibling list is copied once: LRU eviction cannot invalidate traversal frames.
        const auto &first = sorted(tree, parent, opts, filter);
        std::vector<Frame> stack;
        stack.push_back({first, 0, depth});
        while (!stack.empty()) {
            auto &frame = stack.back();
            if (frame.next == frame.ids.size()) {
                stack.pop_back();
                continue;
            }
            const auto id = frame.ids[frame.next++];
            const auto row_depth = frame.depth;
            result.push_back({id, row_depth});
            if ((tree.node(id).flags & kDir) != 0 && expanded[id]) {
                const auto &ids = sorted(tree, id, opts, filter);
                stack.push_back({ids, 0, row_depth + 1});
            }
        }
        return result;
    }
    void set(ViewOptions opts) {
        if (static_cast<unsigned>(opts.sort) > static_cast<unsigned>(SortKey::Ext))
            throw std::invalid_argument("unknown sort key");
        const bool new_filter = opts.filter != options.filter;
        const bool new_files = opts.show_files != options.show_files;
        detail::Visibility next_filter;
        if (new_filter)
            next_filter = detail::filter_visibility(*handle, opts.filter, opts.show_files,
                                                    [&](auto ids) { resolve(ids); });
        else if (new_files && visibility.filtered) {
            next_filter = visibility;
            std::fill(next_filter.has_children.words.begin(), next_filter.has_children.words.end(),
                      0);
            handle->read([&](const Tree &tree) {
                for (NodeId id = 1; id < tree.size(); ++id) {
                    const auto &node = tree.node(id);
                    if (next_filter.eligible.get(id) &&
                        (opts.show_files || (node.flags & kDir) != 0))
                        next_filter.has_children.set(node.parent);
                }
            });
        }
        const auto &filter =
            new_filter || (new_files && visibility.filtered) ? next_filter : visibility;
        resolve_sort_owners(kRoot, opts, filter);
        if (new_filter || new_files || opts.dirs_first != options.dirs_first)
            clear_cache();
        auto next_rows = handle->read(
            [&](const Tree &tree) { return descendants(tree, kRoot, 0, opts, filter); });
        detail::VisibleRows next(node_count());
        next.insert(0, next_rows);
        options = std::move(opts);
        if (&filter == &next_filter)
            visibility = std::move(next_filter);
        visible = std::move(next);
    }
    std::uint32_t expand(NodeId id) {
        const auto index = visible.index_of(id);
        const bool directory =
            handle->read([&](const Tree &tree) { return (tree.node(id).flags & kDir) != 0; });
        if (id == kRoot || !directory || expanded[id])
            return 0;
        if (!index) {
            expanded[id] = true;
            return 0;
        }
        resolve_sort_owners(id, options, visibility);
        const auto depth = visible.at(*index).depth + 1;
        auto inserted = handle->read(
            [&](const Tree &tree) { return descendants(tree, id, depth, options, visibility); });
        visible.insert(*index + 1, inserted);
        expanded[id] = true;
        return static_cast<std::uint32_t>(inserted.size());
    }
    std::uint32_t collapse_count(NodeId id) const {
        if (id >= expanded.size())
            throw std::out_of_range("tree node ID is out of range");
        const auto index = visible.index_of(id);
        if (id == kRoot || !expanded[id] || !index)
            return 0;
        const auto depth = visible.at(*index).depth;
        std::uint32_t count = 0;
        visible.visit(*index + 1, visible.size() - *index - 1, [&](const detail::RowRef &row) {
            if (row.depth <= depth)
                return false;
            ++count;
            return true;
        });
        return count;
    }
};

TreeView::TreeView(std::shared_ptr<const Tree> tree, ViewOptions options)
    : TreeView(std::make_shared<TreeHandle>(std::move(tree)), nullptr, std::move(options)) {}
TreeView::TreeView(std::shared_ptr<TreeHandle> tree, std::shared_ptr<FsBackend> backend,
                   ViewOptions options)
    : impl_(std::make_unique<Impl>(std::move(tree), std::move(backend), std::move(options))) {}
TreeView::~TreeView() = default;

std::uint32_t TreeView::row_count() const {
    std::lock_guard lock(impl_->mutex);
    return impl_->visible.size();
}
ViewOptions TreeView::options() const {
    std::lock_guard lock(impl_->mutex);
    return impl_->options;
}
std::optional<std::uint32_t> TreeView::index_of(NodeId id) const {
    std::lock_guard lock(impl_->mutex);
    return impl_->visible.index_of(id);
}
void TreeView::set_options(ViewOptions options) {
    std::lock_guard lock(impl_->mutex);
    impl_->set(std::move(options));
}
std::uint32_t TreeView::expand(NodeId id) {
    std::lock_guard lock(impl_->mutex);
    return impl_->expand(id);
}

std::uint32_t TreeView::expansion_count(NodeId id) const {
    std::lock_guard lock(impl_->mutex);
    return impl_->handle->read([&](const Tree &tree) {
        const auto &node = tree.node(id); // Validate even when the node is hidden.
        if (id == kRoot || (node.flags & kDir) == 0 || impl_->expanded[id] ||
            !impl_->visible.index_of(id))
            return std::uint32_t{0};
        std::uint32_t count = 0;
        std::vector<NodeId> pending{id};
        while (!pending.empty()) {
            const auto parent = pending.back();
            pending.pop_back();
            const auto [begin, end] = tree.children(parent);
            for (auto child = begin; child < end; ++child) {
                if (!impl_->eligible(tree, child, impl_->options, impl_->visibility))
                    continue;
                ++count;
                if ((tree.node(child).flags & kDir) != 0 && impl_->expanded[child])
                    pending.push_back(child);
            }
        }
        return count;
    });
}

std::uint32_t TreeView::collapse_count(NodeId id) const {
    std::lock_guard lock(impl_->mutex);
    return impl_->collapse_count(id);
}

void TreeView::expand_children(NodeId id) {
    std::lock_guard lock(impl_->mutex);
    const auto children = impl_->handle->read([&](const Tree &tree) {
        std::vector<NodeId> result;
        if ((tree.node(id).flags & kDir) == 0 || id == kRoot)
            return result;
        const auto [begin, end] = tree.children(id);
        for (auto child = begin; child < end; ++child)
            if ((tree.node(child).flags & kDir) != 0 &&
                impl_->eligible(tree, child, impl_->options, impl_->visibility))
                result.push_back(child);
        return result;
    });
    impl_->expand(id);
    for (const auto child : children)
        impl_->expand(child);
}

std::uint32_t TreeView::collapse(NodeId id) {
    std::lock_guard lock(impl_->mutex);
    const auto removed = impl_->collapse_count(id);
    if (id == kRoot || !impl_->expanded[id])
        return 0;
    impl_->expanded[id] = false;
    const auto index = impl_->visible.index_of(id);
    if (!index)
        return 0;
    impl_->visible.erase(*index + 1, removed);
    return removed;
}

std::uint32_t TreeView::expand_to(NodeId id) {
    std::lock_guard lock(impl_->mutex);
    const auto ancestors = impl_->handle->read([&](const Tree &tree) {
        if (id == kRoot || !impl_->eligible(tree, id, impl_->options, impl_->visibility))
            throw std::invalid_argument("node is hidden by the view options");
        std::vector<NodeId> result;
        for (auto parent = tree.node(id).parent; parent != kRoot && parent != kNone;
             parent = tree.node(parent).parent)
            result.push_back(parent);
        return result;
    });
    for (auto cursor = ancestors.rbegin(); cursor != ancestors.rend(); ++cursor)
        impl_->expand(*cursor);
    const auto index = impl_->visible.index_of(id);
    if (!index)
        throw std::invalid_argument("node is hidden by an excluded ancestor");
    return *index;
}

std::vector<Row> TreeView::rows(std::uint32_t start, std::uint32_t count) const {
    std::lock_guard lock(impl_->mutex);
    if (start >= impl_->visible.size() || count == 0)
        return {};
    count = std::min({count, 500u, impl_->visible.size() - start});
    if (impl_->options.resolve_owner) {
        std::array<NodeId, 500> ids{};
        std::size_t used = 0;
        impl_->visible.visit(start, count, [&](const detail::RowRef &row) {
            ids[used++] = row.id;
            return true;
        });
        impl_->resolve(std::span(ids).first(used), true);
    }
    return impl_->handle->read([&](const Tree &tree) {
        std::vector<Row> result;
        result.reserve(count);
        impl_->visible.visit(start, count, [&](const detail::RowRef &ref) {
            const auto &node = tree.node(ref.id);
            const auto counts = tree.counts(ref.id);
            const auto parent_size = node.parent != kNone ? tree.node(node.parent).size : 0;
            const auto copy =
                [](std::optional<std::string_view> value) -> std::optional<std::string> {
                return value && !value->empty() ? std::optional(std::string(*value)) : std::nullopt;
            };
            const bool has_children = impl_->children(tree, ref.id);
            result.push_back(
                {ref.id, static_cast<std::uint16_t>(std::min(ref.depth, std::uint32_t{65535})),
                 has_children, has_children && impl_->expanded[ref.id],
                 std::string(tree.name_bytes(ref.id)), node.size, node.alloc,
                 parent_size != 0 ? static_cast<float>(static_cast<double>(node.size) /
                                                       static_cast<double>(parent_size))
                                  : 0.0f,
                 counts.files, counts.dirs, node.mtime, copy(tree.owner_name(ref.id)),
                 copy(tree.ext(ref.id)), node.flags,
                 static_cast<std::uint8_t>(ExtCategory::Other)});
            return true;
        });
        return result;
    });
}

} // namespace dafree
