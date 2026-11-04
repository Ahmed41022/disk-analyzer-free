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
            "peak_rss",
            []() -> std::optional<std::uint64_t> {
#ifdef _WIN32
                return platform::peak_rss();
#else
                return std::nullopt;
#endif
            },
            nb::call_guard<nb::gil_scoped_release>(),
            "Return the process peak working set in bytes, or None when unavailable.")
        .def_static(
            "relaunch_elevated",
            [](const std::vector<nb::str> &args) {
                const auto native = encode_strings(args);
                nb::gil_scoped_release release;
                platform::relaunch_elevated(native);
            },
            nb::arg("args"),
            "Relaunch the current executable with elevation and explicit arguments.")
        .def_static(
            "owner_of",
            [](nb::str path) -> std::optional<nb::str> {
                const auto native = encode_native(path);
                std::optional<std::pair<OwnerKey, std::string>> owner;
                {
                    nb::gil_scoped_release release;
                    try {
                        owner = platform::owner_of(native);
                    } catch (const IoError &) {
                        return std::nullopt;
                    }
                }
                return owner ? std::optional(decode_native(owner->second)) : std::nullopt;
            },
            nb::arg("path"), "Return the file owner's account name when available.")
        .def_static(
            "show_properties",
            [](nb::str path) {
                const auto native = encode_native(path);
                nb::gil_scoped_release release;
                return platform::show_properties(native);
            },
            nb::arg("path"), "Open a native Windows property sheet when available.");
}
} // namespace dafree::bindings
