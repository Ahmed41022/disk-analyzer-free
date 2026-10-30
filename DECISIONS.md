# Decision log

## D-0001 — 2026-10-30 — Windows stable ABI loading

Context: The Windows test environment uses a managed CPython installation and MinGW. Its venv did not automatically expose the interpreter's stable ABI DLL or MinGW runtime DLLs while loading the extension.

Decision: Add the interpreter base directory before loading the native module and statically link MinGW runtime libraries for MinGW builds.

Reasoning: This keeps local package tests runnable without changing the stable ABI module contract or adding runtime dependencies to MSVC builds.

Alternatives: Require a manually configured DLL search path, or bundle compiler runtime DLLs with the package. Both add setup or packaging burden.

Task: T0.1
