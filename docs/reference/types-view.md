# Extension breakdown

The **Types** tab groups files by extension within the selected folder's subtree.
Its table shows extension, category, file count, logical size, allocated space,
and logical size as a percentage of the scope's total. Files without a recognized
suffix appear as **No extension**. Existing native extension normalization and
accounting rules are shared with the CLI reports.

The bar chart shows the 15 largest positive-size extension groups and one
**Other** remainder. Zero-byte groups remain in the table. Both views come from
one background native aggregation. Unit changes reformat existing results;
obsolete scan or scope results cannot overwrite a newer request.

Selecting a file in Tree scopes the report to its parent folder. Use the
breadcrumb to move to a broader scope. A single target starts at that root;
multiple targets start at **All scan targets**. Switching tabs and changing
units preserve the chosen scope.

Activate a row with Return, keypad Enter, or double-click to open **Find** with
the scope and an extension query such as `ext:txt` or `ext:""` for no extension.
Values requiring quoting use JSON string escaping. Find currently displays the
pending query and scope read-only; query parsing and search execution belong to
M6. New scan snapshots clear stale pending queries.
