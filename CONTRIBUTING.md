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
