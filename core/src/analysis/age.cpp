#include "common.hpp"

#include <algorithm>
#include <stdexcept>

namespace dafree {

auto age_histogram(const Tree &tree, NodeId scope, TimeField field,
                   std::span<const AgeBucket> buckets, std::uint32_t now) -> std::vector<AgeStat> {
    if (buckets.empty() || buckets.back().max_age_secs)
        throw std::invalid_argument("the last age bucket must be unbounded");

    std::uint64_t previous_cutoff = 0;
    for (const auto &bucket : buckets.first(buckets.size() - 1)) {
        if (!bucket.max_age_secs || *bucket.max_age_secs <= previous_cutoff)
            throw std::invalid_argument("age bucket cutoffs must be positive and increasing");
        previous_cutoff = *bucket.max_age_secs;
    }

    std::uint32_t Node::*timestamp_member = nullptr;
    switch (field) {
    case TimeField::Modified:
        timestamp_member = &Node::mtime;
        break;
    case TimeField::Created:
        timestamp_member = &Node::btime;
        break;
    case TimeField::Accessed:
        timestamp_member = &Node::atime;
        break;
    }
    if (timestamp_member == nullptr)
        throw std::invalid_argument("unknown age time field");

    std::vector<AgeStat> result;
    result.reserve(buckets.size() + 1);
    for (std::size_t index = 0; index <= buckets.size(); ++index)
        result.push_back({index, 0, 0, 0});

    if (!analysis_detail::visible_scope(tree, scope)) {
        result.pop_back();
        return result;
    }

    analysis_detail::for_each_node(tree, scope, [&](NodeId id) {
        const auto &node = tree.node(id);
        if ((node.flags & kDir) != 0)
            return;

        const auto timestamp = node.*timestamp_member;
        std::size_t index = buckets.size();
        if (timestamp != 0) {
            const auto age = timestamp > now ? std::uint64_t{0} : std::uint64_t{now - timestamp};
            const auto bucket =
                std::lower_bound(buckets.begin(), buckets.end(), age,
                                 [](const AgeBucket &value, std::uint64_t target) {
                                     return value.max_age_secs && *value.max_age_secs <= target;
                                 });
            index = static_cast<std::size_t>(bucket - buckets.begin());
        }
        auto &stat = result[index];
        analysis_detail::add_file(stat, node);
    });

    if (result.back().files == 0)
        result.pop_back();
    return result;
}

} // namespace dafree
