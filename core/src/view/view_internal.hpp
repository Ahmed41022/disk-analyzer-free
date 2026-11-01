#pragma once

#include "../scan/glob.hpp"
#include "dafree/view.hpp"

#include <functional>
#include <list>
#include <mutex>
#include <span>
#include <unordered_map>

namespace dafree::detail {

/// Compare names naturally using ASCII numeric runs and BMP simple folding.
int natural_compare(std::string_view left, std::string_view right) noexcept;

/// Bit-packed eligibility with disjoint-word parallel writes during filtering.
struct ViewBits {
    std::vector<std::uint64_t> words;
    bool get(NodeId id) const { return (words[id / 64u] & (std::uint64_t{1} << (id % 64u))) != 0; }
    void set(NodeId id) { words[id / 64u] |= std::uint64_t{1} << (id % 64u); }
};

/// Matching nodes and direct displayable-child metadata for one filter version.
struct Visibility {
    bool filtered = false;
    ViewBits eligible, has_children;
};

/// Compile once, resolve owners only for possible matches, and evaluate in native workers.
Visibility filter_visibility(const TreeHandle &tree, const std::optional<FilterSpec> &spec,
                             bool show_files,
                             const std::function<void(std::span<const NodeId>)> &resolve);

/// Sort one sibling list without allocating inside the comparison hot path.
void sort_children(const Tree &tree, std::vector<NodeId> &ids, const ViewOptions &options);

/// One compact visible-row reference; full metadata is copied only in rows().
struct RowRef {
    NodeId id;
    std::uint32_t depth;
};

/// Chunked implicit treap: bounded local shifts and indexed sequential windows.
class VisibleRows {
  public:
    explicit VisibleRows(std::uint32_t nodes);
    ~VisibleRows();
    VisibleRows(VisibleRows &&) noexcept;
    VisibleRows &operator=(VisibleRows &&) noexcept;
    VisibleRows(const VisibleRows &) = delete;
    VisibleRows &operator=(const VisibleRows &) = delete;
    std::uint32_t size() const;
    std::optional<std::uint32_t> index_of(NodeId id) const;
    RowRef at(std::uint32_t index) const;
    void visit(std::uint32_t start, std::uint32_t count,
               const std::function<bool(const RowRef &)> &function) const;
    void insert(std::uint32_t at, std::span<const RowRef> rows);
    void erase(std::uint32_t at, std::uint32_t count);

  private:
    struct Storage;
    std::unique_ptr<Storage> storage_;
};

} // namespace dafree::detail
