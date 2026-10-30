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
