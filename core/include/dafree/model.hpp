#pragma once

#include "dafree/error.hpp"
#include "dafree/scan_types.hpp"

#include <algorithm>
#include <compare>
#include <cstddef>
#include <cstdint>
#include <iterator>
#include <limits>
#include <memory>
#include <mutex>
#include <optional>
#include <shared_mutex>
#include <span>
#include <string>
#include <string_view>
#include <type_traits>
#include <unordered_map>
#include <utility>
#include <vector>

namespace dafree {

class FsBackend;
class TreeHandle;

using NodeId = std::uint32_t;
inline constexpr NodeId kRoot = 0;
inline constexpr NodeId kNone = 0xFFFF'FFFFu;

/// Flags that describe a scanned tree entry.
enum NodeFlags : std::uint16_t {
    kDir = 1u << 0,
    kSymlink = 1u << 1,
    kReparse = 1u << 2,
    kMountPoint = 1u << 3,
    kHardlinkDup = 1u << 4,
    kHidden = 1u << 5,
    kSystem = 1u << 6,
    kAccessDenied = 1u << 7,
    kPartial = 1u << 8,
    kSparse = 1u << 9,
    kCompressed = 1u << 10,
    kCloudPlaceholder = 1u << 11,
    kExcluded = 1u << 12,
    kError = 1u << 13,
    kAllocUnreliable = 1u << 14,
    kSynthetic = 1u << 15,
};

/// A compact node in a scan tree. Names are held in the tree's NameArena.
struct Node {
    NodeId parent = kNone;
    NodeId first_child = kNone;
    std::uint32_t child_count = 0;
    std::uint32_t name_off = 0;
    std::uint16_t name_len = 0;
    std::uint16_t flags = 0;
    std::uint32_t ext_id = 0;
    std::uint64_t size = 0;
    std::uint64_t alloc = 0;
    std::uint32_t mtime = 0, btime = 0, atime = 0;
    std::uint32_t owner = 0;
};
static_assert(sizeof(Node) == 56 && alignof(Node) == 8);
static_assert(std::is_trivially_copyable_v<Node>);

/// Descendant file and directory counts for a node.
struct Counts {
    std::uint32_t files = 0, dirs = 0;
};

/// Memory usage of tree-owned storage.
struct MemoryReport {
    std::size_t nodes = 0;
    std::size_t counts = 0;
    std::size_t names = 0;
    std::size_t interners = 0;
};

/// A segmented vector that preserves existing segments as it grows.
///
/// Segments contain at most 65,536 values. Appending never moves values from
/// earlier segments. The returned indices describe a contiguous logical range,
/// even when the range spans multiple segments.
template <class T> class SegVector {
  private:
    static constexpr std::uint32_t kSegmentSize = 65'536;
    static constexpr std::uint32_t kMaxSize = std::numeric_limits<std::uint32_t>::max() - 1;

    struct Segment {
        std::uint32_t begin;
        std::uint32_t capacity;
        std::unique_ptr<T[]> values;
    };

    template <bool IsConst> class Iterator {
      private:
        using Owner = std::conditional_t<IsConst, const SegVector, SegVector>;

      public:
        using iterator_category = std::random_access_iterator_tag;
        using iterator_concept = std::random_access_iterator_tag;
        using value_type = T;
        using difference_type = std::ptrdiff_t;
        using reference = std::conditional_t<IsConst, const T &, T &>;
        using pointer = std::conditional_t<IsConst, const T *, T *>;

        Iterator() = default;
        Iterator(Owner *owner, std::uint32_t index) : owner_(owner), index_(index) {}

        template <bool OtherConst>
            requires(IsConst && !OtherConst)
        Iterator(const Iterator<OtherConst> &other) : owner_(other.owner_), index_(other.index_) {}

        reference operator*() const { return (*owner_)[index_]; }
        pointer operator->() const { return &(**this); }
        reference operator[](difference_type offset) const { return *(*this + offset); }

        Iterator &operator++() {
            ++index_;
            return *this;
        }
        Iterator operator++(int) {
            auto previous = *this;
            ++*this;
            return previous;
        }
        Iterator &operator--() {
            --index_;
            return *this;
        }
        Iterator operator--(int) {
            auto previous = *this;
            --*this;
            return previous;
        }
        Iterator &operator+=(difference_type offset) {
            index_ = static_cast<std::uint32_t>(static_cast<difference_type>(index_) + offset);
            return *this;
        }
        Iterator &operator-=(difference_type offset) { return *this += -offset; }

        friend Iterator operator+(Iterator iterator, difference_type offset) {
            iterator += offset;
            return iterator;
        }
        friend Iterator operator+(difference_type offset, Iterator iterator) {
            iterator += offset;
            return iterator;
        }
        friend Iterator operator-(Iterator iterator, difference_type offset) {
            iterator -= offset;
            return iterator;
        }
        friend difference_type operator-(const Iterator &lhs, const Iterator &rhs) {
            return static_cast<difference_type>(lhs.index_) -
                   static_cast<difference_type>(rhs.index_);
        }
        friend bool operator==(const Iterator &lhs, const Iterator &rhs) {
            return lhs.owner_ == rhs.owner_ && lhs.index_ == rhs.index_;
        }
        friend auto operator<=>(const Iterator &lhs, const Iterator &rhs) {
            return lhs.index_ <=> rhs.index_;
        }

      private:
        template <bool> friend class Iterator;

        Owner *owner_ = nullptr;
        std::uint32_t index_ = 0;
    };

  public:
    using value_type = T;
    using size_type = std::uint32_t;
    using iterator = Iterator<false>;
    using const_iterator = Iterator<true>;
    using reverse_iterator = std::reverse_iterator<iterator>;
    using const_reverse_iterator = std::reverse_iterator<const_iterator>;

    /// Append one value and return its index. Throws CapacityError at the size limit.
    std::uint32_t push_back(const T &value) {
        if (size_ == kMaxSize) {
            throw CapacityError();
        }
        ensure_tail_capacity();
        const auto index = size_;
        auto &segment = segments_.back();
        segment.values[index - segment.begin] = value;
        ++size_;
        return index;
    }

    /// Append a span and return its contiguous logical half-open index range.
    std::pair<std::uint32_t, std::uint32_t> append(std::span<const T> values) {
        const auto count = values.size();
        if (count > static_cast<std::size_t>(kMaxSize - size_)) {
            throw CapacityError();
        }
        const auto first = size_;
        for (const auto &value : values) {
            push_back(value);
        }
        return {first, size_};
    }

    /// Return the value at an index without bounds checking.
    T &operator[](std::uint32_t index) {
        const auto segment = find_segment(index);
        return segments_[segment].values[index - segments_[segment].begin];
    }

    /// Return the value at an index without bounds checking.
    const T &operator[](std::uint32_t index) const {
        const auto segment = find_segment(index);
        return segments_[segment].values[index - segments_[segment].begin];
    }

    /// Return the number of stored values.
    [[nodiscard]] std::uint32_t size() const noexcept { return size_; }

    /// Return the bytes reserved by segment arrays.
    [[nodiscard]] std::size_t heap_bytes() const noexcept {
        std::size_t bytes = 0;
        for (const auto &segment : segments_) {
            bytes += static_cast<std::size_t>(segment.capacity) * sizeof(T);
        }
        return bytes;
    }

    /// Reallocate the final segment to exactly the number of values it holds.
    void shrink_last() {
        if (segments_.empty()) {
            return;
        }
        auto &segment = segments_.back();
        const auto used = size_ - segment.begin;
        if (used == segment.capacity) {
            return;
        }
        if (used == 0) {
            segments_.pop_back();
            return;
        }
        auto values = std::make_unique_for_overwrite<T[]>(used);
        for (std::uint32_t i = 0; i < used; ++i) {
            values[i] = std::move_if_noexcept(segment.values[i]);
        }
        segment.values = std::move(values);
        segment.capacity = used;
    }

    /// Return an iterator to the first value.
    iterator begin() noexcept { return {this, 0}; }
    /// Return an iterator past the final value.
    iterator end() noexcept { return {this, size_}; }
    /// Return a const iterator to the first value.
    const_iterator begin() const noexcept { return {this, 0}; }
    /// Return a const iterator past the final value.
    const_iterator end() const noexcept { return {this, size_}; }
    /// Return a const iterator to the first value.
    const_iterator cbegin() const noexcept { return begin(); }
    /// Return a const iterator past the final value.
    const_iterator cend() const noexcept { return end(); }
    /// Return a reverse iterator to the final value.
    reverse_iterator rbegin() noexcept { return reverse_iterator(end()); }
    /// Return a reverse iterator before the first value.
    reverse_iterator rend() noexcept { return reverse_iterator(begin()); }
    /// Return a const reverse iterator to the final value.
    const_reverse_iterator rbegin() const noexcept { return const_reverse_iterator(end()); }
    /// Return a const reverse iterator before the first value.
    const_reverse_iterator rend() const noexcept { return const_reverse_iterator(begin()); }

  private:
    void ensure_tail_capacity() {
        if (!segments_.empty()) {
            const auto &tail = segments_.back();
            if (size_ - tail.begin < tail.capacity) {
                return;
            }
        }
        segments_.push_back(
            {size_, kSegmentSize, std::make_unique_for_overwrite<T[]>(kSegmentSize)});
    }

    [[nodiscard]] std::size_t find_segment(std::uint32_t index) const {
        const auto expected = static_cast<std::size_t>(index / kSegmentSize);
        if (expected < segments_.size()) {
            const auto &segment = segments_[expected];
            if (index >= segment.begin && index - segment.begin < segment.capacity) {
                return expected;
            }
        }
        const auto it = std::upper_bound(
            segments_.begin(), segments_.end(), index,
            [](std::uint32_t value, const Segment &segment) { return value < segment.begin; });
        return static_cast<std::size_t>(std::distance(segments_.begin(), it) - 1);
    }

    std::vector<Segment> segments_;
    std::uint32_t size_ = 0;
};

/// Store native filename bytes in 1 MiB chunks without splitting a name.
class NameArena {
  public:
    /// Append bytes and return their 32-bit arena offset and 16-bit byte length.
    std::pair<std::uint32_t, std::uint16_t> push(std::string_view native_bytes);
    /// Return a view of bytes previously stored at the given offset and length.
    [[nodiscard]] std::string_view get(std::uint32_t offset, std::uint16_t length) const;
    /// Return the bytes reserved by arena chunks.
    [[nodiscard]] std::size_t heap_bytes() const noexcept;

  private:
    struct Chunk {
        std::unique_ptr<char[]> data;
        std::size_t used = 0;
    };

    std::vector<Chunk> chunks_;
};

/// Intern lowercase file extensions; ID zero represents no extension.
class ExtInterner {
  public:
    ExtInterner();

    /// Return the ID for a filename's extension, or zero for directories and invalid extensions.
    std::uint32_t intern(std::string_view filename, bool is_directory = false);
    /// Return the extension for an ID; ID zero returns an empty view.
    [[nodiscard]] std::string_view get(std::uint32_t id) const;
    /// Return a lower-bound estimate of extension storage bytes.
    [[nodiscard]] std::size_t heap_bytes() const noexcept;

  private:
    std::vector<std::string> extensions_;
    std::unordered_map<std::string, std::uint32_t> ids_;
};

/// Identify an owner without conflating POSIX, Windows, and remote key spaces.
struct OwnerKey {
    enum class Kind : std::uint8_t { PosixUid, WindowsSid, Remote };

    Kind kind = Kind::PosixUid;
    std::uint32_t uid = 0;
    std::string value;

    /// Build a POSIX UID owner key.
    static OwnerKey posix_uid(std::uint32_t uid);
    /// Build a Windows owner key from the SID's binary bytes.
    static OwnerKey windows_sid(std::string_view sid_bytes);
    /// Build a remote owner key from its backend-provided string.
    static OwnerKey remote(std::string_view remote_key);

    /// Compare the identity kind and its corresponding value.
    bool operator==(const OwnerKey &) const = default;
};

/// Intern owner identities and keep one display name for each identity.
class OwnerTable {
  public:
    OwnerTable();

    /// Return a stable identity ID; fill an unresolved display name when one becomes available.
    std::uint32_t intern(const OwnerKey &key, std::string_view display);
    /// Return the display name for an ID; ID zero returns an empty view.
    [[nodiscard]] std::string_view get(std::uint32_t id) const;
    /// Return a lower-bound estimate of owner storage bytes.
    [[nodiscard]] std::size_t heap_bytes() const noexcept;

    /// Return an identity by stable owner ID, or nullptr for the absent owner.
    [[nodiscard]] const OwnerKey *key(std::uint32_t id) const;

  private:
    struct Hash {
        [[nodiscard]] std::size_t operator()(const OwnerKey &key) const noexcept;
    };

    std::vector<std::string> displays_;
    std::vector<OwnerKey> keys_;
    std::unordered_map<OwnerKey, std::uint32_t, Hash> ids_;
};

/// Compute directory sizes and descendant counts in one reverse node pass.
void aggregate(SegVector<Node> &nodes, SegVector<Counts> &counts);

/// Access and update a built scan tree.
class Tree {
  public:
    /// Return the number of nodes, including the synthetic root.
    [[nodiscard]] std::uint32_t size() const noexcept;
    /// Return a node by ID.
    [[nodiscard]] const Node &node(NodeId id) const;
    /// Return the descendant counts for a node.
    [[nodiscard]] Counts counts(NodeId id) const;
    /// Return a node's native name bytes. Root nodes contain their full path.
    [[nodiscard]] std::string_view name_bytes(NodeId id) const;
    /// Return the node extension when it has one.
    [[nodiscard]] std::optional<std::string_view> ext(NodeId id) const;
    /// Return a node's resolved owner display name when available.
    [[nodiscard]] std::optional<std::string_view> owner_name(NodeId id) const;
    /// Return the contiguous half-open child ID range.
    [[nodiscard]] std::pair<NodeId, NodeId> children(NodeId id) const;
    /// Return the parent ID, or no value for the synthetic root.
    [[nodiscard]] std::optional<NodeId> parent(NodeId id) const;
    /// Reconstruct the node's native path in O(depth).
    [[nodiscard]] std::string path_bytes(NodeId id) const;
    /// Return the node depth below its scan root.
    [[nodiscard]] std::uint16_t depth(NodeId id) const;
    /// Find a path after separator normalization and platform case handling.
    [[nodiscard]] std::optional<NodeId> find_path(std::string_view native_path) const;
    /// Return the root node IDs.
    [[nodiscard]] std::span<const NodeId> roots() const;
    /// Report the bytes reserved by tree-owned storage.
    [[nodiscard]] MemoryReport memory_usage() const;
    /// Intern and assign an owner identity.
    void set_owner(NodeId id, OwnerKey key, std::string_view display);
    /// Exclude a node and incrementally update totals.
    void mark_deleted(NodeId id);
    /// Replace a subtree while preserving the tree invariants.
    void replace_subtree(NodeId at, const Tree &fresh, NodeId fresh_root);
    /// Return scan metadata associated with the tree.
    [[nodiscard]] const ScanMeta &meta() const noexcept;

  private:
    friend class TreeBuilder;
    friend class ScanEngine;
    friend void resolve_owners(TreeHandle &, std::span<const NodeId>, FsBackend &);
    SegVector<Node> nodes_;
    SegVector<Counts> counts_;
    NameArena names_;
    ExtInterner exts_;
    OwnerTable owners_;
    std::vector<NodeId> roots_;
    std::vector<std::string> root_paths_;
    ScanMeta meta_;
};

/// Build a tree while preserving parent-before-child IDs and contiguous children.
class TreeBuilder {
  public:
    /// Create the synthetic root and a root node for each full native root path.
    explicit TreeBuilder(std::vector<std::string> root_paths);

    /// A node specification appended by add_children.
    struct NewNode {
        std::string_view name;
        std::uint16_t flags;
        std::uint64_t size, alloc;
        std::uint32_t mtime, btime, atime;
        std::optional<OwnerKey> owner;
    };

    /// Append all entries contiguously; a directory may be populated only once.
    std::pair<NodeId, NodeId> add_children(NodeId dir, std::span<const NewNode> entries);
    /// Add flags to a node.
    void mark(NodeId id, std::uint16_t flags);
    /// Recompute totals for a partially built tree.
    void aggregate_partial();
    /// Finalize the tree and release unused tail storage.
    Tree finish(ScanMeta meta) &&;

  private:
    friend class ScanEngine;
    Tree tree_;
    std::vector<bool> populated_;
};

/// Shared tree ownership with reader locking for API consumers and later mutations.
class TreeHandle {
  public:
    /// Wrap an engine-owned tree allocated through a mutable backing object.
    explicit TreeHandle(std::shared_ptr<const Tree> tree) : tree_(std::move(tree)) {
        if (!tree_)
            throw std::invalid_argument("tree handle requires a tree");
    }
    /// Read a coherent tree snapshot; copy mutable values before returning them.
    template <class Function> auto read(Function &&function) const {
        std::shared_lock lock(mutex_);
        return std::forward<Function>(function)(*tree_);
    }

  private:
    friend void resolve_owners(TreeHandle &, std::span<const NodeId>, FsBackend &);
    std::shared_ptr<const Tree> tree_;
    mutable std::shared_mutex mutex_;
    std::mutex owner_resolution_mutex_;
};

} // namespace dafree
