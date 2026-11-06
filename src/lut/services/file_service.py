"""File service implementing hash, info, duplicates, and safe rename."""

import ctypes
import datetime
import grp
import hashlib
import json
import os
import pwd
import stat
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from lut.core.errors import InputError, OutputError, UsageError


def _format_size(size_bytes: int) -> str:
    """Format bytes into human-readable representation."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    for unit in ("KB", "MB", "GB", "TB"):
        size_bytes /= 1024.0
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
    return f"{size_bytes:.1f} PB"


# =====================================================================
# File Hash
# =====================================================================

SUPPORTED_ALGORITHMS = ("sha256", "sha512", "sha1", "md5")


def file_hash(
    input_path: str | Path,
    *,
    algorithm: str = "sha256",
    as_json: bool = False,
    stdout_stream=None,
) -> int:
    """Compute cryptographic hash of a file reading in bounded 64KB chunks."""
    out = sys.stdout if stdout_stream is None else stdout_stream
    algo = algorithm.lower()
    if algo not in SUPPORTED_ALGORITHMS:
        raise UsageError(
            f"Unsupported hash algorithm: {algorithm}. Supported: {', '.join(SUPPORTED_ALGORITHMS)}"
        )

    path = Path(input_path)
    if not path.exists():
        raise InputError(f"Input file not found: {input_path}")

    if path.is_dir():
        raise InputError(f"Input must be a file, not a directory: {input_path}")

    try:
        mode = path.stat().st_mode
        if not (stat.S_ISREG(mode) or stat.S_ISLNK(mode)):
            raise InputError(f"Input must be a regular file: {input_path}")

        hasher = hashlib.new(algo)
        with open(path, "rb") as stream:
            while chunk := stream.read(65536):
                hasher.update(chunk)
        digest = hasher.hexdigest()
    except PermissionError:
        raise OutputError(f"Cannot read file: {input_path}") from None
    except OSError as err:
        raise OutputError(f"Error reading file {input_path}: {err}") from None

    algo_label = algo.upper() if algo != "sha256" else "SHA-256"
    if as_json:
        payload = {
            "file": str(path),
            "algorithm": algo,
            "hash": digest,
        }
        out.write(json.dumps(payload, indent=2) + "\n")
    else:
        out.write(f"{algo_label}: {digest}  {path.name}\n")

    return 0


# =====================================================================
# File Info
# =====================================================================


def _file_type_string(mode: int) -> str:
    """Return descriptive file type string from mode bits."""
    if stat.S_ISLNK(mode):
        return "symbolic link"
    if stat.S_ISREG(mode):
        return "regular file"
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISFIFO(mode):
        return "FIFO (pipe)"
    if stat.S_ISSOCK(mode):
        return "socket"
    if stat.S_ISBLK(mode):
        return "block device"
    if stat.S_ISCHR(mode):
        return "character device"
    return "unknown"


def file_info(
    input_path: str | Path,
    *,
    as_json: bool = False,
    stdout_stream=None,
) -> int:
    """Inspect file or directory metadata without reading full contents."""
    out = sys.stdout if stdout_stream is None else stdout_stream
    path = Path(input_path)

    if not os.path.lexists(path):
        raise InputError(f"Path not found: {input_path}")

    try:
        st = path.lstat()
    except PermissionError:
        raise OutputError(f"Permission denied accessing path: {input_path}") from None
    except OSError as err:
        raise OutputError(f"Cannot stat path {input_path}: {err}") from None

    file_type = _file_type_string(st.st_mode)
    is_symlink = stat.S_ISLNK(st.st_mode)
    symlink_target = None
    target_broken = False

    if is_symlink:
        try:
            symlink_target = os.readlink(path)
            target_broken = not os.path.exists(path)
        except OSError:
            pass

    # Permissions
    perm_octal = oct(stat.S_IMODE(st.st_mode))
    perm_symbolic = stat.filemode(st.st_mode)

    # Owner / Group
    try:
        user_name = pwd.getpwuid(st.st_uid).pw_name
    except KeyError:
        user_name = str(st.st_uid)

    try:
        group_name = grp.getgrgid(st.st_gid).gr_name
    except KeyError:
        group_name = str(st.st_gid)

    # Timestamps (ISO format)
    mtime = datetime.datetime.fromtimestamp(st.st_mtime, tz=datetime.timezone.utc).astimezone()
    atime = datetime.datetime.fromtimestamp(st.st_atime, tz=datetime.timezone.utc).astimezone()
    ctime = datetime.datetime.fromtimestamp(st.st_ctime, tz=datetime.timezone.utc).astimezone()

    mtime_str = mtime.strftime("%Y-%m-%d %H:%M:%S")
    atime_str = atime.strftime("%Y-%m-%d %H:%M:%S")
    ctime_str = ctime.strftime("%Y-%m-%d %H:%M:%S")

    # Birth time (creation time) only if supported by OS/filesystem
    btime_str = None
    if hasattr(st, "st_birthtime"):
        btime = datetime.datetime.fromtimestamp(
            st.st_birthtime, tz=datetime.timezone.utc
        ).astimezone()
        btime_str = btime.strftime("%Y-%m-%d %H:%M:%S")

    size_formatted = f"{_format_size(st.st_size)} ({st.st_size:,} bytes)"

    if as_json:
        payload = {
            "name": path.name,
            "path": str(path.resolve() if not is_symlink else path.absolute()),
            "type": file_type,
            "size_bytes": st.st_size,
            "size_human": _format_size(st.st_size),
            "permissions_octal": perm_octal,
            "permissions_symbolic": perm_symbolic,
            "owner": user_name,
            "group": group_name,
            "uid": st.st_uid,
            "gid": st.st_gid,
            "modified": mtime_str,
            "accessed": atime_str,
            "changed": ctime_str,
            "created": btime_str,
            "is_symlink": is_symlink,
            "symlink_target": symlink_target,
            "is_broken_symlink": target_broken if is_symlink else None,
        }
        out.write(json.dumps(payload, indent=2) + "\n")
    else:
        out.write(f"File:       {path.name}\n")
        out.write(f"Path:       {path.resolve() if not is_symlink else path.absolute()}\n")
        out.write(f"Type:       {file_type}\n")
        if is_symlink:
            status = " (broken link)" if target_broken else ""
            out.write(f"Target:     {symlink_target}{status}\n")
        out.write(f"Size:       {size_formatted}\n")
        out.write(f"Mode:       {perm_symbolic} ({perm_octal})\n")
        out.write(f"Owner:      {user_name}:{group_name} ({st.st_uid}:{st.st_gid})\n")
        out.write(f"Modified:   {mtime_str}\n")
        out.write(f"Accessed:   {atime_str}\n")
        out.write(f"Changed:    {ctime_str}\n")
        if btime_str is not None:
            out.write(f"Created:    {btime_str}\n")

    return 0


# =====================================================================
# File Duplicates
# =====================================================================


@dataclass
class DuplicateFile:
    """A file candidate for duplicate detection."""

    path: Path
    relative_str: str
    inode: tuple[int, int]  # (st_dev, st_ino)


def _compute_chunk_hash(file_path: Path, length: int | None = None) -> str:
    """Compute SHA-256 for the first `length` bytes or entire file."""
    hasher = hashlib.sha256()
    bytes_read = 0
    with open(file_path, "rb") as stream:
        while chunk := stream.read(65536):
            if length is not None and bytes_read + len(chunk) > length:
                chunk = chunk[: length - bytes_read]
                hasher.update(chunk)
                break
            hasher.update(chunk)
            bytes_read += len(chunk)
    return hasher.hexdigest()


def file_duplicates(
    search_path: str | Path = ".",
    *,
    min_size: int = 1,
    max_depth: int | None = None,
    as_json: bool = False,
    stdout_stream=None,
) -> int:
    """Find identical content files using multi-stage size and SHA-256 hashing."""
    out = sys.stdout if stdout_stream is None else stdout_stream
    root = Path(search_path)

    if not root.exists():
        raise InputError(f"Search path does not exist: {search_path}")

    if not root.is_dir():
        raise InputError(f"Search path must be a directory: {search_path}")

    if max_depth is not None and max_depth < 0:
        raise UsageError("Max depth must be a nonnegative integer.")

    # Stage 1: Gather regular files grouped by size
    by_size: dict[int, list[DuplicateFile]] = {}
    cwd = Path.cwd().resolve()
    skipped_paths: list[str] = []

    # Traversal queue: (Path, depth)
    queue = [(root.resolve(), 0)]
    while queue:
        current, depth = queue.pop(0)
        try:
            entries = sorted(os.scandir(current), key=lambda e: e.name)
        except PermissionError:
            print(
                f"lut: warning: Permission denied accessing directory: {current}",
                file=sys.stderr,
            )
            skipped_paths.append(str(current))
            continue
        except OSError as err:
            raise OutputError(f"Cannot access directory {current}: {err}") from None

        for entry in entries:
            # Skip .git by default
            if entry.name == ".git":
                continue

            try:
                # Do not follow symlinks
                if entry.is_dir(follow_symlinks=False):
                    if max_depth is None or depth + 1 <= max_depth:
                        queue.append((Path(entry.path), depth + 1))
                elif entry.is_file(follow_symlinks=False):
                    st = entry.stat(follow_symlinks=False)
                    if st.st_size >= min_size:
                        p = Path(entry.path)
                        try:
                            rel = p.relative_to(cwd)
                            rel_str = f"./{rel}" if str(rel) != "." else "."
                        except ValueError:
                            rel_str = str(p)

                        item = DuplicateFile(p, rel_str, (st.st_dev, st.st_ino))
                        by_size.setdefault(st.st_size, []).append(item)
            except (OSError, PermissionError) as err:
                print(
                    f"lut: warning: Cannot access file {entry.path}: {err}",
                    file=sys.stderr,
                )
                skipped_paths.append(str(entry.path))
                continue

    # Stage 2: Discard unique sizes
    candidate_sizes = {s: files for s, files in by_size.items() if len(files) >= 2}

    # Stage 3: Partial hashing (4KB prefix)
    by_partial: dict[tuple[int, str], list[DuplicateFile]] = {}
    for size, files in candidate_sizes.items():
        for f in files:
            try:
                p_hash = _compute_chunk_hash(f.path, length=4096)
                by_partial.setdefault((size, p_hash), []).append(f)
            except (OSError, PermissionError) as err:
                print(
                    f"lut: warning: Cannot read file {f.path}: {err}",
                    file=sys.stderr,
                )
                skipped_paths.append(str(f.path))
                continue

    candidate_partials = {k: files for k, files in by_partial.items() if len(files) >= 2}

    # Stage 4: Full SHA-256 hash
    by_full: dict[tuple[int, str], list[DuplicateFile]] = {}
    for (size, _), files in candidate_partials.items():
        for f in files:
            try:
                full_h = _compute_chunk_hash(f.path)
                by_full.setdefault((size, full_h), []).append(f)
            except (OSError, PermissionError) as err:
                print(
                    f"lut: warning: Cannot read file {f.path}: {err}",
                    file=sys.stderr,
                )
                skipped_paths.append(str(f.path))
                continue

    # Stage 5: Final duplicate groups
    duplicate_groups = [
        (size, digest, files) for (size, digest), files in by_full.items() if len(files) >= 2
    ]

    # Calculate wasted space with hardlink awareness
    total_wasted_bytes = 0
    formatted_groups = []

    for size, digest, files in duplicate_groups:
        # Find unique inodes
        unique_inodes = {f.inode for f in files}
        # Hardlinks do not consume independent disk space
        wasted_for_group = size * max(0, len(unique_inodes) - 1)
        total_wasted_bytes += wasted_for_group

        # Sort files alphabetically
        sorted_files = sorted(files, key=lambda f: f.relative_str)
        formatted_groups.append(
            {
                "size": size,
                "hash": digest,
                "wasted_bytes": wasted_for_group,
                "files": sorted_files,
            }
        )

    # Sort groups by wasted size descending, then size descending
    formatted_groups.sort(key=lambda g: (g["wasted_bytes"], g["size"]), reverse=True)

    is_complete = len(skipped_paths) == 0

    if not formatted_groups:
        if as_json:
            out.write(
                json.dumps(
                    {
                        "groups_count": 0,
                        "wasted_bytes": 0,
                        "groups": [],
                        "complete": is_complete,
                        "skipped_paths": skipped_paths,
                    }
                )
                + "\n"
            )
        else:
            if not is_complete:
                out.write(
                    f"Warning: Scan was incomplete; {len(skipped_paths)} "
                    "paths were skipped due to access or permission errors.\n\n"
                )
                out.write("No duplicate files found among scanned files.\n")
            else:
                out.write("No duplicate files found.\n")
        return 0

    if as_json:
        payload = {
            "groups_count": len(formatted_groups),
            "wasted_bytes": total_wasted_bytes,
            "groups": [
                {
                    "size_bytes": g["size"],
                    "hash": g["hash"],
                    "wasted_bytes": g["wasted_bytes"],
                    "files": [f.relative_str for f in g["files"]],
                }
                for g in formatted_groups
            ],
            "complete": is_complete,
            "skipped_paths": skipped_paths,
        }
        out.write(json.dumps(payload, indent=2) + "\n")
    else:
        if not is_complete:
            out.write(
                f"Warning: Scan was incomplete; {len(skipped_paths)} "
                "paths were skipped due to access or permission errors.\n\n"
            )
        out.write(
            f"Duplicate groups: {len(formatted_groups)} "
            f"(wasted space: {_format_size(total_wasted_bytes)})\n\n"
        )
        for idx, g in enumerate(formatted_groups, start=1):
            seen_inodes = set()
            out.write(f"Group {idx}\n")
            out.write(f"  Size: {_format_size(g['size'])} ({len(g['files'])} files)\n")
            for f in g["files"]:
                hardlink_note = " (hardlink)" if f.inode in seen_inodes else ""
                seen_inodes.add(f.inode)
                out.write(f"  {f.relative_str}{hardlink_note}\n")
            out.write("\n")

    return 0


# =====================================================================
# File Rename
# =====================================================================


def _atomic_rename(source: Path, destination: Path) -> None:
    """Rename source to destination atomically without replacing destination."""
    try:
        renameat2 = ctypes.CDLL(None, use_errno=True).renameat2
    except (AttributeError, OSError):
        raise OutputError("Atomic rename requires libc renameat2 support.") from None

    renameat2.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    renameat2.restype = ctypes.c_int
    # AT_FDCWD = -100, RENAME_NOREPLACE = 1
    res = renameat2(-100, os.fsencode(source), -100, os.fsencode(destination), 1)
    if res != 0:
        err = ctypes.get_errno()
        if err == 17:  # EEXIST
            raise FileExistsError(f"Destination already exists: {destination}")
        raise OSError(err, os.strerror(err))


def _compute_renamed_name(
    old_name: str,
    *,
    prefix: str | None,
    suffix: str | None,
    replace_pair: tuple[str, str] | None,
) -> str:
    """Compute new filename applying prefix, suffix before extension, and replacement."""
    name = old_name

    # Apply replacement
    if replace_pair is not None:
        old_str, new_str = replace_pair
        name = name.replace(old_str, new_str)

    # Split stem and compound extensions (e.g. .tar.gz)
    # Check compound extensions
    compound_exts = (
        ".tar.gz",
        ".tar.bz2",
        ".tar.xz",
        ".tar.zst",
        ".tar.lz",
        ".tar.lzma",
    )
    ext = ""
    lower = name.lower()
    for ce in compound_exts:
        if lower.endswith(ce):
            ext = name[-len(ce) :]
            stem = name[: -len(ce)]
            break
    else:
        # Standard extension
        last_dot = name.rfind(".")
        if last_dot > 0:  # Not leading dot
            ext = name[last_dot:]
            stem = name[:last_dot]
        else:
            stem = name
            ext = ""

    # Apply suffix before extension
    if suffix:
        stem = f"{stem}{suffix}"

    # Apply prefix to stem
    if prefix:
        stem = f"{prefix}{stem}"

    return f"{stem}{ext}"


def file_rename(
    inputs: Sequence[str | Path],
    *,
    prefix: str | None = None,
    suffix: str | None = None,
    replace: tuple[str, str] | None = None,
    apply: bool = False,
    dry_run: bool = False,
    as_json: bool = False,
    stdout_stream=None,
) -> int:
    """Preview or safely execute batch file renames without overwriting."""
    out = sys.stdout if stdout_stream is None else stdout_stream

    if not prefix and not suffix and not replace:
        raise UsageError("At least one of --prefix, --suffix, or --replace must be specified.")

    # Validate rename inputs to prevent directory traversal or invalid characters
    if prefix is not None and ("/" in prefix or "\\" in prefix or "\0" in prefix):
        raise UsageError(f"Prefix cannot contain path separators or NUL bytes: {prefix!r}")
    if suffix is not None and ("/" in suffix or "\\" in suffix or "\0" in suffix):
        raise UsageError(f"Suffix cannot contain path separators or NUL bytes: {suffix!r}")
    if replace is not None and ("/" in replace[1] or "\\" in replace[1] or "\0" in replace[1]):
        raise UsageError(
            f"Replacement string cannot contain path separators or NUL bytes: {replace[1]!r}"
        )

    # Collect target files
    files_to_rename: list[Path] = []
    for inp in inputs:
        p = Path(inp)
        if not p.is_symlink() and not p.exists():
            raise InputError(f"Input path not found: {inp}")

        # Check symlink BEFORE directory: a symlink (even to a directory) must be renamed itself!
        if p.is_symlink():
            files_to_rename.append(p)
        elif p.is_dir():
            # If input is a real directory, rename its direct children
            try:
                entries = sorted(os.scandir(p), key=lambda e: e.name)
            except OSError as err:
                raise OutputError(f"Cannot access directory {inp}: {err}") from None

            for entry in entries:
                if entry.name.startswith("."):
                    continue
                files_to_rename.append(Path(entry.path))
        else:
            files_to_rename.append(p)

    if not files_to_rename:
        raise InputError("No files found to rename.")

    # Calculate planned renames
    plans: list[tuple[Path, Path]] = []
    destination_names: set[Path] = set()

    cwd = Path.cwd().resolve()
    for src in files_to_rename:
        new_name = _compute_renamed_name(
            src.name,
            prefix=prefix,
            suffix=suffix,
            replace_pair=replace,
        )
        if (
            not new_name
            or "/" in new_name
            or "\\" in new_name
            or "\0" in new_name
            or new_name in (".", "..")
        ):
            raise UsageError(f"Invalid destination filename: {new_name!r}")

        dst = src.with_name(new_name)
        if dst == src:
            continue

        # Check collision with other destinations in this batch
        if dst.resolve() in destination_names:
            raise OutputError(f"Name collision: multiple files would be renamed to '{dst.name}'.")
        destination_names.add(dst.resolve())

        # Check collision with existing files on disk
        if os.path.lexists(dst):
            raise OutputError(
                f"Destination already exists: '{dst}'. Operation aborted to prevent data loss."
            )

        plans.append((src, dst))

    if not plans:
        out.write("No files need renaming.\n")
        return 0

    is_preview = dry_run or not apply

    if is_preview:
        header = f"Rename plan ({len(plans)} files) [PREVIEW - use --apply to execute]:"
        if as_json:
            payload = {
                "dry_run": True,
                "count": len(plans),
                "plan": [
                    {
                        "source": str(src),
                        "destination": str(dst),
                    }
                    for src, dst in plans
                ],
            }
            out.write(json.dumps(payload, indent=2) + "\n")
        else:
            out.write(f"{header}\n")
            for src, dst in plans:
                try:
                    rel_src = src.relative_to(cwd)
                    rel_dst = dst.relative_to(cwd)
                except ValueError:
                    rel_src, rel_dst = src, dst
                out.write(f"  {rel_src} -> {rel_dst}\n")
        return 0

    # Actually execute renames
    renamed: list[tuple[Path, Path]] = []
    failed: list[tuple[Path, Path, str]] = []

    for src, dst in plans:
        try:
            _atomic_rename(src, dst)
            renamed.append((src, dst))
        except OSError as err:
            failed.append((src, dst, str(err)))
            break  # Stop on first failure to report accurate partial state

    if failed:
        failed_src, failed_dst, reason = failed[0]
        report = [f"Rename failed on '{failed_src}' -> '{failed_dst}': {reason}"]
        if renamed:
            report.append(f"Successfully renamed {len(renamed)} files before failure:")
            for s, d in renamed:
                report.append(f"  {s.name} -> {d.name}")
        raise OutputError("\n".join(report))

    if as_json:
        payload = {
            "applied": True,
            "count": len(renamed),
            "renamed": [
                {
                    "source": str(src),
                    "destination": str(dst),
                }
                for src, dst in renamed
            ],
        }
        out.write(json.dumps(payload, indent=2) + "\n")
    else:
        out.write(f"Renamed {len(renamed)} files:\n")
        for src, dst in plans:
            try:
                rel_src = src.relative_to(cwd)
                rel_dst = dst.relative_to(cwd)
            except ValueError:
                rel_src, rel_dst = src, dst
            out.write(f"  {rel_src} -> {rel_dst}\n")

    return 0
