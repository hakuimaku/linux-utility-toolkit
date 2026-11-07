"""Shared media service for FFmpeg/FFprobe backend, metadata probe, and process execution."""

import json
import math
import os
import re
import stat
import sys
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path

from lut.core.dependencies import installation_hint, require_executable
from lut.core.errors import (
    DependencyError,
    InputError,
    OutputError,
    ProcessError,
    UsageError,
)
from lut.core.process import ProcessResult, run_process

# =====================================================================
# Constants & Safety Limits
# =====================================================================

DEFAULT_MAX_INPUT_SIZE = 10 * 1024 * 1024 * 1024  # 10 GB limit for media files
DEFAULT_PROCESS_TIMEOUT = 600.0  # 10 minutes timeout for media operations

SUPPORTED_VIDEO_FORMATS = ("mp4", "mkv", "webm", "avi", "mov")
SUPPORTED_AUDIO_FORMATS = ("mp3", "wav", "flac", "ogg", "opus")

VIDEO_EXTENSIONS = {
    "mp4": ".mp4",
    "mkv": ".mkv",
    "webm": ".webm",
    "avi": ".avi",
    "mov": ".mov",
}

AUDIO_EXTENSIONS = {
    "mp3": ".mp3",
    "wav": ".wav",
    "flac": ".flac",
    "ogg": ".ogg",
    "opus": ".opus",
}

AUDIO_CODEC_MAP = {
    "mp3": "libmp3lame",
    "wav": "pcm_s16le",
    "flac": "flac",
    "ogg": "libvorbis",
    "opus": "libopus",
}

VIDEO_CODEC_MAP = {
    "h264": "libx264",
    "x264": "libx264",
    "hevc": "libx265",
    "h265": "libx265",
    "x265": "libx265",
    "vp8": "libvpx",
    "vp9": "libvpx-vp9",
    "av1": "libsvtav1",
    "copy": "copy",
}

COMPRESSION_PRESETS = (
    "ultrafast",
    "superfast",
    "veryfast",
    "faster",
    "fast",
    "medium",
    "slow",
    "slower",
    "veryslow",
)


@dataclass
class VideoStreamInfo:
    """Information about a video stream."""

    index: int
    codec_name: str
    codec_long_name: str = ""
    width: int = 0
    height: int = 0
    fps: float = 0.0
    pixel_format: str = ""
    aspect_ratio: str = ""
    bit_rate: int | None = None
    duration: float | None = None


@dataclass
class AudioStreamInfo:
    """Information about an audio stream."""

    index: int
    codec_name: str
    codec_long_name: str = ""
    sample_rate: int = 0
    channels: int = 0
    channel_layout: str = ""
    bit_rate: int | None = None
    duration: float | None = None


@dataclass
class SubtitleStreamInfo:
    """Information about a subtitle stream."""

    index: int
    codec_name: str
    codec_long_name: str = ""
    language: str = ""


@dataclass
class MediaInfo:
    """Complete metadata representation for a media container and its streams."""

    file: str
    format_name: str
    format_long_name: str = ""
    duration: float | None = None
    duration_formatted: str = ""
    size_bytes: int = 0
    size_formatted: str = ""
    bit_rate: int | None = None
    video_streams: list[VideoStreamInfo] = field(default_factory=list)
    audio_streams: list[AudioStreamInfo] = field(default_factory=list)
    subtitle_streams: list[SubtitleStreamInfo] = field(default_factory=list)
    tags: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Convert to dictionary representation for JSON serialization."""
        return asdict(self)


@dataclass
class BackendInfo:
    """Information about detected FFmpeg and FFprobe executables."""

    ffmpeg_path: Path
    ffprobe_path: Path
    raw_version: str


_CACHED_BACKEND: BackendInfo | None = None


# =====================================================================
# Backend Discovery & Management
# =====================================================================


def _detect_backend() -> BackendInfo:
    """Locate FFmpeg and FFprobe on PATH and verify availability."""
    packages = {
        "arch": "ffmpeg",
        "debian": "ffmpeg",
        "ubuntu": "ffmpeg",
        "fedora": "ffmpeg",
    }
    hint = installation_hint("ffmpeg", packages)

    try:
        ffmpeg_path = require_executable("ffmpeg", packages=packages, version_args=("-version",))
    except DependencyError:
        raise DependencyError(f"Missing dependency: FFmpeg. {hint}") from None

    try:
        ffprobe_path = require_executable("ffprobe", packages=packages, version_args=("-version",))
    except DependencyError:
        raise DependencyError(f"Missing dependency: FFprobe. {hint}") from None

    try:
        res = run_process([str(ffmpeg_path), "-version"], timeout=5)
        banner = res.stdout or res.stderr
        m = re.search(r"ffmpeg\s+version\s+([^\s]+)", banner)
        version_str = m.group(1) if m else "unknown"
    except Exception:
        version_str = "unknown"

    return BackendInfo(
        ffmpeg_path=ffmpeg_path,
        ffprobe_path=ffprobe_path,
        raw_version=version_str,
    )


def get_backend() -> BackendInfo:
    """Get the cached FFmpeg/FFprobe backend info or detect it."""
    global _CACHED_BACKEND
    if _CACHED_BACKEND is None:
        _CACHED_BACKEND = _detect_backend()
    return _CACHED_BACKEND


def is_backend_available() -> bool:
    """Check if both FFmpeg and FFprobe are available without raising."""
    try:
        get_backend()
        return True
    except DependencyError:
        return False


is_media_backend_available = is_backend_available


def reset_backend_cache() -> None:
    """Reset cached backend for testing."""
    global _CACHED_BACKEND
    _CACHED_BACKEND = None


# =====================================================================
# Formatting Helpers
# =====================================================================


def format_size(size_bytes: int) -> str:
    """Format bytes into human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    num = float(size_bytes)
    for unit in ("KB", "MB", "GB", "TB"):
        num /= 1024.0
        if num < 1024:
            return f"{num:.1f} {unit}"
    return f"{num:.1f} PB"


def format_duration(seconds: float | None) -> str:
    """Format duration in seconds to HH:MM:SS.mmm or empty string if None."""
    if seconds is None or not math.isfinite(seconds) or seconds < 0:
        return ""
    total_seconds = int(seconds)
    millis = int(round((seconds - total_seconds) * 1000))
    if millis >= 1000:
        total_seconds += 1
        millis = 0
    h = total_seconds // 3600
    m = (total_seconds % 3600) // 60
    s = total_seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}.{millis:03d}"


def parse_fps(rate_str: str) -> float:
    """Parse frame rate string like '30/1' or '29.97' into float."""
    if not rate_str or rate_str == "0/0":
        return 0.0
    if "/" in rate_str:
        parts = rate_str.split("/", 1)
        try:
            denom = float(parts[1])
            if denom != 0:
                return float(parts[0]) / denom
        except (ValueError, ZeroDivisionError):
            return 0.0
    else:
        try:
            return float(rate_str)
        except ValueError:
            return 0.0
    return 0.0


# =====================================================================
# Timestamp Parsing & Validation
# =====================================================================


def parse_timestamp(val: str | float | int | None) -> float:
    """Parse timestamp into seconds as a float.

    Supports:
      - Seconds: "10", "12.5"
      - MM:SS: "01:30", "1:30"
      - HH:MM:SS: "01:02:03", "0:01:30", "01:02:03.500"
    """
    if val is None:
        raise UsageError("Timestamp cannot be empty.")
    if isinstance(val, (int, float)):
        if isinstance(val, bool) or not math.isfinite(val) or val < 0:
            raise UsageError(f"Timestamp must be a finite, nonnegative number: {val}")
        return float(val)

    val_str = str(val).strip()
    if not val_str:
        raise UsageError("Timestamp cannot be empty.")

    parts = val_str.split(":")
    if len(parts) == 1:
        try:
            sec = float(parts[0])
        except ValueError:
            raise UsageError(
                f"Invalid timestamp format: {val_str!r}. Expected seconds, MM:SS, or HH:MM:SS."
            ) from None
        if not math.isfinite(sec) or sec < 0:
            raise UsageError(f"Timestamp must be a finite, nonnegative number: {val_str}")
        return sec

    if len(parts) == 2:
        try:
            m = int(parts[0])
            s = float(parts[1])
        except ValueError:
            raise UsageError(f"Invalid MM:SS timestamp: {val_str!r}") from None
        if m < 0 or s < 0 or s >= 60:
            raise UsageError(
                f"Invalid MM:SS timestamp (minutes >= 0, 0 <= seconds < 60): {val_str!r}"
            )
        return m * 60.0 + s

    if len(parts) == 3:
        try:
            h = int(parts[0])
            m = int(parts[1])
            s = float(parts[2])
        except ValueError:
            raise UsageError(f"Invalid HH:MM:SS timestamp: {val_str!r}") from None
        if h < 0 or m < 0 or m >= 60 or s < 0 or s >= 60:
            msg = (
                f"Invalid HH:MM:SS timestamp "
                f"(hours >= 0, 0 <= minutes < 60, 0 <= seconds < 60): {val_str!r}"
            )
            raise UsageError(msg)
        return h * 3600.0 + m * 60.0 + s

    raise UsageError(
        f"Invalid timestamp format: {val_str!r}. Expected seconds, MM:SS, or HH:MM:SS."
    )


# =====================================================================
# Path Safety Checks
# =====================================================================


def _validate_no_ancestor_symlinks(
    input_arg: str | os.PathLike[str],
    is_output: bool = False,
) -> None:
    """Reject inputs or outputs containing any symlink in ancestor components or leaf."""
    raw_path = Path(input_arg)
    err_cls = OutputError if is_output else InputError
    label = "output" if is_output else "input"

    if os.path.islink(raw_path):
        raise err_cls(f"Symlinks are not supported for media {label}: {raw_path}")

    if raw_path.is_absolute():
        current = Path(raw_path.parts[0])
        for part in raw_path.parts[1:]:
            current = current / part
            if os.path.islink(current):
                msg = (
                    f"Symlinks are not supported for media {label} "
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
                    f"Symlinks are not supported for media {label} "
                    f"(ancestor symlink in path): {current}"
                )
                raise err_cls(msg)


def validate_media_input(path_str: str | os.PathLike[str]) -> Path:
    """Validate that the input path is an existing, regular media file without symlinks."""
    path = Path(path_str)
    if not path_str or "\0" in str(path_str):
        raise UsageError("Input path must be nonempty and contain no NUL characters.")

    _validate_no_ancestor_symlinks(path_str, is_output=False)

    if os.path.islink(path):
        raise InputError(f"Symlinks are not supported for media input: {path}")

    if not path.exists():
        raise InputError(f"Input file not found: {path}")

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
        max_str = format_size(DEFAULT_MAX_INPUT_SIZE)
        curr_str = format_size(st.st_size)
        raise InputError(f"Input file size ({curr_str}) exceeds limit ({max_str}): {path}")

    return path.resolve()


def _available_candidate(base_path: Path, ext: str) -> Path:
    """Find a non-colliding candidate path starting at base_path + ext."""
    candidate = base_path.with_name(f"{base_path.name}{ext}")
    number = 2
    while os.path.lexists(candidate):
        candidate = base_path.with_name(f"{base_path.name}_{number}{ext}")
        number += 1
    return candidate


def resolve_media_output(
    source_path: Path,
    output_arg: str | None,
    suffix: str,
    target_ext: str,
    *,
    is_convert: bool = False,
    directory: bool = False,
) -> Path:
    """Resolve planned destination, ensuring non-overwriting guarantees."""
    if not target_ext.startswith(".") and not directory:
        target_ext = "." + target_ext

    if output_arg is not None:
        if not output_arg or "\0" in str(output_arg):
            raise UsageError("Output path must be nonempty and contain no NUL characters.")

        raw_path = Path(output_arg)
        _validate_no_ancestor_symlinks(output_arg, is_output=True)

        if os.path.lexists(raw_path):
            raise OutputError(f"Output already exists: {raw_path}")

        parent = raw_path.parent
        if not parent.exists():
            raise OutputError(f"Output directory does not exist: {parent}")
        if not parent.is_dir():
            raise OutputError(f"Output directory is not a directory: {parent}")

        return raw_path.resolve()

    # Automatic destination planning beside source
    if directory:
        base_name = f"{source_path.stem}_{suffix}"
        candidate = source_path.parent / base_name
        number = 2
        while os.path.lexists(candidate):
            candidate = source_path.parent / f"{base_name}_{number}"
            number += 1
        return candidate

    if is_convert:
        base_path = source_path.parent / source_path.stem
        return _available_candidate(base_path, target_ext)

    base_name = f"{source_path.stem}_{suffix}"
    base_path = source_path.parent / base_name
    return _available_candidate(base_path, target_ext)


# =====================================================================
# FFprobe Inspection
# =====================================================================


def probe_media(path: Path) -> MediaInfo:
    """Inspect media file using FFprobe and return structured MediaInfo."""
    backend = get_backend()
    cmd = [
        str(backend.ffprobe_path),
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-print_format",
        "json",
        str(path),
    ]

    try:
        res = run_process(cmd, timeout=30)
    except Exception as e:
        raise ProcessError(f"FFprobe inspection failed: {e}") from None

    if res.returncode != 0:
        raise ProcessError(f"FFprobe failed with exit code {res.returncode}.")

    try:
        data = json.loads(res.stdout)
    except json.JSONDecodeError:
        raise ProcessError("Failed to parse FFprobe JSON metadata.") from None

    format_data = data.get("format", {})
    streams_data = data.get("streams", [])

    raw_duration = format_data.get("duration")
    duration = float(raw_duration) if raw_duration is not None else None

    raw_size = format_data.get("size")
    size_bytes = int(raw_size) if raw_size is not None else path.stat().st_size

    raw_bitrate = format_data.get("bit_rate")
    bit_rate = int(raw_bitrate) if raw_bitrate is not None else None

    video_streams: list[VideoStreamInfo] = []
    audio_streams: list[AudioStreamInfo] = []
    subtitle_streams: list[SubtitleStreamInfo] = []

    for stream in streams_data:
        codec_type = stream.get("codec_type")
        codec_name = stream.get("codec_name", "")
        codec_long = stream.get("codec_long_name", "")
        idx = int(stream.get("index", 0))

        if codec_type == "video":
            # Exclude attached pictures (cover art)
            disposition = stream.get("disposition", {})
            if disposition.get("attached_pic") == 1:
                continue

            w = int(stream.get("width", 0))
            h = int(stream.get("height", 0))
            fps_str = stream.get("avg_frame_rate", "") or stream.get("r_frame_rate", "")
            fps = parse_fps(fps_str)
            pix_fmt = stream.get("pix_fmt", "")
            aspect = stream.get("display_aspect_ratio", "")
            s_br = stream.get("bit_rate")
            stream_bitrate = int(s_br) if s_br is not None else None
            s_dur = stream.get("duration")
            stream_dur = float(s_dur) if s_dur is not None else None

            video_streams.append(
                VideoStreamInfo(
                    index=idx,
                    codec_name=codec_name,
                    codec_long_name=codec_long,
                    width=w,
                    height=h,
                    fps=fps,
                    pixel_format=pix_fmt,
                    aspect_ratio=aspect,
                    bit_rate=stream_bitrate,
                    duration=stream_dur,
                )
            )

        elif codec_type == "audio":
            sr = int(stream.get("sample_rate", 0))
            channels = int(stream.get("channels", 0))
            ch_layout = stream.get("channel_layout", "")
            s_br = stream.get("bit_rate")
            stream_bitrate = int(s_br) if s_br is not None else None
            s_dur = stream.get("duration")
            stream_dur = float(s_dur) if s_dur is not None else None

            audio_streams.append(
                AudioStreamInfo(
                    index=idx,
                    codec_name=codec_name,
                    codec_long_name=codec_long,
                    sample_rate=sr,
                    channels=channels,
                    channel_layout=ch_layout,
                    bit_rate=stream_bitrate,
                    duration=stream_dur,
                )
            )

        elif codec_type == "subtitle":
            tags = stream.get("tags", {})
            lang = tags.get("language", "")
            subtitle_streams.append(
                SubtitleStreamInfo(
                    index=idx,
                    codec_name=codec_name,
                    codec_long_name=codec_long,
                    language=lang,
                )
            )

    # If container duration was missing, check stream durations
    if duration is None:
        all_durs = [
            s.duration
            for s in (*video_streams, *audio_streams)
            if s.duration is not None and s.duration > 0
        ]
        if all_durs:
            duration = max(all_durs)

    return MediaInfo(
        file=str(path),
        format_name=format_data.get("format_name", ""),
        format_long_name=format_data.get("format_long_name", ""),
        duration=duration,
        duration_formatted=format_duration(duration),
        size_bytes=size_bytes,
        size_formatted=format_size(size_bytes),
        bit_rate=bit_rate,
        video_streams=video_streams,
        audio_streams=audio_streams,
        subtitle_streams=subtitle_streams,
        tags=format_data.get("tags", {}),
    )


# =====================================================================
# Safe FFmpeg Execution & Progress Handling
# =====================================================================


def run_ffmpeg(
    command_args: Sequence[str | Path],
    *,
    total_duration: float | None = None,
    as_json: bool = False,
    timeout: float | None = DEFAULT_PROCESS_TIMEOUT,
    capture_limit: int = 8 * 1024 * 1024,
) -> ProcessResult:
    """Run FFmpeg command safely with progress monitoring and noninteractive defaults.

    -nostdin is always added to prevent reading LUT's standard input.
    Stderr is safely consumed to avoid pipe buffer deadlocks.
    """
    args = [str(arg) for arg in command_args]
    if "-nostdin" not in args:
        # Insert -nostdin immediately after the executable
        args.insert(1, "-nostdin")

    # Progress tracking enabled for interactive terminals when not in JSON mode
    has_duration = total_duration is not None and total_duration > 0
    show_progress = not as_json and sys.stderr.isatty()

    if show_progress and "-progress" not in args:
        # Place -progress pipe:1 before output arguments
        args.extend(["-progress", "pipe:1"])

    line_buffer = ""
    last_sec = 0.0

    def progress_callback(stream: str, chunk: str) -> None:
        nonlocal line_buffer, last_sec
        if not show_progress or stream != "stdout":
            return
        line_buffer += chunk
        lines = line_buffer.split("\n")
        line_buffer = lines[-1]
        for line in lines[:-1]:
            line = line.strip()
            if line.startswith("out_time_us="):
                try:
                    us_val = int(line.split("=", 1)[1])
                    cur_sec = us_val / 1_000_000.0
                    last_sec = cur_sec
                    elapsed_str = format_duration(cur_sec)
                    if has_duration and total_duration:
                        pct = min(100.0, max(0.0, (cur_sec / total_duration) * 100.0))
                        total_str = format_duration(total_duration)
                        sys.stderr.write(f"\rProgress: {pct:5.1f}% [{elapsed_str} / {total_str}]")
                    else:
                        sys.stderr.write(f"\rProgress: elapsed {elapsed_str}")
                    sys.stderr.flush()
                except (ValueError, ZeroDivisionError):
                    pass
            elif line.startswith("progress=end"):
                if has_duration:
                    sys.stderr.write("\rProgress: 100.0%\n")
                else:
                    sys.stderr.write(f"\rProgress: complete ({format_duration(last_sec)})\n")
                sys.stderr.flush()

    try:
        res = run_process(
            args,
            timeout=timeout,
            progress=progress_callback if show_progress else None,
            capture_limit=capture_limit,
        )
    finally:
        if show_progress:
            # Clear or end progress line on stderr
            sys.stderr.write("\r\033[K")
            sys.stderr.flush()

    return res


def verify_staging_media(
    staging_path: Path,
    *,
    expected_type: str | None = None,
    min_size: int = 1,
) -> MediaInfo:
    """Verify that backend output exists, is non-empty, and forms valid media."""
    if not staging_path.exists():
        raise OutputError(f"Backend output was not created: {staging_path}")

    st = staging_path.stat()
    if not stat.S_ISREG(st.st_mode):
        raise OutputError("Backend output is not a regular file.")

    if st.st_size < min_size:
        raise OutputError(f"Backend output is too small ({st.st_size} bytes).")

    try:
        info = probe_media(staging_path)
    except Exception as e:
        raise OutputError(f"Backend output failed media validation: {e}") from None

    if expected_type == "video" and not info.video_streams:
        raise OutputError("Backend output does not contain any video streams.")
    if expected_type == "audio" and not info.audio_streams:
        raise OutputError("Backend output does not contain any audio streams.")

    return info
