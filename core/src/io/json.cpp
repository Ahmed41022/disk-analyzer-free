#include "dafree/export.hpp"
#include "dafree/scan.hpp"

#include "io_common.hpp"

#include <array>
#include <charconv>
#include <ostream>
#include <stdexcept>

namespace dafree {
namespace {

constexpr std::string_view schema =
    "https://raw.githubusercontent.com/Ahmed41022/disk-analyzer-free/main/schemas/report.v1.json";
constexpr std::string_view hex = "0123456789abcdef";

class Json {
  public:
    Json(std::ostream &out, bool pretty) : out_(out), pretty_(pretty) {}

    void raw(std::string_view text) {
        if (!text.empty())
            out_.write(text.data(), static_cast<std::streamsize>(text.size()));
    }
    void put(char ch) { out_.put(ch); }

    // Invalid native bytes are represented by replacement characters, with raw bytes
    // emitted separately for names and paths. WTF-8 surrogate triples are one unit.
    bool string(std::string_view text) {
        put('"');
        bool invalid = false;
        std::size_t start = 0;
        for (std::size_t pos = 0; pos < text.size();) {
            const auto begin = pos;
            const auto cp = detail::next_codepoint(text, pos);
            std::string_view escape;
            std::array<char, 6> control{'\\', 'u', '0', '0', '0', '0'};
            switch (cp) {
            case '"':
                escape = "\\\"";
                break;
            case '\\':
                escape = "\\\\";
                break;
            case '\b':
                escape = "\\b";
                break;
            case '\f':
                escape = "\\f";
                break;
            case '\n':
                escape = "\\n";
                break;
            case '\r':
                escape = "\\r";
                break;
            case '\t':
                escape = "\\t";
                break;
            default:
                if (cp < 0x20) {
                    control[4] = hex[cp >> 4];
                    control[5] = hex[cp & 15];
                    escape = {control.data(), control.size()};
                } else if (io_detail::invalid_scalar(cp)) {
                    invalid = true;
                    escape = "\xef\xbf\xbd";
                }
            }
            if (!escape.empty()) {
                raw(text.substr(start, begin - start));
                raw(escape);
                start = pos;
            }
        }
        raw(text.substr(start));
        put('"');
        return invalid;
    }

    void bytes(std::string_view input) {
        put('"');
        for (const char ch : input) {
            const auto byte = static_cast<unsigned char>(ch);
            put(hex[byte >> 4]);
            put(hex[byte & 15]);
        }
        put('"');
    }

    void number(std::uint64_t value) {
        std::array<char, 20> buffer{};
        const auto result = std::to_chars(buffer.data(), buffer.data() + buffer.size(), value);
        raw({buffer.data(), static_cast<std::size_t>(result.ptr - buffer.data())});
    }

    void time(std::int64_t value) {
        if (const auto timestamp = io_detail::iso_time(value)) {
            put('"');
            raw({timestamp->data(), timestamp->size()});
            put('"');
        } else
            raw("null");
    }

    void line(std::size_t depth) {
        if (!pretty_)
            return;
        put('\n');
        constexpr std::string_view spaces = "                                ";
        auto count = depth * 2;
        while (count >= spaces.size()) {
            raw(spaces);
            count -= spaces.size();
        }
        raw(spaces.substr(0, count));
    }

    void key(std::string_view name, std::size_t depth, bool first = false) {
        if (!first)
            put(',');
        line(depth);
        put('"');
        raw(name);
        put('"');
        put(':');
        if (pretty_)
            put(' ');
    }

  private:
    std::ostream &out_;
    bool pretty_;
};

template <class Owner>
void fields(Json &json, const Tree &tree, NodeId id, std::size_t indent, const JsonOptions &opts,
            Owner &owner, std::string &path) {
    const auto &node = tree.node(id);
    const auto counts = tree.counts(id);
    const auto name = tree.name_bytes(id);
    json.put('{');
    json.key("name", indent, true);
    if (json.string(name)) {
        json.key("name_raw_hex", indent);
        json.bytes(name);
    }
    if (opts.ndjson) {
        io_detail::path_of(tree, id, path);
        json.key("path", indent);
        if (json.string(path)) {
            json.key("path_raw_hex", indent);
            json.bytes(path);
        }
    }
    json.key("type", indent);
    json.string(io_detail::node_type(node));
    json.key("size", indent);
    json.number(node.size);
    json.key("alloc", indent);
    json.number(node.alloc);
    json.key("files", indent);
    json.number(counts.files);
    json.key("dirs", indent);
    json.number(counts.dirs);
    json.key("mtime", indent);
    json.time(node.mtime);
    json.key("btime", indent);
    json.time(node.btime);
    json.key("atime", indent);
    json.time(node.atime);
    if (opts.include_owner) {
        if (const auto value = owner(id); value && !value->empty()) {
            json.key("owner", indent);
            json.string(*value);
        }
    }
    if (const auto ext = tree.ext(id); ext && !ext->empty()) {
        json.key("ext", indent);
        json.string(*ext);
    }
    json.key("flags", indent);
    json.put('[');
    bool first = true;
    for (const auto &[flag, label] : io_detail::flag_names) {
        if ((node.flags & flag) == 0)
            continue;
        if (!first)
            json.put(',');
        json.string(label);
        first = false;
    }
    json.put(']');
}

template <class Owner>
void scope(Json &json, const Tree &tree, NodeId root, const JsonOptions &opts, Owner &owner,
           std::string &path) {
    auto id = root;
    std::size_t depth = 0;
    const auto indent = [&](std::size_t level) { return opts.ndjson ? 0 : 2 * level + 2; };
    for (;;) {
        json.line(indent(depth));
        fields(json, tree, id, indent(depth) + 1, opts, owner, path);
        if (opts.ndjson)
            json.raw("}\n");
        const auto [first, end] = tree.children(id);
        const auto child = (!opts.depth || depth < *opts.depth)
                               ? io_detail::next_visible(tree, first, end, opts.include_files)
                               : kNone;
        if (child != kNone) {
            if (!opts.ndjson) {
                json.key("children", indent(depth) + 1);
                json.put('[');
            }
            id = child;
            ++depth;
            continue;
        }
        if (!opts.ndjson) {
            json.line(indent(depth));
            json.put('}');
        }
        // Contiguous child ranges and parent IDs make the DFS stack unnecessary.
        while (id != root) {
            const auto parent = tree.node(id).parent;
            const auto sibling = io_detail::next_visible(tree, id + 1, tree.children(parent).second,
                                                         opts.include_files);
            if (sibling != kNone) {
                if (!opts.ndjson)
                    json.put(',');
                id = sibling;
                break;
            }
            id = parent;
            --depth;
            if (!opts.ndjson) {
                json.line(indent(depth) + 1);
                json.put(']');
                json.line(indent(depth));
                json.put('}');
            }
        }
        if (id == root)
            return;
    }
}

void metadata(Json &json, const ScanMeta &meta) {
    json.put('{');
    json.key("started_at", 2, true);
    json.time(meta.started_at);
    json.key("finished_at", 2);
    json.time(meta.finished_at);
    json.key("mode", 2);
    json.string(meta.mode == ScanModeUsed::Mft    ? "mft"
                : meta.mode == ScanModeUsed::Sftp ? "sftp"
                                                  : "walk");
    json.key("host", 2);
    json.string(meta.host);
    json.key("os", 2);
    json.string(meta.os);
    json.key("app_version", 2);
    json.string(meta.app_version);
    json.key("cancelled", 2);
    json.raw(meta.cancelled ? "true" : "false");
    json.key("issues", 2);
    json.number(meta.issues.total);
    json.line(1);
    json.put('}');
}

template <class Owner>
void write(const Tree &tree, std::span<const NodeId> scopes, std::ostream &out,
           const JsonOptions &opts, Owner owner) {
    if (scopes.empty())
        scopes = tree.roots();
    for (const auto id : scopes)
        if (id == kRoot || id >= tree.size())
            throw std::out_of_range("invalid JSON scope node ID");
    Json json(out, opts.pretty && !opts.ndjson);
    if (!opts.ndjson) {
        json.put('{');
        json.key("schema", 1, true);
        json.string(schema);
        json.key("version", 1);
        json.number(1);
        json.key("meta", 1);
        metadata(json, tree.meta());
        json.key("roots", 1);
        json.put('[');
    }
    std::string path;
    bool first = true;
    for (const auto id : scopes) {
        if (!io_detail::visible(tree.node(id), opts.include_files))
            continue;
        if (!first && !opts.ndjson)
            json.put(',');
        scope(json, tree, id, opts, owner, path);
        first = false;
    }
    if (!opts.ndjson) {
        if (!first)
            json.line(1);
        json.put(']');
        json.line(0);
        json.raw("}\n");
    }
    if (!out)
        throw Error("failed to write JSON report");
}

} // namespace

void write_json(const Tree &tree, std::span<const NodeId> scopes, std::ostream &out,
                const JsonOptions &opts) {
    write(tree, scopes, out, opts, [&](NodeId id) { return tree.owner_name(id); });
}

void write_json(TreeHandle &handle, FsBackend &backend, std::span<const NodeId> scopes,
                std::ostream &out, const JsonOptions &opts) {
    // The handle's tree pointer and all structure are immutable. Owner resolution
    // alone can change owner IDs/table entries and is synchronized separately.
    const auto owner = [&](NodeId id) { return io_detail::resolved_owner(handle, backend, id); };
    write(*handle.tree_, scopes, out, opts, owner);
}

} // namespace dafree
