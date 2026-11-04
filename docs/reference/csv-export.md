# CSV export

`dafree.api.write_csv(tree, stream)` writes UTF-8 CSV to an open binary
stream. It uses the same scope, depth, file and owner options as
[JSON export](json-export.md).

```python
from dafree.api import ScanRequest, scan, write_csv

tree = scan(ScanRequest(["."])).tree
with open("report.csv", "wb") as output:
    write_csv(tree, output, depth=2)
```

The column order is `path,name,type,size,alloc,pct_parent,files,dirs,mtime_iso,
btime_iso,atime_iso,owner,ext,flags`. Numeric fields use locale-independent
notation. `pct_parent` is the ratio of a node's size to its actual parent's
size. Scan roots and nodes whose parent has zero size report zero. Timestamps
are UTC and missing timestamps, owners and extensions use empty fields.
Flags are lowercase labels joined with `|`.

Records use CRLF. Fields with a delimiter, quotation mark or line break
are quoted, and embedded quotation marks are doubled. The default delimiter
is a comma. `excel=True` adds a UTF-8 BOM and defaults to semicolon when the
active numeric locale uses a decimal comma. Pass `delimiter` to override it.
The binary stream is left open.

Invalid native bytes and lone surrogates are replaced with U+FFFD. For
recovery of original native bytes, JSON provides separate raw hex fields.
