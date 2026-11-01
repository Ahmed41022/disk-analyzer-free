#define PCRE2_CODE_UNIT_WIDTH 8
#include <pcre2.h>

#include "../thread_pool.hpp"
#include "view_internal.hpp"

#include <algorithm>
#include <atomic>
#include <bit>
#include <cstddef>
#include <cstdlib>
#include <exception>
#include <thread>

namespace dafree::detail {
namespace {

constexpr std::size_t regex_limit = 1u << 20;

struct CompileMemory {
    struct alignas(std::max_align_t) Header {
        std::size_t size;
    };
    std::size_t live = 0;
    bool rejected = false;
    static void *allocate(PCRE2_SIZE size, void *data) noexcept {
        auto &self = *static_cast<CompileMemory *>(data);
        if (size > regex_limit - self.live || sizeof(Header) > regex_limit - self.live - size) {
            self.rejected = true;
            return nullptr;
        }
        auto *header = static_cast<Header *>(std::malloc(size + sizeof(Header)));
        if (!header)
            return nullptr;
        header->size = size + sizeof(Header);
        self.live += header->size;
        return header + 1;
    }
    static void release(void *pointer, void *data) noexcept {
        if (!pointer)
            return;
        auto *header = static_cast<Header *>(pointer) - 1;
        static_cast<CompileMemory *>(data)->live -= header->size;
        std::free(header);
    }
};

class Regex {
  public:
    explicit Regex(std::string_view pattern) {
        if (pattern.size() > regex_limit)
            throw std::invalid_argument("regular expression exceeds the 1 MiB compilation limit");
        std::unique_ptr<pcre2_general_context, decltype(&pcre2_general_context_free)> general(
            pcre2_general_context_create(CompileMemory::allocate, CompileMemory::release, &memory_),
            pcre2_general_context_free);
        if (!general)
            throw std::bad_alloc();
        std::unique_ptr<pcre2_compile_context, decltype(&pcre2_compile_context_free)> context(
            pcre2_compile_context_create(general.get()), pcre2_compile_context_free);
        if (!context)
            throw std::bad_alloc();
        pcre2_set_max_pattern_length(context.get(), regex_limit);
        int error = 0;
        PCRE2_SIZE offset = 0;
        code_ = pcre2_compile(reinterpret_cast<PCRE2_SPTR>(pattern.data()), pattern.size(),
                              PCRE2_UTF | PCRE2_UCP | PCRE2_CASELESS | PCRE2_MATCH_INVALID_UTF,
                              &error, &offset, context.get());
        if (!code_) {
            if (memory_.rejected)
                throw std::invalid_argument(
                    "regular expression exceeds the 1 MiB compilation budget");
            if (error == PCRE2_ERROR_NOMEMORY)
                throw std::bad_alloc();
            PCRE2_UCHAR message[256]{};
            pcre2_get_error_message(error, message, sizeof(message));
            throw std::invalid_argument(std::string(reinterpret_cast<const char *>(message)) +
                                        " at pattern byte " + std::to_string(offset));
        }
    }
    ~Regex() { pcre2_code_free(code_); }
    Regex(const Regex &) = delete;
    Regex &operator=(const Regex &) = delete;
    pcre2_code *code() const { return code_; }

  private:
    CompileMemory memory_;
    pcre2_code *code_ = nullptr;
};

enum class Truth { No, Yes, PendingOwner };

struct Context {
    CompiledGlob::Workspace glob;
    std::string path;
    std::vector<NodeId> ancestors;
    std::unique_ptr<pcre2_match_data, decltype(&pcre2_match_data_free)> match{
        nullptr, pcre2_match_data_free};
    std::unique_ptr<pcre2_match_context, decltype(&pcre2_match_context_free)> limits{
        nullptr, pcre2_match_context_free};

    void prepare_regex() {
        if (match)
            return;
        match.reset(pcre2_match_data_create(1, nullptr));
        limits.reset(pcre2_match_context_create(nullptr));
        if (!match || !limits)
            throw std::bad_alloc();
        pcre2_set_heap_limit(limits.get(), 1024);
        pcre2_set_match_limit(limits.get(), 1'000'000);
    }

    std::string_view full_path(const Tree &tree, NodeId id) {
        ancestors.clear();
        for (auto cursor = id; cursor != kRoot && cursor != kNone;) {
            ancestors.push_back(cursor);
            cursor = tree.node(cursor).parent;
        }
        path.clear();
        for (auto cursor = ancestors.rbegin(); cursor != ancestors.rend(); ++cursor) {
            if (!path.empty() && path.back() != '/' && path.back() != '\\')
                path.push_back('/');
            path.append(tree.name_bytes(*cursor));
        }
#ifdef _WIN32
        std::replace(path.begin(), path.end(), '\\', '/');
        if (path.starts_with("//?/UNC/"))
            path.erase(2, 6);
        else if (path.starts_with("//?/"))
            path.erase(0, 4);
#endif
        return path;
    }
};

bool compare(std::uint64_t value, Cmp64 cmp) {
    switch (cmp.op) {
    case Cmp64::Lt:
        return value < cmp.v;
    case Cmp64::Le:
        return value <= cmp.v;
    case Cmp64::Eq:
        return value == cmp.v;
    case Cmp64::Ge:
        return value >= cmp.v;
    case Cmp64::Gt:
        return value > cmp.v;
    }
    throw std::invalid_argument("unknown comparison operator");
}

std::string_view basename(const Tree &tree, NodeId id) {
    auto name = tree.name_bytes(id);
    if (tree.node(id).parent != kRoot)
        return name;
#ifdef _WIN32
    constexpr std::string_view separators = "/\\";
#else
    constexpr std::string_view separators = "/";
#endif
    while (!name.empty() && separators.find(name.back()) != std::string_view::npos)
        name.remove_suffix(1);
    const auto end = name.find_last_of(separators);
    return end == std::string_view::npos ? name : name.substr(end + 1);
}

unsigned cost(FilterSpec::Kind kind) {
    using K = FilterSpec::Kind;
    switch (kind) {
    case K::Flag:
    case K::Type:
        return 0;
    case K::Size:
    case K::Alloc:
    case K::Files:
        return 1;
    case K::Ext:
        return 2;
    case K::Time:
        return 3;
    case K::NameGlob:
    case K::PathGlob:
        return 4;
    case K::Regex:
        return 5;
    case K::Owner:
        return 6;
    default:
        return 0;
    }
}

struct Expression {
    FilterSpec::Kind kind;
    Cmp64 cmp;
    TimeField time;
    std::uint16_t flag;
    bool type_dir;
    std::vector<std::unique_ptr<Expression>> children;
    std::vector<CompiledGlob> patterns;
    std::unique_ptr<Regex> regex;
    unsigned rank;

    explicit Expression(const FilterSpec &spec, unsigned depth = 1)
        : kind(spec.kind), cmp(spec.cmp), time(spec.time_field), flag(spec.flag),
          type_dir(spec.type_dir), rank(cost(spec.kind)) {
        using K = FilterSpec::Kind;
        if (depth > 32)
            throw std::invalid_argument("filter expression depth exceeds 32");
        if (kind == K::And || kind == K::Or || kind == K::Not) {
            if (kind == K::Not && spec.children.size() != 1)
                throw std::invalid_argument("Not requires exactly one child");
            for (const auto &child : spec.children) {
                auto compiled = std::make_unique<Expression>(child, depth + 1);
                if (kind == K::And && compiled->kind == K::And) {
                    for (auto &grandchild : compiled->children)
                        children.push_back(std::move(grandchild));
                } else {
                    children.push_back(std::move(compiled));
                }
            }
            if (kind == K::And)
                std::stable_sort(children.begin(), children.end(),
                                 [](const auto &a, const auto &b) { return a->rank < b->rank; });
            for (const auto &child : children)
                rank = std::max(rank, child->rank);
        } else if (!spec.children.empty()) {
            throw std::invalid_argument("a filter leaf cannot contain children");
        }
        if (kind == K::Ext || kind == K::NameGlob || kind == K::PathGlob || kind == K::Owner) {
            for (std::string_view value : spec.values) {
                if (kind == K::Ext && value.starts_with('.'))
                    value.remove_prefix(1);
                patterns.push_back(CompiledGlob::compile(value, true));
            }
        }
        if (kind == K::Regex)
            regex = std::make_unique<Regex>(spec.regex);
        if (static_cast<unsigned>(kind) > static_cast<unsigned>(K::Flag))
            throw std::invalid_argument("unknown filter kind");
        if (static_cast<unsigned>(cmp.op) > static_cast<unsigned>(Cmp64::Gt))
            throw std::invalid_argument("unknown comparison operator");
        if (time != TimeField::Modified && time != TimeField::Created &&
            time != TimeField::Accessed)
            throw std::invalid_argument("unknown timestamp field");
    }

    bool any(std::string_view value, Context &context, bool windows = false) const {
        return std::any_of(patterns.begin(), patterns.end(), [&](const auto &pattern) {
            return pattern.matches(value, windows, context.glob);
        });
    }

    Truth evaluate(const Tree &tree, NodeId id, Context &context, bool allow_pending) const {
        using K = FilterSpec::Kind;
        const auto &node = tree.node(id);
        const auto truth = [](bool value) { return value ? Truth::Yes : Truth::No; };
        switch (kind) {
        case K::And: {
            bool pending = false;
            for (const auto &child : children) {
                const auto value = child->evaluate(tree, id, context, allow_pending);
                if (value == Truth::No)
                    return Truth::No;
                pending = pending || value == Truth::PendingOwner;
            }
            return pending ? Truth::PendingOwner : Truth::Yes;
        }
        case K::Or: {
            bool pending = false;
            for (const auto &child : children) {
                const auto value = child->evaluate(tree, id, context, allow_pending);
                if (value == Truth::Yes)
                    return Truth::Yes;
                pending = pending || value == Truth::PendingOwner;
            }
            return pending ? Truth::PendingOwner : Truth::No;
        }
        case K::Not: {
            const auto value = children.front()->evaluate(tree, id, context, allow_pending);
            return value == Truth::PendingOwner ? value : truth(value == Truth::No);
        }
        case K::Size:
            return truth(compare(node.size, cmp));
        case K::Alloc:
            return truth(compare(node.alloc, cmp));
        case K::Files:
            return truth(compare(tree.counts(id).files, cmp));
        case K::Type:
            return truth(((node.flags & kDir) != 0) == type_dir);
        case K::Flag:
            return truth((node.flags & flag) == flag);
        case K::Ext:
            return truth(any(tree.ext(id).value_or(""), context));
        case K::NameGlob:
            return truth(any(basename(tree, id), context));
        case K::PathGlob:
            return truth(any(context.full_path(tree, id), context,
#ifdef _WIN32
                             true
#else
                             false
#endif
                             ));
        case K::Owner: {
            const auto owner = tree.owner_name(id);
            if (owner && !owner->empty())
                return truth(any(*owner, context));
            return allow_pending && node.owner != 0 ? Truth::PendingOwner : Truth::No;
        }
        case K::Time: {
            const auto value = time == TimeField::Modified  ? node.mtime
                               : time == TimeField::Created ? node.btime
                                                            : node.atime;
            return truth((value != 0 || (cmp.op == Cmp64::Eq && cmp.v == 0)) &&
                         compare(value, cmp));
        }
        case K::Regex: {
            context.prepare_regex();
            const auto name = basename(tree, id);
            const int result =
                pcre2_match(regex->code(), reinterpret_cast<PCRE2_SPTR>(name.data()), name.size(),
                            0, 0, context.match.get(), context.limits.get());
            if (result < 0 && result != PCRE2_ERROR_NOMATCH)
                throw std::runtime_error(
                    "regular expression match failed (resource limit or engine error): " +
                    std::to_string(result));
            return truth(result >= 0);
        }
        }
        throw std::invalid_argument("unknown filter kind");
    }
};

template <class Function> void parallel_words(std::size_t words, Function function) {
    std::atomic<std::size_t> next{0};
    std::atomic<bool> stop{false};
    std::exception_ptr failure;
    std::mutex mutex;
    const auto work = [&] {
        try {
            Context context;
            while (!stop.load(std::memory_order_relaxed)) {
                const auto begin = next.fetch_add(64, std::memory_order_relaxed);
                if (begin >= words)
                    break;
                const auto end = std::min(words, begin + 64);
                for (auto word = begin; word < end; ++word)
                    function(word, context);
            }
        } catch (...) {
            std::lock_guard lock(mutex);
            if (!failure)
                failure = std::current_exception();
            stop.store(true, std::memory_order_relaxed);
        }
    };
    if (words < 128) {
        work();
    } else {
        auto &pool = ThreadPool::analysis();
        pool.run(std::min(pool.size(), (words + 63) / 64), work);
    }
    if (failure)
        std::rethrow_exception(failure);
}

} // namespace

Visibility filter_visibility(const TreeHandle &handle, const std::optional<FilterSpec> &spec,
                             bool show_files,
                             const std::function<void(std::span<const NodeId>)> &resolve) {
    Visibility result;
    if (!spec)
        return result;
    Expression expression(*spec);
    ViewBits active, pending;
    handle.read([&](const Tree &tree) {
        const auto words = (static_cast<std::size_t>(tree.size()) + 63) / 64;
        result.eligible.words.resize(words);
        result.has_children.words.resize(words);
        active.words.resize(words);
        pending.words.resize(words);
        for (NodeId id = 0; id < tree.size(); ++id) {
            const auto &node = tree.node(id);
            if ((node.flags & kExcluded) == 0 && (node.parent == kNone || active.get(node.parent)))
                active.set(id);
        }
        parallel_words(words, [&](std::size_t word, Context &context) {
            std::uint64_t yes = 0, unknown = 0;
            const auto end = std::min<std::size_t>(tree.size(), (word + 1) * 64);
            for (auto index = word * 64; index < end; ++index) {
                const auto id = static_cast<NodeId>(index);
                if (!active.get(id))
                    continue;
                const auto value = expression.evaluate(tree, id, context, true);
                const auto bit = std::uint64_t{1} << (index % 64);
                if (value == Truth::Yes)
                    yes |= bit;
                else if (value == Truth::PendingOwner)
                    unknown |= bit;
            }
            result.eligible.words[word] = yes;
            pending.words[word] = unknown;
        });
    });
    std::vector<NodeId> candidates;
    for (std::size_t word = 0; word < pending.words.size(); ++word) {
        auto mask = pending.words[word];
        while (mask != 0) {
            const auto bit = static_cast<unsigned>(std::countr_zero(mask));
            candidates.push_back(static_cast<NodeId>(word * 64 + bit));
            mask &= mask - 1;
        }
    }
    if (!candidates.empty()) {
        resolve(candidates);
        handle.read([&](const Tree &tree) {
            parallel_words(pending.words.size(), [&](std::size_t word, Context &context) {
                auto mask = pending.words[word];
                auto matches = result.eligible.words[word];
                while (mask != 0) {
                    const auto bit = static_cast<unsigned>(std::countr_zero(mask));
                    const auto id = static_cast<NodeId>(word * 64 + bit);
                    if (expression.evaluate(tree, id, context, false) == Truth::Yes)
                        matches |= std::uint64_t{1} << bit;
                    mask &= mask - 1;
                }
                result.eligible.words[word] = matches;
            });
        });
    }
    handle.read([&](const Tree &tree) {
        for (auto cursor = tree.size(); cursor > 0; --cursor) {
            const auto id = cursor - 1;
            if (!result.eligible.get(id))
                continue;
            const auto &node = tree.node(id);
            if (node.parent != kNone)
                result.eligible.set(node.parent);
        }
        for (NodeId id = 1; id < tree.size(); ++id) {
            const auto &node = tree.node(id);
            if (result.eligible.get(id) && (show_files || (node.flags & kDir) != 0))
                result.has_children.set(node.parent);
        }
    });
    result.filtered = true;
    return result;
}

} // namespace dafree::detail
