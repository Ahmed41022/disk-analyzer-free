#pragma once

#include "dafree/analysis.hpp"
#include "dafree/model.hpp"

#include <memory>
#include <optional>
#include <string>
#include <vector>

namespace dafree {

/// A numeric comparison in a compiled filter expression.
struct Cmp64 {
    enum Op : std::uint8_t { Lt, Le, Eq, Ge, Gt } op{};
    std::uint64_t v = 0;
    /// Compare filter values without recompiling unchanged predicates.
    friend bool operator==(const Cmp64 &, const Cmp64 &) = default;
};

/// Native filter expression; strings remain lossless native UTF-8/WTF-8 bytes.
struct FilterSpec {
    enum class Kind : std::uint8_t {
        And,
        Or,
        Not,
        Size,
        Alloc,
        Ext,
        NameGlob,
        PathGlob,
        Regex,
        Owner,
        Time,
        Type,
        Files,
        Flag
    };
    Kind kind = Kind::And;
    std::vector<FilterSpec> children;
    Cmp64 cmp{};
    TimeField time_field{};
    std::vector<std::string> values;
    std::string regex;
    std::uint16_t flag = 0;
    bool type_dir = false;
    /// Compare expression structure when only display/sort options change.
    friend bool operator==(const FilterSpec &, const FilterSpec &) = default;
};

/// Per-directory sort key; percentages have the same order as size within a parent.
enum class SortKey : std::uint8_t { Name, Size, Alloc, PctParent, Files, Dirs, Mtime, Owner, Ext };

/// Display and filtering policy without modifying the underlying node arena.
struct ViewOptions {
    SortKey sort = SortKey::Size;
    bool descending = true;
    bool dirs_first = false;
    bool show_files = true;
    std::optional<FilterSpec> filter;
    bool resolve_owner = false;
};

/// Copied metadata for a single visible table row.
struct Row {
    NodeId id;
    std::uint16_t depth;
    bool has_children, expanded;
    std::string name;
    std::uint64_t size, alloc;
    float pct_parent;
    std::uint32_t files, dirs, mtime;
    std::optional<std::string> owner, ext;
    std::uint16_t flags;
    std::uint8_t ext_category;
};

/// A flattened, paged tree view with cached sibling sorts and stable node IDs.
class TreeView {
  public:
    /// Read an immutable tree snapshot; owner display names use its cached data.
    TreeView(std::shared_ptr<const Tree> tree, ViewOptions options);
    /// Reuse a live tree's lock and backend for coherent lazy owner resolution.
    TreeView(std::shared_ptr<TreeHandle> tree, std::shared_ptr<FsBackend> backend,
             ViewOptions options);
    ~TreeView();
    TreeView(const TreeView &) = delete;
    TreeView &operator=(const TreeView &) = delete;
    /// Return the number of visible rows, excluding the synthetic root.
    [[nodiscard]] std::uint32_t row_count() const;
    /// Copy a window of at most 500 rows; an out-of-range start returns an empty window.
    [[nodiscard]] std::vector<Row> rows(std::uint32_t start, std::uint32_t count) const;
    /// Expand a directory and return the number of inserted visible rows.
    std::uint32_t expand(NodeId id);
    /// Collapse a directory while retaining descendant expansion preferences.
    std::uint32_t collapse(NodeId id);
    /// Expand ancestors and return the node's visible row index; hidden nodes are rejected.
    std::uint32_t expand_to(NodeId id);
    /// Re-sort/re-filter while retaining expanded paths.
    void set_options(ViewOptions options);
    /// Copy the active options so clients preserve unrelated settings during a sort.
    [[nodiscard]] ViewOptions options() const;
    /// Locate a visible node; absent/filtered nodes have no row index.
    [[nodiscard]] std::optional<std::uint32_t> index_of(NodeId id) const;

  private:
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

} // namespace dafree
