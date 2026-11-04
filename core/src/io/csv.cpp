#include "dafree/export.hpp"

#include "io_common.hpp"

#include <charconv>
#include <limits>
#include <locale>
#include <ostream>
#include <sstream>
#include <stdexcept>

namespace dafree {
namespace {

constexpr std::array<std::string_view, 14> headers{
    "path", "name",      "type",      "size",      "alloc", "pct_parent", "files",
    "dirs", "mtime_iso", "btime_iso", "atime_iso", "owner", "ext",        "flags",
};

class Csv {
  public:
    Csv(std::ostream &out, char delimiter) : out_(out), delimiter_(delimiter) {
        fraction_.imbue(std::locale::classic());
        fraction_.precision(std::numeric_limits<double>::max_digits10);
    }

    void raw(std::string_view value) {
        if (!value.empty())
            out_.write(value.data(), static_cast<std::streamsize>(value.size()));
    }

    void field(std::string_view value) {
        if (!first_)
            out_.put(delimiter_);
        first_ = false;
        const bool quoted = value.find_first_of("\"\r\n") != std::string_view::npos ||
                            value.find(delimiter_) != std::string_view::npos;
        if (quoted)
            out_.put('"');
        std::size_t start = 0;
        for (std::size_t pos = 0; pos < value.size();) {
            const auto begin = pos;
            const auto cp = detail::next_codepoint(value, pos);
            if (cp == '"' || io_detail::invalid_scalar(cp)) {
                raw(value.substr(start, begin - start));
                raw(cp == '"' ? "\"\"" : "\xef\xbf\xbd");
                start = pos;
            }
        }
        raw(value.substr(start));
        if (quoted)
            out_.put('"');
    }

    template <class Number> void number(Number value) {
        std::array<char, 32> bytes{};
        const auto result = std::to_chars(bytes.data(), bytes.data() + bytes.size(), value);
        if (result.ec != std::errc{})
            throw Error("failed to format CSV number");
        field({bytes.data(), static_cast<std::size_t>(result.ptr - bytes.data())});
    }

    void fraction(double value) {
        // Reuse the buffer. Floating-point to_chars requires macOS 13.3,
        // while the wheel deployment target is macOS 13.0.
        fraction_.seekp(0);
        fraction_ << value;
        const auto length = static_cast<std::streamoff>(fraction_.tellp());
        if (length < 0)
            throw Error("failed to format CSV fraction");
        field(fraction_.view().substr(0, static_cast<std::size_t>(length)));
    }

    void time(std::uint32_t value) {
        if (const auto timestamp = io_detail::iso_time(value))
            field({timestamp->data(), timestamp->size()});
        else
            field({});
    }

    void end_row() {
        raw("\r\n");
        if (!out_)
            throw Error("failed to write CSV report");
        first_ = true;
    }

  private:
    std::ostream &out_;
    char delimiter_;
    std::ostringstream fraction_;
    bool first_ = true;
};

double parent_fraction(const Tree &tree, const Node &node) {
    if (node.parent == kRoot || node.parent == kNone)
        return 0;
    const auto size = tree.node(node.parent).size;
    return size == 0 ? 0 : static_cast<double>(node.size) / static_cast<double>(size);
}

template <class Owner>
void row(Csv &csv, const Tree &tree, NodeId id, bool include_owner, Owner &owner, std::string &path,
         std::string &flags) {
    const auto &node = tree.node(id);
    const auto counts = tree.counts(id);
    io_detail::path_of(tree, id, path);
    csv.field(path);
    csv.field(tree.name_bytes(id));
    csv.field(io_detail::node_type(node));
    csv.number(node.size);
    csv.number(node.alloc);
    csv.fraction(parent_fraction(tree, node));
    csv.number(counts.files);
    csv.number(counts.dirs);
    csv.time(node.mtime);
    csv.time(node.btime);
    csv.time(node.atime);
    const auto name = include_owner ? owner(id) : std::nullopt;
    csv.field(name ? std::string_view(*name) : std::string_view{});
    csv.field(tree.ext(id).value_or(std::string_view{}));
    flags.clear();
    for (const auto &[flag, label] : io_detail::flag_names) {
        if ((node.flags & flag) == 0)
            continue;
        if (!flags.empty())
            flags.push_back('|');
        flags.append(label);
    }
    csv.field(flags);
    csv.end_row();
}

template <class Owner>
void scope(Csv &csv, const Tree &tree, NodeId root, const CsvOptions &options, Owner &owner,
           std::string &path, std::string &flags) {
    auto id = root;
    std::size_t depth = 0;
    for (;;) {
        row(csv, tree, id, options.include_owner, owner, path, flags);
        if (!options.depth || depth < *options.depth) {
            const auto [first, end] = tree.children(id);
            const auto child = io_detail::next_visible(tree, first, end, options.include_files);
            if (child != kNone) {
                id = child;
                ++depth;
                continue;
            }
        }
        while (id != root) {
            const auto parent = tree.node(id).parent;
            const auto sibling = io_detail::next_visible(tree, id + 1, tree.children(parent).second,
                                                         options.include_files);
            if (sibling != kNone) {
                id = sibling;
                break;
            }
            id = parent;
            --depth;
        }
        if (id == root)
            return;
    }
}

template <class Owner>
void write(const Tree &tree, std::span<const NodeId> scopes, std::ostream &out,
           const CsvOptions &options, Owner owner) {
    const char delim = options.delimiter;
    if ((delim < ' ' || delim > '~' || delim == '"') && delim != '\t')
        throw std::invalid_argument("invalid CSV delimiter");
    if (scopes.empty())
        scopes = tree.roots();
    for (const auto id : scopes)
        if (id == kRoot || id >= tree.size())
            throw std::out_of_range("invalid CSV scope node ID");

    Csv csv(out, delim);
    if (options.excel)
        csv.raw("\xef\xbb\xbf");
    for (const auto field : headers)
        csv.field(field);
    csv.end_row();
    std::string path, flags;
    for (const auto id : scopes)
        if (io_detail::visible(tree.node(id), options.include_files))
            scope(csv, tree, id, options, owner, path, flags);
}

} // namespace

void write_csv(const Tree &tree, std::span<const NodeId> scopes, std::ostream &out,
               const CsvOptions &options) {
    write(tree, scopes, out, options, [&](NodeId id) { return tree.owner_name(id); });
}

void write_csv(TreeHandle &handle, FsBackend &backend, std::span<const NodeId> scopes,
               std::ostream &out, const CsvOptions &options) {
    const auto owner = [&](NodeId id) { return io_detail::resolved_owner(handle, backend, id); };
    write(*handle.tree_, scopes, out, options, owner);
}

} // namespace dafree
