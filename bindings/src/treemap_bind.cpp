#include "bindings.hpp"
#include "dafree/treemap.hpp"

#include <cmath>
#include <nanobind/ndarray.h>
#include <nanobind/stl/array.h>
#include <nanobind/stl/optional.h>

namespace dafree::bindings {

void bind_treemap(nb::module_ &module) {
    nb::class_<TreemapOptions>(module, "TreemapOptions", "Treemap layout limits and spacing.")
        .def(nb::init<>())
        .def_rw("max_depth", &TreemapOptions::max_depth)
        .def_rw("min_px", &TreemapOptions::min_px)
        .def_rw("padding", &TreemapOptions::padding)
        .def_rw("header_px", &TreemapOptions::header_px)
        .def_rw("max_rects", &TreemapOptions::max_rects);
    nb::class_<Palette>(module, "Palette", "RGBA colors packed as 0xRRGGBBAA.")
        .def(nb::init<>())
        .def_rw("by_class", &Palette::by_class)
        .def_rw("dir_by_depth", &Palette::dir_by_depth)
        .def_rw("background", &Palette::background)
        .def_rw("border", &Palette::border);
    nb::enum_<TmFlags>(module, "TmFlags").value("OTHER", kTmOther).value("DIRECTORY", kTmDirectory);
    nb::class_<TreemapLayout>(module, "TreemapLayout", nb::is_final(),
                              "Immutable native treemap layout.")
        .def_prop_ro(
            "raw_rects",
            [](nb::handle self) {
                const auto &layout = nb::cast<const TreemapLayout &>(self);
                const auto rects = layout.rects();
                // The NumPy byte view inspects this live, trivially copyable record storage.
                // NOLINTNEXTLINE(cppcoreguidelines-pro-type-reinterpret-cast)
                const auto *data = reinterpret_cast<const std::uint8_t *>(rects.data());
                return nb::ndarray<nb::numpy, const std::uint8_t>(data, {rects.size_bytes()}, self);
            },
            "Read-only zero-copy native rectangle bytes, owned by this layout.")
        .def_prop_ro("width", &TreemapLayout::width)
        .def_prop_ro("height", &TreemapLayout::height)
        .def("hit_test", &TreemapLayout::hit_test, nb::arg("x"), nb::arg("y"))
        .def("small_items", &TreemapLayout::small_items, nb::arg("index"));
    module.def(
        "treemap_layout",
        [](const BoundTree &tree, NodeId root, float width, float height, TreemapOptions options) {
            TreemapLayout result = [&] {
                nb::gil_scoped_release release;
                return tree.handle->read([&](const Tree &value) {
                    return dafree::treemap_layout(value, root, width, height, options);
                });
            }();
            return result;
        },
        nb::arg("tree"), nb::arg("root"), nb::arg("width"), nb::arg("height"),
        nb::arg("options") = TreemapOptions{}, "Compute a native squarified treemap layout.");
    module.def(
        "treemap_render",
        [](const TreemapLayout &layout, Palette palette, bool cushion) {
            std::vector<std::uint8_t> pixels;
            {
                nb::gil_scoped_release release;
                pixels = dafree::treemap_render(layout, static_cast<int>(std::ceil(layout.width())),
                                                static_cast<int>(std::ceil(layout.height())),
                                                palette, cushion);
            }
            return nb::bytes(pixels.data(), pixels.size());
        },
        nb::arg("layout"), nb::arg("palette"), nb::arg("cushion") = true,
        "Render the layout to an RGBA8888 bytes buffer.");
}

} // namespace dafree::bindings
