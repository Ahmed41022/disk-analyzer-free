# Age analysis

The **Age** tab groups files in the selected folder's subtree by modified,
created, or accessed time. Separate charts show logical size and file count;
zero-byte files remain represented in the count chart. Selecting a file in
Tree uses its parent folder. Breadcrumb scope survives unit and tab changes.

Enter comma-separated cutoffs, for example `30d,90d,1y`, then choose **Apply**
or press Enter. Units are days (`d`), weeks (`w`), 30-day months (`m`), and
365-day years (`y`), independent of locale. Positive whole-number cutoffs must
increase strictly and fit unsigned 64-bit seconds. The GUI allows up to 14
cutoffs, leaving space for 15 intervals plus an Unknown interval in each chart.
Invalid input displays an explanation and preserves the last valid report.

Intervals include their lower bound and exclude their upper bound; a file
exactly 30 days old belongs in the 30–90 day interval. The final interval has
no upper bound. Future timestamps have age zero, matching native accounting.
Missing timestamps appear as **Unknown**. Chart bars with zero values are
omitted without losing their original interval identity.

**Created** is disabled with an explanatory tooltip when no files in the scope
have creation timestamps. Availability is inferred by the native histogram
because scan metadata does not expose a separate birth-time capability. A
selection without creation times falls back to Modified. Access-time analysis
shows a note about `noatime`, `relatime`, and NTFS `DisableLastAccess`.

Click a known interval or activate it with the keyboard to open Find with its
scope and a query such as `type:file modified>=30d modified<90d`. Find displays
the pending query; execution remains part of M6. Unknown bars explain that the
current time-query grammar cannot express missing timestamps and do not open
Find. Size/count bars use original histogram indexes, not tree node IDs.

Native histogram work and creation-time checks run in TaskRunner. Requests
capture one reference clock, coalesce edits, and reject obsolete scan/scope
results. Changing display units reformats existing values without rescanning.
