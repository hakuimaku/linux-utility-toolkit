# Linux Utility Toolkit (LUT)

LUT is a Linux command-line toolkit under development. **Milestone 5 — Image Tools**
implements operational image tools (`image convert`, `image compress`, `image resize`,
`image crop`, `image rotate`, `image metadata`), alongside Milestone 4 archive tools
(`archive compress`, `archive extract`, `archive list`, `archive test`), Milestone 3
search (`search content`, `search name`), and file management (`file hash`, `file info`,
`file duplicates`, `file rename`) tools.
Other utility groups (video, audio, wifi, bluetooth, system) remain
planned and marked **help only; not implemented**.
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
| `3` | Missing backend or unsupported backend version |
| `4` | Missing or malformed input |
| `5` | Output conflict or filesystem access error |
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
switch in `cli.py`. Commands with handlers execute directly, while planned
commands reject execution with exit code 1.

## Search tools (M3)

- `lut search content <keyword> [path] [options]` (alias: `lut search <keyword>`):
  fast text search powered by `ripgrep` with streaming output, ignore-file support, and JSON.
- `lut search name <pattern> [path] [options]`:
  recursive glob search across files and directories (including empty dirs) using Python traversal.

See [Search documentation](docs/search.md) for complete options and backend details.

## File tools (M3)

- `lut file hash <file> [-a algo]`:
  chunked cryptographic checksums (SHA-256, SHA-512, SHA-1, MD5).
- `lut file info <path>`:
  metadata, size, timestamps, permissions and symlink inspection.
- `lut file duplicates [path]`:
  find duplicate files with hardlink-aware wasted space calculation.
- `lut file rename <inputs> [--prefix] [--suffix] [--replace] [--apply]`:
  preview-by-default safe batch renaming with preflight collision checks and atomic non-overwriting rename.

See [File tools documentation](docs/file.md) for complete details.

## Archive tools (M4)

- `lut archive compress <input> [--format zip|tar|tar.gz|tar.xz|7z] [--level N] [-o output]`:
  safe compression of files or directories with structure preservation, external symlink blocking, and non-overwriting atomic publication.
- `lut archive extract <archive> [-o destination]`:
  safe archive extraction with strict path traversal rejection, no symlink/special-file creation, ZIP bomb resource limits, and atomic directory publication.
- `lut archive list <archive> [--json]`:
  inspect archive contents and metadata with terminal control-character escaping without extracting.
- `lut archive test <archive> [--json]`:
  internal CRC and stream decompression integrity verification without disk writes.

See [Archive documentation](docs/archive.md) for format matrix, security guarantees, and limitations.

## Image tools (M5)

- `lut image convert <input> [--format FORMAT] [-o OUTPUT] [--quality N] [--background COLOR] [--frame N]`:
  safe image format conversion between JPEG, PNG, WebP, BMP, TIFF, and GIF with explicit transparency handling and animation loss protection.
- `lut image compress <input> [-q QUALITY] [-o OUTPUT]`:
  reduce image file size with lossy quality controls for JPEG/WebP, lossless compression for PNG, and accurate before/after size reporting.
- `lut image resize <input> [--width N] [--height N] [--fit contain|cover|stretch] [--allow-upscale] [-o OUTPUT]`:
  dimension resizing preserving aspect ratio by default, with bounding box contain/cover/stretch modes and upscale prevention.
- `lut image crop <input> --x N --y N --width N --height N [-o OUTPUT]`:
  pixel region cropping with strict boundary validation, virtual canvas reset (+repage), and transparency preservation.
- `lut image rotate <input> --angle N [--background COLOR] [-o OUTPUT]`:
  clockwise rotation in degrees, expanding canvas without corner cropping, auto-orienting EXIF and normalizing orientation metadata.
- `lut image metadata <input> [--json]`:
  read-only inspection of format, dimensions, colorspace, alpha channels, profiles, bit depth, and orientation without GPS data leakage.

See [Image documentation](docs/image.md) for supported formats, options, safety rules, and limitations.

## Core utilities

The APIs under `lut.core` provide:

- `output.atomic_output`: automatic names, numbered collisions, explicit output
  overrides, private staging and atomic publication without replacing an existing
  file or directory. Failed operations clean staging; dry runs only plan a path.
- `dependencies.require_executable` and `require_service`: on-demand PATH/version
  checks, distro-aware installation hints and caller-supplied service probes.
  No dependency is installed and no service is started.
- `process.run_process`: literal argument lists, completed exit status, bounded
  stdout/stderr capture, streaming progress callbacks, deadlines and process-group
  cleanup on timeout or cancellation. No arguments or backend output are logged.
- `config`: XDG config/cache/state paths and optional TOML loading without
  first-run writes. Relative XDG overrides are ignored.
- `errors` and `logging`: stable error codes, safe CLI diagnostics and scoped
  stderr logging. Private file logging requires an explicit destination.

See [Core API contracts and examples](docs/core.md) for usage and limitations,
including filesystem requirements and the scope of process-group cleanup.

No new CLI commands or options are introduced by M2. Core dry runs are available
to Python callers; the utility commands still reject execution, including their
planned dry-run invocations. Real image, video, archive and search operations
remain unimplemented.

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

Core tests cover real concurrent file/directory publication, collisions and
symlinks, rollback, permissions, dry-run side effects, XDG overrides, dependency
and service errors, process capture limits, Unicode progress, timeouts, real
SIGINT, descendant termination, descriptor cleanup and credential-free logs.

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
├── docs/
│   ├── core.md
│   ├── file.md
│   ├── search.md
│   ├── archive.md
│   └── image.md
├── src/lut/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── parser.py
│   ├── commands/
│   │   ├── __init__.py
│   │   └── <built-in command modules>.py
│   ├── services/
│   │   ├── search_service.py
│   │   ├── file_service.py
│   │   ├── archive_service.py
│   │   └── image_service.py
│   └── core/
│       ├── __init__.py
│       ├── output.py
│       ├── dependencies.py
│       ├── process.py
│       ├── config.py
│       ├── errors.py
│       └── logging.py
└── tests/
    ├── test_cli.py
    ├── test_help.py
    ├── test_search.py
    ├── test_file.py
    ├── test_archive.py
    ├── test_image.py
    └── core/
```

M2 adds no runtime or development dependencies. The package stays on the standard
library at runtime. All utility implementations belong to later milestones.

## License

MIT; see [LICENSE](LICENSE).
