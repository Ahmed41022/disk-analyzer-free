# Performance checks and fixture tools

## Milestone verification

CI requires a 1,000-example Hypothesis scan-accounting property on every Python
matrix job. It generates exclusions, hidden flags, repeated file identities,
both hard-link policies, and sizes up to the unsigned 64-bit maximum, then checks
native totals and duplicate flags against independent Python accounting.

The full native suite runs under GCC AddressSanitizer and UndefinedBehaviorSanitizer,
with leak detection enabled. ThreadSanitizer separately exercises scanner controls,
snapshots, owner lookups, and allocation instrumentation.

GCC/gcovr coverage enforces at least 85% lines for the model and scanner independently,
including their public headers. Local results on 2026-10-31 are 88.8% model,
87.7% scanner, and 88.2% combined. Coverage HTML, XML, and JSON reports are retained
as the `native-coverage` CI artifact. Branch coverage is reported without a branch
threshold.

Coverage builds use atomic profiling counters because scanner workers execute the
same instrumented functions concurrently. Parse errors remain fatal. Enable the
coverage preset with:

```console
cmake --preset coverage -DCMAKE_CXX_COMPILER=g++
cmake --build build/coverage --target dafree_core_tests
ctest --test-dir build/coverage --output-on-failure
```

## Memory budget

The native tests `memory_per_node_steady_le_100` and
`memory_per_node_peak_le_140` each scan exactly 1,000,000 nodes through MockBackend.
The virtual tree uses 8–40 byte names, ten children per directory, and 10%
directories. Both limits run in the ordinary C++ test suite on Windows, Linux,
and macOS.

The `builder_small_batches_reuse_allocations` regression checks 20,000 one-child
appends against an allocation-call budget. It reproduced 625 allocations before
removing repeated exact reserves, and now uses 10. The million-node scans retain
their two-minute timeout and unchanged memory limits.

The counting `operator new/delete` replacements are linked only into
`dafree_core_tests`. They cover scalar, array, aligned, sized-delete, and
nothrow forms. Measurements count requested C++ allocation bytes; instrumentation
headers, allocator implementation overhead, thread stacks, and OS working-set
pages are outside this metric. It is not an RSS measurement.

The in-memory mock filesystem is constructed before the baseline and kept alive
throughout measurement. This input models an external filesystem and is excluded
from scanner overhead. The peak starts before `start_scan`; steady storage is
measured after `take_result` and destruction of the scan handle, while retaining
the result tree. Identity sets and scan queues therefore contribute to peak but
not to retained tree storage. No partial snapshots are requested.

Measured locally on 2026-10-31, Debug builds, four scanner threads:

| Platform | Retained bytes/node | Peak bytes/node | Limits |
| --- | ---: | ---: | --- |
| Windows, MinGW | 88.1194 | 125.664 | 100 / 140 |
| Linux, GCC in WSL | 88.1194 | 92.4777 | 100 / 140 |

Windows tracks every regular-file identity during deduplication; POSIX tracks
multiply linked files. This accounts for much of the peak difference.

MinGW native tests statically link their C++ runtime so replacement allocations
are consistent across runtime calls. Linux Clang ThreadSanitizer tests use the
dynamic sanitizer runtime, permitting those replacements while retaining memory
interception and race instrumentation. Allocation accounting and concurrency
tests run together under that runtime.

## Benchmarks

Build a Release benchmark executable:

```console
cmake --preset bench
cmake --build build/bench --target dafree_bench
```

Use `build/bench/core/bench/dafree_bench` (with `.exe` on Windows). Run scan and
aggregation measurements in separate processes:

```console
dafree_bench --benchmark_filter=BM_ScanMock --benchmark_min_time=0.3s --benchmark_repetitions=5 --benchmark_out=scan.json --benchmark_out_format=json
dafree_bench --benchmark_filter=BM_Aggregate --benchmark_min_time=0.5s --benchmark_repetitions=5 --benchmark_out=aggregate.json --benchmark_out_format=json
```

The scan benchmark constructs its immutable input backend before timing, then
times complete scans with four workers and result cleanup. It uses real elapsed
time because workers perform most of the CPU work. CI builds the benchmark on
all three operating systems and runs a 10,000-node smoke case.

Local Windows Release measurements on 2026-10-31, MinGW, 24 logical CPUs:

| Benchmark | Median elapsed time, five repetitions |
| --- | ---: |
| Scan 10,000 mock nodes | 26.36 ms |
| Scan 100,000 mock nodes | 241.59 ms |
| Scan 1,000,000 mock nodes | 2,446.72 ms |
| Aggregate 10,000,000 nodes | 104.42 ms |

The million-node scan median corresponds to approximately 409,000 nodes/second.
An additional controlled comparison alternated five old/new runs after a warmup
for each binary, changing only the builder object. Million-node medians were
2,433.37 ms before and 2,456.17 ms after (+0.94%, within the 15% regression
threshold). Earlier measurements under different machine load were faster; they
are not used as a regression baseline.

These are developer-machine measurements, not performance guarantees. The scan
million-node elapsed-time coefficient of variation was 14.51%; aggregation was
noisier at 44.84%. Keep build configuration, machine load, and fixture identical
when comparing revisions.

## Deterministic filesystem fixtures

```console
python tools/gen_fixtures.py --preset small --out NEW_DIRECTORY
```

Presets are `small` (1,000 nodes), `ci_500k` (500,000), `1m`, `10m`, and
`dupes_mix` (1,000). Node counts include the output root and exclude
`manifest.json`. Trees have about 10% directories and balanced depth of roughly
3–7 levels, within the planned 3–12 range. Log-normal file sizes use a fixed seed
and are capped at 1 GiB. Files contain sparse zero-filled ranges. `dupes_mix`
deliberately reuses file lengths to provide duplicate zero-filled contents.

On Windows the generator marks each opened file sparse before truncating that
same handle; other platforms create holes through `os.truncate`. This keeps
physical disk usage low. The tool refuses existing outputs, symlink/junction
ancestors, and unsupported sparse operations. It never overwrites or deletes
existing files. A failed generation can leave its new partial output for review.

`manifest.json` contains `total_size`, `files`, `dirs`, and `listing_sha256`, plus
the preset, node count, and seed. Totals and the hash exclude the manifest itself.
The hash covers UTF-8 JSON rows `[relative_posix_path, kind, size]`, with compact
separators and a newline per row, in lexical path order. The output-root directory
is omitted from rows and directory totals. Tests independently enumerate actual
files to verify totals, hash, and repeatability.

## Regression comparison

```console
python tools/bench_compare.py --gbench-base base.json --gbench-head head.json --threshold-pct 15 --summary NEW_SUMMARY.md
```

The comparator normalizes time units, compares medians of repeated `real_time`
samples, and falls back to supplied median aggregates. A slowdown strictly above
the threshold or a missing head benchmark exits 1. Invalid input exits 2. Existing
summaries and linked output paths are refused. The summary is a Markdown table.

M1 compares Google Benchmark JSON only. The planned `--base`, `--head`,
`--fixture`, `--runs`, and `--rss-threshold-pct` options are accepted for interface
compatibility; CLI warmups, alternating binary runs, wall-time medians, and peak
RSS comparisons become active with T2.2's `scan --stats-json`. Their absence in
M1 is the plan's explicit staging rule.
