"""Archive service implementing safe compression, extraction, listing, and testing."""

import gzip
import json
import lzma
import os
import re
import shutil
import stat
import sys
import tarfile
import zipfile
import zlib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from lut.core.dependencies import require_executable
from lut.core.errors import (
    DependencyError,
    InputError,
    OutputError,
    ProcessError,
    UsageError,
)
from lut.core.output import atomic_output
from lut.core.process import run_process

# =====================================================================
# Constants & Safety Limits
# =====================================================================

SUPPORTED_FORMATS = ("zip", "tar", "tar.gz", "tar.xz", "7z")

FORMAT_EXTENSIONS = {
    "zip": ".zip",
    "tar": ".tar",
    "tar.gz": ".tar.gz",
    "tar.xz": ".tar.xz",
    "7z": ".7z",
}

DEFAULT_MAX_TOTAL_SIZE = 10 * 1024 * 1024 * 1024  # 10 GB
DEFAULT_MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2 GB
DEFAULT_MAX_ENTRIES = 50_000
DEFAULT_MAX_PATH_LENGTH = 1024
DEFAULT_MAX_PATH_DEPTH = 64
CHUNK_SIZE = 64 * 1024  # 64 KB


@dataclass
class ArchiveEntry:
    """Represent an entry in an archive for listing and inspection."""

    name: str
    is_dir: bool
    size: int
    packed_size: int | None = None
    attributes: str = ""
    is_symlink: bool = False
    is_hardlink: bool = False
    is_encrypted: bool = False


@dataclass
class PlannedCompressionEntry:
    """Planned file or directory entry to be added to an archive."""

    source_path: Path
    arcname: str
    is_dir: bool


def _format_size(size_bytes: int) -> str:
    """Format bytes into a human-readable representation."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    num = float(size_bytes)
    for unit in ("KB", "MB", "GB", "TB"):
        num /= 1024.0
        if num < 1024:
            return f"{num:.1f} {unit}"
    return f"{num:.1f} PB"


def _escape_terminal(name: str) -> str:
    """Escape control characters and newlines for safe terminal display."""
    return "".join(
        c if (c.isprintable() and c not in ("\n", "\r", "\t")) else repr(c)[1:-1] for c in name
    )


# =====================================================================
# Path Naming & Extension Helpers
# =====================================================================


def _strip_archive_extension(path: Path) -> str:
    """Strip known archive extensions including compound ones."""
    name = path.name
    lower = name.lower()
    for ext in (".tar.gz", ".tar.xz", ".tgz", ".txz", ".zip", ".tar", ".7z"):
        if lower.endswith(ext):
            return name[: -len(ext)]
    return path.stem


def _available_candidate(base_path: Path, ext: str) -> Path:
    """Find a non-existing candidate path with numbered collision suffix."""
    candidate = base_path.with_name(f"{base_path.name}{ext}")
    number = 2
    while os.path.lexists(candidate):
        candidate = base_path.with_name(f"{base_path.name}_{number}{ext}")
        number += 1
    return candidate


def _get_default_compress_output(source_path: Path, fmt: str) -> Path:
    """Plan default destination for compression beside source."""
    ext = FORMAT_EXTENSIONS.get(fmt, f".{fmt}")
    if source_path.is_dir():
        base_name = source_path.name
    else:
        base_name = source_path.stem
    base_path = source_path.parent / base_name
    return _available_candidate(base_path, ext)


def _get_default_extract_output(archive_path: Path) -> Path:
    """Plan default destination directory for extraction beside archive."""
    base_name = _strip_archive_extension(archive_path)
    base_path = archive_path.parent / f"{base_name}_extracted"
    if not os.path.lexists(base_path):
        return base_path
    number = 2
    candidate = archive_path.parent / f"{base_name}_extracted_{number}"
    while os.path.lexists(candidate):
        number += 1
        candidate = archive_path.parent / f"{base_name}_extracted_{number}"
    return candidate


def _infer_format_from_extension(path: Path) -> str | None:
    """Infer archive format from path extension."""
    lower = path.name.lower()
    if lower.endswith(".tar.gz") or lower.endswith(".tgz"):
        return "tar.gz"
    if lower.endswith(".tar.xz") or lower.endswith(".txz"):
        return "tar.xz"
    if lower.endswith(".tar"):
        return "tar"
    if lower.endswith(".zip"):
        return "zip"
    if lower.endswith(".7z"):
        return "7z"
    return None


# =====================================================================
# Format Detection
# =====================================================================


def detect_archive_format(path: Path) -> str:
    """Detect archive format combining magic bytes and structural inspection."""
    if not path.exists():
        raise InputError(f"Archive not found: {path}")
    if path.is_dir():
        raise InputError(f"Input must be an archive file, not a directory: {path}")

    # Read leading magic bytes
    try:
        with open(path, "rb") as f:
            header = f.read(512)
    except OSError as err:
        raise InputError(f"Cannot read archive file: {path} ({err})") from None

    if len(header) < 2:
        raise InputError(f"File is too small to be a valid archive: {path}")

    # Check GZIP magic (1f 8b)
    if header.startswith(b"\x1f\x8b"):
        if tarfile.is_tarfile(path) or _infer_format_from_extension(path) == "tar.gz":
            return "tar.gz"
        # If it's a raw gzip, for LUT archives we only support tar.gz
        raise InputError(
            f"File is gzip compressed but not a valid tar archive "
            f"(only TAR.GZ is supported): {path}"
        )

    # Check XZ magic (fd 37 7a 58 5a 00)
    if header.startswith(b"\xfd7zXZ\x00"):
        if tarfile.is_tarfile(path) or _infer_format_from_extension(path) == "tar.xz":
            return "tar.xz"
        raise InputError(
            f"File is xz compressed but not a valid tar archive (only TAR.XZ is supported): {path}"
        )

    # Check 7z magic (37 7a bc af 27 1c)
    if header.startswith(b"\x37\x7a\xbc\xaf\x27\x1c"):
        return "7z"

    # Check ZIP magic (PK\x03\x04 or PK\x05\x06 or PK\x07\x08)
    if header.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
        if zipfile.is_zipfile(path):
            return "zip"
        raise InputError(f"File has ZIP magic header but is corrupt: {path}")

    # Check end-of-file ZIP signature for ZIPs with prepended data (e.g. self-extracting)
    if zipfile.is_zipfile(path):
        return "zip"

    # Check uncompressed TAR
    if tarfile.is_tarfile(path):
        return "tar"

    # If magic checks failed, check if extension claims a format and verify
    inferred = _infer_format_from_extension(path)
    if inferred:
        raise InputError(
            f"File extension suggests '{inferred}', but file content is not a valid "
            f"{inferred.upper()} archive: {path}"
        )

    raise InputError(f"Unsupported or unrecognized archive format: {path}")


# =====================================================================
# Safe Path Validation & Security Checks
# =====================================================================


def validate_safe_entry_path(
    entry_name: str,
    staging_root: Path,
    *,
    max_length: int = DEFAULT_MAX_PATH_LENGTH,
    max_depth: int = DEFAULT_MAX_PATH_DEPTH,
) -> Path:
    """Validate archive entry path against path traversal, absolute paths, and escaping.

    Raises InputError on any unsafe component.
    """
    if "\0" in entry_name:
        raise InputError(f"Null byte detected in archive entry name: {entry_name!r}")

    # Reject Windows drive prefix (e.g. C: or C:\)
    if re.match(r"^[a-zA-Z]:", entry_name):
        raise InputError(f"Windows drive prefix detected in entry name: {entry_name}")

    # Convert backslashes to slashes
    clean = entry_name.replace("\\", "/")

    # Reject absolute paths
    if clean.startswith("/"):
        raise InputError(f"Absolute path detected in archive entry: {entry_name}")

    parts = [p for p in clean.split("/") if p]
    if not parts:
        raise InputError(f"Empty entry name or root path in archive: {entry_name!r}")

    for part in parts:
        if part in ("..", "."):
            raise InputError(f"Path traversal detected in archive entry: {entry_name}")

    if len(clean) > max_length:
        raise InputError(
            f"Archive entry path exceeds maximum length limit ({max_length}): {entry_name}"
        )

    if len(parts) > max_depth:
        raise InputError(
            f"Archive entry path exceeds maximum depth limit ({max_depth}): {entry_name}"
        )

    # Resolve target relative to staging_root
    target = (staging_root / clean).resolve()
    staging_resolved = staging_root.resolve()

    if target != staging_resolved and staging_resolved not in target.parents:
        raise InputError(f"Archive entry resolves outside destination staging root: {entry_name}")

    return target


def _on_walk_error(err: OSError, fallback_path: Path) -> None:
    """Handle directory traversal errors during preflight validation.

    Ensures that any directory read failure (such as PermissionError or EIO)
    halts compression immediately with InputError rather than silently omitting entries.
    """
    path_val = getattr(err, "filename", None)
    if path_val is None:
        path_str = str(fallback_path)
    elif isinstance(path_val, bytes):
        path_str = os.fsdecode(path_val)
    else:
        path_str = str(path_val)
    reason = getattr(err, "strerror", None) or str(err)
    raise InputError(f"Cannot read directory: {path_str} ({reason})")


def _validate_no_symlinks(input_arg: str | Path, resolved_path: Path) -> None:
    """Reject inputs containing any symlink in path components, target, or contents.

    Checks:
    - Ancestor path components of the input (relative or absolute).
    - The target path itself.
    - All subdirectories, files, and links if target is a directory.
    """
    raw_path = Path(input_arg)
    if raw_path.is_absolute():
        current = Path(raw_path.parts[0])
        for part in raw_path.parts[1:]:
            current = current / part
            if os.path.islink(current):
                raise InputError(
                    "Symlinks are not supported for compression "
                    f"(ancestor symlink in input path): {current}"
                )
    else:
        current = Path.cwd()
        for part in raw_path.parts:
            if part == ".":
                continue
            if part == "..":
                current = current.parent
                continue
            current = current / part
            if os.path.islink(current):
                raise InputError(
                    "Symlinks are not supported for compression "
                    f"(ancestor symlink in input path): {current}"
                )

    if os.path.islink(resolved_path):
        raise InputError(f"Symlinks are not supported for compression: {resolved_path}")

    if resolved_path.is_dir():

        def _on_symlink_walk_error(err: OSError) -> None:
            _on_walk_error(err, resolved_path)

        for root, dirs, files in os.walk(
            resolved_path, followlinks=False, onerror=_on_symlink_walk_error
        ):
            root_path = Path(root)
            for d in dirs:
                full_d = root_path / d
                if os.path.islink(full_d):
                    raise InputError(
                        f"Symlinks are not supported for compression (directory symlink): {full_d}"
                    )
            for f in files:
                full_f = root_path / f
                if os.path.islink(full_f):
                    raise InputError(
                        f"Symlinks are not supported for compression (file symlink): {full_f}"
                    )


def _validate_safe_compression_entry(
    source_path: Path,
    arcname: str,
    *,
    max_length: int = DEFAULT_MAX_PATH_LENGTH,
    max_depth: int = DEFAULT_MAX_PATH_DEPTH,
) -> None:
    """Validate archive entry name during compression preflight.

    Ensures that entry names can round-trip safely through LUT's extractor:
    - Rejects backslashes '\\' in filenames or arcnames (prevents silent path mutations).
    - Rejects null bytes '\\0'.
    - Rejects Windows drive prefixes (e.g. 'C:' or 'c:') at root or in any path segment.
    - Rejects path traversal segments ('..' or '.').
    - Rejects absolute paths.
    - Enforces length and depth limits.
    """
    if "\\" in source_path.name or "\\" in arcname:
        raise InputError(
            f"Backslash '\\' in entry name is not supported for safe archive round-trip: "
            f"{source_path.name!r}"
        )

    if "\0" in arcname:
        raise InputError(f"Null byte detected in entry name: {arcname!r}")

    # Reject Windows drive prefix (e.g. C: or C:\)
    if re.match(r"^[a-zA-Z]:", arcname):
        raise InputError(
            f"Windows drive prefix detected in entry name (cannot round-trip safely): {arcname!r}"
        )

    clean = arcname.rstrip("/")
    if clean.startswith("/"):
        raise InputError(f"Absolute path detected in entry name: {arcname!r}")

    parts = [p for p in clean.split("/") if p]
    if not parts:
        raise InputError(f"Empty entry name in archive: {arcname!r}")

    for part in parts:
        if part in ("..", "."):
            raise InputError(f"Path traversal component detected in entry name: {arcname!r}")
        if re.match(r"^[a-zA-Z]:", part):
            raise InputError(f"Windows drive prefix detected in entry component: {part!r}")

    if len(clean) > max_length:
        raise InputError(
            f"Archive entry path exceeds maximum length limit ({max_length}): {arcname}"
        )

    if len(parts) > max_depth:
        raise InputError(f"Archive entry path exceeds maximum depth limit ({max_depth}): {arcname}")


def _plan_and_validate_compression_entries(
    raw_inputs: list[str | Path],
    inputs: list[Path],
) -> list[PlannedCompressionEntry]:
    """Scan and validate all inputs for compression.

    Rejects any symlinks (ancestors, file, dir, broken, or root).
    Computes arcname for all items.
    Validates entry names for safe extraction round-trip.
    Detects duplicate file entries and file/directory path conflicts.
    Returns ordered list of planned entries.
    """
    planned: list[PlannedCompressionEntry] = []
    seen_files: dict[str, Path] = {}
    seen_dirs: set[str] = set()

    for raw_in, inp in zip(raw_inputs, inputs, strict=True):
        _validate_no_symlinks(raw_in, inp)

        if inp.is_file():
            arcname = inp.name
            _validate_safe_compression_entry(inp, arcname)
            try:
                with open(inp, "rb"):
                    pass
            except OSError as err:
                reason = getattr(err, "strerror", None) or str(err)
                raise InputError(f"Cannot read file: {inp} ({reason})") from None

            if arcname in seen_files:
                raise InputError(
                    f"Duplicate file entry name in inputs: {arcname} "
                    f"({inp} conflicts with {seen_files[arcname]})"
                )
            if arcname in seen_dirs or f"{arcname}/" in seen_dirs:
                raise InputError(f"Path conflict in inputs between file and directory: {arcname}")
            prefix = f"{arcname}/"
            if any(f.startswith(prefix) for f in seen_files):
                raise InputError(f"Path conflict in inputs between file and directory: {arcname}")
            parts = arcname.split("/")
            for i in range(1, len(parts)):
                parent_prefix = "/".join(parts[:i])
                if parent_prefix in seen_files:
                    raise InputError(
                        f"Path conflict in inputs between file and directory: {arcname}"
                    )

            seen_files[arcname] = inp
            planned.append(PlannedCompressionEntry(source_path=inp, arcname=arcname, is_dir=False))

        elif inp.is_dir():
            root_parent = inp.parent

            def _on_plan_walk_error(err: OSError) -> None:
                _on_walk_error(err, inp)

            for root, dirs, files in os.walk(inp, followlinks=False, onerror=_on_plan_walk_error):
                root_path = Path(root)
                dirs.sort()
                files.sort()

                rel_dir = root_path.relative_to(root_parent)
                arc_dir_clean = str(rel_dir).rstrip("/")
                arc_dir = f"{arc_dir_clean}/"

                _validate_safe_compression_entry(root_path, arc_dir_clean)

                if arc_dir_clean in seen_files:
                    raise InputError(
                        f"Path conflict in inputs between file and directory: {arc_dir_clean}"
                    )
                parts = arc_dir_clean.split("/")
                for i in range(1, len(parts)):
                    parent_prefix = "/".join(parts[:i])
                    if parent_prefix in seen_files:
                        raise InputError(
                            f"Path conflict in inputs between file and directory: {arc_dir_clean}"
                        )

                if arc_dir not in seen_dirs:
                    seen_dirs.add(arc_dir)
                    seen_dirs.add(arc_dir_clean)
                    planned.append(
                        PlannedCompressionEntry(source_path=root_path, arcname=arc_dir, is_dir=True)
                    )

                for f in files:
                    file_path = root_path / f
                    rel_file = file_path.relative_to(root_parent)
                    arc_file = str(rel_file)

                    _validate_safe_compression_entry(file_path, arc_file)

                    if arc_file in seen_files:
                        raise InputError(
                            f"Duplicate file entry name in inputs: {arc_file} "
                            f"({file_path} conflicts with {seen_files[arc_file]})"
                        )
                    if arc_file in seen_dirs or f"{arc_file}/" in seen_dirs:
                        raise InputError(
                            f"Path conflict in inputs between file and directory: {arc_file}"
                        )
                    prefix = f"{arc_file}/"
                    if any(f_seen.startswith(prefix) for f_seen in seen_files):
                        raise InputError(
                            f"Path conflict in inputs between file and directory: {arc_file}"
                        )
                    parts = arc_file.split("/")
                    for i in range(1, len(parts)):
                        parent_prefix = "/".join(parts[:i])
                        if parent_prefix in seen_files:
                            raise InputError(
                                f"Path conflict in inputs between file and directory: {arc_file}"
                            )

                    seen_files[arc_file] = file_path
                    planned.append(
                        PlannedCompressionEntry(
                            source_path=file_path, arcname=arc_file, is_dir=False
                        )
                    )
    return planned


# =====================================================================
# 7Z Backend Helper
# =====================================================================


def _find_7z_backend() -> str:
    """Find a functional 7z/7zz/7za backend or raise DependencyError."""
    packages = {
        "arch": "p7zip",
        "debian": "p7zip-full",
        "ubuntu": "p7zip-full",
        "fedora": "p7zip",
    }
    for candidate in ("7zz", "7z", "7za"):
        if shutil.which(candidate):
            try:
                require_executable(candidate, packages=packages)
                return candidate
            except DependencyError:
                continue
    # If none found, raise DependencyError using require_executable
    require_executable("7z", packages=packages)
    return "7z"


# =====================================================================
# ZIP Backend Implementation
# =====================================================================


def _compress_zip(
    planned_entries: list[PlannedCompressionEntry],
    temp_output: Path,
    level: int | None,
    verbose: bool = False,
) -> int:
    """Compress planned entries to ZIP using Python zipfile."""
    compress_level = 6 if level is None else level
    entries_count = 0

    with zipfile.ZipFile(
        temp_output,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=compress_level,
    ) as zf:
        for entry in planned_entries:
            if entry.is_dir:
                zf.writestr(entry.arcname, b"")
                entries_count += 1
            else:
                try:
                    zf.write(entry.source_path, arcname=entry.arcname)
                except OSError as err:
                    reason = getattr(err, "strerror", None) or str(err)
                    raise InputError(
                        f"Cannot read file for compression: {entry.source_path} ({reason})"
                    ) from None
                entries_count += 1
    return entries_count


def _extract_zip(
    archive_path: Path,
    staging_dir: Path,
    *,
    max_total_size: int | None = None,
    max_file_size: int | None = None,
    max_entries: int | None = None,
    verbose: bool = False,
) -> int:
    """Extract ZIP archive safely into staging directory."""
    limit_total_size = DEFAULT_MAX_TOTAL_SIZE if max_total_size is None else max_total_size
    limit_file_size = DEFAULT_MAX_FILE_SIZE if max_file_size is None else max_file_size
    limit_entries = DEFAULT_MAX_ENTRIES if max_entries is None else max_entries

    try:
        zf = zipfile.ZipFile(archive_path, "r")
    except zipfile.BadZipFile as err:
        raise InputError(f"Corrupted or invalid ZIP archive: {archive_path} ({err})") from None

    with zf:
        members = zf.infolist()
        if len(members) > limit_entries:
            raise InputError(
                f"Archive exceeds maximum entry count limit ({limit_entries}): "
                f"contains {len(members)}"
            )

        extracted_paths: set[Path] = set()
        total_extracted_bytes = 0

        for member in members:
            # Check for encryption
            if member.flag_bits & 0x1:
                raise InputError(f"Encrypted archive entries are not supported: {member.filename}")

            # Check for Unix external attributes: reject symlinks and special files
            mode = member.external_attr >> 16
            if mode != 0:
                if stat.S_ISLNK(mode):
                    raise InputError(
                        f"Unsafe or unsupported entry type in archive (symlink): {member.filename}"
                    )
                if (
                    stat.S_ISCHR(mode)
                    or stat.S_ISBLK(mode)
                    or stat.S_ISFIFO(mode)
                    or stat.S_ISSOCK(mode)
                ):
                    raise InputError(
                        "Unsafe or unsupported entry type in archive "
                        f"(special file): {member.filename}"
                    )

            target = validate_safe_entry_path(member.filename, staging_dir)

            is_dir = member.is_dir()
            if is_dir:
                if target.exists() and not target.is_dir():
                    raise InputError(
                        "Path conflict in archive: directory conflicts with "
                        f"existing file {member.filename}"
                    )
                target.mkdir(parents=True, exist_ok=True)
                target.chmod(0o755)
            else:
                if target in extracted_paths:
                    raise InputError(f"Duplicate file entry in archive: {member.filename}")
                if target.exists() and target.is_dir():
                    raise InputError(
                        "Path conflict in archive: file conflicts with "
                        f"existing directory {member.filename}"
                    )

                target.parent.mkdir(parents=True, exist_ok=True)

                # Stream file with size tracking
                file_bytes = 0
                with zf.open(member, "r") as src_f, open(target, "wb") as dst_f:
                    while True:
                        chunk = src_f.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        chunk_len = len(chunk)
                        file_bytes += chunk_len
                        total_extracted_bytes += chunk_len

                        if file_bytes > limit_file_size:
                            raise InputError(
                                "Archive entry exceeds maximum file size limit "
                                f"({limit_file_size} B): {member.filename}"
                            )
                        if total_extracted_bytes > limit_total_size:
                            raise InputError(
                                "Archive exceeds maximum total uncompressed size limit "
                                f"({limit_total_size} B)"
                            )
                        dst_f.write(chunk)

                # Safe permissions: strip SUID/SGID/sticky, ensure readable
                safe_mode = 0o755 if (mode & 0o100) else 0o644
                target.chmod(safe_mode)
                extracted_paths.add(target)

    return len(members)


def _list_zip(archive_path: Path) -> list[ArchiveEntry]:
    """List entries of a ZIP archive."""
    try:
        with zipfile.ZipFile(archive_path, "r") as zf:
            results = []
            for member in zf.infolist():
                name = member.filename
                is_dir = member.is_dir()
                mode = member.external_attr >> 16
                is_sym = stat.S_ISLNK(mode) if mode else False
                is_enc = bool(member.flag_bits & 0x1)
                results.append(
                    ArchiveEntry(
                        name=name,
                        is_dir=is_dir,
                        size=0 if is_dir else member.file_size,
                        packed_size=member.compress_size,
                        attributes=oct(mode) if mode else "",
                        is_symlink=is_sym,
                        is_hardlink=False,
                        is_encrypted=is_enc,
                    )
                )
            return results
    except zipfile.BadZipFile as err:
        raise InputError(f"Corrupted or invalid ZIP archive: {archive_path} ({err})") from None


def _test_zip(archive_path: Path) -> tuple[bool, int, str | None]:
    """Check integrity of a ZIP archive using CRC check and decompression."""
    try:
        with zipfile.ZipFile(archive_path, "r") as zf:
            bad_file = zf.testzip()
            if bad_file is not None:
                return False, 0, f"CRC check failed for entry: {bad_file}"
            # Also stream through all entries to verify full payload read
            count = 0
            for member in zf.infolist():
                count += 1
                if not member.is_dir():
                    with zf.open(member, "r") as f:
                        while f.read(CHUNK_SIZE):
                            pass
            return True, count, None
    except Exception as err:
        return False, 0, str(err)


# =====================================================================
# TAR Backend Implementation (tar, tar.gz, tar.xz)
# =====================================================================


def _verify_compressed_stream_integrity(archive_path: Path, fmt: str) -> None:
    """Verify that a compressed stream (tar.gz or tar.xz) is complete and uncorrupted to EOF.

    Streams chunk-by-chunk using O(1) memory.
    Raises InputError if the container stream is truncated or corrupt.
    """
    if fmt == "tar.gz":
        try:
            with gzip.GzipFile(archive_path, "rb") as gz:
                while True:
                    chunk = gz.read(CHUNK_SIZE)
                    if not chunk:
                        break
        except (gzip.BadGzipFile, EOFError, zlib.error, OSError) as err:
            raise InputError(
                f"Corrupted or truncated compressed stream in {archive_path.name}: {err}"
            ) from None
    elif fmt == "tar.xz":
        try:
            with lzma.LZMAFile(archive_path, "rb") as xz:
                while True:
                    chunk = xz.read(CHUNK_SIZE)
                    if not chunk:
                        break
        except (lzma.LZMAError, EOFError, OSError) as err:
            raise InputError(
                f"Corrupted or truncated compressed stream in {archive_path.name}: {err}"
            ) from None


def _compress_tar(
    planned_entries: list[PlannedCompressionEntry],
    temp_output: Path,
    fmt: str,
    level: int | None,
    verbose: bool = False,
) -> int:
    """Compress planned entries to TAR / TAR.GZ / TAR.XZ."""
    entries_count = 0
    mode = "w"
    kwargs: dict = {}

    if fmt == "tar.gz":
        mode = "w:gz"
        kwargs["compresslevel"] = 6 if level is None else level
    elif fmt == "tar.xz":
        mode = "w:xz"
        kwargs["preset"] = 6 if level is None else level
    elif fmt == "tar":
        mode = "w"

    with tarfile.open(temp_output, mode=mode, **kwargs) as tf:
        for entry in planned_entries:
            arcname = entry.arcname.rstrip("/") if entry.is_dir else entry.arcname
            try:
                tf.add(entry.source_path, arcname=arcname, recursive=False)
            except OSError as err:
                reason = getattr(err, "strerror", None) or str(err)
                raise InputError(
                    f"Cannot read file for compression: {entry.source_path} ({reason})"
                ) from None
            entries_count += 1
    return entries_count


def _extract_tar(
    archive_path: Path,
    staging_dir: Path,
    fmt: str,
    *,
    max_total_size: int | None = None,
    max_file_size: int | None = None,
    max_entries: int | None = None,
    verbose: bool = False,
) -> int:
    """Extract TAR / TAR.GZ / TAR.XZ archive safely into staging directory."""
    limit_total_size = DEFAULT_MAX_TOTAL_SIZE if max_total_size is None else max_total_size
    limit_file_size = DEFAULT_MAX_FILE_SIZE if max_file_size is None else max_file_size
    limit_entries = DEFAULT_MAX_ENTRIES if max_entries is None else max_entries

    # For compressed TAR streams, verify container stream integrity before extraction
    if fmt in ("tar.gz", "tar.xz"):
        _verify_compressed_stream_integrity(archive_path, fmt)

    try:
        tf = tarfile.open(archive_path, "r:*")
    except Exception as err:
        raise InputError(
            f"Corrupted or invalid TAR archive structure: {archive_path} ({err})"
        ) from None

    with tf:
        extracted_paths: set[Path] = set()
        total_extracted_bytes = 0
        entries_count = 0

        for member in tf:
            entries_count += 1
            if entries_count > limit_entries:
                raise InputError(
                    f"Archive exceeds maximum entry count limit ({limit_entries}): "
                    f"reached {entries_count}"
                )

            # Strict entry type check: only regular files and directories allowed
            if member.issym():
                raise InputError(
                    f"Unsafe or unsupported entry type in archive (symlink): {member.name}"
                )
            if member.islnk():
                raise InputError(
                    f"Unsafe or unsupported entry type in archive (hard link): {member.name}"
                )
            if member.ischr() or member.isblk() or member.isfifo() or member.isdev():
                raise InputError(
                    f"Unsafe or unsupported entry type in archive (special device): {member.name}"
                )

            target = validate_safe_entry_path(member.name, staging_dir)

            if member.isdir():
                if target.exists() and not target.is_dir():
                    raise InputError(
                        "Path conflict in archive: directory conflicts with "
                        f"existing file {member.name}"
                    )
                target.mkdir(parents=True, exist_ok=True)
                target.chmod(0o755)
            elif member.isreg():
                if target in extracted_paths:
                    raise InputError(f"Duplicate file entry in archive: {member.name}")
                if target.exists() and target.is_dir():
                    raise InputError(
                        "Path conflict in archive: file conflicts with "
                        f"existing directory {member.name}"
                    )

                target.parent.mkdir(parents=True, exist_ok=True)

                file_obj = tf.extractfile(member)
                if file_obj is None:
                    raise InputError(f"Cannot extract payload for entry: {member.name}")

                file_bytes = 0
                with file_obj as src_f, open(target, "wb") as dst_f:
                    while True:
                        chunk = src_f.read(CHUNK_SIZE)
                        if not chunk:
                            break
                        chunk_len = len(chunk)
                        file_bytes += chunk_len
                        total_extracted_bytes += chunk_len

                        if file_bytes > limit_file_size:
                            raise InputError(
                                "Archive entry exceeds maximum file size limit "
                                f"({limit_file_size} B): {member.name}"
                            )
                        if total_extracted_bytes > limit_total_size:
                            raise InputError(
                                "Archive exceeds maximum total uncompressed size limit "
                                f"({limit_total_size} B)"
                            )
                        dst_f.write(chunk)

                safe_mode = 0o755 if (member.mode & 0o100) else 0o644
                target.chmod(safe_mode)
                extracted_paths.add(target)
            else:
                raise InputError(
                    "Unsafe or unsupported entry type in archive: "
                    f"{member.name} (type {member.type})"
                )

    return entries_count


def _list_tar(archive_path: Path) -> list[ArchiveEntry]:
    """List entries of a TAR / TAR.GZ / TAR.XZ archive."""
    try:
        with tarfile.open(archive_path, "r:*") as tf:
            results = []
            for member in tf:
                name = member.name
                is_dir = member.isdir()
                if is_dir and not name.endswith("/"):
                    name += "/"
                results.append(
                    ArchiveEntry(
                        name=name,
                        is_dir=is_dir,
                        size=0 if is_dir else member.size,
                        packed_size=None,
                        attributes=oct(member.mode),
                        is_symlink=member.issym(),
                        is_hardlink=member.islnk(),
                        is_encrypted=False,
                    )
                )
            return results
    except Exception as err:
        raise InputError(f"Corrupted or invalid TAR archive: {archive_path} ({err})") from None


def _test_tar(archive_path: Path, fmt: str) -> tuple[bool, int, str | None]:
    """Test integrity of a TAR / TAR.GZ / TAR.XZ archive by verifying stream and structure."""
    try:
        if fmt in ("tar.gz", "tar.xz"):
            _verify_compressed_stream_integrity(archive_path, fmt)

        with tarfile.open(archive_path, "r:*") as tf:
            count = 0
            for member in tf:
                count += 1
                if member.isreg():
                    file_obj = tf.extractfile(member)
                    if file_obj is not None:
                        with file_obj as f:
                            while f.read(CHUNK_SIZE):
                                pass
            return True, count, None
    except Exception as err:
        return False, 0, str(err)


# =====================================================================
# 7Z Backend Implementation
# =====================================================================


def _parse_7z_slt_output(output: str) -> list[dict[str, str]]:
    """Parse technical blocks from 7z l -slt output."""
    blocks: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for line in output.splitlines():
        line = line.strip()
        if not line:
            if current and "Path" in current:
                blocks.append(current)
                current = {}
            continue
        if "=" in line:
            key, val = line.split("=", 1)
            current[key.strip()] = val.strip()
    if current and "Path" in current:
        blocks.append(current)
    return blocks


def _compress_7z(
    inputs: list[Path],
    temp_output: Path,
    level: int | None,
    verbose: bool = False,
) -> int:
    """Compress inputs using 7z backend."""
    backend = _find_7z_backend()
    mx = 5 if level is None else level

    # 7z fails if temp_output exists as an empty 0-byte file (from mkstemp)
    if temp_output.exists():
        temp_output.unlink()

    cmd = [backend, "a", "-t7z", f"-mx={mx}", "-bd", "-y", "--", str(temp_output)]
    for inp in inputs:
        cmd.append(str(inp))

    try:
        # Run 7z process in the parent directory of inputs if possible
        work_dir = inputs[0].parent if inputs else None
        result = run_process(cmd, cwd=work_dir)
        if result.returncode != 0:
            raise ProcessError(f"7z compression failed: {result.stderr or result.stdout}")
    except Exception as err:
        raise ProcessError(f"7z execution failed: {err}") from err

    # Inspect created archive to count entries
    list_entries = _list_7z(temp_output)
    return len(list_entries)


def _list_7z(archive_path: Path) -> list[ArchiveEntry]:
    """List 7z archive entries via 7z l -slt."""
    backend = _find_7z_backend()
    cmd = [backend, "l", "-slt", "-bd", "--", str(archive_path)]
    result = run_process(cmd)
    if result.returncode != 0:
        raise InputError(
            f"Failed to inspect 7z archive: {archive_path} ({result.stderr or result.stdout})"
        )

    blocks = _parse_7z_slt_output(result.stdout)
    entries: list[ArchiveEntry] = []
    # Skip the archive header block which has Path == archive_path
    abs_str = str(archive_path.resolve())
    for b in blocks:
        path_val = b.get("Path", "")
        if not path_val:
            continue
        # Check if this block describes the archive file itself
        if path_val == str(archive_path) or str(Path(path_val).resolve()) == abs_str:
            continue

        attr = b.get("Attributes", "")
        folder_flag = b.get("Folder")
        is_dir = folder_flag == "+" or attr.startswith("D") or "drwx" in attr
        size = int(b.get("Size", 0)) if b.get("Size") else 0
        packed = int(b.get("Packed Size", 0)) if b.get("Packed Size") else None
        name = path_val.replace("\\", "/")
        if is_dir and not name.endswith("/"):
            name += "/"

        is_sym = "l" in attr.lower() or b.get("Symbolic Link") is not None
        is_hard = b.get("Hard Link") is not None
        is_enc = b.get("Encrypted") == "+"

        entries.append(
            ArchiveEntry(
                name=name,
                is_dir=is_dir,
                size=0 if is_dir else size,
                packed_size=packed,
                attributes=attr,
                is_symlink=is_sym,
                is_hardlink=is_hard,
                is_encrypted=is_enc,
            )
        )
    return entries


def _test_7z(archive_path: Path) -> tuple[bool, int, str | None]:
    """Test 7z archive integrity via 7z t."""
    backend = _find_7z_backend()
    cmd = [backend, "t", "-bd", "-y", "--", str(archive_path)]
    try:
        run_process(cmd)
        entries = _list_7z(archive_path)
        return True, len(entries), None
    except ProcessError as err:
        return False, 0, f"7z integrity test failed: {err}"
    except Exception as err:
        return False, 0, str(err)


# =====================================================================
# High-Level Service Operations
# =====================================================================


def archive_compress(
    inputs: str | Sequence[str | Path],
    *,
    fmt: str | None = None,
    output: str | Path | None = None,
    level: int | None = None,
    dry_run: bool = False,
    as_json: bool = False,
    verbose: bool = False,
    stdout_stream=None,
) -> int:
    """Compress file or directory into an archive."""
    out = sys.stdout if stdout_stream is None else stdout_stream

    # Normalize inputs
    raw_inputs = [inputs] if isinstance(inputs, (str, Path)) else list(inputs)
    if not raw_inputs:
        raise UsageError("At least one input path is required for compression.")

    input_paths = [Path(p).absolute() for p in raw_inputs]
    for p in input_paths:
        if not p.exists() and not os.path.islink(p):
            raise InputError(f"Input path not found: {p}")

    if len(input_paths) > 1 and output is None:
        raise UsageError("Multiple inputs require an explicit --output path.")

    # Determine format
    target_format = fmt.lower() if fmt else None
    if target_format and target_format not in SUPPORTED_FORMATS:
        raise UsageError(
            f"Unsupported archive format: {fmt}. Supported formats: {', '.join(SUPPORTED_FORMATS)}"
        )

    if output is not None:
        out_path = Path(output)
        inferred = _infer_format_from_extension(out_path)
        if target_format is not None and inferred is not None and target_format != inferred:
            raise UsageError(
                f"Output extension does not match requested format '{target_format}': {output}"
            )
        if target_format is None:
            target_format = inferred or "zip"
    else:
        if target_format is None:
            target_format = "zip"

    if level is not None and not (0 <= level <= 9):
        raise UsageError(f"Compression level must be between 0 and 9: got {level}")

    # Validate all entries and reject symlinks/collisions upfront
    planned_entries = _plan_and_validate_compression_entries(raw_inputs, input_paths)

    primary_input = input_paths[0]

    # Automatic destination planning with collision resolution
    planned_dest: Path
    if output is not None:
        planned_dest = Path(output).resolve()
        if os.path.lexists(planned_dest):
            raise OutputError(f"Output already exists: {planned_dest}")
    else:
        planned_dest = _get_default_compress_output(primary_input, target_format)

    if dry_run:
        msg = (
            f"[dry-run] Would compress {len(input_paths)} input(s) into: {planned_dest} "
            f"(format: {target_format})"
        )
        if as_json:
            payload = {
                "dry_run": True,
                "format": target_format,
                "destination": str(planned_dest),
                "inputs": [str(p) for p in input_paths],
            }
            out.write(json.dumps(payload, indent=2) + "\n")
        else:
            out.write(f"{msg}\n")
        return 0

    # Publish atomically via atomic_output
    # If explicit output was not supplied, wrap in retry for race collision safety
    while True:
        try:
            with atomic_output(
                primary_input, "archive", output=planned_dest, dry_run=False
            ) as paths:
                temp_file = paths.temporary
                if temp_file is None:
                    raise OutputError("Staging temporary file could not be created.")

                if target_format == "zip":
                    count = _compress_zip(planned_entries, temp_file, level, verbose=verbose)
                elif target_format in ("tar", "tar.gz", "tar.xz"):
                    count = _compress_tar(
                        planned_entries, temp_file, target_format, level, verbose=verbose
                    )
                elif target_format == "7z":
                    count = _compress_7z(input_paths, temp_file, level, verbose=verbose)
                else:
                    raise UsageError(f"Unsupported format: {target_format}")

            # Publication succeeded
            final_dest = paths.destination
            break
        except OutputError as err:
            if output is None and "already exists" in str(err):
                # Another process created the candidate, recalculate next available candidate
                planned_dest = _available_candidate(
                    planned_dest.parent
                    / planned_dest.name[: -len(FORMAT_EXTENSIONS[target_format])],
                    FORMAT_EXTENSIONS[target_format],
                )
                continue
            raise

    if as_json:
        payload = {
            "archive": str(final_dest),
            "format": target_format,
            "entries_count": count,
            "size": final_dest.stat().st_size,
        }
        out.write(json.dumps(payload, indent=2) + "\n")
    else:
        out.write(f"Created archive: {final_dest}\n")

    return 0


def archive_extract(
    archive_path: str | Path,
    *,
    output: str | Path | None = None,
    dry_run: bool = False,
    as_json: bool = False,
    verbose: bool = False,
    stdout_stream=None,
) -> int:
    """Extract an archive safely into an extraction directory."""
    out = sys.stdout if stdout_stream is None else stdout_stream
    archive = Path(archive_path).resolve()

    fmt = detect_archive_format(archive)

    if fmt == "7z":
        raise InputError(
            "7Z extraction is currently disabled due to external backend security limitations "
            "(external processes cannot enforce in-process atomic safety boundaries). "
            "Supported extraction formats: zip, tar, tar.gz, tar.xz. "
            "You can inspect 7Z archives with 'lut archive list' and verify integrity with "
            "'lut archive test'."
        )

    # Plan extraction directory
    planned_dest: Path
    if output is not None:
        planned_dest = Path(output).resolve()
        if os.path.lexists(planned_dest):
            raise OutputError(f"Output already exists: {planned_dest}")
    else:
        planned_dest = _get_default_extract_output(archive)

    if dry_run:
        msg = f"[dry-run] Would extract {archive.name} (format: {fmt}) into: {planned_dest}"
        if as_json:
            payload = {
                "dry_run": True,
                "archive": str(archive),
                "format": fmt,
                "destination": str(planned_dest),
            }
            out.write(json.dumps(payload, indent=2) + "\n")
        else:
            out.write(f"{msg}\n")
        return 0

    # Publish atomically as a directory
    while True:
        try:
            with atomic_output(
                archive, "extracted", output=planned_dest, directory=True, dry_run=False
            ) as paths:
                staging_dir = paths.temporary
                if staging_dir is None:
                    raise OutputError("Staging temporary directory could not be created.")

                if fmt == "zip":
                    count = _extract_zip(archive, staging_dir, verbose=verbose)
                elif fmt in ("tar", "tar.gz", "tar.xz"):
                    count = _extract_tar(archive, staging_dir, fmt, verbose=verbose)
                else:
                    raise InputError(f"Unsupported archive format for extraction: {fmt}")

            final_dest = paths.destination
            break
        except OutputError as err:
            if output is None and "already exists" in str(err):
                planned_dest = _get_default_extract_output(archive)
                continue
            raise

    if as_json:
        payload = {
            "archive": str(archive),
            "format": fmt,
            "destination": str(final_dest),
            "entries_extracted": count,
        }
        out.write(json.dumps(payload, indent=2) + "\n")
    else:
        out.write(f"Extracted archive to: {final_dest}\n")

    return 0


def archive_list(
    archive_path: str | Path,
    *,
    as_json: bool = False,
    verbose: bool = False,
    stdout_stream=None,
) -> int:
    """List contents of an archive without extracting."""
    out = sys.stdout if stdout_stream is None else stdout_stream
    archive = Path(archive_path).resolve()

    fmt = detect_archive_format(archive)

    if fmt == "zip":
        entries = _list_zip(archive)
    elif fmt in ("tar", "tar.gz", "tar.xz"):
        entries = _list_tar(archive)
    elif fmt == "7z":
        entries = _list_7z(archive)
    else:
        raise InputError(f"Unsupported format for listing: {fmt}")

    files_count = sum(1 for e in entries if not e.is_dir)
    dirs_count = sum(1 for e in entries if e.is_dir)
    total_size = sum(e.size for e in entries if not e.is_dir)

    if as_json:
        payload = {
            "archive": archive.name,
            "format": fmt.upper(),
            "files_count": files_count,
            "directories_count": dirs_count,
            "total_size": total_size,
            "entries": [
                {
                    "name": e.name,
                    "type": "directory" if e.is_dir else "file",
                    "size": e.size,
                    "packed_size": e.packed_size,
                }
                for e in entries
            ],
        }
        out.write(json.dumps(payload, indent=2) + "\n")
        return 0

    # Format table for terminal
    out.write(f"Archive: {archive.name}\n")
    out.write(f"Format: {fmt.upper()}\n\n")

    out.write(f"{'Name':<40} {'Size':>10}\n")
    out.write("-" * 52 + "\n")
    for e in entries:
        safe_name = _escape_terminal(e.name)
        size_str = "-" if e.is_dir else _format_size(e.size)
        out.write(f"{safe_name:<40} {size_str:>10}\n")

    out.write("\n")
    out.write(f"Files: {files_count}\n")
    out.write(f"Directories: {dirs_count}\n")
    out.write(f"Total size: {_format_size(total_size)}\n")

    return 0


def archive_test(
    archive_path: str | Path,
    *,
    as_json: bool = False,
    verbose: bool = False,
    stdout_stream=None,
) -> int:
    """Test integrity of an archive without writing to disk."""
    out = sys.stdout if stdout_stream is None else stdout_stream
    archive = Path(archive_path).resolve()

    fmt = detect_archive_format(archive)

    passed = False
    count = 0
    error_msg: str | None = None

    if fmt == "zip":
        passed, count, error_msg = _test_zip(archive)
    elif fmt in ("tar", "tar.gz", "tar.xz"):
        passed, count, error_msg = _test_tar(archive, fmt)
    elif fmt == "7z":
        passed, count, error_msg = _test_7z(archive)
    else:
        raise InputError(f"Unsupported format for integrity test: {fmt}")

    if as_json:
        payload = {
            "archive": archive.name,
            "format": fmt.upper(),
            "status": "PASS" if passed else "FAIL",
            "entries_checked": count,
        }
        if not passed and error_msg:
            payload["error"] = error_msg
        out.write(json.dumps(payload, indent=2) + "\n")
    else:
        out.write(f"Archive: {archive.name}\n")
        out.write(f"Format: {fmt.upper()}\n\n")
        if passed:
            out.write("Integrity check: PASS\n")
            out.write(f"Entries checked: {count}\n")
        else:
            out.write("Integrity check: FAIL\n")
            if error_msg:
                out.write(f"Error: {error_msg}\n")

    return 0 if passed else 1
