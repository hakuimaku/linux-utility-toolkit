# Search Tools (M3)

LUT Milestone 3 implements two search commands: `search content` and `search name`.

## 1. Content Search (`lut search content`)

### Overview
Searches for text or regex patterns in files recursively from the current working directory (or a specified directory/file).

### Syntax & Alias
```bash
# Explicit syntax
lut search content "database"
lut search content "TODO" ./src
lut search content "database" -i
lut search content "error" -e py
lut search content "warning" -l
lut search content "connection" -c

# Alias shortcut
lut search "database"
# Equivalent to: lut search content "database"

# Literal 'help' operand
lut search content -- help
```

### Options
| Option | Description |
| --- | --- |
| `-i`, `--ignore-case` | Case-insensitive matching |
| `-e`, `--ext EXT` | Filter files by extension (e.g. `py`, `.md`) |
| `-l`, `--files-only` | Output matching file paths only |
| `-c`, `--count` | Output match counts |
| `--regex` | Treat keyword as regular expression (default: literal string) |
| `--hidden` | Search hidden files and directories |
| `--no-ignore` | Do not respect `.gitignore` and ignore files |
| `--glob PATTERN` | Filter paths using glob patterns |
| `--max-depth N` | Limit directory recursion depth |
| `--json` | Output results in structured JSON format |

### Backend Design
- **Engine**: `ripgrep` (`rg`) backend.
- **Verification**: Checked on-demand via `lut.core.dependencies.require_executable("rg")` when the command runs (never checked during help).
- **Files-Only Optimization (`-l`) & NUL Delimiter**:
  - When `--files-only` is requested (plain text, `-c`, or `--json`), LUT executes `ripgrep -l --null` directly rather than parsing match lines.
  - Paths are streamed in 64 KiB chunks and split strictly on NUL bytes (`\0`).
  - Filenames are never modified with `.strip()`. Filenames containing embedded newlines (`\n`), leading or trailing whitespace, Unicode characters, and deep paths are preserved exactly as on disk without splitting into fake multiple paths.
  - Incremental UTF-8 decoding prevents multibyte character fragmentation across chunk boundaries.
  - Because `ripgrep -l --null` emits only matching paths without line contents, `--files-only` operates with bounded O(1) memory overhead and is completely immune to oversized lines in files.
- **JSON Schema Separation**:
  - *Standard search (`--json`)*: `{"matches_count": M, "files_count": F, "files": [ ... ]}`.
  - *Count only (`-c --json`)*: `{"matches_count": M, "files_count": F}`.
  - *Files only (`-l --json`)*: `{"files_count": F, "files": [ ... ]}` (`matches_count` is excluded because line matches are not counted in `-l` mode).
  - *Files only count (`-l -c --json`)*: `{"files_count": F}`.
  - *Zero matches*: Returns exit code `1`. For standard search: `{"matches_count": 0, "files_count": 0, "files": []}` (or `{"matches_count": 0, "files_count": 0}` with `-c`). For files-only search: `{"files_count": 0, "files": []}` (or `{"files_count": 0}` with `-c`).
- **Streaming & Memory Bounds**: Uses `subprocess.Popen` in a dedicated process session (`start_new_session=True`). Both human-readable text and structured JSON outputs are streamed through `tempfile.SpooledTemporaryFile(max_size=1MB)` to disk when output exceeds 1 MiB.
- **Large Line & Record Limits**:
  - In match modes, ripgrep JSON records up to `MAX_RECORD_CHARS = 10,000,000` (~10 MiB) are processed completely and accurately without false negatives (lines of 2 MiB, 4 MiB, etc. are matched and context-truncated correctly).
  - *Character vs. Byte Limits*: Stream decoding uses `TextIOWrapper`, where reading limits govern Unicode code points rather than raw bytes (e.g. multi-byte UTF-8 sequences consume 1–4 bytes per code point).
  - *Fail-Loud Integrity Guarantee*: If a search record exceeds `MAX_RECORD_CHARS` or contains malformed JSON, LUT halts execution immediately and raises `ProcessError` (exit code `1`) with a diagnostic error on `stderr`. It **never** silently swallows truncated records, **never** outputs false-negative "No matches found", and **never** presents incomplete counts as complete.
- **Stderr Retention Limit**: Backend stderr capture is capped at `MAX_STDERR_BYTES = 64 KiB` (with a truncation notice) to prevent memory exhaustion under massive error logs while preserving crucial error diagnostics (regex syntax errors, permission issues).
- **Line Truncation & Highlighting**: In text output, lines longer than 200 characters are context-truncated around the match keyword. ANSI color highlighting is applied when stdout is a TTY and disabled when redirected to pipes/files.
- **Signals & Cleanup**: Interruption (SIGINT / Ctrl+C) immediately terminates the child process group via `_stop()` without leaving zombie processes.
- **Ignore Rules**: By default, `.gitignore` is honored inside git repositories. Binary files are skipped. Directory symlinks are not followed.

### Exit Codes
- `0`: Matches found.
- `1`: No matches found.
- `2`: Syntax error or invalid regular expression.
- `3`: Missing `ripgrep` executable on `PATH`.
- `4`: Search path does not exist.
- `5`: Permission denied accessing path or file.
- `130`: Interrupted (Ctrl+C).
- `141`: Stdout pipe closed by reader.

---

## 2. Filename Search (`lut search name`)

### Overview
Finds files and directories by name matching a glob pattern recursively.

### Syntax
```bash
lut search name "*.py"
lut search name "*.json" ./src
lut search name "*config*"
lut search name "README*"
```

### Options
| Option | Description |
| --- | --- |
| `--files` | Only match files (regular files, symlinks) |
| `--dirs` | Only match directories |
| `--hidden` | Include hidden files and directories (dotfiles) |
| `--no-ignore` | Do not skip VCS directories like `.git` (combine with `--hidden` to match dotfiles) |
| `--max-depth N` | Limit search depth (1 = immediate children) |
| `--json` | Output results in structured JSON format |

### Backend Design & Limitations
- **Backend Choice**: Built-in Python filesystem traversal (`os.scandir`).
- **Rationale**: `ripgrep --files` is designed exclusively for files and does not report empty directories. Pure Python traversal guarantees discovery of both files and directories (including empty ones).
- **Symlink Policy**: Does not follow directory symlinks (`follow_symlinks=False`), preventing directory loops and escaping the target tree.
- **Ignore Policy & Flag Semantics**:
  - *Default*: Skips all hidden files and directories (names starting with `.`) and `.git`.
  - *`--hidden` alone*: Includes hidden files and directories, but continues to skip internal VCS directories like `.git`.
  - *`--no-ignore` alone*: Disables skipping VCS directories like `.git`. Because `.git` is itself a hidden directory, searching inside `.git` requires combining with `--hidden` (`--hidden --no-ignore`).
  - *Note*: Unlike `search content` which uses ripgrep, `search name` does not parse custom `.gitignore` rule files.
- **Permission Error Handling**: Catches `PermissionError` when scanning subdirectories, logs a warning to `stderr`, marks `"complete": false` with `"skipped_paths"` in JSON, and alerts the user in human-readable output that the scan was incomplete.
- **Sorting**: Matches are sorted alphabetically by relative path for deterministic output.

