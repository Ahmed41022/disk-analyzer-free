#include "bindings.hpp"

#include <nanobind/stl/optional.h>
#include <nanobind/stl/shared_ptr.h>
#include <nanobind/stl/vector.h>

namespace dafree::bindings {

void bind_testing(nb::module_ &module) {
    nb::class_<RawEntry>(module, "RawEntry", nb::is_final(), "Synthetic native entry metadata.")
        .def(nb::init<>())
        .def_rw("kind", &RawEntry::kind)
        .def_rw("size", &RawEntry::size)
        .def_rw("alloc", &RawEntry::alloc)
        .def_rw("dev", &RawEntry::dev)
        .def_rw("ino_lo", &RawEntry::ino_lo)
        .def_rw("ino_hi", &RawEntry::ino_hi)
        .def_rw("nlink", &RawEntry::nlink)
        .def_rw("hidden", &RawEntry::hidden)
        .def_rw("system", &RawEntry::system)
        .def_rw("sparse", &RawEntry::sparse)
        .def_rw("compressed", &RawEntry::compressed)
        .def_rw("cloud", &RawEntry::cloud)
        .def_rw("access_denied", &RawEntry::access_denied)
        .def_prop_rw(
            "owner_uid",
            [](const RawEntry &entry) -> std::optional<std::uint32_t> {
                return entry.owner ? std::optional(entry.owner->uid) : std::nullopt;
            },
            [](RawEntry &entry, std::optional<std::uint32_t> uid) {
                entry.owner = uid ? std::optional(OwnerKey::posix_uid(*uid)) : std::nullopt;
            });
    nb::class_<MockEntry>(module, "MockEntry", nb::is_final(), "A path and its synthetic metadata.")
        .def(nb::init<>())
        .def_prop_rw(
            "path", [](const MockEntry &entry) { return decode_native(entry.path); },
            [](MockEntry &entry, nb::str path) { entry.path = encode_native(path); })
        .def_rw("entry", &MockEntry::entry);
    nb::class_<MockSpec>(module, "MockSpec", nb::is_final(),
                         "Deterministic native-only test backend inputs.")
        .def(nb::init<>())
        .def_rw("entries", &MockSpec::entries)
        .def_rw("volume", &MockSpec::volume)
        .def_prop_rw(
            "vanish_after_listing",
            [](const MockSpec &spec) { return decode_strings(spec.vanish_after_listing); },
            [](MockSpec &spec, const std::vector<nb::str> &paths) {
                spec.vanish_after_listing = encode_strings(paths);
            })
        .def_prop_rw(
            "delay_ms", [](const MockSpec &spec) { return spec.delay.count(); },
            [](MockSpec &spec, std::int64_t delay) {
                if (delay < 0)
                    throw std::invalid_argument("delay must be non-negative");
                spec.delay = std::chrono::milliseconds(delay);
            })
        .def_prop_rw(
            "errors",
            [](const MockSpec &spec) {
                nb::typed<nb::dict, nb::str, IssueKind> result;
                for (const auto &[path, kind] : spec.errors)
                    result[decode_native(path)] = nb::cast(kind);
                return result;
            },
            [](MockSpec &spec, nb::typed<nb::dict, nb::str, IssueKind> errors) {
                spec.errors.clear();
                for (auto [path, kind] : errors)
                    spec.errors.emplace(encode_native(path), nb::cast<IssueKind>(kind));
            })
        .def_prop_rw(
            "symlink_targets",
            [](const MockSpec &spec) {
                nb::typed<nb::dict, nb::str, nb::str> result;
                for (const auto &[path, target] : spec.symlink_targets)
                    result[decode_native(path)] = decode_native(target);
                return result;
            },
            [](MockSpec &spec, nb::typed<nb::dict, nb::str, nb::str> targets) {
                spec.symlink_targets.clear();
                for (auto [path, target] : targets)
                    spec.symlink_targets.emplace(encode_native(path), encode_native(target));
            })
        .def_prop_rw(
            "owner_names",
            [](const MockSpec &spec) {
                nb::typed<nb::dict, std::uint32_t, nb::str> result;
                for (const auto &[uid, name] : spec.owner_names)
                    result[nb::int_(uid)] = decode_native(name);
                return result;
            },
            [](MockSpec &spec, nb::typed<nb::dict, std::uint32_t, nb::str> names) {
                spec.owner_names.clear();
                for (auto [uid, name] : names)
                    spec.owner_names.emplace(nb::cast<std::uint32_t>(uid), encode_native(name));
            });
    module.def(
        "make_mock_backend",
        [](const MockSpec &spec) {
            auto copied = spec;
            nb::gil_scoped_release release;
            return make_mock_backend(std::move(copied));
        },
        nb::arg("spec"), "Build an immutable native test backend.");
}

} // namespace dafree::bindings
