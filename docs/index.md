# Disk Analyzer Free

Disk Analyzer Free is an open-source disk space analyzer for Windows, macOS, and Linux. It is being built with a Python user interface and CLI backed by a C++20 core.

The Python API supports asynchronous walk scanning, progress and cancellation, exclusions, link and mount policies, lossless native paths, and POSIX owner resolution. The package also provides `dafree --version` and an initial Qt window. CLI scanning, GUI views, analysis, and file actions are staged in later milestones.

## Project status

The [implementation plan](PLAN.md) is the source of truth for architecture, scope, milestone order, and acceptance criteria. Completed tasks are checked there. [Performance checks and tools](performance.md) document the million-node memory budget and reproducible benchmarks.

## Get started

Install from a source checkout using the steps in the [README](https://github.com/Ahmed41022/disk-analyzer-free/blob/main/README.md#install). For development, see [Contributing](https://github.com/Ahmed41022/disk-analyzer-free/blob/main/CONTRIBUTING.md).

## Safety

The scanner does not follow symbolic links or junctions by default and stops at filesystem boundaries unless explicitly instructed otherwise. Destructive operations are planned to use the trash or recycle bin by default, require confirmation, support dry-run, and avoid following links.

## Reference material

- [Architecture and implementation plan](PLAN.md)
- [Decision log](https://github.com/Ahmed41022/disk-analyzer-free/blob/main/DECISIONS.md)
- [Security policy](https://github.com/Ahmed41022/disk-analyzer-free/blob/main/SECURITY.md)
- [License](https://github.com/Ahmed41022/disk-analyzer-free/blob/main/LICENSE)
