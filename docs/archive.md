# Archive Manager (M4)

LUT Milestone 4 implements four archive management commands: `archive compress`, `archive extract`, `archive list`, and `archive test`.

## 1. Supported Formats & Backend Matrix

| Format | Extension(s) | Compress | Extract | List | Test | Backend |
|---|---|---|---|---|---|---|
| **ZIP** | `.zip` | Yes | Yes (Safe) | Yes | Yes (CRC & Payload) | Python standard library `zipfile` |
| **TAR** | `.tar` | Yes | Yes (Safe) | Yes | Yes (Headers & Payload) | Python standard library `tarfile` |
| **TAR.GZ** | `.tar.gz`, `.tgz` | Yes | Yes (Safe) | Yes | Yes (Full stream CRC & Payload) | Python standard library `tarfile` & `gzip` |
| **TAR.XZ** | `.tar.xz`, `.txz` | Yes | Yes (Safe) | Yes | Yes (Full stream Footer & Payload) | Python standard library `tarfile` & `lzma` |
| **7Z** | `.7z` | Yes | Disabled (Security) | Yes | Yes (Backend integrity) | `7z`/`7zz`/`7za` via `run_process` |

---

## 2. Archive Compress (`lut archive compress`)

### Overview
Compresses a single file or directory into an archive.

### Syntax
```bash
# Basic usage (defaults to ZIP)
lut archive compress myfolder/
lut archive compress document.pdf
lut archive compress "my folder with spaces"

# Explicit format
lut archive compress myfolder/ --format tar.gz
lut archive compress myfolder/ --format tar.xz
lut archive compress myfolder/ --format 7z

# Compression level (0-9 where supported)
lut archive compress myfolder/ --level 9

# Override output destination
lut archive compress myfolder/ --output backup.zip

# Preview without creating files
lut archive compress myfolder/ --dry-run
```

### Automatic Output Naming
Outputs are created in the same parent directory as the input:
- `folder/` -> `folder.zip` (or `.tar.gz`, `.tar.xz`, `.7z`)
- `document.pdf` -> `document.zip`
- Numbered collision handling: If `folder.zip` already exists, LUT automatically creates `folder_2.zip`, `folder_3.zip`, etc., preserving compound extensions (`folder_2.tar.gz`).
- When explicit `-o/--output` is provided, automatic collision renaming is disabled; if the destination exists, an `OutputError` (exit code `5`) is raised.

### Archiving Structure, Symlink Policy & Preflight Validation
- **Directory Preservation**: The root folder name is included in archive entry paths (e.g. `project/main.py`), preventing directory structure flattening upon extraction.
- **Strict Symlink Rejection Across All Path Ancestors**: Any symlink in the input is strictly rejected with exit code `4` (`InputError`). This policy checks:
  - The input file or directory itself.
  - All recursive contents within input directories (`os.walk(followlinks=False)`).
  - All ancestor path components of user-supplied arguments (both relative from current working directory and absolute from root). For example, invoking `lut archive compress shortcut/secret.txt` when `shortcut -> external/` is rejected upfront without traversing the target or reading files outside the expected boundary.
- **Preflight Name Collision & Conflict Rejection**: All archive entry names are planned and validated before compression. Duplicate file names (e.g. compressing `a/same.txt` and `b/same.txt` into the same archive) and conflicts between files and directories are rejected upfront with exit code `4` (`InputError`), ensuring that LUT never produces archives known to be incompatible with safe extractors.
- **Entry Name Preflight Safety & Round-Trip Compatibility**:
  - **Windows Drive Prefixes**: File or directory names starting with Windows drive specifications (e.g. `C:secret.txt` or `D:\path`) are rejected upfront to prevent path injection or extraction rejection.
  - **Backslash Rejection**: Filenames containing backslash characters (`\`, e.g. `abc\def.txt`, `..\outside.txt`) are rejected upfront. Although POSIX filesystems technically allow `\` within filenames, archiving them creates severe cross-platform ambiguity: many extractors (including standard zip/tar tools) either treat `\` as a path separator—mutating single files into directory trees—or reject them outright.
  - **Path Traversal Rejection**: Traversal elements (`..`, `.`) are prohibited in archive entry names.
  - **Safe Special Characters Supported**: Valid POSIX filenames containing safe colons (not at drive position, e.g. `log:2026-11-06.txt`), UTF-8 Unicode characters, spaces, and newlines round-trip cleanly without modification or corruption.
- **Directory Traversal Completeness & Scan Error Handling**:
  - Both `_validate_no_symlinks` and `_plan_and_validate_compression_entries` attach active `onerror` handlers to all `os.walk()` traversals.
  - If an input directory itself or any of its subdirectories cannot be scanned (due to `PermissionError`, `EIO`, or any `OSError`), compression halts immediately with `InputError` (exit code `4`), reporting the offending path and system error.
  - LUT never silently drops unreadable subdirectories, never produces incomplete archives, and never creates empty archives from unreadable roots.
  - All staging outputs (`.lut-*`) are automatically purged upon failure, and source data remains completely unmodified.

### TOCTOU Evaluation & Security Limits
LUT performs thorough preflight validation in userspace before initiating archive operations. Users should note the following real-world boundaries:
- **Time-Of-Check to Time-Of-Use (TOCTOU)**: Preflight filesystem validation checks path ancestors and child nodes immediately before opening files. In multi-user or hostile environments, a race condition exists if a concurrent local process or malicious thread modifies path components or swaps directories for symlinks between check time and open time.
- **Kernel-level Mitigation**: Python standard libraries (`zipfile`, `tarfile`) and external CLI utilities (such as `7z`) do not expose atomic Linux `openat2(..., RESOLVE_NO_SYMLINKS)` primitives. Absolute immunity against concurrent local race conditions is therefore impossible without kernel-level atomic path resolution; LUT provides strict preflight validation and safe-by-default execution within documented POSIX limitations.

---

## 3. Archive Extract (`lut archive extract`)

### Overview
Extracts archives safely into a dedicated extraction directory without overwriting existing files. Supported formats: `.zip`, `.tar`, `.tar.gz`, `.tar.xz`. Note that 7Z extraction is currently disabled for security reasons.

### Syntax
```bash
# Basic usage (automatic format detection and output directory)
lut archive extract backup.zip
lut archive extract project.tar.gz
lut archive extract package.tar.xz

# Override destination directory
lut archive extract backup.zip --output ./restored

# Preview extraction plan
lut archive extract backup.zip --dry-run
```

### Automatic Extraction Directory Naming
- `backup.zip` -> `backup_extracted/`
- `project.tar.gz` -> `project_extracted/` (compound extensions cleanly stripped)
- `package.tar.xz` -> `package_extracted/`
- If `backup_extracted/` already exists, numbered variants are used: `backup_extracted_2/`, `backup_extracted_3/`.

### Atomic Publication & Container Integrity
Extraction is staged in a private temporary directory (`prefix=".lut-"`) inside the destination's parent directory.
- For compressed streams (`.tar.gz`, `.tar.xz`), LUT verifies stream completeness and trailing checksums/footers to EOF before publishing. Truncated streams or corrupt footers raise `InputError` (exit code `4`), and temporary directories are wiped without publication.
- Once all members are decompressed and verified, the directory is atomically published using `renameat2(..., RENAME_NOREPLACE)`.
- If the filesystem (e.g. FUSE mounts lacking `RENAME_NOREPLACE`) cannot publish the directory atomically, LUT fails closed with `OutputError` (exit code `5`) without leaving partial or corrupted output.

---

## 4. Extraction Security Policy & Threat Model

Extraction is designed to process untrusted archives without allowing path escapes, symlink attacks, or resource exhaustion:

1. **Path Traversal Protection**:
   - Every archive entry path is validated before writing.
   - Absolute paths (e.g. `/etc/passwd`), Windows-style absolute paths (`C:\`), and traversal segments (`../`, `foo/../../bar`) are strictly rejected.
   - Canonical path resolution enforces that every target lies strictly inside the staging root.
2. **Safe Entry Types (No Symlinks/Special Files)**:
   - By default, LUT only extracts regular files and directories.
   - Symlinks, hard links, character devices, block devices, FIFOs, and sockets are rejected with `InputError` (exit code `4`).
   - This eliminates symlink traversal, symlink chains, directory swaps, and hardlink escape vulnerabilities.
3. **Collision & Conflict Rejection**:
   - Duplicate file entries in the same archive are rejected.
   - Conflicting entries (e.g. attempting to create a file over a directory or vice-versa) are rejected.
4. **Permissions Sanitization**:
   - SUID (`0o4000`), SGID (`0o2000`), and sticky (`0o1000`) bits are stripped.
   - Files are extracted with safe permissions (`0o644` or `0o755` if owner-executable).
   - Ownership (UID/GID) from the archive is never applied.
5. **Resource Limits & ZIP Bomb Protection**:
   - `MAX_TOTAL_SIZE`: 10 GB default uncompressed limit.
   - `MAX_FILE_SIZE`: 2 GB default individual file limit.
   - `MAX_ENTRIES`: 50,000 entries limit.
   - `MAX_PATH_LENGTH`: 1,024 characters.
   - `MAX_PATH_DEPTH`: 64 path segments.
   - Decompression tracks actual written bytes chunk-by-chunk (64 KiB buffer), terminating immediately if limits are exceeded.
   - On limit violation, staging directories are cleaned up immediately; no files are published.

---

## 5. 7Z Backend Integration & Safety Architecture

- **Discovery**: Detected dynamically via `require_executable` checking `7zz`, `7z`, and `7za` on PATH.
- **Operations Supported**:
  - `archive compress`: Creates 7z archives using backend subprocess (pre-flight checks ensure no symlinks or name conflicts).
  - `archive list`: Inspects 7z archives with `7z l -slt`, parsing entry attributes, folder flags, symlinks, and sizes.
  - `archive test`: Verifies 7z integrity via native `7z t`.
- **Extraction Policy (Disabled by Design)**:
  - 7Z extraction is disabled because external subprocesses cannot enforce in-process byte limits during extraction (e.g. decompression bombs), cannot intercept intermediate links in real-time, and cannot guarantee atomic sandboxing.
  - Attempting `lut archive extract <file.7z>` reports `InputError` (exit code `4`) informing the user of this design restriction and directing them to `archive list` and `archive test`.

---

## 6. Archive List (`lut archive list`)

Inspects archive contents and metadata without extracting to disk.

### Syntax
```bash
lut archive list backup.zip
lut archive list project.tar.gz
lut archive list files.7z
lut archive list backup.zip --json
```

### Output Example
```text
Archive: project.zip
Format: ZIP

Name                                           Size
----------------------------------------------------
project/                                          -
project/main.py                              2.4 KB
project/src/                                      -
project/src/app.py                           5.1 KB

Files: 2
Directories: 2
Total size: 7.5 KB
```

- Control characters (such as newlines) in filenames are escaped for safe terminal display.
- `--json` provides structured JSON output with entry types, sizes, and counts.

---

## 7. Archive Test (`lut archive test`)

Checks the integrity of an archive without writing to disk.

### Syntax
```bash
lut archive test backup.zip
lut archive test project.tar.gz
lut archive test project.tar.xz
lut archive test files.7z
lut archive test backup.zip --json
```

### Verification Level
- **ZIP**: CRC32 verification and payload decompression check across all entries.
- **TAR.GZ**: Full gzip container stream verification to EOF (checking header, blocks, and trailer CRC32/ISIZE) plus TAR member structure and payload readability.
- **TAR.XZ**: Full xz container stream verification to EOF (checking header, index, checks, and stream footer) plus TAR member structure and payload readability.
- **TAR (uncompressed)**: Header octal checksums and member payload readability (pure TAR format does not provide container payload checksums).
- **7Z**: Native `7z t` backend integrity verification.
- Returns exit code `0` on PASS, exit code `1` on FAIL.

