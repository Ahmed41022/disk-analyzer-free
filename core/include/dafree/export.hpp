#pragma once

#include "dafree/model.hpp"

#include <iosfwd>

namespace dafree {

/// Select depth relative to each scope, visible entry types, and JSON layout.
struct JsonOptions {
    std::optional<std::uint16_t> depth;
    bool include_files = true, ndjson = false, include_owner = false, pretty = false;
};

/// Stream JSON or NDJSON. Empty scopes select all scan roots.
/// The caller owns the stream and any synchronization for owner metadata.
void write_json(const Tree &, std::span<const NodeId>, std::ostream &, const JsonOptions &);

/// Stream an engine-owned tree and resolve owners on demand if requested.
/// Stream callbacks run outside the tree lock.
void write_json(TreeHandle &, FsBackend &, std::span<const NodeId>, std::ostream &,
                const JsonOptions &);

} // namespace dafree
