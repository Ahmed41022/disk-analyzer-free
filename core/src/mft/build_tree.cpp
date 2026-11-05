#include "dafree/mft.hpp"
#include "dafree/model.hpp"
#include "dafree/scan.hpp"

#include "../scan/glob.hpp"
#include "index.hpp"

#include <algorithm>
#include <array>
#include <limits>
#include <optional>
#include <unordered_map>
#include <unordered_set>
#include <utility>

namespace dafree {
namespace {

constexpr std::uint64_t reference_mask = UINT64_C(0x0000ffffffffffff);
constexpr std::size_t no_entity = std::numeric_limits<std::size_t>::max();

std::uint64_t saturated(std::uint64_t left, std::uint64_t right) {
    const auto maximum = std::numeric_limits<std::uint64_t>::max();
    return right > maximum - left ? maximum : left + right;
}

std::string folded(std::string_view text) {
    std::string result;
    result.reserve(text.size());
    for (std::size_t position = 0; position < text.size();) {
        const auto value = detail::next_codepoint(text, position);
        if (value >= 0x110000)
            result.push_back(static_cast<char>(value - 0x110000));
        else
            mft_detail::append_utf8(result, detail::fold_codepoint(value));
    }
    return result;
}

std::string joined(std::string_view parent, std::string_view name) {
    std::string result(parent);
    if (!result.empty() && result.back() != '/' && result.back() != '\\') {
#ifdef _WIN32
        result.push_back('\\');
#else
        result.push_back('/');
#endif
    }
    result.append(name);
    return result;
}

struct NormalPath {
    std::string text;
    bool absolute;
};

NormalPath normalize(std::string_view input) {
    if (input.find('\0') != std::string_view::npos)
        throw ScanError(ScanError::Code::InvalidTarget, "MFT paths cannot contain NUL");
    std::string path(input);
    std::replace(path.begin(), path.end(), '\\', '/');
    if (path.starts_with("//?/UNC/"))
        path = "//" + path.substr(8);
    else if (path.starts_with("//?/"))
        path.erase(0, 4);
    std::size_t start = 0;
    std::string prefix;
    if (path.size() >= 3 && path[1] == ':' && path[2] == '/') {
        prefix = path.substr(0, 3);
        start = 3;
    } else if (path.starts_with('/')) {
        prefix = "/";
        start = 1;
    }
    std::vector<std::string_view> components;
    while (start < path.size()) {
        const auto slash = path.find('/', start);
        const auto end = slash == std::string::npos ? path.size() : slash;
        const std::string_view component(path.data() + start, end - start);
        if (component == "..") {
            if (components.empty())
                throw ScanError(ScanError::Code::InvalidTarget, "MFT path escapes its root");
            components.pop_back();
        } else if (!component.empty() && component != ".")
            components.push_back(component);
        start = end == path.size() ? end : end + 1;
    }
    const bool absolute = !prefix.empty();
    for (const auto component : components) {
        if (!prefix.empty() && !prefix.ends_with('/'))
            prefix.push_back('/');
        prefix.append(component);
    }
    return {std::move(prefix), absolute};
}

std::optional<std::size_t> under(std::string_view path, std::string_view parent) {
    if (!path.starts_with(parent))
        return std::nullopt;
    if (path.size() == parent.size() || parent.ends_with('/') || path[parent.size()] == '/')
        return parent.size();
    return std::nullopt;
}

class Reporter {
  public:
    Reporter(ScanMeta &meta, IssueSink &sink, std::string_view root)
        : meta_(meta), sink_(sink), root_(root) {}

    void emit(std::uint64_t record, IssueKind kind, std::string message) {
        ScanIssue issue{joined(root_, "$MFT:" + std::to_string(record)), kind, std::move(message)};
        auto &summary = meta_.issues;
        summary.total = saturated(summary.total, 1);
        auto &count = summary.counts[static_cast<std::size_t>(kind)];
        count = saturated(count, 1);
        if (summary.first.size() < 1000)
            summary.first.push_back(issue);
        else
            summary.overflow = saturated(summary.overflow, 1);
        if (sink_)
            sink_(std::move(issue));
    }

  private:
    ScanMeta &meta_;
    IssueSink &sink_;
    std::string root_;
};

std::vector<std::uint64_t> ordered_numbers(const mft_detail::IndexData &index) {
    std::vector<std::uint64_t> numbers;
    numbers.reserve(index.records.size());
    for (const auto &[number, record] : index.records) {
        (void)record;
        numbers.push_back(number);
    }
    std::vector<std::uint64_t> scratch(numbers.size());
    for (unsigned shift = 0; shift < 64; shift += 8) {
        std::array<std::size_t, 256> counts{};
        for (const auto number : numbers)
            ++counts[static_cast<std::size_t>((number >> shift) & 0xff)];
        std::size_t offset = 0;
        for (auto &count : counts) {
            const auto size = count;
            count = offset;
            offset += size;
        }
        for (const auto number : numbers)
            scratch[counts[static_cast<std::size_t>((number >> shift) & 0xff)]++] = number;
        numbers.swap(scratch);
    }
    return numbers;
}

struct Entity {
    std::uint64_t number;
    const mft_detail::IndexedRecord *base;
    std::optional<StdInfo> standard;
    bool reparse = false, orphan_reported = false;
    std::vector<const mft_detail::IndexedName *> names;
    std::vector<const mft_detail::IndexedStream *> streams;
    std::uint64_t size = 0, alloc = 0;

    bool directory() const { return (base->header.flags & 2) != 0; }

    void append(const mft_detail::IndexedRecord &record) {
        if (!standard && record.standard)
            standard = record.standard;
        reparse = reparse || record.reparse;
        for (const auto &name : record.names)
            names.push_back(&name);
        for (const auto &stream : record.streams)
            streams.push_back(&stream);
    }

    void summarize(bool include_ads) {
        bool unnamed_seen = false;
        std::unordered_set<std::string> named_seen;
        for (const auto *stream : streams) {
            if (stream->name.empty()) {
                if (unnamed_seen)
                    continue;
                unnamed_seen = true;
            } else if (!include_ads || !named_seen.insert(folded(stream->name)).second)
                continue;
            size = saturated(size, stream->size);
            alloc = saturated(alloc, stream->alloc);
        }
        if (standard && (standard->file_attributes & 0x400) != 0)
            reparse = true;
    }
};

struct Edge {
    std::size_t parent, child;
    const mft_detail::IndexedName *name;
    bool metafile = false, blocked = false;
};

struct Graph {
    std::vector<Entity> entities;
    std::unordered_map<std::uint64_t, std::size_t> by_number;
    std::vector<std::size_t> offsets;
    std::vector<Edge> edges;
    std::size_t root = no_entity;
};

struct NameKey {
    std::uint64_t parent;
    std::string_view name;
    bool operator==(const NameKey &) const = default;
};

struct NameHash {
    std::size_t operator()(const NameKey &value) const {
        return std::hash<std::uint64_t>{}(value.parent) ^
               (std::hash<std::string_view>{}(value.name) << 1);
    }
};

Graph make_graph(const mft_detail::IndexData &index, const ScanOptions &options,
                 Reporter &reporter) {
    Graph graph;
    const auto numbers = ordered_numbers(index);
    graph.entities.reserve(numbers.size());
    graph.by_number.reserve(numbers.size());
    for (const auto number : numbers) {
        const auto &record = index.records.at(number);
        if (record.duplicate || record.error) {
            reporter.emit(number, IssueKind::Other,
                          record.duplicate ? "conflicting MFT record number"
                                           : "malformed MFT record");
            continue;
        }
        if ((record.header.flags & 1) != 0 && record.header.base_record == 0) {
            graph.by_number.emplace(number, graph.entities.size());
            graph.entities.push_back({number, &record, {}, false, false, {}, {}, 0, 0});
            graph.entities.back().append(record);
        }
    }
    for (const auto number : numbers) {
        const auto &record = index.records.at(number);
        if (record.duplicate || record.error || record.header.base_record == 0 ||
            (record.header.flags & 1) == 0)
            continue;
        const auto base = graph.by_number.find(record.header.base_record & reference_mask);
        if (base == graph.by_number.end() ||
            graph.entities[base->second].base->header.sequence != record.header.base_record >> 48) {
            reporter.emit(number, IssueKind::Orphaned, "MFT extension base is absent or stale");
            continue;
        }
        graph.entities[base->second].append(record);
    }
    const auto root = graph.by_number.find(5);
    if (root == graph.by_number.end() || !graph.entities[root->second].directory())
        throw ScanError(ScanError::Code::InvalidTarget, "MFT directory record 5 is unavailable");
    graph.root = root->second;
    std::vector<Edge> edges;
    for (std::size_t child = 0; child < graph.entities.size(); ++child) {
        auto &entity = graph.entities[child];
        entity.summarize(options.include_ads);
        if (child == graph.root)
            continue;
        std::unordered_set<std::uint64_t> win32_parents;
        for (const auto *name : entity.names)
            if (name->name_space == 1 || name->name_space == 3)
                win32_parents.insert(name->parent);
        std::unordered_set<NameKey, NameHash> seen_names;
        for (const auto *name : entity.names) {
            if ((name->name_space == 2 && win32_parents.contains(name->parent)) ||
                !seen_names.insert({name->parent, name->name}).second)
                continue;
            if (name->name.empty() || name->name == "." || name->name == ".." ||
                name->name.find_first_of("/\\") != std::string::npos ||
                name->name.find('\0') != std::string::npos) {
                reporter.emit(entity.number, IssueKind::InvalidName, "invalid MFT entry name");
                entity.orphan_reported = true;
                continue;
            }
            const auto parent = graph.by_number.find(name->parent & reference_mask);
            if (parent == graph.by_number.end() || !graph.entities[parent->second].directory() ||
                graph.entities[parent->second].base->header.sequence != name->parent >> 48) {
                reporter.emit(entity.number, IssueKind::Orphaned, "MFT parent is absent or stale");
                entity.orphan_reported = true;
                continue;
            }
            const bool metafile = entity.number < 16 ||
                                  (parent->second == graph.root && folded(name->name) == "$extend");
            edges.push_back({parent->second, child, name, metafile, false});
        }
    }
    // Two counting-sort passes group direct children without record-number-sized arrays.
    graph.offsets.resize(graph.entities.size() + 1);
    for (const auto &edge : edges)
        ++graph.offsets[edge.parent + 1];
    for (std::size_t position = 1; position < graph.offsets.size(); ++position)
        graph.offsets[position] += graph.offsets[position - 1];
    auto cursor = graph.offsets;
    graph.edges.resize(edges.size());
    for (const auto &edge : edges)
        graph.edges[cursor[edge.parent]++] = edge;

    std::vector<bool> reachable(graph.entities.size()), directories(graph.entities.size());
    std::vector<std::size_t> queue{graph.root};
    reachable[graph.root] = directories[graph.root] = true;
    for (std::size_t position = 0; position < queue.size(); ++position) {
        const auto parent = queue[position];
        for (auto offset = graph.offsets[parent]; offset < graph.offsets[parent + 1]; ++offset) {
            const auto &edge = graph.edges[offset];
            reachable[edge.child] = true;
            if (graph.entities[edge.child].directory() && !directories[edge.child]) {
                directories[edge.child] = true;
                queue.push_back(edge.child);
            }
        }
    }
    for (std::size_t position = 0; position < graph.entities.size(); ++position)
        if (!reachable[position] && !graph.entities[position].orphan_reported)
            reporter.emit(graph.entities[position].number, IssueKind::Orphaned,
                          "MFT record is not reachable from the volume root");
    // Structural reachability is separate from traversal: skipping a reparse point
    // intentionally must not turn its indexed descendants into alleged orphans.
    std::fill(directories.begin(), directories.end(), false);
    directories[graph.root] = true;
    queue.resize(1);
    for (std::size_t position = 0; position < queue.size(); ++position) {
        const auto parent = queue[position];
        if (graph.entities[parent].reparse)
            continue;
        for (auto offset = graph.offsets[parent]; offset < graph.offsets[parent + 1]; ++offset) {
            auto &edge = graph.edges[offset];
            if (!graph.entities[edge.child].directory())
                continue;
            if (directories[edge.child]) {
                edge.blocked = true;
                reporter.emit(graph.entities[edge.child].number, IssueKind::SymlinkLoop,
                              "MFT directory was already visited");
            } else {
                directories[edge.child] = true;
                queue.push_back(edge.child);
            }
        }
    }
    return graph;
}

struct Selection {
    std::size_t entity;
    std::string path;
    bool metafile = false;
};

Selection select(const Graph &graph, std::string_view root,
                 std::optional<std::string_view> subtree) {
    const auto normalized_root = normalize(root);
    if (!normalized_root.absolute)
        throw ScanError(ScanError::Code::InvalidTarget, "MFT volume root must be absolute");
    Selection selected{graph.root, std::string(root), false};
    if (!subtree)
        return selected;
    auto relative = normalize(subtree.value());
    if (relative.absolute) {
        const auto key_root = folded(normalized_root.text);
        const auto key_path = folded(relative.text);
        const auto start = under(key_path, key_root);
        if (!start)
            throw ScanError(ScanError::Code::InvalidTarget,
                            "MFT subtree is outside the volume root");
        relative.text = key_path.substr(start.value());
    }
    std::size_t position = 0;
    while (position < relative.text.size()) {
        if (relative.text[position] == '/') {
            ++position;
            continue;
        }
        const auto slash = relative.text.find('/', position);
        const auto end = slash == std::string::npos ? relative.text.size() : slash;
        const auto component =
            folded(std::string_view(relative.text).substr(position, end - position));
        const Edge *match = nullptr;
        if (!graph.entities[selected.entity].reparse)
            for (auto offset = graph.offsets[selected.entity];
                 offset < graph.offsets[selected.entity + 1]; ++offset) {
                const auto &edge = graph.edges[offset];
                if (!edge.blocked && folded(edge.name->name) == component) {
                    match = &edge;
                    break;
                }
            }
        if (!match)
            throw ScanError(ScanError::Code::InvalidTarget, "MFT subtree was not found");
        selected.entity = match->child;
        selected.path = joined(selected.path, match->name->name);
        selected.metafile = selected.metafile || match->metafile;
        position = end;
    }
    return selected;
}

class Exclusions {
  public:
    Exclusions(const ExcludeRules &rules, std::string_view root)
        : hidden_(rules.hidden), system_(rules.system) {
        if (rules.paths.empty() && rules.globs.empty())
            return;
        ExcludeRules translated;
        const auto key_root = folded(normalize(root).text);
        for (const auto &path : rules.paths) {
            NormalPath normalized;
            try {
                normalized = normalize(path);
            } catch (const ScanError &error) {
                throw ExcludeError(path, error.what());
            }
            if (!normalized.absolute)
                throw ExcludeError(path, "excluded paths must be absolute");
            const auto key = folded(normalized.text);
            if (under(key_root, key))
                translated.paths.push_back(anchor());
            else if (const auto offset = under(key, key_root)) {
                auto relative = key.substr(offset.value());
                if (!relative.empty() && relative.front() != '/')
                    relative.insert(relative.begin(), '/');
                translated.paths.push_back(anchor() + relative);
            }
        }
        for (const auto &glob : rules.globs)
            translated.globs.push_back(folded(glob));
        compiled_ = CompiledExcludes::compile(translated, anchor());
    }

    bool needs_paths() const { return compiled_.has_value(); }

    bool excluded(std::string_view relative, std::string_view name, std::uint16_t flags) const {
        if ((hidden_ && (flags & kHidden) != 0) || (system_ && (flags & kSystem) != 0))
            return true;
        if (!compiled_)
            return false;
        RawEntry entry;
        entry.kind = (flags & kDir) != 0 ? EntryKind::Dir : EntryKind::File;
        return compiled_->excluded(folded(relative), folded(name), entry);
    }

  private:
    static std::string anchor() {
#ifdef _WIN32
        return "C:/mft";
#else
        return "/mft";
#endif
    }

    bool hidden_, system_;
    std::optional<CompiledExcludes> compiled_;
};

std::uint16_t flags_of(const Entity &entity, bool metafile) {
    unsigned flags = entity.directory() ? kDir : 0;
    const auto attributes = entity.standard ? entity.standard->file_attributes : 0;
    if (attributes & 0x2)
        flags |= kHidden;
    if (attributes & 0x4)
        flags |= kSystem;
    if (attributes & 0x200)
        flags |= kSparse;
    if (attributes & 0x800)
        flags |= kCompressed;
    if (attributes & (0x1000 | 0x40000 | 0x400000))
        flags |= kCloudPlaceholder;
    if (entity.reparse)
        flags |= kReparse;
    if (metafile)
        flags |= kHidden | kSystem;
    return static_cast<std::uint16_t>(flags);
}

std::uint32_t node_time(std::int64_t seconds) {
    if (seconds <= 0)
        return 1;
    return static_cast<std::uint32_t>(std::min<std::uint64_t>(
        static_cast<std::uint64_t>(seconds), std::numeric_limits<std::uint32_t>::max()));
}

TreeBuilder::NewNode node_for(const Entity &entity, std::string_view name, std::uint16_t flags) {
    return {name,
            flags,
            entity.size,
            entity.alloc,
            entity.standard ? node_time(entity.standard->modified) : 0,
            entity.standard ? node_time(entity.standard->created) : 0,
            entity.standard ? node_time(entity.standard->accessed) : 0,
            std::nullopt};
}

} // namespace

Tree build_tree_from_mft(const MftIndex &index, std::string_view root_path,
                         std::optional<std::string_view> subtree, const ScanOptions &options,
                         IssueSink &sink) {
    if (options.follow_symlinks)
        throw ScanError(ScanError::Code::UnsupportedMode,
                        "MFT scanning cannot follow reparse points");
    if (!index.data_)
        throw ScanError(ScanError::Code::InvalidTarget, "MFT index is empty");
    ScanMeta meta;
    meta.mode = ScanModeUsed::Mft;
    meta.options = options;
    Reporter reporter(meta, sink, root_path);
    const auto graph = make_graph(*index.data_, options, reporter);
    const auto selected = select(graph, root_path, subtree);
    meta.options.targets = {selected.path};
    const Exclusions exclusions(options.exclude, selected.path);
    TreeBuilder builder({selected.path});
    const auto &root_entity = graph.entities[selected.entity];
    const auto root_metadata =
        node_for(root_entity, selected.path, flags_of(root_entity, selected.metafile));
    auto &root_node = builder.tree_.nodes_[1];
    root_node.flags = root_metadata.flags;
    root_node.size = root_metadata.size;
    root_node.alloc = root_metadata.alloc;
    root_node.mtime = root_metadata.mtime;
    root_node.btime = root_metadata.btime;
    root_node.atime = root_metadata.atime;
    root_node.ext_id = builder.tree_.exts_.intern(selected.path, root_entity.directory());

    struct Pending {
        std::size_t entity;
        NodeId node;
        std::string relative;
        bool metafile;
    };
    std::vector<Pending> queue;
    if (root_entity.directory() && !root_entity.reparse)
        queue.push_back({selected.entity, 1, {}, selected.metafile});
    std::vector<bool> seen_files(graph.entities.size()), seen_dirs(graph.entities.size());
    seen_dirs[selected.entity] = root_entity.directory();
    seen_files[selected.entity] = !root_entity.directory();
    for (std::size_t position = 0; position < queue.size(); ++position) {
        // Copy because appending child directories may reallocate the queue.
        const auto parent = queue[position];
        std::vector<TreeBuilder::NewNode> children;
        struct Child {
            std::size_t offset, entity;
            std::string relative;
            bool metafile;
        };
        std::vector<Child> directories;
        for (auto offset = graph.offsets[parent.entity]; offset < graph.offsets[parent.entity + 1];
             ++offset) {
            const auto &edge = graph.edges[offset];
            const auto &entity = graph.entities[edge.child];
            if (edge.blocked)
                continue;
            const bool metafile = parent.metafile || edge.metafile;
            if (metafile && !options.show_ntfs_metafiles)
                continue;
            auto flags = flags_of(entity, metafile);
            std::string relative;
            if (exclusions.needs_paths()) {
                relative = parent.relative;
                if (!relative.empty())
                    relative.push_back('/');
                relative.append(edge.name->name);
            }
            if (exclusions.excluded(relative, edge.name->name, flags))
                continue;
            if (entity.directory()) {
                if (seen_dirs[edge.child])
                    continue;
                seen_dirs[edge.child] = true;
            } else {
                if (seen_files[edge.child] && options.hardlinks == HardlinkMode::Dedup)
                    flags = static_cast<std::uint16_t>(flags | kHardlinkDup);
                seen_files[edge.child] = true;
            }
            if (entity.directory() && !entity.reparse)
                directories.push_back({children.size(), edge.child, std::move(relative), metafile});
            children.push_back(node_for(entity, edge.name->name, flags));
        }
        const auto [first, last] = builder.add_children(parent.node, children);
        (void)last;
        for (auto &directory : directories)
            queue.push_back({directory.entity, first + static_cast<NodeId>(directory.offset),
                             std::move(directory.relative), directory.metafile});
    }
    return std::move(builder).finish(std::move(meta));
}

} // namespace dafree
