#include "bindings.hpp"

#include <mutex>
#include <nanobind/stl/optional.h>
#include <nanobind/stl/vector.h>

namespace dafree::bindings {
namespace {
struct PlatformNamespace {};
std::mutex volumes_mutex;
} // namespace

void bind_platform(nb::module_ &module) {
    nb::class_<PlatformNamespace>(module, "platform", "Native read-only platform services.")
        .def_static(
            "volumes",
            [] {
                // Some host mount-table APIs use process-global scratch storage.
                std::lock_guard lock(volumes_mutex);
                return platform::list_volumes();
            },
            nb::call_guard<nb::gil_scoped_release>(),
            "List mounted volumes using the native platform implementation.")
        .def_static(
            "is_elevated",
            []() -> std::optional<bool> {
#ifdef _WIN32
                // The actual Windows token API belongs to paused T3.7. Unknown is not false.
                return std::nullopt;
#else
                return platform::is_elevated();
#endif
            },
            nb::call_guard<nb::gil_scoped_release>(),
            "Return known elevation, or None when the platform API is unavailable.");
}
} // namespace dafree::bindings
