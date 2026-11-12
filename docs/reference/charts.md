# Chart data

`dafree.api.analysis.chart_data(tree, scope, kind, top=15)` returns immutable
`ChartSlice(label, value, node=None, is_other=False)` records. `ChartKind` selects
`CHILDREN_BY_SIZE`, `CHILDREN_BY_ALLOC`, `CHILDREN_BY_FILES`, `EXT_BY_SIZE`,
`EXT_BY_COUNT`, or `CATEGORY_BY_SIZE`. These are also exported through `dafree.api`.

Child reports rank direct children in C++; nested descendants contribute only
through their directory totals. Eligible files count as one in file-count reports.
Extension/category reports reuse native extension aggregation. A file scope has no
children, while extension/category scopes include its own file. Scope zero combines
all scan targets. Excluded scopes and hard-link duplicates do not contribute.

Positive values are ordered descending. Ties use natural names/node IDs for children,
raw extensions for extension reports, and category IDs for category reports.
`top` counts retained groups; a final **Other** slice contains the remainder.
`top=0` combines everything into that remainder and a negative limit raises
`ValueError`. Empty reports contain no slices. Grouped totals saturate at
`UINT64_MAX`, matching existing native accounting. Labels are localized at call
time; extension labels include a leading dot. Qt escapes undecodable filename
characters only for display.

Child records retain their native `node` ID. Grouped reports and the remainder
have `node=None`; `is_other` identifies the remainder independently of its label.
The Charts tab shows at most 15 groups plus Other and builds reports off-thread.
Its folder activation uses node identity, while selecting a file charts its parent.
