# Largest files and folders

Open **Top** after a scan to rank files or folders by descending logical size.
Choose 20, 50, 100, or 500 results. Rankings cover the selected folder's whole
subtree, including nested entries. Folder rankings can include the scope itself;
ties retain the native natural-name and node-ID order.

Selecting a folder in **Tree** changes the Top scope. Selecting a file uses its
parent folder. A single scan target is the initial scope; multiple targets start
at **All scan targets**. The breadcrumb's **Up** button broadens the scope without
requiring a different Tree selection. Changing units or switching tabs preserves
that scope. Enter or double-click a result to select its node in Tree.

**Leaf folders only** is available for folder rankings. It uses the existing
native rule: no child folder may account for at least 1% of the folder's logical
size. This can include folders with very small child folders.

Columns show name, logical size, allocated space, and full path. Allocated values
marked **≈** have unreliable allocation metadata. Tooltips and accessible labels
retain full paths. Units follow the toolbar and Settings. Right-click a result
for the shared **Properties** menu; file-changing actions arrive in M8.

Ranking runs in TaskRunner, coalescing changes to scope, kind and result limit.
Results from superseded requests or scans cannot replace the current report.
The table retains ranked node IDs and reads metadata lazily in 64-row pages,
keeping at most eight pages. Unit changes reformat those pages without ranking
again. This view adds no saved preferences.
