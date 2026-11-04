#include "bindings.hpp"
#include "dafree/analysis.hpp"
#include "dafree/view.hpp"

#include <nanobind/stl/optional.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/vector.h>

namespace dafree::bindings {

void bind_analysis(nb::module_ &module) {
    nb::enum_<TopKind>(module, "TopKind")
        .value("FILES", TopKind::Files)
        .value("DIRS", TopKind::Dirs);
    nb::class_<ExtStat>(module, "ExtStat")
        .def_prop_ro("ext", [](const ExtStat &stat) { return decode_native(stat.ext); })
        .def_ro("files", &ExtStat::files)
        .def_ro("size", &ExtStat::size)
        .def_ro("alloc", &ExtStat::alloc)
        .def_ro("category", &ExtStat::category);
    nb::class_<AgeBucket>(module, "AgeBucket")
        .def(nb::init<std::string, std::optional<std::uint64_t>>(), nb::arg("label"),
             nb::arg("max_age_secs").none())
        .def_ro("label", &AgeBucket::label)
        .def_ro("max_age_secs", &AgeBucket::max_age_secs);
    nb::class_<AgeStat>(module, "AgeStat")
        .def_ro("bucket", &AgeStat::bucket)
        .def_ro("files", &AgeStat::files)
        .def_ro("size", &AgeStat::size)
        .def_ro("alloc", &AgeStat::alloc);
    module.def(
        "top_n",
        [](const BoundTree &bound, NodeId scope, TopKind kind, std::size_t n, SortKey by,
           bool leaf_only) {
            return bound.handle->read(
                [&](const Tree &tree) { return top_n(tree, scope, kind, n, by, leaf_only); });
        },
        nb::arg("tree"), nb::arg("scope"), nb::arg("kind"), nb::arg("n"), nb::arg("by"),
        nb::arg("leaf_only") = false, nb::call_guard<nb::gil_scoped_release>(),
        "Rank file or directory IDs within the selected scope.");
    module.def(
        "ext_breakdown",
        [](const BoundTree &bound, NodeId scope) {
            return bound.handle->read([&](const Tree &tree) { return ext_breakdown(tree, scope); });
        },
        nb::arg("tree"), nb::arg("scope"), nb::call_guard<nb::gil_scoped_release>(),
        "Group file counts and bytes by extension.");
    module.def(
        "age_histogram",
        [](const BoundTree &bound, NodeId scope, TimeField field,
           const std::vector<AgeBucket> &buckets, std::uint32_t now) {
            return bound.handle->read(
                [&](const Tree &tree) { return age_histogram(tree, scope, field, buckets, now); });
        },
        nb::arg("tree"), nb::arg("scope"), nb::arg("field"), nb::arg("buckets"), nb::arg("now"),
        nb::call_guard<nb::gil_scoped_release>(), "Partition file counts and bytes by age.");
}

} // namespace dafree::bindings
