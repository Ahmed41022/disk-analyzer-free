#include "dafree/backend.hpp"

#include <algorithm>
#include <atomic>
#include <mutex>
#include <stdexcept>
#include <thread>
#include <unordered_set>

namespace dafree {

namespace {

std::string normalized(std::string_view input) {
    if (input.empty())
        throw std::invalid_argument("mock path is empty");
    std::string path(input);
#ifdef _WIN32
    std::replace(path.begin(), path.end(), '\\', '/');
#endif
    while (path.size() > 1 && path.back() == '/' && !(path.size() == 3 && path[1] == ':'))
        path.pop_back();
    return path;
}

bool directory(EntryKind kind) { return kind == EntryKind::Dir || kind == EntryKind::MountPoint; }

} // namespace

struct MockBackend::Impl {
    MockSpec spec;
    std::unordered_map<std::string_view, std::size_t> index;
    std::unordered_map<std::size_t, std::vector<std::size_t>> children;
    std::unordered_map<std::string, IssueKind> errors;
    std::unordered_set<std::string> vanish;
    mutable std::mutex vanished_mutex;
    std::unordered_set<std::size_t> vanished;
    std::atomic<std::uint64_t> reads{0}, owners{0};

    explicit Impl(MockSpec input) : spec(std::move(input)) {
        if (spec.delay.count() < 0)
            throw std::invalid_argument("mock delay must be non-negative");
        for (auto &item : spec.entries) {
            item.path = normalized(item.path);
            if (item.entry.name.empty()) {
                const auto separator = item.path.find_last_of('/');
                item.entry.name =
                    separator == std::string::npos ? item.path : item.path.substr(separator + 1);
                if (item.entry.name.empty())
                    item.entry.name = item.path;
            }
        }
        index.reserve(spec.entries.size());
        for (std::size_t id = 0; id < spec.entries.size(); ++id) {
            auto &metadata = spec.entries[id].entry;
            if (metadata.dev == 0)
                metadata.dev = 1;
            if (metadata.ino_lo == 0 && metadata.ino_hi == 0)
                metadata.ino_lo = id + 1;
            if (!index.emplace(spec.entries[id].path, id).second)
                throw std::invalid_argument("duplicate mock path");
        }
        for (std::size_t id = 0; id < spec.entries.size(); ++id) {
            const auto &path = spec.entries[id].path;
            const auto separator = path.find_last_of('/');
            if (separator == std::string::npos || path == "/" ||
                (path.size() == 3 && path[1] == ':'))
                continue;
            const std::size_t parent_length =
                separator == 0 ? 1 : (separator == 2 && path[1] == ':' ? 3 : separator);
            const std::string_view parent = std::string_view(path).substr(0, parent_length);
            const auto found = index.find(parent);
            if (found != index.end()) {
                if (!directory(spec.entries[found->second].entry.kind))
                    throw std::invalid_argument("mock parent is not a directory");
                children[found->second].push_back(id);
            }
        }
        for (const auto &[path, kind] : spec.errors)
            errors.emplace(normalized(path), kind);
        spec.errors.clear();
        for (const auto &path : spec.vanish_after_listing)
            vanish.insert(normalized(path));
        spec.vanish_after_listing.clear();
    }

    void pause() const {
        if (spec.delay.count() > 0)
            std::this_thread::sleep_for(spec.delay);
    }

    std::size_t lookup(const std::string &path) const {
        if (const auto fault = errors.find(path); fault != errors.end())
            throw IoError(path, fault->second, "injected mock error");
        const auto found = index.find(path);
        if (found == index.end())
            throw IoError(path, IssueKind::NotFound, "mock entry not found");
        {
            std::lock_guard guard(vanished_mutex);
            if (vanished.contains(found->second))
                throw IoError(path, IssueKind::NotFound, "mock entry vanished");
        }
        return found->second;
    }
};

MockBackend::MockBackend(MockSpec spec) : impl_(std::make_unique<Impl>(std::move(spec))) {}
MockBackend::~MockBackend() = default;
BackendKind MockBackend::kind() const { return BackendKind::Local; }

RawEntry MockBackend::stat_root(std::string_view path) {
    impl_->pause();
    return impl_->spec.entries[impl_->lookup(normalized(path))].entry;
}

DirListing MockBackend::read_dir(std::string_view path, const DirHint &) {
    impl_->reads.fetch_add(1, std::memory_order_relaxed);
    impl_->pause();
    const auto key = normalized(path);
    const auto id = impl_->lookup(key);
    if (!directory(impl_->spec.entries[id].entry.kind))
        throw IoError(key, IssueKind::NotFound, "mock entry is not a directory");
    DirListing listing;
    const auto children = impl_->children.find(id);
    if (children == impl_->children.end())
        return listing;
    listing.entries.reserve(children->second.size());
    for (const auto child : children->second) {
        const auto &item = impl_->spec.entries[child];
        if (impl_->vanish.contains(item.path)) {
            {
                std::lock_guard guard(impl_->vanished_mutex);
                impl_->vanished.insert(child);
            }
            listing.partial = true;
            listing.issues.push_back(
                {item.path, IssueKind::NotFound, "mock entry vanished during listing"});
            continue;
        }
        if (const auto fault = impl_->errors.find(item.path);
            fault != impl_->errors.end() && !directory(item.entry.kind)) {
            listing.partial = true;
            listing.issues.push_back({item.path, fault->second, "injected mock metadata error"});
            if (fault->second == IssueKind::AccessDenied) {
                auto denied = item.entry;
                denied.size = denied.alloc = 0;
                denied.access_denied = true;
                listing.entries.push_back(std::move(denied));
            }
            continue;
        }
        listing.entries.push_back(item.entry);
    }
    return listing;
}

std::optional<VolumeInfo> MockBackend::volume_info(std::string_view path) {
    impl_->pause();
    try {
        (void)impl_->lookup(normalized(path));
    } catch (const IoError &) {
        return std::nullopt;
    }
    return impl_->spec.volume;
}

std::optional<std::pair<OwnerKey, std::string>> MockBackend::resolve_owner(std::string_view path,
                                                                           const OwnerKey *hint) {
    impl_->owners.fetch_add(1, std::memory_order_relaxed);
    impl_->pause();
    std::optional<OwnerKey> key;
    if (hint != nullptr)
        key = *hint;
    else {
        try {
            key = impl_->spec.entries[impl_->lookup(normalized(path))].entry.owner;
        } catch (const IoError &) {
            return std::nullopt;
        }
    }
    if (!key)
        return std::nullopt;
    if (key->kind != OwnerKey::Kind::PosixUid)
        return std::pair{*key, key->value};
    const auto found = impl_->spec.owner_names.find(key->uid);
    return std::pair{*key, found == impl_->spec.owner_names.end() ? std::to_string(key->uid)
                                                                  : found->second};
}

std::uint64_t MockBackend::read_dir_calls() const noexcept {
    return impl_->reads.load(std::memory_order_relaxed);
}

std::uint64_t MockBackend::owner_resolution_calls() const noexcept {
    return impl_->owners.load(std::memory_order_relaxed);
}

std::shared_ptr<FsBackend> make_mock_backend(MockSpec spec) {
    return std::make_shared<MockBackend>(std::move(spec));
}

} // namespace dafree
