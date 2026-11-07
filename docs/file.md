# File Tools

LUT provides four file management commands: `file hash`, `file info`, `file duplicates`, and `file rename`.

## 1. File Hash (`lut file hash`)

### Overview
Computes cryptographic checksums of files reading in bounded 64 KiB chunks without loading entire files into memory.

### Syntax
```bash
lut file hash document.pdf
lut file hash archive.zip --algorithm sha512
lut file hash "my file.txt" --json
```

### Options
- `-a`, `--algorithm`: Hash algorithm. Supported: `sha256` (default), `sha512`, `sha1`, `md5`.
  *(Note: MD5 and SHA-1 are provided for legacy checksum verification only and are not collision-resistant.)*
- `--json`: Output result as JSON.

### Safety & Guarantees
- Bounded memory streaming (`64 KiB` buffer) handles arbitrarily large files.
- Empty files correctly produce standard zero-byte digests (e.g. SHA-256 `e3b0c44...`).
- Directories are rejected with exit code `4`.
- Never modifies or creates any file.

---

## 2. File Info (`lut file info`)

### Overview
Inspects metadata, permissions, ownership, and timestamps of a file or directory using only the Python standard library without reading file contents.

### Syntax
```bash
lut file info document.pdf
lut file info ./photos
lut file info "my notes.txt" --json
```

### Attributes Reported
- File name and absolute path
- File type (regular file, directory, symlink, FIFO, socket, block/character device)
- File size (formatted human-readable and raw bytes)
- Permissions (symbolic e.g. `-rw-r--r--` and octal `0644`)
- Owner username and group name (with UID/GID)
- Timestamps (modification `mtime`, access `atime`, and status-change `changed/ctime` in ISO 8601). Creation time (`created/st_birthtime`) is reported only when supported by the underlying filesystem/kernel; otherwise omitted in text and `null` in JSON.
- Symlink details: symlink target path and broken link status

---

## 3. Duplicate Detection (`lut file duplicates`)

### Overview
Identifies duplicate files across a directory tree using multi-stage candidate filtering and cryptographic hashing.

### Syntax
```bash
lut file duplicates
lut file duplicates ./Downloads
lut file duplicates ./Documents --min-size 1024 --max-depth 3
```

### Algorithm
1. **Size grouping**: Scans directory tree and groups files by byte size. Unique sizes are discarded immediately without hashing.
2. **Partial hash**: Computes SHA-256 for the first 4 KiB of files sharing the same size. Unique prefixes are discarded.
3. **Full hash**: Computes full SHA-256 for remaining candidates.
4. **Hardlink Awareness**: Tracks `(st_dev, st_ino)`. Hardlinks to the same inode share disk storage, so wasted space is calculated as `size * (unique_inodes - 1)`. Hardlinks are clearly labeled in the report.

### Safety & Error Handling
- **Read-only**: Never modifies or deletes any file.
- Does not follow directory symlinks (`follow_symlinks=False`).
- **Robust Incomplete Scan Reporting**: Catches access and read errors across all stages (directory traversal, file `stat`, 4 KiB partial hash, and full SHA-256 hash). Emits warnings to `stderr`, marks `"complete": false` with detailed `"skipped_paths"` in JSON, and clearly warns in human-readable output that the scan was incomplete instead of claiming zero duplicates definitively.

---

## 4. File Rename (`lut file rename`)

### Overview
Safely previews or executes batch file renaming with collision preflight and non-overwriting atomic operations.

### Syntax
```bash
# Preview operations (default)
lut file rename photo.png --prefix old_
lut file rename photo.png --suffix _backup
lut file rename ./photos --replace IMG_ photo_

# Apply rename operations
lut file rename photo.png --prefix old_ --apply
lut file rename ./photos --replace IMG_ photo_ --apply

# Force preview
lut file rename photo.png --prefix old_ --apply --dry-run
```

### Safety & Preflight Policy
- **Preview by default**: Running `lut file rename` plans and prints the proposed changes. Renaming occurs only when `--apply` is explicitly passed.
- **Dry-run**: Passing `--dry-run` forces preview mode even if `--apply` is present.
- **Strict Destination Validation**:
  - Rejects path separators (`/`, `\`), NUL bytes (`\0`), empty names, and `.`/`..` in `--prefix`, `--suffix`, and `--replace`.
  - Violations fail fast with exit code `2` (`UsageError`) before planning, leaving original files untouched.
- **Symlink Handling**:
  - Symlinks (to file, to directory, or broken) are checked before `is_dir()` and renamed directly.
  - Never follows directory symlinks into target contents.
- **Preflight Collision Detection**:
  - Aborts immediately if multiple inputs would be renamed to the same destination name.
  - Aborts immediately if any destination already exists on disk (preventing data loss).
- **Non-Overwriting Atomic Execution**:
  - Uses Linux `renameat2(AT_FDCWD, src, AT_FDCWD, dst, RENAME_NOREPLACE)` via libc to guarantee the kernel will not overwrite existing files under race conditions.
  - Fails closed with `OutputError` if safe atomic rename is unsupported (no fallback to non-atomic `os.rename`).
- **Partial Failure Reporting**: If an unexpected filesystem error occurs during a batch rename, LUT halts and reports precisely which files succeeded and which failed.
- **Directory targets**: When a real directory path is supplied, its direct file children are renamed without moving the directory itself.

