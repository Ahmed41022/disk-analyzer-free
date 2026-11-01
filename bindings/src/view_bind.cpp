#include "../../core/src/thread_pool.hpp"
#include "bindings.hpp"
#include "dafree/view.hpp"

#include <nanobind/stl/optional.h>
#include <nanobind/stl/shared_ptr.h>
#include <nanobind/stl/vector.h>

namespace dafree::bindings {

void bind_view(nb::module_ &module) {
    // Python callbacks finish before Windows unloads this DLL under the loader lock.
    // Workers never call Python, so joining them with the GIL released is safe.
    nb::module_::import_("atexit").attr("register")(nb::cpp_function(
        &detail::ThreadPool::shutdown_analysis, nb::call_guard<nb::gil_scoped_release>()));
    nb::enum_<TimeField>(module, "TimeField")
        .value("MODIFIED", TimeField::Modified)
        .value("CREATED", TimeField::Created)
        .value("ACCESSED", TimeField::Accessed);
    nb::enum_<ExtCategory>(module, "ExtCategory")
        .value("IMAGE", ExtCategory::Image)
        .value("VIDEO", ExtCategory::Video)
        .value("AUDIO", ExtCategory::Audio)
        .value("ARCHIVE", ExtCategory::Archive)
        .value("DOCUMENT", ExtCategory::Document)
        .value("CODE", ExtCategory::Code)
        .value("EXECUTABLE", ExtCategory::Executable)
        .value("DISK_IMAGE", ExtCategory::DiskImage)
        .value("SYSTEM", ExtCategory::System)
        .value("OTHER", ExtCategory::Other);
    nb::enum_<SortKey>(module, "SortKey")
        .value("NAME", SortKey::Name)
        .value("SIZE", SortKey::Size)
        .value("ALLOC", SortKey::Alloc)
        .value("PCT_PARENT", SortKey::PctParent)
        .value("FILES", SortKey::Files)
        .value("DIRS", SortKey::Dirs)
        .value("MTIME", SortKey::Mtime)
        .value("OWNER", SortKey::Owner)
        .value("EXT", SortKey::Ext);
    nb::enum_<Cmp64::Op>(module, "CmpOp")
        .value("LT", Cmp64::Lt)
        .value("LE", Cmp64::Le)
        .value("EQ", Cmp64::Eq)
        .value("GE", Cmp64::Ge)
        .value("GT", Cmp64::Gt);
    nb::class_<Cmp64>(module, "Cmp64", "Unsigned numeric filter comparison.")
        .def(nb::init<>())
        .def_rw("op", &Cmp64::op)
        .def_rw("v", &Cmp64::v);
    nb::enum_<FilterSpec::Kind>(module, "FilterKind")
        .value("AND", FilterSpec::Kind::And)
        .value("OR", FilterSpec::Kind::Or)
        .value("NOT", FilterSpec::Kind::Not)
        .value("SIZE", FilterSpec::Kind::Size)
        .value("ALLOC", FilterSpec::Kind::Alloc)
        .value("EXT", FilterSpec::Kind::Ext)
        .value("NAME_GLOB", FilterSpec::Kind::NameGlob)
        .value("PATH_GLOB", FilterSpec::Kind::PathGlob)
        .value("REGEX", FilterSpec::Kind::Regex)
        .value("OWNER", FilterSpec::Kind::Owner)
        .value("TIME", FilterSpec::Kind::Time)
        .value("TYPE", FilterSpec::Kind::Type)
        .value("FILES", FilterSpec::Kind::Files)
        .value("FLAG", FilterSpec::Kind::Flag);
    nb::class_<FilterSpec>(module, "FilterSpec", "Copied native filter expression.")
        .def(nb::init<>())
        .def_rw("kind", &FilterSpec::kind)
        .def_rw("children", &FilterSpec::children)
        .def_rw("cmp", &FilterSpec::cmp)
        .def_rw("time_field", &FilterSpec::time_field)
        .def_prop_rw(
            "values", [](const FilterSpec &self) { return decode_strings(self.values); },
            [](FilterSpec &self, const std::vector<nb::str> &values) {
                self.values = encode_strings(values);
            })
        .def_prop_rw(
            "regex", [](const FilterSpec &self) { return decode_native(self.regex); },
            [](FilterSpec &self, nb::str value) { self.regex = encode_native(value); })
        .def_rw("flag", &FilterSpec::flag)
        .def_rw("type_dir", &FilterSpec::type_dir);
    nb::class_<ViewOptions>(module, "ViewOptions", "Copied view display options.")
        .def(nb::init<>())
        .def_rw("sort", &ViewOptions::sort)
        .def_rw("descending", &ViewOptions::descending)
        .def_rw("dirs_first", &ViewOptions::dirs_first)
        .def_rw("show_files", &ViewOptions::show_files)
        .def_rw("filter", &ViewOptions::filter)
        .def_rw("resolve_owner", &ViewOptions::resolve_owner);
    nb::class_<TreeView>(module, "TreeView", nb::is_final(), "Paged native visible tree.")
        .def(
            "__init__",
            [](TreeView *self, const std::shared_ptr<BoundTree> &tree, ViewOptions options) {
                nb::gil_scoped_release release;
                new (self) TreeView(tree->handle, tree->backend, std::move(options));
            },
            nb::arg("tree"), nb::arg("options"))
        .def_prop_ro("row_count", &TreeView::row_count, nb::call_guard<nb::gil_scoped_release>())
        .def_prop_ro("options", &TreeView::options, nb::call_guard<nb::gil_scoped_release>())
        .def(
            "rows",
            [](const TreeView &self, std::uint32_t start, std::uint32_t count) {
                std::vector<Row> rows;
                {
                    nb::gil_scoped_release release;
                    rows = self.rows(start, count);
                }
                nb::list result;
                for (const auto &row : rows) {
                    const nb::object owner =
                        row.owner ? nb::object(decode_native(*row.owner)) : nb::none();
                    const nb::object ext =
                        row.ext ? nb::object(decode_native(*row.ext)) : nb::none();
                    result.append(nb::make_tuple(row.id, row.depth, row.has_children, row.expanded,
                                                 decode_native(row.name), row.size, row.alloc,
                                                 row.pct_parent, row.files, row.dirs, row.mtime,
                                                 owner, ext, row.flags, row.ext_category));
                }
                return result;
            },
            nb::arg("start"), nb::arg("count"),
            nb::sig("def rows(self, start: int, count: int) -> list[tuple[int, int, bool, bool, "
                    "str, int, int, float, int, int, int, str | None, str | None, int, int]]"),
            "Return at most 500 native tuples:\n"
            "(id, depth, has_children, expanded, name, size, alloc, pct,\n"
            " files, dirs, mtime, owner, ext, flags, ext_cat).")
        .def("expand", &TreeView::expand, nb::arg("id"), nb::call_guard<nb::gil_scoped_release>())
        .def("expansion_count", &TreeView::expansion_count, nb::arg("id"),
             nb::call_guard<nb::gil_scoped_release>())
        .def("collapse_count", &TreeView::collapse_count, nb::arg("id"),
             nb::call_guard<nb::gil_scoped_release>())
        .def("expand_children", &TreeView::expand_children, nb::arg("id"),
             nb::call_guard<nb::gil_scoped_release>())
        .def("collapse", &TreeView::collapse, nb::arg("id"),
             nb::call_guard<nb::gil_scoped_release>())
        .def("expand_to", &TreeView::expand_to, nb::arg("id"),
             nb::call_guard<nb::gil_scoped_release>())
        .def("set_options", &TreeView::set_options, nb::arg("options"),
             nb::call_guard<nb::gil_scoped_release>())
        .def("index_of", &TreeView::index_of, nb::arg("id"),
             nb::call_guard<nb::gil_scoped_release>());
}

} // namespace dafree::bindings
