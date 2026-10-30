#include "dafree/units.hpp"

#include <nanobind/nanobind.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/string_view.h>

namespace nb = nanobind;

namespace dafree {
const char *version() noexcept;
}

NB_MODULE(_core, module) {
    module.def("version", &dafree::version, "Return the installed package version.");

    nb::enum_<dafree::UnitMode>(module, "UnitMode")
        .value("AUTO", dafree::UnitMode::Auto)
        .value("BYTES", dafree::UnitMode::Bytes)
        .value("KILO", dafree::UnitMode::Kilo)
        .value("MEGA", dafree::UnitMode::Mega)
        .value("GIGA", dafree::UnitMode::Giga)
        .value("TERA", dafree::UnitMode::Tera)
        .value("PETA", dafree::UnitMode::Peta)
        .value("EXA", dafree::UnitMode::Exa);
    nb::enum_<dafree::UnitSystem>(module, "UnitSystem")
        .value("TRADITIONAL", dafree::UnitSystem::Traditional)
        .value("IEC", dafree::UnitSystem::IEC)
        .value("SI", dafree::UnitSystem::SI);
    nb::class_<dafree::UnitStyle>(module, "UnitStyle")
        .def(nb::init<dafree::UnitSystem, char>(), nb::arg("system"), nb::arg("decimal_separator"))
        .def_rw("system", &dafree::UnitStyle::system)
        .def_rw("decimal_separator", &dafree::UnitStyle::decimal_separator);
    module.def("format_size", &dafree::format_size, nb::arg("bytes"), nb::arg("mode"),
               nb::arg("style"), "Format a byte count.");
    module.def("parse_size", &dafree::parse_size, nb::arg("text"), nb::arg("style"),
               "Parse a byte count.");
}
