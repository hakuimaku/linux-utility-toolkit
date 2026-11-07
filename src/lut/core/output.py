"""Stage complete outputs and publish them atomically without overwriting."""

import ctypes
import os
import shutil
import stat
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from lut.core.errors import InputError, OutputError, UsageError


@dataclass
class OutputPaths:
    """Expose the final destination and the private backend output path."""

    destination: Path
    temporary: Path | None


def _available(path: Path, extension: str) -> Path:
    """Find a free name while counting dangling symlinks as existing outputs."""
    # Preserve the operation suffix and extension when adding collision numbers.
    candidate = path
    # Keep a caller-supplied compound extension intact when numbering collisions.
    stem = path.name[: -len(extension)] if extension else path.name
    # Start numbering after the unsuffixed candidate.
    number = 2
    while os.path.lexists(candidate):
        candidate = path.with_name(f"{stem}_{number}{extension}")
        number += 1
    return candidate


def output_path(
    source: str | os.PathLike[str],
    suffix: str,
    *,
    extension: str | None = None,
    output: str | os.PathLike[str] | None = None,
    directory: bool = False,
) -> Path:
    """Validate input and determine an output path beside it, without creating anything."""
    # Reject suffixes and extensions that could escape the selected parent directory.
    if not suffix or "/" in suffix or "\0" in suffix:
        raise UsageError("Output suffix must be a nonempty filename component.")
    if extension is not None and ("/" in extension or "\0" in extension):
        raise UsageError("Output extension must be a filename component.")
    # Absolute paths keep cleanup independent of later working-directory changes.
    original = Path(source).absolute()
    try:
        # Reject devices and missing inputs before creating any temporary output.
        mode = original.stat().st_mode
        if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise InputError(f"Input must be a file or directory: {original}")
        if output is not None:
            # Explicit destinations never receive automatic collision renaming.
            destination = Path(output).absolute()
            if os.path.lexists(destination):
                raise OutputError(f"Output already exists: {destination}")
        else:
            # Directory outputs have no extension; files keep or replace the last extension.
            ending = "" if directory or stat.S_ISDIR(mode) else original.suffix
            if extension is not None and not directory:
                ending = extension
            if ending and not ending.startswith("."):
                ending = "." + ending
            # Input directory names retain dots because those dots are not file extensions.
            stem = original.name if stat.S_ISDIR(mode) else original.stem
            destination = _available(original.with_name(f"{stem}_{suffix}{ending}"), ending)
        if not destination.parent.is_dir():
            raise OutputError(f"Output directory does not exist: {destination.parent}")
        return destination
    except FileNotFoundError:
        raise InputError(f"Input not found: {original}") from None
    except OSError:
        raise OutputError("Cannot access the input or output directory.") from None


def _publish_directory(source: Path, destination: Path) -> None:
    """Use Linux no-replace rename because os.rename can overwrite an empty directory."""
    try:
        # Resolve libc lazily so help and file-only operations need no platform probe.
        rename = ctypes.CDLL(None, use_errno=True).renameat2
    except AttributeError:
        raise OutputError("Atomic directory output requires libc renameat2 support.") from None
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    # AT_FDCWD and RENAME_NOREPLACE are Linux ABI constants, independent of distro.
    if rename(-100, os.fsencode(source), -100, os.fsencode(destination), 1) != 0:
        # Preserve EEXIST as FileExistsError so automatic output names can retry safely.
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code))


@contextmanager
def atomic_output(
    source: str | os.PathLike[str],
    suffix: str,
    *,
    extension: str | None = None,
    output: str | os.PathLike[str] | None = None,
    directory: bool = False,
    dry_run: bool = False,
):
    """Yield a private staging path, publishing it only after a successful context body."""
    # Reuse the same destination contract for operations and file-free previews.
    original = Path(source).absolute()
    # Determine destination from the absolute input used for safety and collision checks.
    destination = output_path(
        original, suffix, extension=extension, output=output, directory=directory
    )
    # The destination can change at publication if another writer wins the same auto name.
    paths = OutputPaths(destination, None)
    if dry_run:
        yield paths
        return
    try:
        if directory:
            paths.temporary = Path(tempfile.mkdtemp(prefix=".lut-", dir=destination.parent))
        else:
            # Keep the extension so backends that infer output format can recognize it.
            descriptor, name = tempfile.mkstemp(
                prefix=".lut-",
                suffix=destination.suffix,
                dir=destination.parent,
            )
            os.close(descriptor)
            paths.temporary = Path(name)
        yield paths
        # Refuse backend output that changed into a symlink or an unexpected file type.
        mode = paths.temporary.lstat().st_mode
        if not (stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode)):
            raise OutputError("Backend output has an unexpected file type.")
        if not directory and paths.temporary.samefile(original):
            raise OutputError("Backend output must not be a hard link to the input.")
        while True:
            try:
                if directory:
                    _publish_directory(paths.temporary, paths.destination)
                else:
                    # Hard-link publication fails atomically if any destination entry exists.
                    os.link(paths.temporary, paths.destination, follow_symlinks=False)
                break
            except FileExistsError:
                if output is not None:
                    raise OutputError(f"Output already exists: {paths.destination}") from None
                paths.destination = output_path(
                    original,
                    suffix,
                    extension=extension,
                    directory=directory,
                )
    except OSError:
        raise OutputError(
            "Cannot create or publish output; no existing file was overwritten."
        ) from None
    finally:
        try:
            if paths.temporary is not None and os.path.lexists(paths.temporary):
                if paths.temporary.is_symlink() or not paths.temporary.is_dir():
                    paths.temporary.unlink()
                else:
                    shutil.rmtree(paths.temporary)
        except OSError:
            raise OutputError(f"Cannot remove temporary output: {paths.temporary}") from None
