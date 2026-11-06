# Core utilities (M2)

These are Python APIs for future command handlers. M2 does not make any utility
command operational or add backend-specific CLI options. All APIs use the Python
standard library. Help and version output never read config, check backends or
create cache/state/log files.

## Output transactions

```python
import shutil
from pathlib import Path
from lut.core.output import atomic_output

source = Path("notes.txt")
with atomic_output(source, "copy") as output:
    shutil.copyfile(source, output.temporary)
print(output.destination)
```

This library example produces `notes_copy.txt` beside its input, or
`notes_copy_2.txt`, `_3`, etc. The CLI `file` commands remain unimplemented.

`output_path(source, suffix, *, extension=None, output=None, directory=False)`
validates the input and returns an absolute planned destination without creating
anything. The last input extension is retained unless replaced by `extension`;
input directory names retain their dots. Compound output extensions such as
`.tar.gz` stay intact when collision numbers are added.

`atomic_output` accepts the same arguments plus `dry_run=False`. It yields
`OutputPaths(destination, temporary)`. A file staging path already exists and
retains the final extension; a directory staging path is a private empty
directory. The caller must write only to that staging path, finish the backend
and close its writers before exiting the context. Any exception, including
cancellation, attempts staging cleanup without publishing the result. Cleanup
failures are reported explicitly rather than hidden.

Only a successful context publishes output. Existing entries, including dangling
symlinks, are never replaced. Automatic names retry if another writer creates
the candidate before publication; read `output.destination` after context exit
for the final name. An explicit `output=` conflict raises `OutputError` instead
of choosing another path. Treat the yielded object's fields as read-only.
Backend output that becomes a symlink or hard link to the original is rejected.

With `dry_run=True`, `temporary` is `None`: no file, directory or backend is
created. This is path planning, not a preview of an unimplemented utility.
Source files and directories are never deleted by these APIs.

File publication uses a same-filesystem hard link. Directory publication uses
Linux `renameat2(RENAME_NOREPLACE)` because ordinary rename can replace an empty
directory. The filesystem must support the relevant primitive; directory output
also needs the libc wrapper. Unsupported operations fail with code `5`, without
falling back to an overwrite. Atomic visibility does not promise power-loss
durability. See the [Linux rename contract](https://man7.org/linux/man-pages/man2/rename.2.html).

## Dependency checks

`require_executable(name, *, packages=None, minimum_version=None,
version_args=("--version",))` resolves the executable through `PATH`, returning
its absolute path. Checks occur only when called by a feature. An optional
minimum is a tuple such as `(2, 0, 0)`; missing zero components compare equally.
The probe has a five-second deadline and bounded capture. It expects the first
dotted numeric release in the banner. Unknown, prerelease or tagged version
formats fail closed; this is not a complete semantic-version parser.

Missing/unsupported backends raise `DependencyError` (code `3`). If `packages`
maps distro families to known package names, the error includes a manual
`pacman -S`, `apt install` or `dnf install` suggestion, using os-release `ID` and
`ID_LIKE`. Unknown distros get a generic instruction. LUT never invokes those
commands or assumes executable names are package names. Distro behavior is unit
tested with release fixtures, not claimed as live cross-distro certification.

`require_service(name, probe, *, expected_output=None, timeout=5)` runs a probe
chosen by the feature, optionally comparing stripped stdout. It does not assume
systemd, start a service or replace a network manager. A missing probe executable
is still code `3`; failed/timed-out probes or unexpected service state raise
`ServiceUnavailable` (code `1`).

## Process execution

```python
import sys
from lut.core.process import run_process

result = run_process([sys.executable, "-c", "print('ready')"], timeout=5)
assert result.executed and result.returncode == 0
assert result.stdout == "ready\n"
```

`run_process` requires an argument list, never command text or `shell=True`.
It accepts `cwd`, a complete `env` mapping, `timeout`, `dry_run`, a `progress`
callback and `capture_limit` (default: 4 MiB combined stdout/stderr). Both pipes
are drained concurrently. Capture overflow stops the process and raises an
error instead of consuming unbounded memory or silently truncating results.

The result contains `returncode`, `stdout`, `stderr` and `executed`. Output is
decoded as UTF-8 with replacement of invalid bytes. `progress(stream, text)`
receives incrementally decoded chunks from `stdout` or `stderr`; chunks need not
be lines and the callback must not block. No percentage is guessed. Backend
progress parsing belongs to the corresponding later milestone.

The runner is noninteractive (`stdin=DEVNULL`). A nonzero status raises
`ProcessError`, retaining the backend's `returncode` separately from LUT's exit
code `1`. Timeout raises `ProcessTimeout`. Ctrl+C raises `CancelledError` with
code `130` after cleanup. A new process session owns each backend: failure,
timeout, callback error or cancellation sends SIGTERM then SIGKILL as needed,
closes both pipes and reaps the leader. Descendants remaining in that process
group are also killed. Backends that deliberately detach into another session
are outside this ownership contract and should not be used with this runner.
Orphaned descendants are reaped by the system's init process.

The deadline also covers waiting after pipes close. OS process creation itself
cannot always be interrupted. A successful return means the backend completed,
not merely that it started. `dry_run=True` starts nothing, performs no backend
lookup and returns `executed=False`; it must not be reported as an execution
success. See [Python subprocess semantics](https://docs.python.org/3.11/library/subprocess.html).

## XDG config and paths

`config_file()`, `cache_dir()` and `state_dir()` default to:

- `~/.config/lut/config.toml`
- `~/.cache/lut/`
- `~/.local/state/lut/`

Absolute, nonempty `XDG_CONFIG_HOME`, `XDG_CACHE_HOME` and `XDG_STATE_HOME`
overrides are honored. Relative values are ignored, following the
[XDG Base Directory Specification](https://specifications.freedesktop.org/basedir/latest/).
Path lookup creates nothing. `load_config()` returns `{}` if the default file
is absent. An explicit missing file raises `InputError`; malformed UTF-8/TOML
and nonregular config paths also use code `4`; access failures use code `5`.
Returned TOML values have no
feature-specific schema yet. There is no automatic config writer.

## Errors and logging

`LutError` subclasses use the existing codes: usage `2`, dependency `3`, input
`4`, output/access `5`, cancellation `130`; generic execution/service/process
failures use `1`. CLI handlers report expected messages without tracebacks.
Unexpected exception data is hidden because it may include credentials or
complete subprocess arguments. Broken stdout pipes keep the existing quiet
code `141` behavior.

```python
from lut.core.config import state_dir
from lut.core.logging import logging_context

with logging_context(verbose=True, log_file=state_dir() / "lut.log") as log:
    log.debug("Operation prepared.")
```

Without `log_file`, logging uses stderr and creates no files. Explicit log
files append with verified mode `0600`; symlinks, hard links and nonregular log
targets are rejected. Filesystems that cannot enforce private permissions are
also rejected before any log event is written. Logging contexts restore previous
handlers and levels on exit.
File logs do not rotate automatically. The runner logs lifecycle/status metadata
only: never arguments, environment values, stdout or stderr. Captured output and
progress belong to the caller and are not automatic logs; callers must keep
their own secret values out of custom messages.
