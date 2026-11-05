#include "dafree/mft.hpp"
#include "dafree/model.hpp"

#include <array>
#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <limits>
#include <span>
#include <vector>

namespace {

// Seed a valid, empty volume root so malformed fuzz records still reach tree building.
std::array<std::byte, 1024> root_record() {
    std::array<std::byte, 1024> bytes{};
    const auto put = [&](std::size_t offset, std::uint32_t value, std::size_t width) {
        for (std::size_t i = 0; i < width; ++i) {
            bytes[offset + i] = static_cast<std::byte>(value & 0xffu);
            value >>= 8;
        }
    };
    put(0, 0x454c4946u, 4); // FILE
    put(4, 0x30, 2);
    put(6, 3, 2);
    put(16, 1, 2);
    put(20, 0x38, 2);
    put(22, 3, 2);
    put(24, 0x40, 4);
    put(28, 1024, 4);
    put(0x30, 0xa55a, 2);
    put(0x38, 0xffffffffu, 4);
    put(510, 0xa55a, 2);
    put(1022, 0xa55a, 2);
    return bytes;
}

std::uint64_t add(std::uint64_t a, std::uint64_t b) {
    return b > std::numeric_limits<std::uint64_t>::max() - a
               ? std::numeric_limits<std::uint64_t>::max()
               : a + b;
}

} // namespace

/// Exercise raw-record ingestion and complete tree invariants without filesystem I/O.
extern "C" int LLVMFuzzerTestOneInput(const std::uint8_t *data, std::size_t size) {
    constexpr std::size_t max_input_bytes = 1024u * 1024u;
    if (size > max_input_bytes)
        return 0;
    auto root = root_record();
    const auto input = std::as_bytes(std::span<const std::uint8_t>(data, size));
    std::vector<std::byte> record(input.begin(), input.end());
    dafree::MftIndex index;
    index.ingest(5, root, 512);
    index.ingest(16, record, 512);
    dafree::ScanOptions options;
    dafree::IssueSink sink;
#ifdef _WIN32
    constexpr auto path = "C:\\ntfs";
#else
    constexpr auto path = "/ntfs";
#endif
    const auto tree = dafree::build_tree_from_mft(index, path, std::nullopt, options, sink);
    if (tree.size() < 2 || tree.roots().size() != 1 || tree.roots()[0] == 0 ||
        tree.roots()[0] >= tree.size() || tree.node(tree.roots()[0]).parent != 0 ||
        tree.node(0).parent != dafree::kNone)
        std::abort();
    for (dafree::NodeId id = 0; id < tree.size(); ++id) {
        const auto &node = tree.node(id);
        if (id != 0) {
            if (node.parent >= id)
                std::abort();
            const auto &parent = tree.node(node.parent);
            if ((parent.flags & dafree::kDir) == 0 || parent.first_child > id ||
                id - parent.first_child >= parent.child_count)
                std::abort();
        }
        if (node.child_count == 0) {
            if (node.first_child != dafree::kNone || tree.counts(id).files != 0 ||
                tree.counts(id).dirs != 0 ||
                ((node.flags & dafree::kDir) != 0 && (node.size != 0 || node.alloc != 0)))
                std::abort();
            continue;
        }
        if ((node.flags & dafree::kDir) == 0 || node.first_child <= id ||
            node.first_child >= tree.size() || node.child_count > tree.size() - node.first_child)
            std::abort();
        std::uint64_t logical = 0, allocated = 0;
        std::uint64_t files = 0, dirs = 0;
        for (auto child = node.first_child; child < node.first_child + node.child_count; ++child) {
            const auto &entry = tree.node(child);
            if (entry.parent != id)
                std::abort();
            if ((entry.flags & (dafree::kHardlinkDup | dafree::kExcluded)) == 0) {
                logical = add(logical, entry.size);
                allocated = add(allocated, entry.alloc);
            }
            if ((entry.flags & dafree::kExcluded) == 0) {
                files += (entry.flags & dafree::kDir) != 0 ? tree.counts(child).files : 1;
                dirs +=
                    (entry.flags & dafree::kDir) != 0 ? UINT64_C(1) + tree.counts(child).dirs : 0;
            }
        }
        if (node.size != logical || node.alloc != allocated || tree.counts(id).files != files ||
            tree.counts(id).dirs != dirs)
            std::abort();
    }
    const auto &issues = tree.meta().issues;
    std::uint64_t issue_count = 0;
    for (const auto count : issues.counts)
        issue_count = add(issue_count, count);
    if (issue_count != issues.total || issues.first.size() > 1000 ||
        issues.first.size() > issues.total || issues.overflow != issues.total - issues.first.size())
        std::abort();
    return 0;
}
