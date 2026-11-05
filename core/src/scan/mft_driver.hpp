#pragma once

#include "dafree/model.hpp"

#include <functional>

namespace dafree::detail {

/// Read and parse one Windows MFT stream. A false checkpoint cancels without publishing it.
std::optional<Tree> scan_mft(std::string_view volume_root, std::string_view target,
                             const ScanOptions &options, const std::function<bool()> &checkpoint,
                             const std::function<void(std::uint64_t)> &estimate);

} // namespace dafree::detail
