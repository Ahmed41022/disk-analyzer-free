# Command line interface

Use `dafree --help` for the available commands and options. Global options go
before the command name and apply to that invocation. Scanning, reporting and
shell completion follow their planned tasks.

| Option | Meaning |
| --- | --- |
| `--format table\|json\|ndjson\|csv` | Select a report format. The default is table on a terminal and JSON when redirected. |
| `--units auto\|b\|kb\|mb\|gb\|tb` | Select automatic or fixed-size units. |
| `--si`, `--iec-labels` | Choose decimal SI units or IEC binary labels. Specify one at most. |
| `--no-color` | Disable table colors. A nonempty `NO_COLOR` also disables colors. |
| `--locale TAG` | Select a shipped locale. |
| `-q`, `-v` | Decrease or increase verbosity. Both can be repeated. |
| `--progress auto\|always\|never` | Select progress output policy for commands that report progress. |
| `--threads N` | Set the requested worker count. `0` selects it automatically. |
| `--config FILE` | Read global option defaults from TOML. Explicit command-line options take precedence. |
| `--portable` | Request portable mode. This currently reports a usage error until T10.2 supplies portable storage. |

The TOML file uses top-level long option names without the leading dashes.
For example, `threads = 4`, `format = "json"` and `no-color = true` set three
defaults. Unknown keys and malformed values report a usage error. The settings
commands below manage persistent preferences separately from this file.

See [exit codes](reference/exit-codes.md) for process status meanings.

## Configuration commands

```console
dafree config path
dafree config get theme
dafree config set theme dark
dafree config set default_scan.threads 4
dafree config set default_scan.follow_symlinks false
dafree config set units auto
dafree config set unit_style.system iec
```

`get` prints a JSON value. `set` accepts JSON numbers, booleans, null, arrays,
and objects, or a bare string such as `dark`. Quote JSON for your shell:

```sh
dafree config set default_scan.exclude.globs '["*.tmp", "build/**"]'
dafree config set locale null
dafree config get default_scan.exclude.globs
```

Keys use dotted field names. Lists accept non-negative indices, for example
`columns.0.width`; dictionary keys such as `shortcuts.new_scan` can be added.
Optional objects such as `window` must be initialized as an object before
editing their individual fields. Unsupported keys or invalid types exit with
status 2 and leave the previous preferences unchanged. File access errors and
unsupported future schema versions exit with status 1. Schema `version` is
managed by migrations and cannot be changed with `config set`.

## Storage and recovery

CLI and GUI share `settings.json` in
`platformdirs.user_config_dir("disk-analyzer-free", appauthor=False)`.
`config path` prints the actual location without creating it. Saving validates
the complete document, flushes and fsyncs a sibling temporary file, and atomically
replaces the previous file. Failed saves retain the original.

Corrupt JSON, UTF-8, or schema data is preserved as
`settings.json.bad-<unix timestamp>`; a numeric suffix avoids replacing an earlier
backup from the same second. Defaults are then loaded. A future schema version
is left untouched and reported as unsupported. Unversioned/v0 preferences retain
known fields, receive v1 defaults, and are upgraded on the next explicit save.

Preferences include theme (`system`, `light`, `dark`), locale, unit mode/style,
column visibility/width/order, scan defaults, duplicate defaults, window geometry,
shortcuts, and treemap defaults. Recent targets retain at most ten entries, most
recent first. These preferences do not enable features from deferred tasks.
Portable detection is a stub until T10.2; explicit portable requests report an
error rather than silently use normal directories.

## Test isolation

`DAFREE_CONFIG_DIR` is a **test-only override**, not a supported portable-mode
interface. Set it to a directory created by the test: preferences use that root,
and data/log/snapshot directories are contained below it. Tests must never write
real user preferences. The override does not create directories until needed.
