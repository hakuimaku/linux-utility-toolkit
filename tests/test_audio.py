"""Comprehensive tests for Audio Tools (Milestone 6)."""

import json
from pathlib import Path

import pytest

from lut.cli import main
from lut.core.errors import (
    ProcessError,
    UsageError,
)
from lut.core.process import ProcessResult, run_process
from lut.services.audio_service import (
    audio_convert,
    audio_info,
    audio_normalize,
    audio_trim,
    audio_volume,
)
from lut.services.media_service import (
    get_backend,
    is_backend_available,
    probe_media,
)

requires_backend = pytest.mark.skipif(
    not is_backend_available(), reason="FFmpeg/FFprobe backend is not available"
)


# =====================================================================
# Audio Fixtures
# =====================================================================


@pytest.fixture
def sample_wav(tmp_path) -> Path:
    """Create a small 2-second synthesized sine wave WAV audio fixture."""
    backend = get_backend()
    p = tmp_path / "sample.wav"
    cmd = [
        str(backend.ffmpeg_path),
        "-nostdin",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=2",
        "-c:a",
        "pcm_s16le",
        str(p),
    ]
    res = run_process(cmd, timeout=30)
    assert res.returncode == 0
    return p


@pytest.fixture
def sample_mp3(tmp_path) -> Path:
    """Create a small 2-second synthesized MP3 audio fixture."""
    backend = get_backend()
    p = tmp_path / "sample.mp3"
    cmd = [
        str(backend.ffmpeg_path),
        "-nostdin",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=880:duration=2",
        "-c:a",
        "libmp3lame",
        "-b:a",
        "128k",
        str(p),
    ]
    res = run_process(cmd, timeout=30)
    assert res.returncode == 0
    return p


# =====================================================================
# Audio Convert Tests
# =====================================================================


@requires_backend
def test_audio_convert_wav_to_mp3(sample_wav, capsys):
    """Convert WAV to MP3 format."""
    code = audio_convert(sample_wav, fmt="mp3")
    assert code == 0
    captured = capsys.readouterr()
    assert "Converted" in captured.out
    assert "sample.mp3" in captured.out

    dest = sample_wav.parent / "sample.mp3"
    assert dest.exists()
    assert dest.stat().st_size > 0

    info = probe_media(dest)
    assert len(info.audio_streams) == 1
    assert info.audio_streams[0].codec_name == "mp3"


@requires_backend
def test_audio_convert_with_bitrate(sample_wav):
    """Convert WAV to MP3 with explicit bitrate."""
    dest = sample_wav.parent / "custom_bitrate.mp3"
    code = audio_convert(sample_wav, fmt="mp3", bitrate="192k", output=str(dest))
    assert code == 0
    assert dest.exists()
    info = probe_media(dest)
    assert info.audio_streams[0].codec_name == "mp3"


@requires_backend
def test_audio_convert_bitrate_lossless_rejected(sample_wav):
    """Reject --bitrate option when converting to lossless formats (WAV, FLAC)."""
    with pytest.raises(UsageError, match="--bitrate is not supported for lossless FLAC"):
        audio_convert(sample_wav, fmt="flac", bitrate="320k")


@requires_backend
def test_audio_convert_noop_rejected(sample_mp3):
    """Reject no-op conversion when already in target format."""
    with pytest.raises(UsageError, match="Input is already in MP3 format"):
        audio_convert(sample_mp3, fmt="mp3")


@requires_backend
def test_audio_convert_dry_run_and_json(sample_wav, capsys):
    """Test audio convert dry-run and JSON output."""
    code = audio_convert(sample_wav, fmt="ogg", dry_run=True, as_json=True)
    assert code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["dry_run"] is True
    assert payload["format"] == "ogg"
    assert not (sample_wav.parent / "sample.ogg").exists()


# =====================================================================
# Audio Trim Tests
# =====================================================================


@requires_backend
def test_audio_trim_valid(sample_wav, capsys):
    """Trim an audio time segment."""
    code = audio_trim(sample_wav, start="0.5", end="1.5")
    assert code == 0
    captured = capsys.readouterr()
    assert "Trimmed" in captured.out

    dest = sample_wav.parent / "sample_trimmed.wav"
    assert dest.exists()
    info = probe_media(dest)
    assert info.duration is not None
    assert 0.8 <= info.duration <= 1.2


@requires_backend
def test_audio_trim_copy_mode(sample_mp3, capsys):
    """Trim audio with --copy stream copy mode."""
    code = audio_trim(sample_mp3, start=0, end=1.0, copy=True)
    assert code == 0
    captured = capsys.readouterr()
    assert "Note: Trimming with --copy" in captured.out


def test_audio_trim_invalid_ranges(sample_wav):
    """Reject invalid trim timestamps."""
    with pytest.raises(UsageError, match="--end timestamp is required"):
        audio_trim(sample_wav, start=0, end=None)
    with pytest.raises(UsageError, match="strictly greater than start"):
        audio_trim(sample_wav, start=1.5, end=0.5)
    with pytest.raises(UsageError, match="strictly greater than start"):
        audio_trim(sample_wav, start=1.0, end=1.0)
    with pytest.raises(UsageError, match="exceeds audio duration"):
        audio_trim(sample_wav, start=5.0, end=6.0)


# =====================================================================
# Audio Normalize Tests
# =====================================================================


@requires_backend
def test_audio_normalize_default(sample_wav, capsys):
    """Normalize audio loudness using loudnorm."""
    code = audio_normalize(sample_wav)
    assert code == 0
    captured = capsys.readouterr()
    assert "Normalized" in captured.out
    assert "target -16.0 LUFS" in captured.out

    dest = sample_wav.parent / "sample_normalized.wav"
    assert dest.exists()
    assert dest.stat().st_size > 0


@requires_backend
def test_audio_normalize_custom_lufs_and_json(sample_wav, capsys):
    """Normalize audio with custom target LUFS and JSON output."""
    code = audio_normalize(sample_wav, target_lufs=-14.0, as_json=True)
    assert code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["status"] == "success"
    assert payload["target_lufs"] == -14.0


def test_audio_normalize_invalid_lufs(sample_wav):
    """Reject target LUFS outside valid range (-70 to -5)."""
    with pytest.raises(UsageError, match="Target LUFS must be a finite number"):
        audio_normalize(sample_wav, target_lufs=-80.0)
    with pytest.raises(UsageError, match="Target LUFS must be a finite number"):
        audio_normalize(sample_wav, target_lufs=0.0)


def test_audio_normalize_pass1_failure(sample_wav, monkeypatch):
    """Fail closed when pass 1 measurement exit code is non-zero."""

    def mock_run_ffmpeg(*args, **kwargs):
        return ProcessResult(1, "", "loudnorm internal failure")

    monkeypatch.setattr("lut.services.audio_service.run_ffmpeg", mock_run_ffmpeg)
    with pytest.raises(ProcessError, match="Audio normalization pass 1 failed with exit code 1"):
        audio_normalize(sample_wav)


def test_audio_normalize_missing_json(sample_wav, monkeypatch):
    """Fail closed when pass 1 output does not contain loudnorm measurement JSON."""

    def mock_run_ffmpeg(*args, **kwargs):
        return ProcessResult(0, "", "no json output produced")

    monkeypatch.setattr("lut.services.audio_service.run_ffmpeg", mock_run_ffmpeg)
    with pytest.raises(ProcessError, match="loudnorm measurement JSON not found"):
        audio_normalize(sample_wav)


def test_audio_normalize_malformed_json(sample_wav, monkeypatch):
    """Fail closed when pass 1 JSON is truncated or invalid."""

    def mock_run_ffmpeg(*args, **kwargs):
        bad_json = '{\n "input_i": [unclosed array\n}'
        return ProcessResult(0, "", bad_json)

    monkeypatch.setattr("lut.services.audio_service.run_ffmpeg", mock_run_ffmpeg)
    with pytest.raises(ProcessError, match="malformed loudnorm measurement JSON"):
        audio_normalize(sample_wav)


def test_audio_normalize_missing_required_keys(sample_wav, monkeypatch):
    """Fail closed when pass 1 JSON is missing essential measurement keys."""

    def mock_run_ffmpeg(*args, **kwargs):
        partial_json = '{\n "input_i": "-20.0",\n "input_tp": "-1.5"\n}'
        return ProcessResult(0, "", partial_json)

    monkeypatch.setattr("lut.services.audio_service.run_ffmpeg", mock_run_ffmpeg)
    with pytest.raises(ProcessError, match="missing measurement\\(s\\)"):
        audio_normalize(sample_wav)


def test_audio_normalize_non_numeric_values(sample_wav, monkeypatch):
    """Fail closed when pass 1 measurements contain non-numeric data."""

    def mock_run_ffmpeg(*args, **kwargs):
        invalid_json = (
            '{\n "input_i": "corrupted",\n "input_tp": "-1.5",\n'
            ' "input_lra": "7.0",\n "input_thresh": "-30.0"\n}'
        )
        return ProcessResult(0, "", invalid_json)

    monkeypatch.setattr("lut.services.audio_service.run_ffmpeg", mock_run_ffmpeg)
    with pytest.raises(ProcessError, match="invalid numeric value for 'input_i'"):
        audio_normalize(sample_wav)


def test_audio_normalize_non_finite_values(sample_wav, monkeypatch):
    """Fail closed when pass 1 measurements contain NaN or Infinite values."""

    def mock_run_ffmpeg(*args, **kwargs):
        nan_json = (
            '{\n "input_i": "nan",\n "input_tp": "-1.5",\n'
            ' "input_lra": "7.0",\n "input_thresh": "-30.0"\n}'
        )
        return ProcessResult(0, "", nan_json)

    monkeypatch.setattr("lut.services.audio_service.run_ffmpeg", mock_run_ffmpeg)
    with pytest.raises(ProcessError, match="non-finite value for 'input_i'"):
        audio_normalize(sample_wav)


# =====================================================================
# Audio Volume Tests
# =====================================================================


@requires_backend
def test_audio_volume_adjust_gain(sample_wav, capsys):
    """Adjust audio volume by +3 dB."""
    code = audio_volume(sample_wav, db=3.0)
    assert code == 0
    captured = capsys.readouterr()
    assert "Adjusted volume" in captured.out
    assert "+3.0 dB" in captured.out

    dest = sample_wav.parent / "sample_volume.wav"
    assert dest.exists()


@requires_backend
def test_audio_volume_negative_db_and_json(sample_wav, capsys):
    """Adjust audio volume by negative dB with JSON output."""
    code = audio_volume(sample_wav, db=-6.0, as_json=True)
    assert code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["status"] == "success"
    assert payload["gain_db"] == -6.0


def test_audio_volume_invalid_db(sample_wav):
    """Reject invalid volume adjustment values."""
    with pytest.raises(UsageError, match="--db value is required"):
        audio_volume(sample_wav, db=None)
    with pytest.raises(UsageError, match="Volume adjustment must be between"):
        audio_volume(sample_wav, db=50.0)
    with pytest.raises(UsageError, match="Volume adjustment must be between"):
        audio_volume(sample_wav, db=-100.0)


# =====================================================================
# Audio Info Tests
# =====================================================================


@requires_backend
def test_audio_info_text(sample_wav, capsys):
    """Inspect audio metadata formatted as text."""
    code = audio_info(sample_wav)
    assert code == 0
    captured = capsys.readouterr()
    assert "File:" in captured.out
    assert "Container:" in captured.out
    assert "Audio Streams:" in captured.out
    assert "PCM_S16LE" in captured.out


@requires_backend
def test_audio_info_json(sample_mp3, capsys):
    """Inspect audio metadata formatted as JSON."""
    code = audio_info(sample_mp3, as_json=True)
    assert code == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert "audio_streams" in payload
    assert len(payload["audio_streams"]) == 1
    assert payload["audio_streams"][0]["codec_name"] == "mp3"


# =====================================================================
# CLI Integration Tests
# =====================================================================


@requires_backend
def test_cli_audio_convert(sample_wav):
    """CLI test: lut audio convert."""
    dest = sample_wav.parent / "cli_converted.flac"
    code = main(["audio", "convert", str(sample_wav), "--format", "flac", "--output", str(dest)])
    assert code == 0
    assert dest.exists()


@requires_backend
def test_cli_audio_volume(sample_wav):
    """CLI test: lut audio volume."""
    dest = sample_wav.parent / "cli_vol.wav"
    code = main(["audio", "volume", str(sample_wav), "--db", "-3", "--output", str(dest)])
    assert code == 0
    assert dest.exists()


@requires_backend
def test_cli_audio_info_json(sample_wav, capsys):
    """CLI test: lut audio info --json."""
    code = main(["audio", "info", str(sample_wav), "--json"])
    assert code == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["file"] == str(sample_wav.resolve())
