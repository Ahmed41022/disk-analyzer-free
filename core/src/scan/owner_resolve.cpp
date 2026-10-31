#include "dafree/scan.hpp"

#include <atomic>
#include <exception>
#include <thread>
#include <unordered_set>

namespace dafree {

void resolve_owners(TreeHandle &handle, std::span<const NodeId> ids, FsBackend &backend) {
    // Serialize resolution batches while allowing ordinary readers throughout slow lookups.
    std::lock_guard batch_lock(handle.owner_resolution_mutex_);
    struct Lookup {
        NodeId node;
        OwnerKey key;
        std::string path;
        std::optional<std::pair<OwnerKey, std::string>> result;
    };
    std::vector<Lookup> lookups;
    handle.read([&](const Tree &tree) {
        std::unordered_set<std::uint32_t> seen;
        for (const auto id : ids) {
            const auto owner = tree.node(id).owner;
            if (owner == 0 || !tree.owners_.get(owner).empty() || !seen.insert(owner).second)
                continue;
            lookups.push_back({id, *tree.owners_.key(owner), tree.path_bytes(id), {}});
        }
    });
    if (lookups.empty())
        return;
    std::atomic<std::size_t> next{0};
    std::exception_ptr failure;
    std::mutex failure_mutex;
    const auto work = [&] {
        try {
            for (;;) {
                const auto index = next.fetch_add(1, std::memory_order_relaxed);
                if (index >= lookups.size())
                    break;
                auto &lookup = lookups[index];
                try {
                    lookup.result = backend.resolve_owner(lookup.path, &lookup.key);
                } catch (const IoError &) {
                    // A vanished path does not invalidate the rest of this batch.
                }
            }
        } catch (...) {
            std::lock_guard lock(failure_mutex);
            if (!failure)
                failure = std::current_exception();
        }
    };
    const auto count = std::min<std::size_t>(
        lookups.size(), std::min(8u, std::max(1u, std::thread::hardware_concurrency())));
    std::vector<std::thread> workers;
    try {
        for (std::size_t i = 1; i < count; ++i)
            workers.emplace_back(work);
    } catch (...) {
        for (auto &worker : workers)
            worker.join();
        throw;
    }
    work();
    for (auto &worker : workers)
        worker.join();
    if (failure)
        std::rethrow_exception(failure);
    std::unique_lock lock(handle.mutex_);
    auto &tree = *std::const_pointer_cast<Tree>(handle.tree_);
    for (const auto &lookup : lookups)
        if (lookup.result)
            tree.set_owner(lookup.node, lookup.result->first, lookup.result->second);
}

} // namespace dafree
