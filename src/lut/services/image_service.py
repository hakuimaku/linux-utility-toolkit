"""Image service implementing safe conversion, compression, resize, crop, rotate, and metadata."""

import json
import math
import os
import re
import shutil
import stat
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from lut.core.dependencies import installation_hint
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

SUPPORTED_FORMATS = ("jpeg", "jpg", "png", "webp", "bmp", "tiff", "tif", "gif")

FORMAT_EXTENSIONS = {
    "jpeg": ".jpg",
    "jpg": ".jpg",
    "png": ".png",
    "webp": ".webp",
    "bmp": ".bmp",
    "tiff": ".tiff",
    "tif": ".tiff",
    "gif": ".gif",
}

# Normalization map for canonical format names
CANONICAL_FORMATS = {
    "jpeg": "jpeg",
    "jpg": "jpeg",
    "png": "png",
    "webp": "webp",
    "bmp": "bmp",
    "tiff": "tiff",
    "tif": "tiff",
    "gif": "gif",
}

DEFAULT_MAX_INPUT_SIZE = 500 * 1024 * 1024  # 500 MB
DEFAULT_MAX_DIMENSION = 32768  # 32,768 pixels per side
DEFAULT_MAX_PIXELS = 100_000_000  # 100 MP total pixel budget
DEFAULT_MAX_FRAMES = 100
DEFAULT_PROCESS_TIMEOUT = 30.0

# Resource limits passed to ImageMagick to protect memory and disk
BACKEND_LIMIT_ARGS = [
    "-limit",
    "memory",
    "512MiB",
    "-limit",
    "map",
    "1GiB",
    "-limit",
    "disk",
    "2GiB",
]


@dataclass
class ImageMetadata:
    """Representation of extracted image metadata."""

    file: str
    format: str
    width: int
    height: int
    raw_width: int
    raw_height: int
    size_bytes: int
    size_formatted: str
    colorspace: str
    has_alpha: bool
    is_opaque: bool
    bit_depth: int | None
    frame_count: int
    orientation: str
    resolution: str | None
    icc_profile: str | None
    has_exif: bool
    has_gps: bool


@dataclass
class BackendInfo:
    """Information about the detected ImageMagick backend."""

    version_major: int
    raw_version: str
    identify_cmd: list[str]
    convert_cmd: list[str]


_CACHED_BACKEND: BackendInfo | None = None


# =====================================================================
# Backend Discovery & Management
# =====================================================================


def _detect_backend() -> BackendInfo:
    """Detect ImageMagick 7 or fallback to ImageMagick 6."""
    packages = {
        "arch": "imagemagick",
        "debian": "imagemagick",
        "ubuntu": "imagemagick",
        "fedora": "ImageMagick",
    }
    hint = installation_hint("ImageMagick", packages)

    # 1. Probe ImageMagick 7 ("magick")
    magick_path = shutil.which("magick")
    if magick_path:
        try:
            res = run_process([magick_path, "-version"], timeout=5)
            banner = res.stdout or res.stderr
            m = re.search(r"ImageMagick\s+(\d+)\.(\d+)\.(\d+)", banner)
            if m:
                major = int(m.group(1))
                if major >= 7:
                    return BackendInfo(
                        version_major=major,
                        raw_version=m.group(0),
                        identify_cmd=[magick_path, "identify"],
                        convert_cmd=[magick_path],
                    )
        except Exception:
            pass

    # 2. Probe ImageMagick 6 fallback ("identify" and "convert")
    identify_path = shutil.which("identify")
    convert_path = shutil.which("convert")
    if identify_path and convert_path:
        try:
            res = run_process([identify_path, "-version"], timeout=5)
            banner = res.stdout or res.stderr
            m = re.search(r"ImageMagick\s+(\d+)\.(\d+)\.(\d+)", banner)
            if m:
                major = int(m.group(1))
                return BackendInfo(
                    version_major=major,
                    raw_version=m.group(0),
                    identify_cmd=[identify_path],
                    convert_cmd=[convert_path],
                )
        except Exception:
            pass

    raise DependencyError(f"Missing dependency: ImageMagick. {hint}")


def get_backend() -> BackendInfo:
    """Get the cached ImageMagick backend or detect it."""
    global _CACHED_BACKEND
    if _CACHED_BACKEND is None:
        _CACHED_BACKEND = _detect_backend()
    return _CACHED_BACKEND


def is_backend_available() -> bool:
    """Check if an ImageMagick backend is available without raising."""
    try:
        get_backend()
        return True
    except DependencyError:
        return False


def reset_backend_cache() -> None:
    """Reset cached backend for testing purposes."""
    global _CACHED_BACKEND
    _CACHED_BACKEND = None


# =====================================================================
# Format & Header Safety Checks
# =====================================================================


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


def _validate_no_ancestor_symlinks(
    input_arg: str | os.PathLike[str],
    is_output: bool = False,
) -> None:
    """Reject inputs or outputs containing any symlink in ancestor path components or leaf."""
    raw_path = Path(input_arg)
    err_cls = OutputError if is_output else InputError
    label = "output" if is_output else "input"

    if os.path.islink(raw_path):
        raise err_cls(f"Symlinks are not supported for image {label}: {raw_path}")

    if raw_path.is_absolute():
        current = Path(raw_path.parts[0])
        for part in raw_path.parts[1:]:
            current = current / part
            if os.path.islink(current):
                msg = (
                    f"Symlinks are not supported for image {label} "
                    f"(ancestor symlink in path): {current}"
                )
                raise err_cls(msg)
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
                msg = (
                    f"Symlinks are not supported for image {label} "
                    f"(ancestor symlink in path): {current}"
                )
                raise err_cls(msg)


def validate_input_path(path_str: str | os.PathLike[str]) -> Path:
    """Validate that the input path is an existing, regular file without symlinks."""
    path = Path(path_str)
    if not path_str or "\0" in str(path_str):
        raise UsageError("Input path must be nonempty and contain no NUL characters.")

    # Check all ancestor components and leaf for symlinks
    _validate_no_ancestor_symlinks(path_str)

    if os.path.islink(path):
        raise InputError(f"Symlinks are not supported for image input: {path}")

    if not path.exists():
        raise InputError(f"Input file not found: {path}")

    # Ensure it is a regular file
    try:
        st = path.stat()
    except OSError as e:
        raise InputError(f"Cannot access input file: {e}") from None

    if stat.S_ISDIR(st.st_mode):
        raise InputError(f"Input must be a file, not a directory: {path}")
    if not stat.S_ISREG(st.st_mode):
        raise InputError(f"Input must be a regular file: {path}")

    if st.st_size == 0:
        raise InputError(f"Input file is empty (0 bytes): {path}")

    if st.st_size > DEFAULT_MAX_INPUT_SIZE:
        max_str = _format_size(DEFAULT_MAX_INPUT_SIZE)
        curr_str = _format_size(st.st_size)
        raise InputError(f"Input file size ({curr_str}) exceeds limit ({max_str}): {path}")

    return path.resolve()


def detect_magic_format(path: Path) -> str:
    """Check the initial bytes of a file to verify it is a valid image and detect format."""
    try:
        with open(path, "rb") as f:
            header = f.read(32)
    except OSError as e:
        raise InputError(f"Cannot read file header: {e}") from None

    if len(header) < 4:
        raise InputError(f"File is too small to be a valid image: {path}")

    # JPEG magic: FF D8 FF
    if header.startswith(b"\xff\xd8\xff"):
        return "jpeg"

    # PNG magic: \x89PNG\r\n\x1a\n
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"

    # GIF magic: GIF87a or GIF89a
    if header.startswith((b"GIF87a", b"GIF89a")):
        return "gif"

    # BMP magic: BM
    if header.startswith(b"BM"):
        return "bmp"

    # WebP magic: RIFF....WEBP
    if len(header) >= 12 and header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return "webp"

    # TIFF magic: II*\x00 (little-endian) or MM\x00* (big-endian)
    if header.startswith((b"II*\x00", b"MM\x00*")):
        return "tiff"

    raise InputError(f"Unsupported or unrecognized image format: {path}")


def validate_color_string(color: str) -> str:
    """Validate background color string to prevent argument or syntax injection."""
    clean = color.strip()
    if not clean:
        raise UsageError("Background color cannot be empty.")
    # Allow hex color (#rgb, #rrggbb, #rrggbbaa), alphanumeric names (white, black, red, none),
    # or basic rgb/rgba notation.
    if re.match(r"^#[0-9a-fA-F]{3,8}$", clean) or re.match(r"^[a-zA-Z0-9_-]+$", clean):
        return clean
    if re.match(r"^rgba?\(\s*\d+\s*,\s*\d+\s*,\s*\d+\s*(?:,\s*[0-9.]+\s*)?\)$", clean):
        return clean
    raise UsageError(f"Invalid or unsafe background color specification: {color!r}")


def check_partial_alpha(
    source_path: Path,
    backend: BackendInfo | None = None,
    frame: int | None = None,
    timeout: float = DEFAULT_PROCESS_TIMEOUT,
) -> bool:
    """Check if an image contains partial (semi-transparent) alpha values.

    Returns True if any pixel has alpha strictly between 0 and 1 (0 < alpha < 255).
    Returns False if all pixels are either fully transparent (0) or fully opaque (255).
    Raises ProcessError if backend execution fails or returns malformed output (fail-closed).
    """
    if backend is None:
        backend = get_backend()

    frame_spec = f"[{frame}]" if frame is not None else "[0]"
    cmd = [
        *backend.convert_cmd,
        *BACKEND_LIMIT_ARGS,
        f"{source_path}{frame_spec}",
        "-alpha",
        "extract",
        "-format",
        "%k %[fx:minima] %[fx:maxima]",
        "info:",
    ]
    res = run_process(cmd, timeout=timeout)
    if res.returncode != 0:
        raise ProcessError(
            f"Failed to inspect alpha channel: backend exited with code {res.returncode}",
            returncode=res.returncode,
        )

    parts = res.stdout.strip().split()
    if len(parts) != 3:
        raise ProcessError(
            f"Failed to inspect image alpha channel: invalid backend output {res.stdout!r}"
        )

    try:
        k = int(parts[0])
        mn = float(parts[1])
        mx = float(parts[2])
    except ValueError as e:
        raise ProcessError(
            f"Failed to parse numeric alpha channel statistics: {res.stdout!r}"
        ) from e

    # Fail-closed validation for non-finite values (NaN, Inf)
    if math.isnan(mn) or math.isnan(mx) or math.isinf(mn) or math.isinf(mx):
        raise ProcessError(
            f"Failed to inspect image alpha channel: non-finite alpha values {res.stdout!r}"
        )

    # Fail-closed validation for range and structural sanity
    if k < 1 or mn < 0.0 or mx > 1.0 or mn > mx:
        raise ProcessError(
            f"Failed to inspect image alpha channel: alpha statistics out of range {res.stdout!r}"
        )

    # Fail-closed validation for statistical consistency between unique count and bounds
    if (k == 1 and mn != mx) or (k >= 2 and mn == mx):
        raise ProcessError(
            f"Failed to inspect image alpha channel: inconsistent alpha statistics {res.stdout!r}"
        )

    if k == 1:
        # Single alpha value: binary ONLY if strictly 0.0 (transparent) or 1.0 (opaque).
        # Any intermediate value (including 16-bit 0.0005 or 0.9995) is partial alpha.
        return not (mn == 0.0 or mn == 1.0)
    if k == 2:
        # Two unique alpha values: binary ONLY if one is strictly 0.0 and other is strictly 1.0.
        return not (mn == 0.0 and mx == 1.0)
    # Three or more unique values in [0, 1] must contain intermediate partial alpha.
    return True


# =====================================================================
# Destination & Output Planning
# =====================================================================


def _available_candidate(base_path: Path, ext: str) -> Path:
    """Find a non-existing candidate path with numbered collision suffix."""
    candidate = base_path.with_name(f"{base_path.name}{ext}")
    number = 2
    while os.path.lexists(candidate):
        candidate = base_path.with_name(f"{base_path.name}_{number}{ext}")
        number += 1
    return candidate


def get_default_convert_output(source_path: Path, target_ext: str) -> Path:
    """Compute default destination for convert beside source (e.g. photo.jpg, photo_2.jpg)."""
    base_name = source_path.stem
    base_path = source_path.parent / base_name
    return _available_candidate(base_path, target_ext)


def get_default_operation_output(source_path: Path, operation_suffix: str) -> Path:
    """Compute default destination for operations beside source (e.g. photo_resized.jpg)."""
    base_name = f"{source_path.stem}_{operation_suffix}"
    ext = source_path.suffix
    base_path = source_path.parent / base_name
    return _available_candidate(base_path, ext)


def resolve_output_destination(
    source_path: Path,
    output_arg: str | None,
    default_getter,
    expected_extension: str | None = None,
    is_convert: bool = False,
) -> Path:
    """Resolve and validate the planned destination, enforcing non-overwriting guarantees."""
    if output_arg is not None:
        if not output_arg or "\0" in str(output_arg):
            raise UsageError("Output path must be nonempty and contain no NUL characters.")

        raw_path = Path(output_arg)

        # 1. Reject symlinks in output path and all ancestor directories BEFORE resolving
        _validate_no_ancestor_symlinks(output_arg, is_output=True)

        # 2. Check if the output destination already exists (including broken symlinks)
        if os.path.lexists(raw_path):
            raise OutputError(f"Output already exists: {raw_path}")

        # 3. Check if parent directory exists and is a directory
        parent = raw_path.parent
        if not parent.exists():
            raise OutputError(f"Output directory does not exist: {parent}")
        if not parent.is_dir():
            raise OutputError(f"Output directory is not a directory: {parent}")

        # 4. Enforce output extension format consistency
        if expected_extension:
            norm_expected = expected_extension.lower().lstrip(".")
            norm_actual = raw_path.suffix.lower().lstrip(".")
            # Allow jpg/jpeg interchangeably
            if norm_expected in ("jpg", "jpeg"):
                valid_exts = ("jpg", "jpeg")
            elif norm_expected in ("tif", "tiff"):
                valid_exts = ("tif", "tiff")
            else:
                valid_exts = (norm_expected,)

            if norm_actual not in valid_exts:
                if is_convert:
                    msg = (
                        f"Output extension '{raw_path.suffix}' does not match "
                        f"target format '{expected_extension}'."
                    )
                else:
                    msg = (
                        f"Output extension '{raw_path.suffix}' does not match "
                        f"source format '{expected_extension}'. "
                        "Use 'lut image convert' to change format."
                    )
                raise UsageError(msg)

        # Canonical destination: resolve parent directory to ensure absolute path,
        # but keep leaf filename un-resolved since it does not exist yet.
        dest = parent.resolve() / raw_path.name
        if os.path.lexists(dest):
            raise OutputError(f"Output already exists: {dest}")

        return dest

    return default_getter()


def _verify_staging_output(
    temp_file: Path,
    expected_format: str,
    expected_dimensions: tuple[int, int] | None = None,
) -> ImageMetadata:
    """Verify that backend output exists, is non-empty, and has expected format and dimensions."""
    if not temp_file.exists() or temp_file.stat().st_size == 0:
        raise OutputError("Backend output file is missing or empty.")

    actual_magic = detect_magic_format(temp_file)
    actual_canonical = CANONICAL_FORMATS.get(actual_magic)
    expected_canonical = CANONICAL_FORMATS.get(expected_format)
    if actual_canonical != expected_canonical:
        msg = (
            f"Backend output format '{actual_magic}' does not match "
            f"expected format '{expected_format}'."
        )
        raise OutputError(msg)

    out_meta = inspect_image(temp_file)
    if expected_dimensions is not None:
        exp_w, exp_h = expected_dimensions
        if out_meta.width != exp_w or out_meta.height != exp_h:
            msg = (
                f"Backend output dimensions ({out_meta.width}x{out_meta.height}) do not match "
                f"expected dimensions ({exp_w}x{exp_h})."
            )
            raise OutputError(msg)
    return out_meta


# =====================================================================
# Metadata Inspection
# =====================================================================


def inspect_image(
    source_path: Path,
    frame: int | None = None,
    timeout: float = DEFAULT_PROCESS_TIMEOUT,
) -> ImageMetadata:
    """Extract comprehensive metadata from the image using the backend."""
    valid_path = validate_input_path(source_path)
    magic_fmt = detect_magic_format(valid_path)
    backend = get_backend()

    # 1. Determine frame count
    count_cmd = [
        *backend.identify_cmd,
        *BACKEND_LIMIT_ARGS,
        "-format",
        "%m\n",
        "--",
        str(valid_path),
    ]
    try:
        count_res = run_process(count_cmd, timeout=timeout)
    except ProcessError as e:
        raise InputError(f"Corrupt or unreadable image file: {valid_path}") from e

    frame_lines = [line.strip() for line in count_res.stdout.splitlines() if line.strip()]
    frame_count = max(1, len(frame_lines))

    if frame_count > DEFAULT_MAX_FRAMES:
        msg = (
            f"Image frame count ({frame_count}) exceeds "
            f"safety limit ({DEFAULT_MAX_FRAMES}): {valid_path}"
        )
        raise InputError(msg)

    if frame is not None:
        if frame < 0 or frame >= frame_count:
            raise UsageError(
                f"Frame index {frame} out of range (image has {frame_count} frames: "
                f"0 to {frame_count - 1})."
            )
        target_frame = frame
    else:
        target_frame = 0

    # 2. Extract detailed metadata on the selected frame
    fmt_spec = (
        "format:%m\n"
        "width:%w\n"
        "height:%h\n"
        "colorspace:%[colorspace]\n"
        "channels:%[channels]\n"
        "depth:%z\n"
        "orientation:%[orientation]\n"
        "exif_orientation:%[exif:Orientation]\n"
        "x_res:%x\n"
        "y_res:%y\n"
        "opaque:%[opaque]\n"
        "profiles:%[profiles]\n"
        "icc_name:%[profile:icc]\n"
        "exif_data:%[exif:*]\n"
    )

    detail_cmd = [
        *backend.identify_cmd,
        *BACKEND_LIMIT_ARGS,
        "-format",
        fmt_spec,
        "--",
        f"{valid_path}[{target_frame}]",
    ]
    try:
        detail_res = run_process(detail_cmd, timeout=timeout)
    except ProcessError as e:
        raise InputError(f"Failed to read image metadata: {valid_path}") from e

    meta_dict: dict[str, str] = {}
    exif_lines: list[str] = []
    in_exif = False

    for line in detail_res.stdout.splitlines():
        if line.startswith("exif_data:"):
            in_exif = True
            val = line[len("exif_data:") :].strip()
            if val:
                exif_lines.append(val)
            continue
        if in_exif:
            if ":" in line and not line.startswith("exif:"):
                in_exif = False
            else:
                exif_lines.append(line.strip())
                continue

        if ":" in line:
            key, val = line.split(":", 1)
            meta_dict[key.strip()] = val.strip()

    # Parse numerical fields
    try:
        raw_width = int(meta_dict.get("width", 0))
        raw_height = int(meta_dict.get("height", 0))
    except ValueError:
        raise InputError(f"Invalid dimensions reported for image: {valid_path}") from None

    if raw_width <= 0 or raw_height <= 0:
        raise InputError(f"Image has invalid dimensions ({raw_width}x{raw_height}): {valid_path}")

    # Determine visual / normalized dimensions based on EXIF orientation
    orientation = meta_dict.get("orientation", "Undefined")
    if not orientation or orientation == "Undefined":
        orientation = "Undefined"
    exif_orientation = meta_dict.get("exif_orientation", "").strip()

    is_transposed = orientation in (
        "LeftTop",
        "RightTop",
        "RightBottom",
        "LeftBottom",
    ) or exif_orientation in ("5", "6", "7", "8")
    if is_transposed:
        width = raw_height
        height = raw_width
    else:
        width = raw_width
        height = raw_height

    # Enforce pixel dimension and budget limits on normalized dimensions
    if width > DEFAULT_MAX_DIMENSION or height > DEFAULT_MAX_DIMENSION:
        msg = (
            f"Image dimension ({width}x{height}) exceeds maximum limit "
            f"({DEFAULT_MAX_DIMENSION}px): {valid_path}"
        )
        raise InputError(msg)

    total_pixels = width * height
    if total_pixels > DEFAULT_MAX_PIXELS:
        msg = (
            f"Image total pixels ({total_pixels:,}) exceeds maximum limit "
            f"({DEFAULT_MAX_PIXELS:,}): {valid_path}"
        )
        raise InputError(msg)

    raw_depth = meta_dict.get("depth", "")
    bit_depth = int(raw_depth) if raw_depth.isdigit() else None

    # Color & alpha channels
    colorspace = meta_dict.get("colorspace", "Unknown")
    channels = meta_dict.get("channels", "").lower()
    opaque_str = meta_dict.get("opaque", "True").lower()
    is_opaque = opaque_str == "true"
    has_alpha = "a" in channels or not is_opaque

    # Resolution
    x_res = meta_dict.get("x_res", "")
    y_res = meta_dict.get("y_res", "")
    resolution = f"{x_res} × {y_res} dpi" if (x_res and y_res and x_res != "0") else None

    # Profiles & EXIF
    profiles = meta_dict.get("profiles", "").lower()
    icc_name = meta_dict.get("icc_name", "").strip()
    has_icc = "icc" in profiles or bool(icc_name)
    icc_profile = icc_name if icc_name else ("Present" if has_icc else None)

    exif_blob = "\n".join(exif_lines)
    has_exif = "exif" in profiles or bool(exif_lines)
    has_gps = "exif:gps" in exif_blob.lower()

    file_size = valid_path.stat().st_size

    return ImageMetadata(
        file=valid_path.name,
        format=meta_dict.get("format", magic_fmt.upper()),
        width=width,
        height=height,
        raw_width=raw_width,
        raw_height=raw_height,
        size_bytes=file_size,
        size_formatted=_format_size(file_size),
        colorspace=colorspace,
        has_alpha=has_alpha,
        is_opaque=is_opaque,
        bit_depth=bit_depth,
        frame_count=frame_count,
        orientation=orientation,
        resolution=resolution,
        icc_profile=icc_profile,
        has_exif=has_exif,
        has_gps=has_gps,
    )


# =====================================================================
# Image Operations
# =====================================================================


def image_metadata(
    input_path: str,
    as_json: bool = False,
    verbose: bool = False,
    out=None,
) -> int:
    """Inspect and display image metadata (read-only)."""
    if out is None:
        out = sys.stdout
    meta = inspect_image(Path(input_path))

    if as_json:
        data = asdict(meta)
        out.write(json.dumps(data, indent=2) + "\n")
        return 0

    lines = [
        f"File: {meta.file}",
        f"Format: {meta.format}",
        f"Dimensions: {meta.width} × {meta.height}",
        f"Size: {meta.size_formatted} ({meta.size_bytes} bytes)",
        f"Colorspace: {meta.colorspace}",
        f"Alpha: {'Yes' if meta.has_alpha else 'No'}",
    ]
    if meta.bit_depth is not None:
        lines.append(f"Bit depth: {meta.bit_depth}-bit")
    lines.append(f"Frames: {meta.frame_count}")
    lines.append(f"Orientation: {meta.orientation}")
    if meta.resolution:
        lines.append(f"Resolution: {meta.resolution}")
    lines.append(f"ICC profile: {meta.icc_profile or 'Absent'}")
    lines.append(f"EXIF: {'Present' if meta.has_exif else 'Absent'}")

    out.write("\n".join(lines) + "\n")
    return 0


def image_convert(
    input_path: str,
    fmt: str | None = None,
    output: str | None = None,
    quality: int | None = None,
    background: str | None = None,
    frame: int | None = None,
    keep_metadata: bool = False,
    dry_run: bool = False,
    as_json: bool = False,
    verbose: bool = False,
    out=None,
) -> int:
    """Convert an image from one format to another safely."""
    if out is None:
        out = sys.stdout
    source = validate_input_path(input_path)
    metadata = inspect_image(source, frame=frame)
    backend = get_backend()

    # Determine target format
    target_format: str
    supported_list = ", ".join(sorted(set(CANONICAL_FORMATS.keys())))
    if fmt is not None:
        norm_fmt = fmt.lower().strip()
        if norm_fmt not in FORMAT_EXTENSIONS:
            raise UsageError(f"Unsupported format '{fmt}'. Supported formats: {supported_list}")
        target_format = CANONICAL_FORMATS[norm_fmt]
    elif output is not None:
        ext = Path(output).suffix.lower().lstrip(".")
        if ext not in FORMAT_EXTENSIONS:
            raise UsageError(
                f"Cannot infer format from output extension '{Path(output).suffix}'. "
                f"Specify --format explicitly. Supported formats: {supported_list}"
            )
        target_format = CANONICAL_FORMATS[ext]
    else:
        raise UsageError(
            "Target format must be specified via --format or inferred from --output extension."
        )

    target_ext = FORMAT_EXTENSIONS[target_format]

    # Validate destination
    dest = resolve_output_destination(
        source,
        output,
        lambda: get_default_convert_output(source, target_ext),
        expected_extension=target_ext,
        is_convert=True,
    )

    # Frame validation for multi-frame images
    if metadata.frame_count > 1 and frame is None:
        msg = (
            f"Image '{source.name}' has {metadata.frame_count} frames/pages. "
            "Converting multi-frame images without specifying a frame would cause data loss. "
            f"Specify --frame <index> (0 to {metadata.frame_count - 1}) to extract a frame."
        )
        raise UsageError(msg)

    # Transparency handling when converting to non-alpha or restricted-alpha formats
    flatten_required = False
    flatten_bg = "white"

    if target_format in ("jpeg", "bmp"):
        fmt_name = target_format.upper()
        if not metadata.is_opaque:
            if background is None:
                msg = (
                    f"Image '{source.name}' contains transparency, but target format ({fmt_name}) "
                    "does not support alpha. Specify --background <color> (e.g. "
                    "--background white) to flatten transparency, or convert to a format "
                    "supporting alpha (PNG, WebP)."
                )
                raise UsageError(msg)
            flatten_required = True
            flatten_bg = validate_color_string(background)
        else:
            # Opaque image can be flattened safely to white background without data loss
            flatten_required = True
            flatten_bg = validate_color_string(background) if background else "white"

    elif target_format == "gif":
        if not metadata.is_opaque:
            if check_partial_alpha(source, backend, frame=frame):
                if background is None:
                    msg = (
                        f"Image '{source.name}' contains partial (semi-transparent) alpha, "
                        "which GIF cannot represent without data loss. "
                        "Specify --background <color> (e.g. --background white) to flatten "
                        "transparency, or convert to a format supporting full alpha (PNG, WebP)."
                    )
                    raise UsageError(msg)
                flatten_required = True
                flatten_bg = validate_color_string(background)
            elif background is not None:
                flatten_required = True
                flatten_bg = validate_color_string(background)
        elif background is not None:
            flatten_required = True
            flatten_bg = validate_color_string(background)

    if background is not None and not flatten_required:
        flatten_required = True
        flatten_bg = validate_color_string(background)

    # Quality validation - only supported on lossy formats (JPEG, WebP)
    if quality is not None:
        if quality < 1 or quality > 100:
            raise UsageError(f"Quality must be between 1 and 100: {quality}")
        if target_format not in ("jpeg", "webp"):
            msg = (
                f"Quality option (--quality) cannot be used with {target_format.upper()} "
                "(only supported for JPEG and WebP)."
            )
            raise UsageError(msg)

    if dry_run:
        msg = f"[dry-run] Would convert '{source.name}' to {target_format.upper()} at: {dest}"
        if as_json:
            payload = {
                "dry_run": True,
                "input": str(source),
                "destination": str(dest),
                "format": target_format,
            }
            out.write(json.dumps(payload, indent=2) + "\n")
        else:
            out.write(f"{msg}\n")
        return 0

    # Build transformation command with auto-orient and orientation normalization
    input_arg = f"{source}[{frame}]" if frame is not None else str(source)
    cmd = [*backend.convert_cmd, *BACKEND_LIMIT_ARGS, "--", input_arg, "-auto-orient"]

    if flatten_required:
        cmd.extend(["+repage", "-background", flatten_bg, "-flatten"])

    if quality is not None and target_format in ("jpeg", "webp"):
        cmd.extend(["-quality", str(quality)])

    cmd.extend(["-orient", "undefined"])
    if not keep_metadata:
        cmd.append("-strip")

    exp_dims = (metadata.width, metadata.height)

    while True:
        try:
            with atomic_output(source, "convert", output=dest, dry_run=False) as paths:
                temp_file = paths.temporary
                if temp_file is None:
                    raise OutputError("Staging temporary file could not be created.")

                exec_cmd = [*cmd, str(temp_file)]
                res = run_process(exec_cmd, timeout=DEFAULT_PROCESS_TIMEOUT)
                if res.returncode != 0:
                    raise ProcessError(f"Image conversion failed with exit code {res.returncode}.")

                _verify_staging_output(temp_file, target_format, expected_dimensions=exp_dims)
            break
        except FileExistsError:
            if output is not None:
                raise OutputError(f"Output already exists: {dest}") from None
            dest = get_default_convert_output(source, target_ext)

    if as_json:
        payload = {
            "input": str(source),
            "output": str(dest),
            "format": target_format,
            "size_bytes": dest.stat().st_size,
        }
        out.write(json.dumps(payload, indent=2) + "\n")
    else:
        out.write(f"Converted: {source.name} -> {dest.name} ({target_format.upper()})\n")

    return 0


def image_compress(
    input_path: str,
    quality: int | None = None,
    output: str | None = None,
    keep_metadata: bool = False,
    dry_run: bool = False,
    as_json: bool = False,
    verbose: bool = False,
    out=None,
) -> int:
    """Compress an image safely, reporting before/after sizes accurately."""
    if out is None:
        out = sys.stdout
    source = validate_input_path(input_path)
    metadata = inspect_image(source)
    backend = get_backend()

    source_fmt = CANONICAL_FORMATS[detect_magic_format(source)]
    source_ext = FORMAT_EXTENSIONS[source_fmt]

    # Enforce output extension matches source format
    dest = resolve_output_destination(
        source,
        output,
        lambda: get_default_operation_output(source, "compressed"),
        expected_extension=source_ext,
    )

    if quality is not None:
        if quality < 1 or quality > 100:
            raise UsageError(f"Quality must be between 1 and 100: {quality}")
        if source_fmt not in ("jpeg", "webp"):
            msg = (
                f"Quality option (--quality) cannot be used with {metadata.format.upper()} "
                "(only supported for JPEG and WebP)."
            )
            raise UsageError(msg)

    # Multi-frame compression policy
    if metadata.frame_count > 1:
        raise UsageError(
            f"Image '{source.name}' has {metadata.frame_count} frames. "
            "Compressing multi-frame animations without frame selection is not supported."
        )

    if dry_run:
        msg = f"[dry-run] Would compress '{source.name}' into: {dest}"
        if as_json:
            payload = {
                "dry_run": True,
                "input": str(source),
                "destination": str(dest),
            }
            out.write(json.dumps(payload, indent=2) + "\n")
        else:
            out.write(f"{msg}\n")
        return 0

    cmd = [*backend.convert_cmd, *BACKEND_LIMIT_ARGS, "--", str(source), "-auto-orient"]

    if source_fmt == "jpeg":
        q = quality if quality is not None else 85
        cmd.extend(["-quality", str(q)])
    elif source_fmt == "webp":
        q = quality if quality is not None else 75
        cmd.extend(["-quality", str(q)])
    elif source_fmt == "png":
        # Lossless PNG compression with level 9 and adaptive filter
        cmd.extend(["-quality", "95"])

    cmd.extend(["-orient", "undefined"])
    if not keep_metadata:
        cmd.append("-strip")

    before_size = source.stat().st_size

    while True:
        try:
            with atomic_output(source, "compressed", output=dest, dry_run=False) as paths:
                temp_file = paths.temporary
                if temp_file is None:
                    raise OutputError("Staging temporary file could not be created.")

                exec_cmd = [*cmd, str(temp_file)]
                res = run_process(exec_cmd, timeout=DEFAULT_PROCESS_TIMEOUT)
                if res.returncode != 0:
                    raise ProcessError(f"Image compression failed with exit code {res.returncode}.")

                _verify_staging_output(
                    temp_file,
                    source_fmt,
                    expected_dimensions=(metadata.width, metadata.height),
                )
            break
        except FileExistsError:
            if output is not None:
                raise OutputError(f"Output already exists: {dest}") from None
            dest = get_default_operation_output(source, "compressed")

    after_size = dest.stat().st_size

    if after_size < before_size:
        reduction_pct = ((before_size - after_size) / before_size) * 100.0
        reduced = True
    else:
        increase_pct = (
            ((after_size - before_size) / before_size) * 100.0 if before_size > 0 else 0.0
        )
        reduction_pct = -increase_pct
        reduced = False

    if as_json:
        payload = {
            "input": str(source),
            "output": str(dest),
            "before_bytes": before_size,
            "after_bytes": after_size,
            "reduction_percent": round(reduction_pct, 2),
            "reduced": reduced,
        }
        out.write(json.dumps(payload, indent=2) + "\n")
    else:
        lines = [
            f"Input:  {source.name}",
            f"Output: {dest.name}",
            f"Before: {_format_size(before_size)} ({before_size} bytes)",
            f"After:  {_format_size(after_size)} ({after_size} bytes)",
        ]
        if reduced:
            lines.append(f"Reduction: {reduction_pct:.1f}%")
        else:
            lines.append(f"Increase: {abs(reduction_pct):.1f}% (no size reduction achieved)")
        out.write("\n".join(lines) + "\n")

    return 0


def image_resize(
    input_path: str,
    width: int | None = None,
    height: int | None = None,
    fit: str = "contain",
    allow_upscale: bool = False,
    output: str | None = None,
    keep_metadata: bool = False,
    dry_run: bool = False,
    as_json: bool = False,
    verbose: bool = False,
    out=None,
) -> int:
    """Resize an image preserving aspect ratio or fitting boundaries safely."""
    if out is None:
        out = sys.stdout
    source = validate_input_path(input_path)
    metadata = inspect_image(source)
    backend = get_backend()

    source_fmt = CANONICAL_FORMATS[detect_magic_format(source)]
    source_ext = FORMAT_EXTENSIONS[source_fmt]

    # Enforce multi-frame policy: reject multi-frame animations
    if metadata.frame_count > 1:
        msg = (
            f"Image '{source.name}' has {metadata.frame_count} frames/pages. "
            "Resizing multi-frame/animated images is not supported to prevent data loss."
        )
        raise UsageError(msg)

    if width is None and height is None:
        raise UsageError("At least one of --width or --height must be specified.")

    if width is not None and width <= 0:
        raise UsageError(f"Width must be greater than zero: {width}")

    if height is not None and height <= 0:
        raise UsageError(f"Height must be greater than zero: {height}")

    if width is not None and width > DEFAULT_MAX_DIMENSION:
        raise UsageError(f"Requested width ({width}px) exceeds limit ({DEFAULT_MAX_DIMENSION}px).")

    if height is not None and height > DEFAULT_MAX_DIMENSION:
        raise UsageError(
            f"Requested height ({height}px) exceeds limit ({DEFAULT_MAX_DIMENSION}px)."
        )

    valid_fits = ("contain", "cover", "stretch")
    norm_fit = fit.lower().strip()
    if norm_fit not in valid_fits:
        raise UsageError(f"Invalid fit mode '{fit}'. Valid choices: {', '.join(valid_fits)}.")

    # All calculations use normalized (post-auto-orient) dimensions
    orig_w = metadata.width
    orig_h = metadata.height

    # Calculate target dimensions and check upscaling
    target_w: int
    target_h: int

    if width is not None and height is None:
        target_w = width
        target_h = max(1, round(orig_h * (width / orig_w)))
        if width > orig_w and not allow_upscale:
            raise UsageError(
                f"Target width ({width}px) exceeds original width ({orig_w}px). "
                "Specify --allow-upscale to permit upscaling."
            )
    elif height is not None and width is None:
        target_h = height
        target_w = max(1, round(orig_w * (height / orig_h)))
        if height > orig_h and not allow_upscale:
            raise UsageError(
                f"Target height ({height}px) exceeds original height ({orig_h}px). "
                "Specify --allow-upscale to permit upscaling."
            )
    else:
        assert width is not None and height is not None
        target_w = width
        target_h = height
        if norm_fit == "contain":
            scale = min(width / orig_w, height / orig_h)
            if scale > 1.0 and not allow_upscale:
                msg = (
                    f"Target dimensions ({width}x{height}) would upscale image from "
                    f"{orig_w}x{orig_h}. Specify --allow-upscale to permit upscaling."
                )
                raise UsageError(msg)
            target_w = max(1, round(orig_w * scale))
            target_h = max(1, round(orig_h * scale))
        elif norm_fit == "cover":
            scale = max(width / orig_w, height / orig_h)
            if scale > 1.0 and not allow_upscale:
                msg = (
                    f"Target dimensions ({width}x{height}) would upscale image from "
                    f"{orig_w}x{orig_h}. Specify --allow-upscale to permit upscaling."
                )
                raise UsageError(msg)
        elif norm_fit == "stretch":
            if (width > orig_w or height > orig_h) and not allow_upscale:
                msg = (
                    f"Target dimensions ({width}x{height}) would upscale image from "
                    f"{orig_w}x{orig_h}. Specify --allow-upscale to permit upscaling."
                )
                raise UsageError(msg)

    if (target_w * target_h) > DEFAULT_MAX_PIXELS:
        msg = (
            f"Resulting pixels ({target_w * target_h:,}) exceed maximum limit "
            f"({DEFAULT_MAX_PIXELS:,})."
        )
        raise UsageError(msg)

    dest = resolve_output_destination(
        source,
        output,
        lambda: get_default_operation_output(source, "resized"),
        expected_extension=source_ext,
    )

    if dry_run:
        msg = (
            f"[dry-run] Would resize '{source.name}' ({orig_w}x{orig_h}) "
            f"to ({target_w}x{target_h}) at: {dest}"
        )
        if as_json:
            payload = {
                "dry_run": True,
                "input": str(source),
                "destination": str(dest),
                "original_dimensions": [orig_w, orig_h],
                "target_dimensions": [target_w, target_h],
                "fit": norm_fit,
            }
            out.write(json.dumps(payload, indent=2) + "\n")
        else:
            out.write(f"{msg}\n")
        return 0

    cmd = [*backend.convert_cmd, *BACKEND_LIMIT_ARGS, "--", str(source), "-auto-orient"]

    if width is not None and height is None:
        cmd.extend(["-resize", f"{width}x"])
    elif height is not None and width is None:
        cmd.extend(["-resize", f"x{height}"])
    else:
        assert width is not None and height is not None
        if norm_fit == "contain":
            cmd.extend(["-resize", f"{width}x{height}"])
        elif norm_fit == "stretch":
            cmd.extend(["-resize", f"{width}x{height}!"])
        elif norm_fit == "cover":
            cmd.extend(
                [
                    "-resize",
                    f"{width}x{height}^",
                    "-gravity",
                    "center",
                    "-extent",
                    f"{width}x{height}",
                ]
            )

    cmd.extend(["-orient", "undefined"])
    if not keep_metadata:
        cmd.append("-strip")

    while True:
        try:
            with atomic_output(source, "resized", output=dest, dry_run=False) as paths:
                temp_file = paths.temporary
                if temp_file is None:
                    raise OutputError("Staging temporary file could not be created.")

                exec_cmd = [*cmd, str(temp_file)]
                res = run_process(exec_cmd, timeout=DEFAULT_PROCESS_TIMEOUT)
                if res.returncode != 0:
                    raise ProcessError(f"Image resize failed with exit code {res.returncode}.")

                _verify_staging_output(
                    temp_file, source_fmt, expected_dimensions=(target_w, target_h)
                )
            break
        except FileExistsError:
            if output is not None:
                raise OutputError(f"Output already exists: {dest}") from None
            dest = get_default_operation_output(source, "resized")

    new_meta = inspect_image(dest)

    if as_json:
        payload = {
            "input": str(source),
            "output": str(dest),
            "original_width": orig_w,
            "original_height": orig_h,
            "width": new_meta.width,
            "height": new_meta.height,
        }
        out.write(json.dumps(payload, indent=2) + "\n")
    else:
        dims_str = f"({orig_w} × {orig_h}) -> {dest.name} ({new_meta.width} × {new_meta.height})"
        out.write(f"Resized: {source.name} {dims_str}\n")

    return 0


def image_crop(
    input_path: str,
    x: int,
    y: int,
    width: int,
    height: int,
    output: str | None = None,
    keep_metadata: bool = False,
    dry_run: bool = False,
    as_json: bool = False,
    verbose: bool = False,
    out=None,
) -> int:
    """Crop a sub-region of an image safely."""
    if out is None:
        out = sys.stdout
    source = validate_input_path(input_path)
    metadata = inspect_image(source)
    backend = get_backend()

    source_fmt = CANONICAL_FORMATS[detect_magic_format(source)]
    source_ext = FORMAT_EXTENSIONS[source_fmt]

    # Enforce multi-frame policy: reject multi-frame animations
    if metadata.frame_count > 1:
        msg = (
            f"Image '{source.name}' has {metadata.frame_count} frames/pages. "
            "Cropping multi-frame/animated images is not supported to prevent data loss."
        )
        raise UsageError(msg)

    if x < 0:
        raise UsageError(f"Crop X coordinate must be non-negative: {x}")
    if y < 0:
        raise UsageError(f"Crop Y coordinate must be non-negative: {y}")
    if width <= 0:
        raise UsageError(f"Crop width must be greater than zero: {width}")
    if height <= 0:
        raise UsageError(f"Crop height must be greater than zero: {height}")

    # Validate against normalized (post-auto-orient) dimensions
    orig_w = metadata.width
    orig_h = metadata.height

    if x + width > orig_w or y + height > orig_h:
        msg = (
            f"Crop rectangle (x={x}, y={y}, w={width}, h={height}) extends "
            f"beyond image dimensions ({orig_w} × {orig_h})."
        )
        raise UsageError(msg)

    dest = resolve_output_destination(
        source,
        output,
        lambda: get_default_operation_output(source, "cropped"),
        expected_extension=source_ext,
    )

    if dry_run:
        msg = f"[dry-run] Would crop '{source.name}' to {width}x{height}+{x}+{y} into: {dest}"
        if as_json:
            payload = {
                "dry_run": True,
                "input": str(source),
                "destination": str(dest),
                "crop_box": {"x": x, "y": y, "width": width, "height": height},
            }
            out.write(json.dumps(payload, indent=2) + "\n")
        else:
            out.write(f"{msg}\n")
        return 0

    cmd = [
        *backend.convert_cmd,
        *BACKEND_LIMIT_ARGS,
        "--",
        str(source),
        "-auto-orient",
        "-crop",
        f"{width}x{height}+{x}+{y}",
        "+repage",
        "-orient",
        "undefined",
    ]
    if not keep_metadata:
        cmd.append("-strip")

    while True:
        try:
            with atomic_output(source, "cropped", output=dest, dry_run=False) as paths:
                temp_file = paths.temporary
                if temp_file is None:
                    raise OutputError("Staging temporary file could not be created.")

                exec_cmd = [*cmd, str(temp_file)]
                res = run_process(exec_cmd, timeout=DEFAULT_PROCESS_TIMEOUT)
                if res.returncode != 0:
                    raise ProcessError(f"Image crop failed with exit code {res.returncode}.")

                _verify_staging_output(temp_file, source_fmt, expected_dimensions=(width, height))
            break
        except FileExistsError:
            if output is not None:
                raise OutputError(f"Output already exists: {dest}") from None
            dest = get_default_operation_output(source, "cropped")

    if as_json:
        payload = {
            "input": str(source),
            "output": str(dest),
            "width": width,
            "height": height,
            "x": x,
            "y": y,
        }
        out.write(json.dumps(payload, indent=2) + "\n")
    else:
        out.write(f"Cropped: {source.name} -> {dest.name} ({width} × {height} at +{x}+{y})\n")

    return 0


def image_rotate(
    input_path: str,
    angle: float,
    background: str | None = None,
    output: str | None = None,
    keep_metadata: bool = False,
    dry_run: bool = False,
    as_json: bool = False,
    verbose: bool = False,
    out=None,
) -> int:
    """Rotate an image clockwise by an angle in degrees."""
    if out is None:
        out = sys.stdout
    source = validate_input_path(input_path)
    metadata = inspect_image(source)
    backend = get_backend()

    source_fmt = CANONICAL_FORMATS[detect_magic_format(source)]
    source_ext = FORMAT_EXTENSIONS[source_fmt]

    # Enforce multi-frame policy: reject multi-frame animations
    if metadata.frame_count > 1:
        msg = (
            f"Image '{source.name}' has {metadata.frame_count} frames/pages. "
            "Rotating multi-frame/animated images is not supported to prevent data loss."
        )
        raise UsageError(msg)

    # Normalize angle into [0, 360)
    norm_angle = angle % 360.0
    if norm_angle < 0:
        norm_angle += 360.0

    dest = resolve_output_destination(
        source,
        output,
        lambda: get_default_operation_output(source, "rotated"),
        expected_extension=source_ext,
    )

    # Determine background color for non-orthogonal rotations
    is_orthogonal = (norm_angle % 90.0) == 0.0
    bg_color = None
    if background is not None:
        bg_color = validate_color_string(background)
    elif not is_orthogonal:
        # If output or source is JPEG, default to white background
        if metadata.format.upper() == "JPEG" or dest.suffix.lower() in (".jpg", ".jpeg"):
            bg_color = "white"
        else:
            bg_color = "none"

    if dry_run:
        msg = f"[dry-run] Would rotate '{source.name}' by {angle}° clockwise into: {dest}"
        if as_json:
            payload = {
                "dry_run": True,
                "input": str(source),
                "destination": str(dest),
                "angle": angle,
                "background": bg_color,
            }
            out.write(json.dumps(payload, indent=2) + "\n")
        else:
            out.write(f"{msg}\n")
        return 0

    cmd = [
        *backend.convert_cmd,
        *BACKEND_LIMIT_ARGS,
        "--",
        str(source),
        "-auto-orient",
    ]

    if bg_color is not None:
        cmd.extend(["-background", bg_color])

    cmd.extend(["-rotate", str(angle), "-orient", "undefined"])

    if not keep_metadata:
        cmd.append("-strip")

    exp_dims = None
    if is_orthogonal:
        if norm_angle in (90.0, 270.0):
            exp_dims = (metadata.height, metadata.width)
        else:
            exp_dims = (metadata.width, metadata.height)

    while True:
        try:
            with atomic_output(source, "rotated", output=dest, dry_run=False) as paths:
                temp_file = paths.temporary
                if temp_file is None:
                    raise OutputError("Staging temporary file could not be created.")

                exec_cmd = [*cmd, str(temp_file)]
                res = run_process(exec_cmd, timeout=DEFAULT_PROCESS_TIMEOUT)
                if res.returncode != 0:
                    raise ProcessError(f"Image rotate failed with exit code {res.returncode}.")

                _verify_staging_output(temp_file, source_fmt, expected_dimensions=exp_dims)
            break
        except FileExistsError:
            if output is not None:
                raise OutputError(f"Output already exists: {dest}") from None
            dest = get_default_operation_output(source, "rotated")

    new_meta = inspect_image(dest)

    if as_json:
        payload = {
            "input": str(source),
            "output": str(dest),
            "angle": angle,
            "width": new_meta.width,
            "height": new_meta.height,
        }
        out.write(json.dumps(payload, indent=2) + "\n")
    else:
        out_dims = f"({angle}° clockwise, {new_meta.width} × {new_meta.height})"
        out.write(f"Rotated: {source.name} -> {dest.name} {out_dims}\n")

    return 0
