#include "common.hpp"

#include <algorithm>
#include <unordered_map>

namespace dafree {

std::vector<ExtStat> ext_breakdown(const Tree &tree, NodeId scope) {
    if (!analysis_detail::visible_scope(tree, scope))
        return {};

    std::unordered_map<std::string_view, ExtStat> grouped;
    analysis_detail::for_each_node(tree, scope, [&](NodeId id) {
        const auto &node = tree.node(id);
        if ((node.flags & kDir) != 0)
            return;

        const auto extension = tree.ext(id).value_or(std::string_view{});
        auto &stat = grouped[extension];
        analysis_detail::add_file(stat, node);
    });

    std::vector<ExtStat> result;
    result.reserve(grouped.size());
    for (auto &[extension, stat] : grouped) {
        stat.ext = extension;
        stat.category = classify_extension(extension);
        result.push_back(std::move(stat));
    }
    std::sort(result.begin(), result.end(), [](const ExtStat &left, const ExtStat &right) {
        if (left.size != right.size)
            return left.size > right.size;
        return left.ext < right.ext;
    });
    return result;
}

} // namespace dafree
