#include "bindings.hpp"

#include <nanobind/stl/optional.h>
#include <nanobind/stl/pair.h>
#include <nanobind/stl/shared_ptr.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>

namespace dafree::bindings {
namespace {

struct NodeInfo {
    NodeId id;
    std::optional<NodeId> parent;
    std::uint16_t flags;
    std::uint64_t size, alloc;
    std::uint32_t files, dirs;
    std::optional<std::uint32_t> mtime, btime, atime;
    std::optional<std::string> owner, ext;
};

std::optional<std::string> owned(std::optional<std::string_view> value) {
    if (!value || value->empty())
        return std::nullopt;
    return std::string(*value);
}

std::optional<nb::str> decoded(const std::optional<std::string> &value) {
    if (!value)
        return std::nullopt;
    return decode_native(*value);
}

NodeInfo node_info(const Tree &tree, NodeId id) {
    const auto &node = tree.node(id);
    const auto counts = tree.counts(id);
    const auto time = [](std::uint32_t value) -> std::optional<std::uint32_t> {
        return value == 0 ? std::nullopt : std::optional(value);
    };
    return {id,
            tree.parent(id),
            node.flags,
            node.size,
            node.alloc,
            counts.files,
            counts.dirs,
            time(node.mtime),
            time(node.btime),
            time(node.atime),
            owned(tree.owner_name(id)),
            owned(tree.ext(id))};
}

} // namespace

void bind_tree(nb::module_ &module) {
    nb::class_<MemoryReport>(module, "MemoryReport", nb::is_final(), "Reserved tree storage bytes.")
        .def_ro("nodes", &MemoryReport::nodes)
        .def_ro("counts", &MemoryReport::counts)
        .def_ro("names", &MemoryReport::names)
        .def_ro("interners", &MemoryReport::interners);
    nb::class_<NodeInfo>(module, "NodeInfo", nb::is_final(),
                         "Copied node metadata and descendant counts.")
        .def_ro("id", &NodeInfo::id)
        .def_ro("parent", &NodeInfo::parent)
        .def_ro("flags", &NodeInfo::flags)
        .def_ro("size", &NodeInfo::size)
        .def_ro("alloc", &NodeInfo::alloc)
        .def_ro("files", &NodeInfo::files)
        .def_ro("dirs", &NodeInfo::dirs)
        .def_ro("mtime", &NodeInfo::mtime)
        .def_ro("btime", &NodeInfo::btime)
        .def_ro("atime", &NodeInfo::atime)
        .def_prop_ro("owner", [](const NodeInfo &value) { return decoded(value.owner); })
        .def_prop_ro("ext", [](const NodeInfo &value) { return decoded(value.ext); });
    nb::class_<BoundTree>(module, "Tree", nb::is_final(),
                          "A shared tree with coherent reader locking.")
        .def("__len__",
             [](const BoundTree &self) {
                 return self.handle->read([](const Tree &tree) { return tree.size(); });
             })
        .def(
            "node",
            [](const BoundTree &self, NodeId id) {
                nb::gil_scoped_release release;
                return self.handle->read([&](const Tree &tree) { return node_info(tree, id); });
            },
            nb::arg("id"), "Copy node metadata.")
        .def(
            "name",
            [](const BoundTree &self, NodeId id) {
                std::string name;
                {
                    nb::gil_scoped_release release;
                    name = self.handle->read(
                        [&](const Tree &tree) { return std::string(tree.name_bytes(id)); });
                }
                return decode_native(name);
            },
            nb::arg("id"), "Return a lossless native entry name.")
        .def(
            "path",
            [](const BoundTree &self, NodeId id) {
                std::string path;
                {
                    nb::gil_scoped_release release;
                    path = self.handle->read([&](const Tree &tree) { return tree.path_bytes(id); });
                }
                return decode_native(path);
            },
            nb::arg("id"), "Reconstruct a lossless native path.")
        .def(
            "children",
            [](const BoundTree &self, NodeId id) {
                return self.handle->read([&](const Tree &tree) {
                    auto range = tree.children(id);
                    if (range.first == kNone)
                        range = {0, 0};
                    return range;
                });
            },
            nb::arg("id"), "Return the half-open contiguous child range.")
        .def(
            "parent",
            [](const BoundTree &self, NodeId id) {
                return self.handle->read([&](const Tree &tree) { return tree.parent(id); });
            },
            nb::arg("id"), "Return the parent ID, or None for the synthetic root.")
        .def(
            "roots",
            [](const BoundTree &self) {
                return self.handle->read([](const Tree &tree) {
                    const auto roots = tree.roots();
                    return std::vector<NodeId>(roots.begin(), roots.end());
                });
            },
            "Return scan target node IDs.")
        .def(
            "find_path",
            [](const BoundTree &self, nb::str input) {
                const auto path = encode_native(input);
                nb::gil_scoped_release release;
                return self.handle->read([&](const Tree &tree) { return tree.find_path(path); });
            },
            nb::arg("path"), "Find a native path within the scan.")
        .def(
            "meta",
            [](const BoundTree &self) {
                nb::gil_scoped_release release;
                return self.handle->read([](const Tree &tree) { return tree.meta(); });
            },
            "Copy scan provenance and diagnostics.")
        .def(
            "memory_usage",
            [](const BoundTree &self) {
                nb::gil_scoped_release release;
                return self.handle->read([](const Tree &tree) { return tree.memory_usage(); });
            },
            "Return reserved tree storage bytes.");
}

} // namespace dafree::bindings
