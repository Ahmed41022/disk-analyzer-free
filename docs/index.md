# Disk Analyzer Free

Disk Analyzer Free is an open-source disk space analyzer for Windows, macOS, and Linux. It is being built with a Python user interface and CLI backed by a C++20 core.

The current milestone provides a buildable package, `dafree --version`, and an initial Qt window. Disk scanning, analysis, and file actions are future milestones; the current application does not inspect or change user files.

## Project status

The [implementation plan](PLAN.md) is the source of truth for architecture, scope, milestone order, and acceptance criteria. Completed M0 tasks are checked there. Planned user documentation will grow alongside each feature milestone.

## Get started

Install from a source checkout using the steps in the [README](https://github.com/Ahmed41022/disk-analyzer-free/blob/main/README.md#install). For development, see [Contributing](https://github.com/Ahmed41022/disk-analyzer-free/blob/main/CONTRIBUTING.md).

## Safety

The planned scanner does not follow symbolic links or junctions by default. Destructive operations are planned to use the trash or recycle bin by default, require confirmation, support dry-run, and avoid following links. These features are not present in the current scaffold.

## Reference material

- [Architecture and implementation plan](PLAN.md)
- [Decision log](https://github.com/Ahmed41022/disk-analyzer-free/blob/main/DECISIONS.md)
- [Security policy](https://github.com/Ahmed41022/disk-analyzer-free/blob/main/SECURITY.md)
- [License](https://github.com/Ahmed41022/disk-analyzer-free/blob/main/LICENSE)
