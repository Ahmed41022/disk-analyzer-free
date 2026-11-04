# JSON export

`dafree.api.write_json(tree, stream)` writes UTF-8 to an open binary stream.
It writes chunks of at most 64 KiB and leaves the stream open. The writer can
target files, pipes and in-memory streams through the same API.

```python
from dafree.api import ScanRequest, scan, write_json

tree = scan(ScanRequest(["."])).tree
with open("report.json", "wb") as output:
    write_json(tree, output, depth=2, pretty=True)
```

The version 1 document has `schema`, `version`, `meta`, and `roots` fields.
Metadata records the scan mode, host, OS, app version, timestamps, cancellation
and issue count. Roots contain native byte totals and descendant counts, even
when an export's depth or file filter limits the displayed entries.

Pass `scopes` to select subtree node IDs. An empty selection exports all scan
roots. Depth is relative to each scope, with zero writing only that scope.
`include_files=False` keeps directories. `include_owner=True` requests lazy
resolution for exported nodes. Unavailable owner names are omitted.

With `ndjson=True`, each line is one compact object with a full native path.
The NDJSON row schema is `$defs.line` in `schemas/report.v1.json`. The report
schema uses Draft 2020-12. Timestamps are UTC or null when unknown. An invalid
native name is displayed with U+FFFD and paired with its lowercase
`name_raw_hex` bytes. NDJSON adds `path_raw_hex` when any path component
needs replacement. These fields let consumers recover the original bytes.
