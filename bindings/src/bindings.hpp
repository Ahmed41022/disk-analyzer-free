#pragma once

#include "dafree/scan.hpp"

#include <mutex>
#include <nanobind/nanobind.h>

namespace dafree::bindings {

namespace nb = nanobind;

nb::str decode_native(std::string_view input);
std::string encode_native(nb::handle input);
std::vector<nb::str> decode_strings(const std::vector<std::string> &input);
std::vector<std::string> encode_strings(const std::vector<nb::str> &input);
void bind_scan_types(nb::module_ &module);
void bind_scan(nb::module_ &module);
void bind_tree(nb::module_ &module);
void bind_view(nb::module_ &module);
void bind_testing(nb::module_ &module);
void bind_platform(nb::module_ &module);

struct BoundTree {
    std::shared_ptr<TreeHandle> handle;
    std::shared_ptr<FsBackend> backend;
    BoundTree(std::shared_ptr<const Tree> tree, std::shared_ptr<FsBackend> context)
        : handle(std::make_shared<TreeHandle>(std::move(tree))), backend(std::move(context)) {}
};

struct BoundResult {
    std::shared_ptr<BoundTree> tree;
    ScanSummary summary;
};

class BoundScanHandle {
  public:
    BoundScanHandle(ScanOptions options, std::shared_ptr<FsBackend> backend)
        : backend_(backend ? std::move(backend) : make_local_backend()),
          handle_(start_scan(std::move(options), backend_)) {}
    ScanHandle &handle() noexcept { return handle_; }
    std::shared_ptr<BoundTree> wrap_tree(std::shared_ptr<const Tree> tree) {
        if (!tree)
            return nullptr;
        std::lock_guard lock(cache_mutex_);
        if (source_ == tree.get())
            if (auto cached = cached_.lock())
                return cached;
        source_ = tree.get();
        auto wrapped = std::make_shared<BoundTree>(std::move(tree), backend_);
        cached_ = wrapped;
        return wrapped;
    }

  private:
    std::shared_ptr<FsBackend> backend_;
    ScanHandle handle_;
    std::mutex cache_mutex_;
    const Tree *source_ = nullptr;
    std::weak_ptr<BoundTree> cached_;
};

} // namespace dafree::bindings
