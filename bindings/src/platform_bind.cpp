#include "bindings.hpp"

#include <mutex>
#include <nanobind/stl/vector.h>

namespace dafree::bindings {
namespace {
struct PlatformNamespace {};
std::mutex volumes_mutex;
} // namespace

void bind_platform(nb::module_ &module) {
    nb::class_<PlatformNamespace>(module, "platform", "Native platform services.")
        .def_static(
            "volumes",
            [] {
                // Some host mount-table APIs use process-global scratch storage.
                std::lock_guard lock(volumes_mutex);
                return platform::list_volumes();
            },
            nb::call_guard<nb::gil_scoped_release>(),
            "List mounted volumes using the native platform implementation.")
        .def_static("is_elevated", &platform::is_elevated, nb::call_guard<nb::gil_scoped_release>(),
                    "Return whether the current process is elevated.")
        .def_static(
            "relaunch_elevated",
            [](const std::vector<nb::str> &args) {
                const auto native = encode_strings(args);
                nb::gil_scoped_release release;
                platform::relaunch_elevated(native);
            },
            nb::arg("args"),
            "Relaunch the current executable with elevation and explicit arguments.");
}
} // namespace dafree::bindings
