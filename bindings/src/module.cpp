#include <nanobind/nanobind.h>

namespace nb = nanobind;

namespace dafree {
const char* version() noexcept;
}

NB_MODULE(_core, module) {
    module.def("version", &dafree::version, "Return the installed package version.");
}
