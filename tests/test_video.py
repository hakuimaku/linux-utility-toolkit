"""Comprehensive tests for Video Tools (Milestone 6)."""

import json
from pathlib import Path

import pytest

from lut.cli import main
from lut.core.errors import (
    InputError,
    UsageError,
)
from lut.core.process import run_process
from lut.services.media_service import (
    get_backend,
    is_backend_available,
    probe_media,
)
from lut.services.video_service import (
    video_compress,
    video_convert,
    video_extract_audio,
    video_frames,
    video_gif,
    video_info,
    video_resize,
    video_trim,
)

requires_backend = pytest.mark.skipif(
    not is_backend_available(), reason="FFmpeg/FFprobe backend is not available"
)


# =====================================================================
# Media Fixtures
# =====================================================================


@pytest.fixture
def sample_mp4(tmp_path) -> Path:
    """Create a small 1-second 320x240 MP4 video fixture with video and audio."""
    backend = get_backend()
    p = tmp_path / "sample.mp4"
    cmd = [
        str(backend.ffmpeg_path),
        "-nostdin",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=1:size=320x240:rate=10",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=1000:duration=1",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        str(p),
    ]
    res = run_process(cmd, timeout=30)
    assert res.returncode == 0
    return p


@pytest.fixture
def sample_no_audio_mp4(tmp_path) -> Path:
    """Create a small 1-second MP4 video fixture with NO audio stream."""
    backend = get_backend()
    p = tmp_path / "no_audio.mp4"
    cmd = [
        str(backend.ffmpeg_path),
        "-nostdin",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=1:size=320x240:rate=10",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(p),
    ]
    res = run_process(cmd, timeout=30)
    assert res.returncode == 0
    return p


@pytest.fixture
def sample_webm(tmp_path) -> Path:
    """Create a small WebM video fixture with VP9 video and Opus audio."""
    backend = get_backend()
    p = tmp_path / "sample.webm"
    cmd = [
        str(backend.ffmpeg_path),
        "-nostdin",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "testsrc=duration=1:size=320x240:rate=10",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=1000:duration=1",
        "-c:v",
        "libvpx-vp9",
        "-c:a",
        "libopus",
        str(p),
    ]
    res = run_process(cmd, timeout=30)
    assert res.returncode == 0
    return p


# =====================================================================
# Video Convert Tests
# =====================================================================


@requires_backend
def test_video_convert_mp4_to_webm(sample_mp4, capsys):
    """Convert an MP4 video to WebM format."""
    code = video_convert(sample_mp4, fmt="webm")
    assert code == 0
    captured = capsys.readouterr()
    assert "Converted" in captured.out
    assert "sample.webm" in captured.out

    dest = sample_mp4.parent / "sample.webm"
    assert dest.exists()
    assert dest.stat().st_size > 0

    info = probe_media(dest)
    assert "webm" in info.format_name.lower() or "matroska" in info.format_name.lower()
    assert len(info.video_streams) == 1
    assert info.video_streams[0].codec_name in ("vp9", "vp8", "av1")


@requires_backend
def test_video_convert_dry_run_and_json(sample_mp4, capsys):
    """Test video convert dry run and JSON output."""
    code = video_convert(sample_mp4, fmt="mkv", dry_run=True, as_json=True)
    assert code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["dry_run"] is True
    assert payload["format"] == "mkv"
    assert not (sample_mp4.parent / "sample.mkv").exists()


@requires_backend
def test_video_convert_incompatible_codec_rejected(sample_mp4):
    """Reject incompatible video codec for container (e.g. h264 for webm)."""
    with pytest.raises(UsageError, match="WebM container does not support 'h264'"):
        video_convert(sample_mp4, fmt="webm", codec="h264")


@requires_backend
def test_video_convert_noop_rejected(sample_mp4):
    """Reject no-op conversion when input is already in target format."""
    with pytest.raises(UsageError, match="Input is already in MP4 format"):
        video_convert(sample_mp4, fmt="mp4")


# =====================================================================
# Video Compress Tests
# =====================================================================


@requires_backend
def test_video_compress_default(sample_mp4, capsys):
    """Compress video with default settings."""
    orig_size = sample_mp4.stat().st_size
    code = video_compress(sample_mp4)
    assert code == 0
    captured = capsys.readouterr()
    assert "Compressed" in captured.out

    dest = sample_mp4.parent / "sample_compressed.mp4"
    assert dest.exists()
    assert dest.stat().st_size > 0

    # Ensure original was not modified
    assert sample_mp4.stat().st_size == orig_size


@requires_backend
def test_video_compress_custom_crf_and_json(sample_mp4, capsys):
    """Compress video with explicit CRF and JSON output."""
    code = video_compress(sample_mp4, crf=28, preset="ultrafast", as_json=True)
    assert code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["status"] == "success"
    assert "compressed_size_bytes" in payload


def test_video_compress_invalid_options(sample_mp4):
    """Reject invalid compression options."""
    with pytest.raises(UsageError, match="CRF must be an integer between 0 and 51"):
        video_compress(sample_mp4, crf=99)
    with pytest.raises(UsageError, match="Invalid quality"):
        video_compress(sample_mp4, quality="extreme")
    with pytest.raises(UsageError, match="Invalid preset"):
        video_compress(sample_mp4, preset="insane")


# =====================================================================
# Video Resize Tests
# =====================================================================


@requires_backend
def test_video_resize_width_only(sample_mp4, capsys):
    """Resize video specifying only width (aspect ratio kept, even height)."""
    code = video_resize(sample_mp4, width=160)
    assert code == 0
    captured = capsys.readouterr()
    assert "Resized" in captured.out

    dest = sample_mp4.parent / "sample_resized.mp4"
    assert dest.exists()
    info = probe_media(dest)
    v = info.video_streams[0]
    assert v.width == 160
    assert v.height == 120  # 320x240 halved is 160x120


@requires_backend
def test_video_resize_height_only(sample_mp4):
    """Resize video specifying only height."""
    code = video_resize(sample_mp4, height=120)
    assert code == 0
    dest = sample_mp4.parent / "sample_resized.mp4"
    assert dest.exists()
    info = probe_media(dest)
    assert info.video_streams[0].height == 120
    assert info.video_streams[0].width == 160


@requires_backend
def test_video_resize_upscale_rejected(sample_mp4):
    """Reject upscaling without --allow-upscale."""
    with pytest.raises(UsageError, match="exceeds original width.*allow-upscale"):
        video_resize(sample_mp4, width=640)
    with pytest.raises(UsageError, match="exceeds original height.*allow-upscale"):
        video_resize(sample_mp4, height=480)


@requires_backend
def test_video_resize_upscale_allowed(sample_mp4):
    """Permit upscaling when --allow-upscale is enabled."""
    dest_path = sample_mp4.parent / "upscaled.mp4"
    code = video_resize(sample_mp4, width=640, allow_upscale=True, output=str(dest_path))
    assert code == 0
    assert dest_path.exists()
    info = probe_media(dest_path)
    assert info.video_streams[0].width == 640


def test_video_resize_no_dimensions(sample_mp4):
    """Reject resize when neither width nor height is specified."""
    with pytest.raises(UsageError, match="At least one dimension"):
        video_resize(sample_mp4)


# =====================================================================
# Video Trim Tests
# =====================================================================


@requires_backend
def test_video_trim_valid_range(sample_mp4, capsys):
    """Trim a slice from video."""
    code = video_trim(sample_mp4, start="0.2", end="0.8")
    assert code == 0
    captured = capsys.readouterr()
    assert "Trimmed" in captured.out

    dest = sample_mp4.parent / "sample_trimmed.mp4"
    assert dest.exists()
    info = probe_media(dest)
    assert info.duration is not None
    assert 0.4 <= info.duration <= 0.8


@requires_backend
def test_video_trim_copy_mode(sample_mp4, capsys):
    """Trim with --copy mode."""
    code = video_trim(sample_mp4, start=0, end=0.5, copy=True)
    assert code == 0
    captured = capsys.readouterr()
    assert "Note: Trimming with --copy" in captured.out


def test_video_trim_invalid_ranges(sample_mp4):
    """Reject invalid trim ranges."""
    with pytest.raises(UsageError, match="--end timestamp is required"):
        video_trim(sample_mp4, start=0, end=None)
    with pytest.raises(UsageError, match="strictly greater than start"):
        video_trim(sample_mp4, start=5, end=2)
    with pytest.raises(UsageError, match="strictly greater than start"):
        video_trim(sample_mp4, start=5, end=5)
    with pytest.raises(UsageError, match="exceeds video duration"):
        video_trim(sample_mp4, start=10, end=20)


# =====================================================================
# Video Extract Audio Tests
# =====================================================================


@requires_backend
def test_video_extract_audio_mp3(sample_mp4, capsys):
    """Extract audio from video to MP3."""
    code = video_extract_audio(sample_mp4, fmt="mp3")
    assert code == 0
    captured = capsys.readouterr()
    assert "Extracted audio" in captured.out

    dest = sample_mp4.parent / "sample.mp3"
    assert dest.exists()
    info = probe_media(dest)
    assert len(info.audio_streams) == 1
    assert info.audio_streams[0].codec_name == "mp3"


@requires_backend
def test_video_extract_audio_no_audio(sample_no_audio_mp4):
    """Reject audio extraction from video with no audio streams."""
    with pytest.raises(InputError, match="contains no audio streams"):
        video_extract_audio(sample_no_audio_mp4)


@requires_backend
def test_video_extract_audio_stream_out_of_range(sample_mp4):
    """Reject invalid stream index."""
    with pytest.raises(UsageError, match="out of range"):
        video_extract_audio(sample_mp4, stream=5)


# =====================================================================
# Video Frames Tests
# =====================================================================


@requires_backend
def test_video_frames_extraction(sample_mp4, capsys):
    """Extract frames at 1 FPS."""
    code = video_frames(sample_mp4, fps=1.0, fmt="png")
    assert code == 0
    captured = capsys.readouterr()
    assert "Extracted" in captured.out

    frames_dir = sample_mp4.parent / "sample_frames"
    assert frames_dir.exists() and frames_dir.is_dir()
    frames = list(frames_dir.glob("frame_*.png"))
    assert len(frames) >= 1


@requires_backend
def test_video_frames_max_frames_limit(sample_mp4):
    """Reject frame extraction exceeding safety ceiling."""
    with pytest.raises(UsageError, match="exceeds limit"):
        video_frames(sample_mp4, fps=50.0, max_frames=5)


@requires_backend
def test_video_frames_hard_limit_with_unknown_duration(sample_mp4, monkeypatch):
    """Verify that FFmpeg -frames:v hard limit caps extracted count when duration is unknown."""
    from lut.services.media_service import probe_media as real_probe_media

    real_info = real_probe_media(sample_mp4)

    # Return MediaInfo with duration=None to bypass pre-check and test runtime hard limit
    def mock_probe(path):
        from dataclasses import replace

        return replace(real_info, duration=None, duration_formatted="")

    monkeypatch.setattr("lut.services.video_service.probe_media", mock_probe)

    out_dir = sample_mp4.parent / "unknown_dur_frames"
    code = video_frames(sample_mp4, fps=10.0, max_frames=3, output=str(out_dir))
    assert code == 0
    assert out_dir.exists()

    frames = list(out_dir.glob("frame_*.png"))
    # Hard limit of 3 must be strictly enforced
    assert len(frames) == 3


def test_video_frames_invalid_options(sample_mp4):
    """Reject invalid fps, max_frames, or format."""
    with pytest.raises(UsageError, match="Max frames limit must be positive"):
        video_frames(sample_mp4, max_frames=0)
    with pytest.raises(UsageError, match="Max frames limit must be positive"):
        video_frames(sample_mp4, max_frames=-5)
    with pytest.raises(UsageError, match="FPS must be a positive number"):
        video_frames(sample_mp4, fps=0)
    with pytest.raises(UsageError, match="FPS must be a positive number"):
        video_frames(sample_mp4, fps=-2.0)
    with pytest.raises(UsageError, match="Unsupported frame format"):
        video_frames(sample_mp4, fmt="gif")


# =====================================================================
# Video GIF Tests
# =====================================================================


@requires_backend
def test_video_gif_creation(sample_mp4, capsys):
    """Create an animated GIF from video clip."""
    code = video_gif(sample_mp4, start=0, duration=0.5, fps=10, width=160)
    assert code == 0
    captured = capsys.readouterr()
    assert "Created GIF" in captured.out

    dest = sample_mp4.parent / "sample_gif.gif"
    assert dest.exists()
    assert dest.stat().st_size > 100


def test_video_gif_duration_limit(sample_mp4):
    """Reject GIF duration exceeding 30 seconds."""
    with pytest.raises(UsageError, match="cannot exceed 30 seconds"):
        video_gif(sample_mp4, duration=35.0)


# =====================================================================
# Video Info Tests
# =====================================================================


@requires_backend
def test_video_info_text(sample_mp4, capsys):
    """Inspect video properties formatted as text."""
    code = video_info(sample_mp4)
    assert code == 0
    captured = capsys.readouterr()
    assert "File:" in captured.out
    assert "Container:" in captured.out
    assert "Video Streams:" in captured.out
    assert "Audio Streams:" in captured.out
    assert "320x240" in captured.out


@requires_backend
def test_video_info_json(sample_mp4, capsys):
    """Inspect video properties formatted as JSON."""
    code = video_info(sample_mp4, as_json=True)
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert "video_streams" in data
    assert len(data["video_streams"]) == 1
    assert data["video_streams"][0]["width"] == 320


# =====================================================================
# CLI Integration Tests
# =====================================================================


@requires_backend
def test_cli_video_convert(sample_mp4):
    """CLI test: lut video convert."""
    dest = sample_mp4.parent / "cli_out.webm"
    code = main(["video", "convert", str(sample_mp4), "--output", str(dest)])
    assert code == 0
    assert dest.exists()


@requires_backend
def test_cli_video_info(sample_mp4, capsys):
    """CLI test: lut video info --json."""
    code = main(["video", "info", str(sample_mp4), "--json"])
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["file"] == str(sample_mp4.resolve())
