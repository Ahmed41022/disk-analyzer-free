# Decision log

## D-0001 — 2026-10-30 — Windows stable ABI loading

Question: How should local Windows venv tests load the stable ABI module with the available managed CPython and MinGW toolchain?

Choice: Add the interpreter base directory before loading the native module and statically link MinGW runtime libraries for MinGW builds.

Reasoning: This keeps local package tests runnable without changing the stable ABI module contract or adding runtime dependencies to MSVC builds.

Alternatives: Require a manually configured DLL search path, or bundle compiler runtime DLLs with the package. Both add setup or packaging burden.

Task: T0.1

## D-0002 — 2026-10-30 — CLI exit code names

Question: How should `exit_codes.py` expose values when the plan only specifies the missing-GUI exit status?

Choice: Provide an `ExitCode` integer enum with `SUCCESS = 0`, `ERROR = 1`, and `USAGE = 2`.

Reasoning: Named values make the scaffold's exit statuses clear while preserving Click's specified usage error code of 2.

Alternatives: Use bare integer constants; these provide no additional clarity over the enum.

Task: T0.4

## D-0003 — 2026-10-30 — Staged CI rollout

Question: How can CI stay green while the plan's complete workflow refers to presets, tools, and feature tests that are scheduled for later tasks?

Choice: Start with a required `ci-success` check covering the current lint, C++ build, Python tests, and dependency audits; add the remaining workflow jobs when their planned prerequisites are implemented.

Reasoning: This lets every push be checked without pulling later milestone work forward or hiding missing checks behind skipped jobs.

Alternatives: Add the full workflow immediately, which would fail on files and test suites that do not exist yet; or mark those jobs skipped, which would not verify them.

Task: T0.5

## D-0004 — 2026-10-30 — NumPy license expression

Question: How should the runtime allowlist treat NumPy's compound license expression, which the planned exact allowlist does not include?

Choice: Add NumPy's exact expression `BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0` to the exact allowlist.

Reasoning: NumPy is an explicitly required dependency and the listed identifiers are permissive; exact matching keeps mixed expressions from passing through a broad partial match.

Alternatives: Use partial matching, which could admit an expression containing a forbidden license, or remove NumPy contrary to the plan.

Task: T0.5
