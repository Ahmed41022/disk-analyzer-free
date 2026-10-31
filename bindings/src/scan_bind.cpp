#include "bindings.hpp"

#include <nanobind/stl/array.h>
#include <nanobind/stl/optional.h>
#include <nanobind/stl/shared_ptr.h>
#include <nanobind/stl/string.h>
#include <nanobind/stl/unique_ptr.h>
#include <nanobind/stl/vector.h>

namespace dafree::bindings {
namespace {

void public_error(const char *family, int code, std::string_view message,
                  std::optional<std::string_view> path = {},
                  std::optional<std::string_view> pattern = {}) {
    auto errors = nb::module_::import_("dafree.api.errors");
    nb::object native_path = path ? nb::object(decode_native(*path)) : nb::none();
    nb::object native_pattern = pattern ? nb::object(decode_native(*pattern)) : nb::none();
    auto exception = errors.attr("_from_native")(family, code, decode_native(message), native_path,
                                                 native_pattern);
    PyErr_SetObject(exception.type().ptr(), exception.ptr());
}

} // namespace

void bind_scan_types(nb::module_ &module) {
    nb::enum_<ScanMode>(module, "ScanMode")
        .value("AUTO", ScanMode::Auto)
        .value("WALK", ScanMode::Walk)
        .value("MFT", ScanMode::Mft);
    nb::enum_<OwnerMode>(module, "OwnerMode")
        .value("OFF", OwnerMode::Off)
        .value("LAZY", OwnerMode::Lazy)
        .value("EAGER", OwnerMode::Eager);
    nb::enum_<HardlinkMode>(module, "HardlinkMode")
        .value("DEDUP", HardlinkMode::Dedup)
        .value("COUNT_ALL", HardlinkMode::CountAll);
    nb::enum_<ScanModeUsed>(module, "ScanModeUsed")
        .value("WALK", ScanModeUsed::Walk)
        .value("MFT", ScanModeUsed::Mft)
        .value("SFTP", ScanModeUsed::Sftp);
    nb::enum_<ScanState>(module, "ScanState")
        .value("RUNNING", ScanState::Running)
        .value("PAUSED", ScanState::Paused)
        .value("FINALIZING", ScanState::Finalizing)
        .value("DONE", ScanState::Done)
        .value("CANCELLED", ScanState::Cancelled)
        .value("FAILED", ScanState::Failed);
    nb::enum_<IssueKind>(module, "IssueKind")
        .value("ACCESS_DENIED", IssueKind::AccessDenied)
        .value("NOT_FOUND", IssueKind::NotFound)
        .value("PATH_TOO_LONG", IssueKind::PathTooLong)
        .value("INVALID_NAME", IssueKind::InvalidName)
        .value("IO", IssueKind::Io)
        .value("TIMEOUT", IssueKind::Timeout)
        .value("SYMLINK_LOOP", IssueKind::SymlinkLoop)
        .value("ORPHANED", IssueKind::Orphaned)
        .value("CHANGED", IssueKind::Changed)
        .value("OTHER", IssueKind::Other);
    nb::enum_<EntryKind>(module, "EntryKind")
        .value("FILE", EntryKind::File)
        .value("DIR", EntryKind::Dir)
        .value("SYMLINK", EntryKind::Symlink)
        .value("JUNCTION", EntryKind::Junction)
        .value("MOUNT_POINT", EntryKind::MountPoint)
        .value("OTHER_REPARSE", EntryKind::OtherReparse)
        .value("OTHER", EntryKind::Other);
    nb::enum_<Notice::Kind>(module, "NoticeKind")
        .value("FAST_MODE_UNAVAILABLE", Notice::FastModeUnavailable)
        .value("NETWORK_VOLUME", Notice::NetworkVolume)
        .value("ROTATIONAL_DISK", Notice::RotationalDisk)
        .value("HARDLINK_DEDUP_DISABLED", Notice::HardlinkDedupDisabled);
    nb::class_<FsBackend>(module, "Backend", nb::is_final(),
                          "Opaque filesystem backend; workers never call Python.")
        .def_prop_ro("read_dir_calls",
                     [](const FsBackend &backend) {
                         const auto *mock = dynamic_cast<const MockBackend *>(&backend);
                         return mock ? mock->read_dir_calls() : 0;
                     })
        .def_prop_ro("owner_resolution_calls", [](const FsBackend &backend) {
            const auto *mock = dynamic_cast<const MockBackend *>(&backend);
            return mock ? mock->owner_resolution_calls() : 0;
        });
    nb::class_<ExcludeRules>(module, "ExcludeRules", nb::is_final(),
                             "Paths, globs, and attribute exclusions.")
        .def(nb::init<>())
        .def_prop_rw(
            "paths", [](const ExcludeRules &value) { return decode_strings(value.paths); },
            [](ExcludeRules &value, const std::vector<nb::str> &paths) {
                value.paths = encode_strings(paths);
            })
        .def_prop_rw(
            "globs", [](const ExcludeRules &value) { return decode_strings(value.globs); },
            [](ExcludeRules &value, const std::vector<nb::str> &globs) {
                value.globs = encode_strings(globs);
            })
        .def_rw("hidden", &ExcludeRules::hidden)
        .def_rw("system", &ExcludeRules::system);
    nb::class_<ScanOptions>(module, "ScanOptions", nb::is_final(),
                            "Native scan input copied at start.")
        .def(nb::init<>())
        .def_prop_rw(
            "targets", [](const ScanOptions &value) { return decode_strings(value.targets); },
            [](ScanOptions &value, const std::vector<nb::str> &targets) {
                value.targets = encode_strings(targets);
            })
        .def_rw("mode", &ScanOptions::mode)
        .def_rw("threads", &ScanOptions::threads)
        .def_rw("follow_symlinks", &ScanOptions::follow_symlinks)
        .def_rw("cross_filesystems", &ScanOptions::cross_filesystems)
        .def_rw("exclude", &ScanOptions::exclude)
        .def_rw("owner", &ScanOptions::owner)
        .def_rw("hardlinks", &ScanOptions::hardlinks)
        .def_rw("include_ads", &ScanOptions::include_ads)
        .def_rw("show_ntfs_metafiles", &ScanOptions::show_ntfs_metafiles)
        .def_rw("progress_interval_ms", &ScanOptions::progress_interval_ms);
    nb::class_<ScanIssue>(module, "ScanIssue", nb::is_final(), "A recoverable scan issue.")
        .def_prop_ro("path", [](const ScanIssue &value) { return decode_native(value.path); })
        .def_ro("kind", &ScanIssue::kind)
        .def_prop_ro("message",
                     [](const ScanIssue &value) { return decode_native(value.message); });
    nb::class_<IssueSummary>(module, "IssueSummary", nb::is_final(),
                             "Complete counts and the first 1,000 diagnostics.")
        .def_ro("counts", &IssueSummary::counts)
        .def_ro("first", &IssueSummary::first)
        .def_ro("total", &IssueSummary::total)
        .def_ro("overflow", &IssueSummary::overflow);
    nb::class_<Notice>(module, "Notice", nb::is_final(), "Informational volume or policy notice.")
        .def_ro("kind", &Notice::kind)
        .def_prop_ro("detail", [](const Notice &value) { return decode_native(value.detail); });
    nb::class_<VolumeInfo>(module, "VolumeInfo", nb::is_final(),
                           "Capacity and scan-relevant volume properties.")
        .def(nb::init<>())
        .def_prop_rw(
            "mount", [](const VolumeInfo &value) { return decode_native(value.mount); },
            [](VolumeInfo &value, nb::str mount) { value.mount = encode_native(mount); })
        .def_rw("fs_type", &VolumeInfo::fs_type)
        .def_prop_rw(
            "label", [](const VolumeInfo &value) { return decode_native(value.label); },
            [](VolumeInfo &value, nb::str label) { value.label = encode_native(label); })
        .def_rw("serial", &VolumeInfo::serial)
        .def_rw("total", &VolumeInfo::total)
        .def_rw("free", &VolumeInfo::free)
        .def_rw("cluster_size", &VolumeInfo::cluster_size)
        .def_rw("is_network", &VolumeInfo::is_network)
        .def_rw("is_removable", &VolumeInfo::is_removable)
        .def_rw("supports_mft", &VolumeInfo::supports_mft)
        .def_rw("is_rotational", &VolumeInfo::is_rotational);
    nb::class_<ScanMeta>(module, "ScanMeta", nb::is_final(),
                         "Copied scan provenance, options, and diagnostics.")
        .def_ro("started_at", &ScanMeta::started_at)
        .def_ro("finished_at", &ScanMeta::finished_at)
        .def_ro("mode", &ScanMeta::mode)
        .def_ro("options", &ScanMeta::options)
        .def_prop_ro("host", [](const ScanMeta &value) { return decode_native(value.host); })
        .def_ro("os", &ScanMeta::os)
        .def_ro("app_version", &ScanMeta::app_version)
        .def_ro("volumes", &ScanMeta::volumes)
        .def_ro("issues", &ScanMeta::issues)
        .def_ro("cancelled", &ScanMeta::cancelled);
    nb::class_<ScanProgress>(module, "ScanProgress", nb::is_final(),
                             "A non-blocking scan progress snapshot.")
        .def_ro("files", &ScanProgress::files)
        .def_ro("dirs", &ScanProgress::dirs)
        .def_ro("bytes", &ScanProgress::bytes)
        .def_ro("alloc", &ScanProgress::alloc)
        .def_ro("issues", &ScanProgress::issues)
        .def_prop_ro("current",
                     [](const ScanProgress &value) { return decode_native(value.current); })
        .def_ro("elapsed_ms", &ScanProgress::elapsed_ms)
        .def_ro("state", &ScanProgress::state)
        .def_ro("est_total", &ScanProgress::est_total)
        .def_ro("mode", &ScanProgress::mode);
    nb::class_<ScanSummary>(module, "ScanSummary", nb::is_final(),
                            "Final scan entry and byte totals.")
        .def_ro("files", &ScanSummary::files)
        .def_ro("dirs", &ScanSummary::dirs)
        .def_ro("bytes", &ScanSummary::bytes)
        .def_ro("alloc", &ScanSummary::alloc)
        .def_ro("elapsed_ms", &ScanSummary::elapsed_ms)
        .def_ro("issues", &ScanSummary::issues)
        .def_ro("cancelled", &ScanSummary::cancelled);

    nb::register_exception_translator([](const std::exception_ptr &exception, void *) {
        try {
            std::rethrow_exception(exception);
        } catch (const IoError &error) {
            public_error("io", static_cast<int>(error.kind()), error.what(), error.path());
        } catch (const ScanError &error) {
            public_error("scan", static_cast<int>(error.code()), error.what());
        } catch (const ExcludeError &error) {
            public_error("exclude", 0, error.what(), {}, error.pattern);
        } catch (const Error &error) {
            public_error("core", 0, error.what());
        }
    });
}

void bind_scan(nb::module_ &module) {
    nb::class_<BoundResult>(module, "ScanResult", nb::is_final(),
                            "An immutable tree and final scan summary.")
        .def_ro("tree", &BoundResult::tree)
        .def_ro("summary", &BoundResult::summary);
    nb::class_<BoundScanHandle>(module, "ScanHandle", nb::is_final(),
                                "Asynchronous scan control; native threads never enter Python.")
        .def(
            "progress", [](BoundScanHandle &self) { return self.handle().progress(); },
            "Return a progress snapshot.")
        .def(
            "drain_issues",
            [](BoundScanHandle &self, std::size_t max) { return self.handle().drain_issues(max); },
            nb::arg("max") = 1000, "Drain live diagnostics.")
        .def(
            "drain_notices", [](BoundScanHandle &self) { return self.handle().drain_notices(); },
            "Drain policy notices.")
        .def(
            "pause", [](BoundScanHandle &self) { self.handle().pause(); },
            "Pause between directory reads.")
        .def(
            "resume", [](BoundScanHandle &self) { self.handle().resume(); },
            "Resume directory reads.")
        .def(
            "cancel", [](BoundScanHandle &self) { self.handle().cancel(); },
            "Request cancellation.")
        .def(
            "wait",
            [](BoundScanHandle &self, std::int64_t timeout_ms) {
                if (timeout_ms < 0)
                    throw std::invalid_argument("timeout must be non-negative");
                nb::gil_scoped_release release;
                return self.handle().wait(std::chrono::milliseconds(timeout_ms));
            },
            nb::arg("timeout_ms"), "Wait with the GIL released.")
        .def(
            "partial_tree",
            [](BoundScanHandle &self) { return self.wrap_tree(self.handle().partial_tree()); },
            "Request a throttled immutable snapshot.")
        .def(
            "take_result",
            [](BoundScanHandle &self) {
                nb::gil_scoped_release release;
                auto result = self.handle().take_result();
                return BoundResult{self.wrap_tree(std::move(result.tree)),
                                   std::move(result.summary)};
            },
            "Consume the completed result once.");
    module.def(
        "start_scan",
        [](const ScanOptions &options, std::shared_ptr<FsBackend> backend) {
            auto copied = options;
            nb::gil_scoped_release release;
            return std::make_unique<BoundScanHandle>(std::move(copied), std::move(backend));
        },
        nb::arg("options"), nb::arg("backend") = nb::none(), "Start an asynchronous scan.");
}

} // namespace dafree::bindings
