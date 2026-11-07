"""Unit tests for shared media service helpers, timestamp parsing, probe, and validation."""

import math
import sys
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest

from lut.core.errors import (
    CancelledError,
    DependencyError,
    InputError,
    OutputError,
    ProcessError,
    UsageError,
)
from lut.core.output import atomic_output
from lut.core.process import ProcessResult
from lut.services.media_service import (
    DEFAULT_MAX_INPUT_SIZE,
    _detect_backend,
    format_duration,
    format_size,
    get_backend,
    is_media_backend_available,
    parse_fps,
    parse_timestamp,
    probe_media,
    reset_backend_cache,
    resolve_media_output,
    run_ffmpeg,
    validate_media_input,
    verify_staging_media,
)

requires_backend = pytest.mark.skipif(
    not is_media_backend_available(), reason="FFmpeg/FFprobe backend is not available"
)


# =====================================================================
# Timestamp Parsing Tests
# =====================================================================


def test_parse_timestamp_numeric():
    """Parse pure numeric seconds."""
    assert parse_timestamp(0) == 0.0
    assert parse_timestamp(10) == 10.0
    assert parse_timestamp(12.5) == 12.5
    assert parse_timestamp("10") == 10.0
    assert parse_timestamp("12.5") == 12.5


def test_parse_timestamp_mm_ss():
    """Parse MM:SS timestamps."""
    assert parse_timestamp("01:30") == 90.0
    assert parse_timestamp("1:30") == 90.0
    assert parse_timestamp("00:45.5") == 45.5
    assert parse_timestamp("0:00") == 0.0
    assert parse_timestamp("59:59") == 3599.0


def test_parse_timestamp_hh_mm_ss():
    """Parse HH:MM:SS timestamps."""
    assert parse_timestamp("01:02:03") == 3723.0
    assert parse_timestamp("0:01:30") == 90.0
    assert parse_timestamp("01:02:03.500") == 3723.5
    assert parse_timestamp("00:00:00") == 0.0


def test_parse_timestamp_invalid():
    """Reject invalid, negative, or malformed timestamps."""
    with pytest.raises(UsageError, match="Timestamp cannot be empty"):
        parse_timestamp(None)
    with pytest.raises(UsageError, match="Timestamp cannot be empty"):
        parse_timestamp("")
    with pytest.raises(UsageError, match="Timestamp cannot be empty"):
        parse_timestamp("   ")

    with pytest.raises(UsageError, match="finite, nonnegative"):
        parse_timestamp(-5)
    with pytest.raises(UsageError, match="finite, nonnegative"):
        parse_timestamp("-5")
    with pytest.raises(UsageError, match="finite, nonnegative"):
        parse_timestamp(float("nan"))
    with pytest.raises(UsageError, match="finite, nonnegative"):
        parse_timestamp(float("inf"))

    with pytest.raises(UsageError, match="Invalid timestamp format"):
        parse_timestamp("abc")
    with pytest.raises(UsageError, match="Invalid timestamp format"):
        parse_timestamp("1:2:3:4")

    with pytest.raises(UsageError, match="Invalid MM:SS timestamp"):
        parse_timestamp("01:65")
    with pytest.raises(UsageError, match="Invalid MM:SS timestamp"):
        parse_timestamp("01:abc")

    with pytest.raises(UsageError, match="Invalid HH:MM:SS timestamp"):
        parse_timestamp("01:60:00")
    with pytest.raises(UsageError, match="Invalid HH:MM:SS timestamp"):
        parse_timestamp("01:00:60")
    with pytest.raises(UsageError, match="Invalid HH:MM:SS timestamp"):
        parse_timestamp("01:00:abc")


# =====================================================================
# Formatting Helper Tests
# =====================================================================


def test_format_duration():
    """Format duration to HH:MM:SS.mmm."""
    assert format_duration(None) == ""
    assert format_duration(-1) == ""
    assert format_duration(float("nan")) == ""
    assert format_duration(0.0) == "00:00:00.000"
    assert format_duration(65.5) == "00:01:05.500"
    assert format_duration(3661.123) == "01:01:01.123"


def test_format_size():
    """Format bytes to human-readable strings."""
    assert format_size(500) == "500 B"
    assert format_size(1024) == "1.0 KB"
    assert format_size(1024 * 1024 * 5) == "5.0 MB"
    assert format_size(1024 * 1024 * 1024 * 2) == "2.0 GB"


def test_parse_fps():
    """Parse frame rate ratios or numbers."""
    assert parse_fps("") == 0.0
    assert parse_fps("0/0") == 0.0
    assert parse_fps("30/1") == 30.0
    assert parse_fps("25") == 25.0
    assert math.isclose(parse_fps("30000/1001"), 29.97002997, rel_tol=1e-5)
    assert parse_fps("invalid") == 0.0
    assert parse_fps("30/0") == 0.0


# =====================================================================
# Backend Discovery Tests
# =====================================================================


def test_backend_detection_missing(monkeypatch):
    """Raise DependencyError when FFmpeg or FFprobe is missing."""
    reset_backend_cache()

    def mock_which(cmd):
        return None

    monkeypatch.setattr("shutil.which", mock_which)

    with pytest.raises(DependencyError, match="Missing dependency: FFmpeg"):
        _detect_backend()


def test_backend_detection_missing_ffprobe(monkeypatch):
    """Raise DependencyError when FFprobe is missing."""
    reset_backend_cache()

    def mock_which(cmd):
        if cmd == "ffmpeg":
            return "/usr/bin/ffmpeg"
        return None

    monkeypatch.setattr("shutil.which", mock_which)

    with pytest.raises(DependencyError, match="Missing dependency: FFprobe"):
        _detect_backend()


def test_backend_cache_and_reset():
    """Verify backend caching and resetting behavior."""
    reset_backend_cache()
    if is_media_backend_available():
        b1 = get_backend()
        b2 = get_backend()
        assert b1 is b2
        reset_backend_cache()


# =====================================================================
# Input Path Validation Tests
# =====================================================================


def test_validate_input_path_empty():
    """Reject empty or NUL input paths."""
    with pytest.raises(UsageError, match="nonempty and contain no NUL"):
        validate_media_input("")
    with pytest.raises(UsageError, match="nonempty and contain no NUL"):
        validate_media_input("file\0name.mp4")


def test_validate_input_path_not_found(tmp_path):
    """Reject nonexistent files."""
    missing = tmp_path / "missing.mp4"
    with pytest.raises(InputError, match="Input file not found"):
        validate_media_input(missing)


def test_validate_input_path_directory(tmp_path):
    """Reject directory inputs."""
    d = tmp_path / "my_dir"
    d.mkdir()
    with pytest.raises(InputError, match="Input must be a file, not a directory"):
        validate_media_input(d)


def test_validate_input_path_empty_file(tmp_path):
    """Reject 0-byte files."""
    f = tmp_path / "empty.mp4"
    f.touch()
    with pytest.raises(InputError, match="Input file is empty"):
        validate_media_input(f)


def test_validate_input_path_symlink_leaf(tmp_path):
    """Reject leaf symlinks."""
    real_f = tmp_path / "real.mp4"
    real_f.write_bytes(b"dummy media data")
    link_f = tmp_path / "link.mp4"
    link_f.symlink_to(real_f)

    with pytest.raises(InputError, match="Symlinks are not supported for media input"):
        validate_media_input(link_f)


def test_validate_input_path_symlink_ancestor(tmp_path):
    """Reject ancestor directory symlinks."""
    real_dir = tmp_path / "real_dir"
    real_dir.mkdir()
    real_f = real_dir / "clip.mp4"
    real_f.write_bytes(b"dummy media data")

    link_dir = tmp_path / "link_dir"
    link_dir.symlink_to(real_dir)
    f_through_link = link_dir / "clip.mp4"

    with pytest.raises(InputError, match="ancestor symlink in path"):
        validate_media_input(f_through_link)


def test_validate_input_path_size_limit(tmp_path, monkeypatch):
    """Reject files exceeding the size limit."""
    f = tmp_path / "large.mp4"
    f.write_bytes(b"content")

    real_stat = f.stat()

    class MockStat:
        st_size = DEFAULT_MAX_INPUT_SIZE + 1024
        st_mode = real_stat.st_mode

    orig_stat = Path.stat

    def mock_stat(self, *args, **kwargs):
        try:
            if str(self.absolute()) == str(f.absolute()):
                return MockStat()
        except OSError:
            pass
        return orig_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", mock_stat)
    with pytest.raises(InputError, match="exceeds limit"):
        validate_media_input(f)


# =====================================================================
# Output Path Resolution Tests
# =====================================================================


def test_resolve_media_output_default(tmp_path):
    """Compute collision-free output paths beside input."""
    source = tmp_path / "video.mp4"
    source.write_bytes(b"video")

    dest = resolve_media_output(
        source, None, suffix="converted", target_ext=".mkv", is_convert=True
    )
    assert dest == tmp_path / "video.mkv"

    # Simulate existing destination
    (tmp_path / "video.mkv").touch()
    dest2 = resolve_media_output(
        source, None, suffix="converted", target_ext=".mkv", is_convert=True
    )
    assert dest2 == tmp_path / "video_2.mkv"


def test_resolve_media_output_operation(tmp_path):
    """Compute operation suffix destination beside input."""
    source = tmp_path / "clip.mp4"
    source.write_bytes(b"clip")

    dest = resolve_media_output(source, None, suffix="compressed", target_ext=".mp4")
    assert dest == tmp_path / "clip_compressed.mp4"

    (tmp_path / "clip_compressed.mp4").touch()
    dest2 = resolve_media_output(source, None, suffix="compressed", target_ext=".mp4")
    assert dest2 == tmp_path / "clip_compressed_2.mp4"


def test_resolve_media_output_explicit_already_exists(tmp_path):
    """Reject explicit output if destination already exists."""
    source = tmp_path / "input.mp4"
    source.write_bytes(b"input")
    existing_dest = tmp_path / "existing.mp4"
    existing_dest.touch()

    with pytest.raises(OutputError, match="Output already exists"):
        resolve_media_output(source, str(existing_dest), suffix="compressed", target_ext=".mp4")


def test_resolve_media_output_explicit_symlink(tmp_path):
    """Reject explicit output paths containing symlinks."""
    source = tmp_path / "input.mp4"
    source.write_bytes(b"input")
    real_dir = tmp_path / "real_dir"
    real_dir.mkdir()
    link_dir = tmp_path / "link_dir"
    link_dir.symlink_to(real_dir)
    target = link_dir / "out.mp4"

    with pytest.raises(OutputError, match="ancestor symlink in path"):
        resolve_media_output(source, str(target), suffix="compressed", target_ext=".mp4")


# =====================================================================
# FFprobe Parsing & Staging Verification Tests
# =====================================================================


def test_probe_media_failure():
    """Raise ProcessError on FFprobe execution failure."""
    with patch("lut.services.media_service.run_process") as mock_run:
        mock_run.return_value = ProcessResult(1, "", "probe error")
        with pytest.raises(ProcessError, match="FFprobe failed"):
            probe_media(Path("/fake/file.mp4"))


def test_probe_media_invalid_json():
    """Raise ProcessError on invalid JSON output from FFprobe."""
    with patch("lut.services.media_service.run_process") as mock_run:
        mock_run.return_value = ProcessResult(0, "not json", "")
        with pytest.raises(ProcessError, match="Failed to parse FFprobe JSON"):
            probe_media(Path("/fake/file.mp4"))


def test_verify_staging_media_missing(tmp_path):
    """Raise OutputError when staging file was not created."""
    missing = tmp_path / "missing.mp4"
    with pytest.raises(OutputError, match="Backend output was not created"):
        verify_staging_media(missing)


def test_verify_staging_media_too_small(tmp_path):
    """Raise OutputError when staging file is empty."""
    empty = tmp_path / "empty.mp4"
    empty.touch()
    with pytest.raises(OutputError, match="Backend output is too small"):
        verify_staging_media(empty, min_size=10)


def test_unicode_and_spaces_in_path(tmp_path):
    """Handle files with spaces, hyphens, and Unicode characters safely."""
    special_name = "tập tin - phim việt 🎬.mp4"
    source = tmp_path / special_name
    source.write_bytes(b"content")

    validated = validate_media_input(source)
    assert validated.name == special_name

    dest = resolve_media_output(source, None, suffix="trimmed", target_ext=".mp4")
    assert "tập tin - phim việt 🎬_trimmed.mp4" == dest.name


# =====================================================================
# Progress Handling & Cancellation Tests
# =====================================================================


def test_run_ffmpeg_progress_known_duration(monkeypatch):
    """Display percentage and elapsed time when total_duration is known."""
    captured_stderr = StringIO()
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
    monkeypatch.setattr(sys.stderr, "write", captured_stderr.write)
    monkeypatch.setattr(sys.stderr, "flush", lambda: None)

    saved_callback = None

    def mock_run_process(args, timeout=None, progress=None, capture_limit=None):
        nonlocal saved_callback
        saved_callback = progress
        assert "-nostdin" in args
        assert "-progress" in args
        assert progress is not None
        # Simulate FFmpeg output ticks
        progress("stdout", "out_time_us=5000000\nprogress=continue\n")
        progress("stdout", "progress=end\n")
        return ProcessResult(0, "", "")

    monkeypatch.setattr("lut.services.media_service.run_process", mock_run_process)

    res = run_ffmpeg(["ffmpeg", "-i", "in.mp4", "out.mp4"], total_duration=10.0, as_json=False)
    assert res.returncode == 0
    text = captured_stderr.getvalue()
    assert "Progress:  50.0% [00:00:05.000 / 00:00:10.000]" in text
    assert "Progress: 100.0%" in text


def test_run_ffmpeg_progress_unknown_duration(monkeypatch):
    """Display elapsed time without percentage when duration is unknown."""
    captured_stderr = StringIO()
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
    monkeypatch.setattr(sys.stderr, "write", captured_stderr.write)
    monkeypatch.setattr(sys.stderr, "flush", lambda: None)

    def mock_run_process(args, timeout=None, progress=None, capture_limit=None):
        assert "-nostdin" in args
        assert "-progress" in args
        assert progress is not None
        progress("stdout", "out_time_us=3500000\nprogress=continue\n")
        progress("stdout", "progress=end\n")
        return ProcessResult(0, "", "")

    monkeypatch.setattr("lut.services.media_service.run_process", mock_run_process)

    res = run_ffmpeg(["ffmpeg", "-i", "in.mp4", "out.mp4"], total_duration=None, as_json=False)
    assert res.returncode == 0
    text = captured_stderr.getvalue()
    assert "Progress: elapsed 00:00:03.500" in text
    assert "%" not in text  # Must NOT show fake or zero-division percentages
    assert "Progress: complete (00:00:03.500)" in text


def test_run_ffmpeg_progress_json_mode_suppressed(monkeypatch):
    """Suppress interactive progress when running with as_json=True."""
    captured_stderr = StringIO()
    monkeypatch.setattr(sys.stderr, "isatty", lambda: True)
    monkeypatch.setattr(sys.stderr, "write", captured_stderr.write)
    monkeypatch.setattr(sys.stderr, "flush", lambda: None)

    def mock_run_process(args, timeout=None, progress=None, capture_limit=None):
        assert "-progress" not in args
        assert progress is None
        return ProcessResult(0, "", "")

    monkeypatch.setattr("lut.services.media_service.run_process", mock_run_process)

    res = run_ffmpeg(["ffmpeg", "-i", "in.mp4", "out.mp4"], total_duration=10.0, as_json=True)
    assert res.returncode == 0
    assert captured_stderr.getvalue() == ""


def test_cancellation_cleans_up_staging(tmp_path):
    """Verify CancelledError stops backend and cleans up temporary staging output."""
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source content")
    dest = tmp_path / "out.mp4"

    staging_path = None
    try:
        with atomic_output(source, "converted", extension=".mp4", output=dest) as paths:
            staging_path = paths.temporary
            assert staging_path.exists()
            # Simulate Ctrl+C triggering CancelledError
            raise CancelledError("Operation cancelled.")
    except CancelledError:
        pass

    assert staging_path is not None
    # Verify staging temporary file was deleted
    assert not staging_path.exists()
    assert not dest.exists()
