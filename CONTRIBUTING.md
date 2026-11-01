# Contributing

Thanks for helping improve Disk Analyzer Free. The project is in early development; check the [plan](docs/PLAN.md) before proposing work so changes fit the current milestone.

## Development setup

You need Python 3.12 or newer, a C++20 compiler, CMake 3.26 or newer, and Ninja. On Windows use Visual Studio 2022 Build Tools with the C++ workload; on macOS use Apple Clang and the command line developer tools; on Linux use GCC 12 or newer. Linux GUI tests need the Qt runtime libraries installed by CI, including `libegl1`, `libgl1`, `libxkbcommon0`, `libxkbcommon-x11-0`, `libfontconfig1`, `libdbus-1-3`, and `libxcb-cursor0` on Debian-based systems.

From the repository root:

```console
python -m pip install cmake ninja
python -m pip install -r requirements/dev.txt
python -m pip install -e ".[gui]"
```

Editable installs use scikit-build-core to build the C++ extension.

## Linux quick setup (Debian / Ubuntu)

From the repository root, install the compiler and Qt offscreen runtime libraries:

```sh
sudo apt-get update
sudo apt-get install --yes build-essential python3-dev python3-venv \
  libegl1 libgl1 libxkbcommon0 libxkbcommon-x11-0 libfontconfig1 \
  libdbus-1-3 libxcb-cursor0 fonts-dejavu-core
python3 -m venv .venv
. .venv/bin/activate
python -m pip install cmake ninja scikit-build-core
python -m pip install --require-hashes -r requirements/dev.txt
export CMAKE_GENERATOR=Ninja
export FETCHCONTENT_BASE_DIR="$PWD/.deps"
export CMAKE_BUILD_PARALLEL_LEVEL=4
python -m pip install ".[gui]" --no-build-isolation -Cbuild-dir=build/python-dev
QT_QPA_PLATFORM=offscreen python -m pytest -m "not slow"
```

Use Python 3.12+ and GCC 12+. The locked development requirements include the
nanobind and Babel build requirements. `build/python-dev` keeps the CMake/Ninja
build and `.deps` keeps FetchContent sources inside the repository; both are in
`.gitignore`. After recreating `.venv` at the same path, repeat the pip commands
with these exports to reuse the native build and downloaded dependencies.
Do not delete either cache to refresh only Python packages. A compiler, Python
ABI, or build-configuration change can legitimately require recompilation.

This quick setup uses an ordinary package installation so compiled gettext
catalogues load from the installed package. Repeat the last pip command after
source edits; unchanged native objects remain incremental. Fresh editable
installs currently resolve catalogue paths to the source tree, which does not
contain tracked `.mo` files (see D-0036 in `DECISIONS.md`). On WSL, keeping the
Python environment on the Linux filesystem avoids slow package extraction on
Windows mounts; the native build and FetchContent cache still stay inside this
repository as above.

## CI gates after M4-core

M4-core is complete. Every configured CI event now runs all existing gates:
lint/types/stubs, full native and Python correctness suites on all three OSes,
coverage, sanitizers, wide fixtures, installed abi3 wheels, and release performance.
The explicit slow repaint test runs without coverage instrumentation; its Linux
leg runs on every event, with additional Windows/macOS legs nightly. Thresholds
and assertions are unchanged. Report every job's duration in the PR summary.

## Common checks

```console
ruff check .
ruff format --check .
mypy
python -m pytest -m "not slow"
cmake --preset dev
cmake --build --preset dev
ctest --preset dev --output-on-failure
```

The GUI tests run offscreen in CI. Set `QT_QPA_PLATFORM=offscreen` when running them in a headless environment. If Qt is installed, the smoke test opens and closes the window; CI sets `DAFREE_REQUIRE_GUI=1` so a missing Qt installation fails instead of silently skipping the test.

The GUI repaint benchmark runs in Release, with real system fonts, exactly ten
million native rows, and 60 viewport jumps. It retains every sample and enforces
median ≤16.7 ms and p95 ≤33 ms. CI runs its Linux leg on every event and all
three OSes nightly. For local Linux verification, reuse the repo's caches:

```sh
SKBUILD_CMAKE_BUILD_TYPE=Release python -m pip install ".[gui]" --no-build-isolation -Cbuild-dir=build/gui-scroll-release
QT_QPA_PLATFORM=offscreen python -m pytest tests/perf/test_tree_scroll.py -m slow -s
```

Windows offscreen tests read installed fonts from `SYSTEMROOT/Fonts` unless
`QT_QPA_FONTDIR` is already set. No fonts are bundled. Official Windows CI and
wheels use MSVC. The optional local MinGW GCC 15.1.0 fallback disables Release
binding LTO to avoid an observed compiler crash; other optimization and all
supported toolchains remain unchanged (D-0046).

Filesystem tests can describe a tree with `tests.testkit.spec`, create it under pytest's `tmp_path` with `Fixture.create`, and compare logical totals with `oracle`. Keep each fixture inside the test's temporary directory. Call `fixture.caps.require("feature")` before relying on an optional OS feature; CI sets `DAFREE_REQUIRE_ALL_CAPS=1` so an unexpected missing capability fails the test.

On Linux with Clang and libFuzzer installed, build the glob fuzz target with `cmake --preset fuzz -DCMAKE_CXX_COMPILER=clang++` and `cmake --build build/fuzz --target fuzz_glob`. Run it with a corpus directory created for that test, for example `build/fuzz/core/fuzz_glob /path/to/temporary/corpus -runs=10000`. CI builds the target and runs a smoke campaign with address and undefined-behavior sanitizers.

The Linux scanner concurrency gate uses `cmake --preset dev-tsan -DCMAKE_CXX_COMPILER=clang++` and `cmake --build build/dev-tsan --target dafree_core_tests`. Run the scanner cases with `TSAN_OPTIONS=halt_on_error=1`; the CI workflow lists their doctest names explicitly.

## Project boundaries

- The Python package owns orchestration and the user interface; the C++20 core owns work over file-system entries.
- `dafree.api` is the only Python package layer that imports `dafree._core`.
- OS-specific calls belong under `core/src/platform/`.
- Keep C++ warning checks enabled and use RAII for resource ownership.
- Do not use `shutil.rmtree` or `os.system`.
- Filesystem tests must create and use temporary directories owned by the test.
- Add tests for behavior changes and keep documentation current.

## Stubs, translations, and documentation

After changing nanobind bindings, regenerate the checked-in type stub:

```console
python tools/gen_stubs.py
```

When adding a translation, initialize its gettext catalogue with `pybabel init -l xx`. Update `src/dafree/i18n/dafree.pot` with `pybabel extract`, then run `python tools/i18n_check.py` to check for stale strings and placeholder mismatches. Build the documentation with:

```console
mkdocs build --strict -f docs/mkdocs.yml
```

## Commits and reviews

Use [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/) such as `feat:`, `fix:`, `test:`, `docs:`, `ci:`, and `chore:`. Keep a commit focused on one task. Pull requests should explain the change, link a related issue, include tests, regenerate stubs when needed, update docs, and include screenshots for visible UI changes.

There is no DCO requirement. Contributions are accepted under the project's MIT license.


### Coverage checks

Coverage jobs run the complete correctness suite on Linux, Windows,
and macOS, retaining Python XML/data reports. Overall/API/settings/paths remain
at 85%, CLI at 80%, and GUI at 70%; native model/scanner line gates remain 85%
each on Linux. Repaint budgets run separately without coverage instrumentation.
The optional Codecov upload runs only when the repository has `CODECOV_TOKEN`;
thresholds and artifacts remain mandatory without it. Use `coverage run
--parallel-mode -m pytest -m "not slow"`, then `coverage combine --keep` and
`coverage report` for a local report. Keep per-platform `COVERAGE_FILE` paths
separate when testing Windows and WSL concurrently.
