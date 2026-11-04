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

/// Select scope-relative depth, file visibility, owner lookup and CSV dialect.
struct CsvOptions {
    std::optional<std::uint16_t> depth;
    bool include_files = true, excel = false, include_owner = false;
    char delimiter = ',';
};

/// Stream UTF-8 CSV with CRLF records. Empty scopes select all scan roots.
void write_csv(const Tree &, std::span<const NodeId>, std::ostream &, const CsvOptions &);

/// Stream an engine-owned tree with optional lazy owner lookup outside stream callbacks.
void write_csv(TreeHandle &, FsBackend &, std::span<const NodeId>, std::ostream &,
               const CsvOptions &);

} // namespace dafree
