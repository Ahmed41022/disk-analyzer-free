#pragma once

#include "dafree/backend.hpp"

namespace dafree {

/// Entries removed from both the scan tree and its totals.
struct ExcludeRules {
    std::vector<std::string> paths;
    std::vector<std::string> globs;
    bool hidden = false;
    bool system = false;
};

/// An invalid exclusion pattern, with the original input for diagnostics.
class ExcludeError : public Error {
  public:
    /// Construct an exclusion syntax error.
    ExcludeError(std::string input, const std::string &message)
        : Error(message), pattern(std::move(input)) {}
    const std::string pattern;
};

/// Immutable exclusions compiled once for a scan root.
class CompiledExcludes {
  public:
    /// Validate patterns and resolve excluded paths relative to the root.
    static CompiledExcludes compile(const ExcludeRules &rules, std::string_view root);
    /// Test a root-relative path and native entry name without filesystem access.
    [[nodiscard]] bool excluded(std::string_view rel_path, std::string_view name,
                                const RawEntry &entry) const;

  private:
    struct Impl;
    explicit CompiledExcludes(std::shared_ptr<const Impl> impl) : impl_(std::move(impl)) {}
    std::shared_ptr<const Impl> impl_;
};

} // namespace dafree
