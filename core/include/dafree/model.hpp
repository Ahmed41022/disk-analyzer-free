#pragma once

#include "dafree/detail/tree_mutex.hpp"
#include "dafree/error.hpp"
#include "dafree/scan_types.hpp"

#include <algorithm>
#include <compare>
#include <cstddef>
#include <cstdint>
#include <iosfwd>
#include <iterator>
#include <limits>
#include <memory>
#include <mutex>
#include <optional>
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
class MftIndex;
struct JsonOptions;
struct CsvOptions;

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
// Literal size/alignment pin the external Node layout contract.
// NOLINTNEXTLINE(cppcoreguidelines-avoid-magic-numbers)
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
        // Heap-sized stable arena segments require owning dynamic arrays.
        // NOLINTNEXTLINE(cppcoreguidelines-avoid-c-arrays,modernize-avoid-c-arrays)
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

        auto operator*() const -> reference { return (*owner_)[index_]; }
        auto operator->() const -> pointer { return &(**this); }
        auto operator[](difference_type offset) const -> reference { return *(*this + offset); }

        auto operator++() -> Iterator & {
            ++index_;
            return *this;
        }
        // C++20 iterator concepts require the exact Iterator postfix return type.
        // NOLINTNEXTLINE(cert-dcl21-cpp)
        auto operator++(int) -> Iterator {
            auto previous = *this;
            ++*this;
            return previous;
        }
        auto operator--() -> Iterator & {
            --index_;
            return *this;
        }
        // C++20 iterator concepts require the exact Iterator postfix return type.
        // NOLINTNEXTLINE(cert-dcl21-cpp)
        auto operator--(int) -> Iterator {
            auto previous = *this;
            --*this;
            return previous;
        }
        auto operator+=(difference_type offset) -> Iterator & {
            index_ = static_cast<std::uint32_t>(static_cast<difference_type>(index_) + offset);
            return *this;
        }
        auto operator-=(difference_type offset) -> Iterator & { return *this += -offset; }

        friend auto operator+(Iterator iterator, difference_type offset) -> Iterator {
            iterator += offset;
            return iterator;
        }
        friend auto operator+(difference_type offset, Iterator iterator) -> Iterator {
            iterator += offset;
            return iterator;
        }
        friend auto operator-(Iterator iterator, difference_type offset) -> Iterator {
            iterator -= offset;
            return iterator;
        }
        friend auto operator-(const Iterator &lhs, const Iterator &rhs) -> difference_type {
            return static_cast<difference_type>(lhs.index_) -
                   static_cast<difference_type>(rhs.index_);
        }
        friend auto operator==(const Iterator &lhs, const Iterator &rhs) -> bool {
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
    auto push_back(const T &value) -> std::uint32_t {
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
    auto append(std::span<const T> values) -> std::pair<std::uint32_t, std::uint32_t> {
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
    auto operator[](std::uint32_t index) -> T & {
        const auto segment = find_segment(index);
        return segments_[segment].values[index - segments_[segment].begin];
    }

    /// Return the value at an index without bounds checking.
    auto operator[](std::uint32_t index) const -> const T & {
        const auto segment = find_segment(index);
        return segments_[segment].values[index - segments_[segment].begin];
    }

    /// Return the number of stored values.
    [[nodiscard]] auto size() const noexcept -> std::uint32_t { return size_; }

    /// Return the bytes reserved by segment arrays.
    [[nodiscard]] auto heap_bytes() const noexcept -> std::size_t {
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
        // Heap-sized stable arena segments require owning dynamic arrays.
        // NOLINTNEXTLINE(cppcoreguidelines-avoid-c-arrays,modernize-avoid-c-arrays)
        auto values = std::make_unique_for_overwrite<T[]>(used);
        for (std::uint32_t i = 0; i < used; ++i) {
            values[i] = std::move_if_noexcept(segment.values[i]);
        }
        segment.values = std::move(values);
        segment.capacity = used;
    }

    /// Return an iterator to the first value.
    auto begin() noexcept -> iterator { return {this, 0}; }
    /// Return an iterator past the final value.
    auto end() noexcept -> iterator { return {this, size_}; }
    /// Return a const iterator to the first value.
    [[nodiscard]] auto begin() const noexcept -> const_iterator { return {this, 0}; }
    /// Return a const iterator past the final value.
    [[nodiscard]] auto end() const noexcept -> const_iterator { return {this, size_}; }
    /// Return a const iterator to the first value.
    [[nodiscard]] auto cbegin() const noexcept -> const_iterator { return begin(); }
    /// Return a const iterator past the final value.
    [[nodiscard]] auto cend() const noexcept -> const_iterator { return end(); }
    /// Return a reverse iterator to the final value.
    auto rbegin() noexcept -> reverse_iterator { return reverse_iterator(end()); }
    /// Return a reverse iterator before the first value.
    auto rend() noexcept -> reverse_iterator { return reverse_iterator(begin()); }
    /// Return a const reverse iterator to the final value.
    [[nodiscard]] auto rbegin() const noexcept -> const_reverse_iterator {
        return const_reverse_iterator(end());
    }
    /// Return a const reverse iterator before the first value.
    [[nodiscard]] auto rend() const noexcept -> const_reverse_iterator {
        return const_reverse_iterator(begin());
    }

  private:
    void ensure_tail_capacity() {
        if (!segments_.empty()) {
            const auto &tail = segments_.back();
            if (size_ - tail.begin < tail.capacity) {
                return;
            }
        }
        segments_.push_back(
            // Heap-sized stable arena segments require owning dynamic arrays.
            // NOLINTNEXTLINE(cppcoreguidelines-avoid-c-arrays,modernize-avoid-c-arrays)
            {size_, kSegmentSize, std::make_unique_for_overwrite<T[]>(kSegmentSize)});
    }

    [[nodiscard]] auto find_segment(std::uint32_t index) const -> std::size_t {
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
    auto push(std::string_view native_bytes) -> std::pair<std::uint32_t, std::uint16_t>;
    /// Return a view of bytes previously stored at the given offset and length.
    [[nodiscard]] auto get(std::uint32_t offset, std::uint16_t length) const -> std::string_view;
    /// Return the bytes reserved by arena chunks.
    [[nodiscard]] auto heap_bytes() const noexcept -> std::size_t;

  private:
    struct Chunk {
        // Heap-sized stable arena segments require owning dynamic arrays.
        // NOLINTNEXTLINE(cppcoreguidelines-avoid-c-arrays,modernize-avoid-c-arrays)
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
    auto intern(std::string_view filename, bool is_directory = false) -> std::uint32_t;
    /// Return the extension for an ID; ID zero returns an empty view.
    [[nodiscard]] auto get(std::uint32_t id) const -> std::string_view;
    /// Return a lower-bound estimate of extension storage bytes.
    [[nodiscard]] auto heap_bytes() const noexcept -> std::size_t;

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
    static auto posix_uid(std::uint32_t uid) -> OwnerKey;
    /// Build a Windows owner key from the SID's binary bytes.
    static auto windows_sid(std::string_view sid_bytes) -> OwnerKey;
    /// Build a remote owner key from its backend-provided string.
    static auto remote(std::string_view remote_key) -> OwnerKey;

    /// Compare the identity kind and its corresponding value.
    auto operator==(const OwnerKey &) const -> bool = default;
};

/// Intern owner identities and keep one display name for each identity.
class OwnerTable {
  public:
    OwnerTable();

    /// Return a stable identity ID; fill an unresolved display name when one becomes available.
    auto intern(const OwnerKey &key, std::string_view display) -> std::uint32_t;
    /// Return the display name for an ID; ID zero returns an empty view.
    [[nodiscard]] auto get(std::uint32_t id) const -> std::string_view;
    /// Return a lower-bound estimate of owner storage bytes.
    [[nodiscard]] auto heap_bytes() const noexcept -> std::size_t;

    /// Return an identity by stable owner ID, or nullptr for the absent owner.
    [[nodiscard]] auto key(std::uint32_t id) const -> const OwnerKey *;

  private:
    struct Hash {
        [[nodiscard]] auto operator()(const OwnerKey &key) const noexcept -> std::size_t;
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
    [[nodiscard]] auto size() const noexcept -> std::uint32_t;
    /// Return a node by ID.
    [[nodiscard]] auto node(NodeId id) const -> const Node &;
    /// Return the descendant counts for a node.
    [[nodiscard]] auto counts(NodeId id) const -> Counts;
    /// Return a node's native name bytes. Root nodes contain their full path.
    [[nodiscard]] auto name_bytes(NodeId id) const -> std::string_view;
    /// Return the node extension when it has one.
    [[nodiscard]] auto ext(NodeId id) const -> std::optional<std::string_view>;
    /// Return a node's resolved owner display name when available.
    [[nodiscard]] auto owner_name(NodeId id) const -> std::optional<std::string_view>;
    /// Return the contiguous half-open child ID range.
    [[nodiscard]] auto children(NodeId id) const -> std::pair<NodeId, NodeId>;
    /// Return the parent ID, or no value for the synthetic root.
    [[nodiscard]] auto parent(NodeId id) const -> std::optional<NodeId>;
    /// Reconstruct the node's native path in O(depth).
    [[nodiscard]] auto path_bytes(NodeId id) const -> std::string;
    /// Return the node depth below its scan root.
    [[nodiscard]] auto depth(NodeId id) const -> std::uint16_t;
    /// Find a path after separator normalization and platform case handling.
    [[nodiscard]] auto find_path(std::string_view native_path) const -> std::optional<NodeId>;
    /// Return the root node IDs.
    [[nodiscard]] auto roots() const -> std::span<const NodeId>;
    /// Report the bytes reserved by tree-owned storage.
    [[nodiscard]] auto memory_usage() const -> MemoryReport;
    /// Intern and assign an owner identity.
    void set_owner(NodeId id, const OwnerKey &key, std::string_view display);
    /// Exclude a node and incrementally update totals.
    void mark_deleted(NodeId id);
    /// Replace a subtree while preserving the tree invariants.
    void replace_subtree(NodeId at, const Tree &fresh, NodeId fresh_root);
    /// Return scan metadata associated with the tree.
    [[nodiscard]] auto meta() const noexcept -> const ScanMeta &;

  private:
    friend class TreeBuilder;
    friend class ScanEngine;
    friend auto build_tree_from_mft(const MftIndex &, std::string_view,
                                    std::optional<std::string_view>, const ScanOptions &,
                                    IssueSink &) -> Tree;
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
    auto add_children(NodeId dir, std::span<const NewNode> entries) -> std::pair<NodeId, NodeId>;
    /// Add flags to a node.
    void mark(NodeId id, std::uint16_t flags);
    /// Recompute totals for a partially built tree.
    void aggregate_partial();
    /// Finalize the tree and release unused tail storage.
    auto finish(ScanMeta meta) && -> Tree;

  private:
    friend class ScanEngine;
    friend auto build_tree_from_mft(const MftIndex &, std::string_view,
                                    std::optional<std::string_view>, const ScanOptions &,
                                    IssueSink &) -> Tree;
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
    friend void write_json(TreeHandle &, FsBackend &, std::span<const NodeId>, std::ostream &,
                           const JsonOptions &);
    friend void write_csv(TreeHandle &, FsBackend &, std::span<const NodeId>, std::ostream &,
                          const CsvOptions &);
    std::shared_ptr<const Tree> tree_;
    mutable detail::TreeMutex mutex_;
    std::mutex owner_resolution_mutex_;
};

} // namespace dafree
