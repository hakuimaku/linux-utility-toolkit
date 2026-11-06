# Linux Utility Toolkit (LUT)

LUT is a Linux command-line toolkit under development. **Milestone 1 — CLI & Help**
provides nested command documentation, argument parsing and module registration.
All utility operations are marked **help only; not implemented** and never run.
The development version remains `0.0.0`; `0.1.0` is reserved for release.

This is a standalone Python project. Installation does not change system
configuration.

## Requirements and installation

Python 3.11 or newer with `venv` and `pip` is required. No root access or external
utility backend is needed. LUT has no runtime dependencies outside the standard
library. Building the package uses setuptools 77 or newer.

From the repository root:

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
```

The explicit installation command may download the build tool. LUT itself never
installs dependencies, runs a package manager or creates a config on startup.

## CLI and help

```bash
lut --version
lut help
lut --help
lut help --all
lut search help
lut search content --help
lut image convert help
lut image convert --help
python -m lut --version
python -m lut image convert help
```

Calling `lut` or a command group such as `lut search` without a subcommand shows
that group's help. `help` and `--help` work at every registered command level;
`lut help --all` prints the entire tree. Help includes usage, arguments, options,
examples, output behavior and dependencies. It never checks or starts a backend.
Each utility leaf includes 1–3 operation examples marked `planned; not implemented`.
These examples use only the syntax currently accepted by M1; they do not execute
the operation or imply support for options from later milestones.

The registered groups are `search`, `file`, `archive`, `image`, `video`, `audio`,
`wifi`, `bluetooth` and `system`, with the subcommands from the specification.
Their help describes initial, planned input arguments. It is not a promise that
the complete future option set is already accepted. In particular, the
`lut search "keyword"` shortcut and search filtering belong to Milestone 3.

Options have explicit scope:

- `--version` is a root option: `lut --version`.
- `--verbose` works before or after command names. For an unavailable operation,
  it adds command and dry-run diagnostics to stderr without logging operands.
- `--dry-run` is accepted only on leaf commands that would modify files or
  connection state, such as `image convert`, `file rename` and `wifi connect`.
  It is rejected for read-only queries and command groups. **No preview is
  implemented yet**: a syntactically valid operation still returns `1`, including
  a dry run, and creates no files or side effects.

A trailing `help` at a command position requests documentation. To pass a literal
input named `help`, use `--`, for example `lut search content -- help`. Quoting
alone does not distinguish that word from the help alias.

| Exit code | Meaning |
| --- | --- |
| `0` | Help or version displayed successfully |
| `1` | Syntactically valid operation is not implemented; future execution error |
| `2` | Invalid command, option or missing required argument |
| `3` | Reserved: missing backend |
| `4` | Reserved: invalid input |
| `5` | Reserved: output conflict or access error |
| `130` | Interrupted with Ctrl+C |
| `141` | Stdout pipe closed by the reader (`128 + SIGPIPE`) |

Piping help into `head`, for example `lut help --all | head -n 5`, exits quietly
when the reader closes early. LUT handles both writes and buffered stdout flushes
without a Python traceback or a shutdown error, following
[Python's stdout cleanup guidance](https://docs.python.org/3/library/signal.html#note-on-sigpipe).
With shell `pipefail` enabled,
an interrupted producer reports `141`; otherwise the pipeline uses the final
command's status.

Syntax errors print usage, valid command choices where applicable and a contextual
`--help` hint on stderr. No utility command currently reports an execution success.
Once search is implemented, code `1` can also mean no matches, following grep's
convention; this is not a working search feature in M1.

## Registering a module

Each built-in module in `src/lut/commands/` exposes `register(parser)` and declares
its command tree with `parser.add_command(...)`. Add the module to `MODULES` in
[`src/lut/commands/__init__.py`](src/lut/commands/__init__.py). **No edit to `cli.py`
is needed** to add a module or its help pages. Registration only describes syntax
and help; it must not check dependencies, read user files or perform operations.

`add_command` requires a name, description and examples. It accepts dependency
documentation, a scoped dry-run flag and an optional `handler(namespace) -> int`.
Commands without handlers are labeled help only; valid leaf invocations return
`1`. The handler contract supports future implementations without a dispatch
switch in `cli.py`. M1 registers no utility handlers. There is no plugin discovery
or external plugin framework.

## Development and validation

Install the optional test and lint tools inside the activated virtual environment:

```bash
python -m pip install -e '.[dev]'
python -m pytest
python -m ruff check .
python -m ruff format --check .
```

Unit tests derive help cases from the real registry, checking every level and
both help spellings. They cover recursive help, flag inheritance and scope,
syntax errors, literal `help` inputs, Ctrl+C, no backend checks and registration
of an additional fixture module without modifying `cli.py`.

Entry point tests run outside the source tree with no executable backends on
`PATH`. They exercise both launchers, including nested help, version, invalid
arguments and refusal of planned operations. They also check that invocations
create no files in the working directory.

CI is defined in [`.github/workflows/lut.yml`](.github/workflows/lut.yml).
It installs the package normally and runs LUT-only tests, lint and entry point
smoke checks on Ubuntu with Python 3.11–3.14. This matrix is not a claim of
verified compatibility across Linux distributions.

## Structure

```text
linux-utility-toolkit/
├── pyproject.toml
├── README.md
├── LICENSE
├── src/lut/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── parser.py
│   ├── commands/
│   │   ├── __init__.py
│   │   └── <built-in command modules>.py
│   └── core/__init__.py
└── tests/
    ├── test_cli.py
    └── test_help.py
```

The `core` namespace contains no utilities yet. Output/dependency/config/process
managers, logging infrastructure, real dry-run previews and every utility
operation remain outside M1. No additional runtime or development dependencies
are introduced by the help system.

## License

MIT; see [LICENSE](LICENSE).
