#include "dafree/scan.hpp"
#include "glob.hpp"

#include <algorithm>
#include <optional>

namespace dafree {
namespace {

#if defined(_WIN32) || defined(__APPLE__)
constexpr bool ignore_case = true;
#else
constexpr bool ignore_case = false;
#endif
#ifdef _WIN32
constexpr bool windows_paths = true;
#else
constexpr bool windows_paths = false;
#endif

std::string normalized_path(std::string_view input) {
    std::string path(input);
    if (windows_paths) {
        std::replace(path.begin(), path.end(), '\\', '/');
        if (path.starts_with("//?/UNC/"))
            path = "//" + path.substr(8);
        else if (path.starts_with("//?/"))
            path.erase(0, 4);
    }
    const bool absolute = windows_paths ? ((path.size() >= 3 && path[1] == ':' && path[2] == '/') ||
                                           path.starts_with("//"))
                                        : path.starts_with('/');
    if (!absolute)
        throw ExcludeError(std::string(input), "excluded paths must be absolute");
    std::size_t offset = windows_paths && path.size() >= 3 && path[1] == ':'
                             ? 3
                             : (windows_paths && path.starts_with("//") ? 2 : 1);
    std::string result = path.substr(0, offset);
    std::vector<std::string_view> components;
    while (offset < path.size()) {
        const auto end = path.find('/', offset);
        const auto stop = end == std::string::npos ? path.size() : end;
        const std::string_view component(path.data() + offset, stop - offset);
        if (component == "..") {
            if (!components.empty())
                components.pop_back();
        } else if (!component.empty() && component != ".")
            components.push_back(component);
        offset = stop + 1;
    }
    for (const auto component : components) {
        if (!result.ends_with('/'))
            result.push_back('/');
        result.append(component);
    }
    return result;
}

std::optional<std::size_t> under(std::string_view path, std::string_view prefix) {
    std::size_t left = 0, right = 0;
    while (right < prefix.size()) {
        if (left == path.size())
            return std::nullopt;
        auto a = detail::next_codepoint(path, left);
        auto b = detail::next_codepoint(prefix, right);
        if (windows_paths) {
            if (a == '\\')
                a = '/';
            if (b == '\\')
                b = '/';
        }
        if (ignore_case) {
            a = detail::fold_codepoint(a);
            b = detail::fold_codepoint(b);
        }
        if (a != b)
            return std::nullopt;
    }
    if (left == path.size() || prefix.ends_with('/') || path[left] == '/' ||
        (windows_paths && path[left] == '\\'))
        return left;
    return std::nullopt;
}

bool directory(EntryKind kind) {
    return kind == EntryKind::Dir || kind == EntryKind::MountPoint || kind == EntryKind::Junction;
}

} // namespace

struct CompiledExcludes::Impl {
    struct GlobRule {
        detail::CompiledGlob glob;
        bool by_name = false;
        bool directory_only = false;
        std::optional<detail::CompiledGlob> directory_prefix;
    };
    bool all = false, hidden = false, system = false;
    std::vector<std::string> paths;
    std::vector<GlobRule> globs;
};

CompiledExcludes CompiledExcludes::compile(const ExcludeRules &rules, std::string_view root) {
    auto impl = std::make_shared<Impl>();
    impl->hidden = rules.hidden;
    impl->system = rules.system;
    const auto normalized_root = normalized_path(root);
    for (const auto &path : rules.paths) {
        const auto absolute = normalized_path(path);
        if (under(normalized_root, absolute))
            impl->all = true;
        else if (const auto offset = under(absolute, normalized_root)) {
            std::size_t start = *offset;
            while (start < absolute.size() && absolute[start] == '/')
                ++start;
            impl->paths.push_back(absolute.substr(start));
        }
    }
    for (const auto &input : rules.globs) {
        const auto compile_glob = [&](std::string_view source) {
            try {
                return detail::CompiledGlob::compile(source, ignore_case);
            } catch (const ExcludeError &error) {
                throw ExcludeError(input, error.what());
            }
        };
        std::string_view pattern(input);
        bool anchored = pattern.starts_with('/');
        if (anchored)
            pattern.remove_prefix(1);
        if (pattern.starts_with("./")) {
            pattern.remove_prefix(2);
            anchored = true;
        }
        const bool directory_only = pattern.ends_with('/');
        if (directory_only)
            pattern.remove_suffix(1);
        if (pattern.empty())
            throw ExcludeError(input, "empty exclusion glob");
        Impl::GlobRule rule{compile_glob(pattern),
                            !anchored && pattern.find('/') == std::string_view::npos,
                            directory_only, std::nullopt};
        if (pattern.ends_with("/**"))
            rule.directory_prefix = compile_glob(pattern.substr(0, pattern.size() - 3));
        impl->globs.push_back(std::move(rule));
    }
    return CompiledExcludes(std::move(impl));
}

bool CompiledExcludes::excluded(std::string_view rel_path, std::string_view name,
                                const RawEntry &entry) const {
    if (impl_->all)
        return true;
    if (impl_->hidden && (entry.hidden || (!windows_paths && name.starts_with('.'))))
        return true;
    if (windows_paths && impl_->system && entry.system)
        return true;
    for (const auto &path : impl_->paths)
        if (under(rel_path, path))
            return true;
    for (const auto &rule : impl_->globs) {
        if (rule.directory_only && !directory(entry.kind))
            continue;
        if (rule.glob.matches(rule.by_name ? name : rel_path, !rule.by_name && windows_paths))
            return true;
        if (directory(entry.kind) && rule.directory_prefix &&
            rule.directory_prefix->matches(rel_path, windows_paths))
            return true;
    }
    return false;
}

} // namespace dafree
