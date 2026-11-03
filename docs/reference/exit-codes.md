# Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success. |
| `1` | Runtime failure, such as an I/O error. |
| `2` | Usage error, such as an invalid option or option value. |
| `3` | An alert threshold was exceeded. |
| `4` | A scan using `--strict` completed with access errors. |
| `5` | A command using `--fail-if-found` found a result. |
| `10` | Safety checks blocked an action. |
| `130` | The user interrupted the command. |

Commands write diagnostics to stderr. Codes for scan, report and action features
are reserved here for their planned commands.
