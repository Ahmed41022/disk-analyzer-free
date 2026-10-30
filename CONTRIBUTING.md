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
