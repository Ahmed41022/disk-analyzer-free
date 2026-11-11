# Treemap API

`dafree.api.treemap_layout` computes geometry in C++; `treemap_render` returns
RGBA8888 pixels. The desktop Treemap tab uses this API for interactive navigation.

After a scan, open **Treemap**. Hover for a name, size and percentage of the zoom
root; click to select the same node in the Tree tab. Double-click a directory to
zoom in, then use the breadcrumb's **Up** button to return to its parent. Right-click
for the shared **Properties** action. In **Settings → General**, **Flat colours in
treemap** turns off cushion shading. Settings apply after pressing OK.

Layout and rendering run in the background. Resizes wait 150 ms after the last
change; rendering and hit testing account for the monitor's pixel ratio. Screen
readers see up to 50 of the largest real rectangles with their names and sizes.

```python
from pathlib import Path
from dafree.api import Palette, ScanRequest, TreemapOptions, scan, treemap_layout, treemap_render

result = scan(ScanRequest(targets=[Path("/path/to/folder")]))
tree = result.tree
options = TreemapOptions()
options.max_rects = 50_000
layout = treemap_layout(tree, tree.roots()[0], 800, 600, options)

palette = Palette()
palette.by_class = [0x4477AAFF] * 16
palette.dir_by_depth = [0x667788FF] * 8
palette.background = 0x202020FF
palette.border = 0x101010FF
rgba = treemap_render(layout, palette, cushion=True)
assert len(rgba) == 800 * 600 * 4
node_id = layout.hit_test(120.5, 100.5)
```

Defaults are depth 12, minimum area 3×3 device pixels, one-pixel padding, no
header, and 50,000 rectangles including the selected root. Width and height must
be finite, nonnegative device-pixel values fitting an `int`; rendering uses their
ceiling dimensions. Zero dimensions or a zero budget give an empty geometry view.
With a positive image size and zero budget, rendering fills the background.

`layout.rects` is a read-only, zero-copy NumPy structured array with fields
`x`, `y`, `w`, `h` (native float32), `node` (native uint32), and `depth`, `cls`,
`flags`, `pad` (uint8), totaling 24 bytes per record. It keeps native storage alive
even when the layout wrapper or source tree is released. No Python node loop is
needed to compute geometry or images.

Tiny siblings and siblings omitted by the rectangle budget become one
`TmFlags.OTHER` rectangle with `node=0xFFFFFFFF`. `layout.small_items(index)` gives
its sibling count. Hit testing that group selects its containing real ancestor.
Directory rectangles carry `TmFlags.DIRECTORY`; their class cycles by depth.
File classes use the existing `ExtCategory` numeric IDs. Bounds are half-open,
so the right and bottom image edges are outside the hit region. Float32 edges
round inward to prevent sibling overlaps; subpixel gaps can select their ancestor.
`header_px`
reserves header space below the zoom root; `padding` applies to every directory.

Colors use `0xRRGGBBAA` integer notation, independently of machine byte order.
Alpha is preserved in flat and cushion modes. The native C++ renderer also accepts
explicit image dimensions and clips geometry without rescaling it. Negative
dimensions or buffer-size overflow raise an exception.

The algorithms are original implementations of
[Squarified Treemaps](https://vanwijk.win.tue.nl/stm.pdf) and
[Cushion Treemaps](https://vanwijk.win.tue.nl/ctm.pdf).
