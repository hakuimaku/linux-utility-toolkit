"""Audio service for format conversion, trimming, normalization, and volume adjustment."""

import json
import math
import os
import re
import sys
from pathlib import Path

from lut.core.errors import (
    InputError,
    OutputError,
    ProcessError,
    UsageError,
)
from lut.core.output import atomic_output
from lut.services.media_service import (
    AUDIO_CODEC_MAP,
    SUPPORTED_AUDIO_FORMATS,
    format_duration,
    get_backend,
    parse_timestamp,
    probe_media,
    resolve_media_output,
    run_ffmpeg,
    validate_media_input,
    verify_staging_media,
)


def audio_convert(
    input_path: str | os.PathLike[str],
    fmt: str | None = None,
    bitrate: str | None = None,
    output: str | None = None,
    dry_run: bool = False,
    as_json: bool = False,
    verbose: bool = False,
) -> int:
    """Convert an audio file to a different container format and codec."""
    source = validate_media_input(input_path)
    info = probe_media(source)

    if not info.audio_streams:
        raise InputError(f"Input file '{source.name}' contains no audio streams.")

    if fmt is None and output is None:
        raise UsageError("Target format must be specified via --format or inferred from --output.")

    if fmt is None and output is not None:
        target_ext = Path(output).suffix.lstrip(".").lower()
        if not target_ext:
            raise UsageError("Cannot infer format from --output without a file extension.")
        target_fmt = target_ext
    else:
        target_fmt = str(fmt).lower()

    if target_fmt not in SUPPORTED_AUDIO_FORMATS:
        allowed = ", ".join(SUPPORTED_AUDIO_FORMATS)
        raise UsageError(f"Unsupported audio format: {target_fmt!r}. Supported: {allowed}")

    # Bitrate validation
    if bitrate is not None:
        if target_fmt in ("wav", "flac"):
            msg = f"--bitrate is not supported for lossless {target_fmt.upper()} format."
            raise UsageError(msg)
        # Validate bitrate syntax (e.g. 128k, 192k, 320k)
        br_clean = bitrate.strip().lower()
        if not re.match(r"^\d+k?$", br_clean):
            raise UsageError(f"Invalid bitrate specification: {bitrate!r} (e.g. 128k, 192k, 320k).")
        actual_bitrate = br_clean if br_clean.endswith("k") else f"{br_clean}k"
    else:
        actual_bitrate = None

    # Check for no-op conversion
    src_ext = source.suffix.lstrip(".").lower()
    if src_ext == target_fmt and actual_bitrate is None:
        raise UsageError(f"Input is already in {target_fmt.upper()} format.")

    audio_codec = AUDIO_CODEC_MAP[target_fmt]
    dest = resolve_media_output(
        source, output, suffix="converted", target_ext=f".{target_fmt}", is_convert=True
    )

    if dry_run:
        if as_json:
            payload = {
                "dry_run": True,
                "input": str(source),
                "destination": str(dest),
                "format": target_fmt,
                "codec": audio_codec,
                "bitrate": actual_bitrate,
            }
            sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        else:
            br_info = f" at {actual_bitrate}" if actual_bitrate else ""
            sys.stdout.write(
                f"[dry-run] Would convert '{source.name}' to "
                f"{target_fmt.upper()}{br_info} at: {dest}\n"
            )
        return 0

    backend = get_backend()
    cmd = [
        str(backend.ffmpeg_path),
        "-nostdin",
        "-y",
        "-i",
        str(source),
        "-vn",
        "-c:a",
        audio_codec,
    ]

    if actual_bitrate:
        cmd.extend(["-b:a", actual_bitrate])

    with atomic_output(source, "converted", extension=f".{target_fmt}", output=dest) as paths:
        temp_file = paths.temporary
        if temp_file is None:
            raise OutputError("Staging temporary file could not be created.")

        exec_cmd = [*cmd, str(temp_file)]
        res = run_ffmpeg(exec_cmd, total_duration=info.duration, as_json=as_json)
        if res.returncode != 0:
            raise ProcessError(f"Audio conversion failed with exit code {res.returncode}.")

        verify_staging_media(temp_file, expected_type="audio")

    final_info = probe_media(paths.destination)
    src_codec = info.audio_streams[0].codec_name.lower()
    lossy_src = src_codec in ("aac", "mp3", "vorbis", "opus")
    lossless_tgt = target_fmt in ("flac", "wav")
    is_lossy_to_lossless = lossy_src and lossless_tgt

    if as_json:
        payload = {
            "status": "success",
            "input": str(source),
            "output": str(paths.destination),
            "format": target_fmt,
            "duration": final_info.duration,
            "size_bytes": final_info.size_bytes,
            "size": final_info.size_formatted,
            "lossy_to_lossless": is_lossy_to_lossless,
        }
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    else:
        note = (
            "\nNote: Converting lossy audio to a lossless format "
            "does not restore lost audio fidelity."
            if is_lossy_to_lossless
            else ""
        )
        sys.stdout.write(
            f"Converted '{source.name}' -> '{paths.destination.name}' "
            f"({target_fmt.upper()}, {final_info.size_formatted}){note}\n"
        )
    return 0


def audio_trim(
    input_path: str | os.PathLike[str],
    start: str | float | None = "0",
    end: str | float | None = None,
    copy: bool = False,
    output: str | None = None,
    dry_run: bool = False,
    as_json: bool = False,
    verbose: bool = False,
) -> int:
    """Trim an audio time range accurately or via stream copy."""
    source = validate_media_input(input_path)
    info = probe_media(source)

    if not info.audio_streams:
        raise InputError(f"Input file '{source.name}' contains no audio streams.")

    if end is None:
        raise UsageError("--end timestamp is required for audio trim.")

    start_sec = parse_timestamp(start if start is not None else 0)
    end_sec = parse_timestamp(end)

    if start_sec < 0:
        raise UsageError(f"Start time must be >= 0: {start_sec}")
    if end_sec <= start_sec:
        raise UsageError(
            f"End time ({end_sec}s) must be strictly greater than start time ({start_sec}s)."
        )

    if info.duration is not None and info.duration > 0:
        if start_sec >= info.duration:
            msg = f"Start time ({start_sec:.2f}s) exceeds audio duration ({info.duration:.2f}s)."
            raise UsageError(msg)
        if end_sec > info.duration:
            msg = f"End time ({end_sec:.2f}s) exceeds audio duration ({info.duration:.2f}s)."
            raise UsageError(msg)

    target_duration = end_sec - start_sec
    ext = source.suffix if output is None else Path(output).suffix
    if not ext:
        ext = source.suffix or ".mp3"

    dest = resolve_media_output(source, output, suffix="trimmed", target_ext=ext)

    if dry_run:
        if as_json:
            payload = {
                "dry_run": True,
                "input": str(source),
                "destination": str(dest),
                "start": start_sec,
                "end": end_sec,
                "duration": target_duration,
                "copy_mode": copy,
            }
            sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        else:
            mode_desc = "copy" if copy else "re-encode"
            sys.stdout.write(
                f"[dry-run] Would trim '{source.name}' from {format_duration(start_sec)} to "
                f"{format_duration(end_sec)} ({mode_desc}) at: {dest}\n"
            )
        return 0

    backend = get_backend()
    cmd = [
        str(backend.ffmpeg_path),
        "-nostdin",
        "-y",
        "-ss",
        f"{start_sec:.3f}",
        "-to",
        f"{end_sec:.3f}",
        "-i",
        str(source),
        "-vn",
    ]

    if copy:
        cmd.extend(["-c:a", "copy"])
    else:
        # Determine appropriate audio encoder for the format
        fmt_key = ext.lstrip(".").lower()
        enc = AUDIO_CODEC_MAP.get(fmt_key, "aac")
        cmd.extend(["-c:a", enc])

    with atomic_output(source, "trimmed", extension=ext, output=dest) as paths:
        temp_file = paths.temporary
        if temp_file is None:
            raise OutputError("Staging temporary file could not be created.")

        exec_cmd = [*cmd, str(temp_file)]
        res = run_ffmpeg(exec_cmd, total_duration=target_duration, as_json=as_json)
        if res.returncode != 0:
            raise ProcessError(f"Audio trim failed with exit code {res.returncode}.")

        out_info = verify_staging_media(temp_file, expected_type="audio")

    if as_json:
        payload = {
            "status": "success",
            "input": str(source),
            "output": str(paths.destination),
            "start": start_sec,
            "end": end_sec,
            "duration": out_info.duration,
            "size": out_info.size_formatted,
            "copy_mode": copy,
        }
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    else:
        s_fmt = format_duration(start_sec)
        e_fmt = format_duration(end_sec)
        note = (
            "\nNote: Trimming with --copy cuts at packet boundaries "
            "and may not match exact timestamps."
            if copy
            else ""
        )
        sys.stdout.write(
            f"Trimmed '{source.name}' [{s_fmt} -> {e_fmt}] -> "
            f"'{paths.destination.name}' ({out_info.duration_formatted}, "
            f"{out_info.size_formatted}){note}\n"
        )
    return 0


def audio_normalize(
    input_path: str | os.PathLike[str],
    target_lufs: float = -16.0,
    output: str | None = None,
    dry_run: bool = False,
    as_json: bool = False,
    verbose: bool = False,
) -> int:
    """Normalize audio loudness using EBU R128 two-pass loudnorm."""
    source = validate_media_input(input_path)
    info = probe_media(source)

    if not info.audio_streams:
        raise InputError(f"Input file '{source.name}' contains no audio streams.")

    if not math.isfinite(target_lufs) or target_lufs < -70.0 or target_lufs > -5.0:
        raise UsageError(
            f"Target LUFS must be a finite number between -70.0 and -5.0: {target_lufs}"
        )

    ext = source.suffix if output is None else Path(output).suffix
    if not ext:
        ext = source.suffix or ".mp3"

    dest = resolve_media_output(source, output, suffix="normalized", target_ext=ext)

    if dry_run:
        if as_json:
            payload = {
                "dry_run": True,
                "input": str(source),
                "destination": str(dest),
                "target_lufs": target_lufs,
                "method": "two-pass loudnorm",
            }
            sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        else:
            sys.stdout.write(
                f"[dry-run] Would normalize '{source.name}' to {target_lufs:.1f} LUFS at: {dest}\n"
            )
        return 0

    backend = get_backend()

    # Pass 1: Measure loudness statistics
    pass1_cmd = [
        str(backend.ffmpeg_path),
        "-nostdin",
        "-i",
        str(source),
        "-vn",
        "-af",
        f"loudnorm=I={target_lufs:.1f}:TP=-1.5:LRA=11:print_format=json",
        "-f",
        "null",
        "-",
    ]

    pass1_res = run_ffmpeg(pass1_cmd, total_duration=info.duration, as_json=as_json)
    if pass1_res.returncode != 0:
        raise ProcessError(
            f"Audio normalization pass 1 failed with exit code {pass1_res.returncode}."
        )

    # Parse JSON block from stderr
    stderr_text = pass1_res.stderr or ""
    m = re.search(r"\{\s*\"input_i\"\s*:.*?\n\}", stderr_text, re.DOTALL)
    if not m:
        raise ProcessError(
            "Audio normalization pass 1 failed: loudnorm measurement JSON not found in output."
        )

    try:
        measured = json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        raise ProcessError(
            f"Audio normalization pass 1 failed: malformed loudnorm measurement JSON: {exc}"
        ) from None

    if not isinstance(measured, dict):
        raise ProcessError(
            "Audio normalization pass 1 failed: loudnorm measurement JSON must be an object."
        )

    required_keys = ("input_i", "input_tp", "input_lra", "input_thresh")
    missing = [k for k in required_keys if k not in measured]
    if missing:
        missing_str = ", ".join(missing)
        msg = f"Audio normalization pass 1 failed: missing measurement(s): {missing_str}."
        raise ProcessError(msg)

    validated_vals: dict[str, float] = {}
    for key in (*required_keys, "target_offset"):
        if key in measured:
            val_raw = measured[key]
            try:
                val_float = float(val_raw)
            except (ValueError, TypeError):
                msg = (
                    f"Audio normalization pass 1 failed: "
                    f"invalid numeric value for '{key}': {val_raw!r}."
                )
                raise ProcessError(msg) from None
            if not math.isfinite(val_float):
                msg = (
                    f"Audio normalization pass 1 failed: non-finite value for '{key}': {val_raw!r}."
                )
                raise ProcessError(msg)
            validated_vals[key] = val_float

    target_offset_str = str(validated_vals.get("target_offset", 0.0))

    # Pass 2: Apply normalization with strictly validated measurement parameters
    filter_str = (
        f"loudnorm=I={target_lufs:.1f}:TP=-1.5:LRA=11:"
        f"measured_I={validated_vals['input_i']:.2f}:"
        f"measured_TP={validated_vals['input_tp']:.2f}:"
        f"measured_LRA={validated_vals['input_lra']:.2f}:"
        f"measured_thresh={validated_vals['input_thresh']:.2f}:"
        f"offset={target_offset_str}:linear=true"
    )

    fmt_key = ext.lstrip(".").lower()
    enc = AUDIO_CODEC_MAP.get(fmt_key, "aac")

    pass2_cmd = [
        str(backend.ffmpeg_path),
        "-nostdin",
        "-y",
        "-i",
        str(source),
        "-vn",
        "-af",
        filter_str,
        "-c:a",
        enc,
    ]

    with atomic_output(source, "normalized", extension=ext, output=dest) as paths:
        temp_file = paths.temporary
        if temp_file is None:
            raise OutputError("Staging temporary file could not be created.")

        exec_cmd = [*pass2_cmd, str(temp_file)]
        res = run_ffmpeg(exec_cmd, total_duration=info.duration, as_json=as_json)
        if res.returncode != 0:
            raise ProcessError(f"Audio normalization failed with exit code {res.returncode}.")

        out_info = verify_staging_media(temp_file, expected_type="audio")

    if as_json:
        payload = {
            "status": "success",
            "input": str(source),
            "output": str(paths.destination),
            "target_lufs": target_lufs,
            "measured_stats": measured,
            "duration": out_info.duration,
            "size": out_info.size_formatted,
        }
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    else:
        sys.stdout.write(
            f"Normalized '{source.name}' -> '{paths.destination.name}' "
            f"(target {target_lufs:.1f} LUFS, {out_info.size_formatted})\n"
        )
    return 0


def audio_volume(
    input_path: str | os.PathLike[str],
    db: float | None = None,
    output: str | None = None,
    dry_run: bool = False,
    as_json: bool = False,
    verbose: bool = False,
) -> int:
    """Adjust audio volume by gain in decibels (dB)."""
    source = validate_media_input(input_path)
    info = probe_media(source)

    if not info.audio_streams:
        raise InputError(f"Input file '{source.name}' contains no audio streams.")

    if db is None:
        raise UsageError("--db value is required for volume adjustment (e.g. --db -3 or --db 6).")

    try:
        gain_db = float(db)
    except (ValueError, TypeError):
        raise UsageError(f"Invalid volume value: {db!r}. Expected a numeric value in dB.") from None

    if not math.isfinite(gain_db) or gain_db < -60.0 or gain_db > 30.0:
        raise UsageError(f"Volume adjustment must be between -60.0 dB and +30.0 dB: {gain_db}")

    if gain_db > 0 and not dry_run and not as_json:
        sys.stderr.write(
            f"Warning: Increasing volume by +{gain_db:.1f} dB may cause audio clipping "
            f"if peaks exceed 0 dBFS.\n"
        )

    ext = source.suffix if output is None else Path(output).suffix
    if not ext:
        ext = source.suffix or ".mp3"

    dest = resolve_media_output(source, output, suffix="volume", target_ext=ext)

    if dry_run:
        if as_json:
            payload = {
                "dry_run": True,
                "input": str(source),
                "destination": str(dest),
                "gain_db": gain_db,
            }
            sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        else:
            sign = "+" if gain_db > 0 else ""
            sys.stdout.write(
                f"[dry-run] Would adjust volume of '{source.name}' by "
                f"{sign}{gain_db:.1f} dB at: {dest}\n"
            )
        return 0

    backend = get_backend()
    fmt_key = ext.lstrip(".").lower()
    enc = AUDIO_CODEC_MAP.get(fmt_key, "aac")

    cmd = [
        str(backend.ffmpeg_path),
        "-nostdin",
        "-y",
        "-i",
        str(source),
        "-vn",
        "-af",
        f"volume={gain_db:.2f}dB",
        "-c:a",
        enc,
    ]

    with atomic_output(source, "volume", extension=ext, output=dest) as paths:
        temp_file = paths.temporary
        if temp_file is None:
            raise OutputError("Staging temporary file could not be created.")

        exec_cmd = [*cmd, str(temp_file)]
        res = run_ffmpeg(exec_cmd, total_duration=info.duration, as_json=as_json)
        if res.returncode != 0:
            raise ProcessError(f"Volume adjustment failed with exit code {res.returncode}.")

        out_info = verify_staging_media(temp_file, expected_type="audio")

    sign = "+" if gain_db > 0 else ""
    if as_json:
        payload = {
            "status": "success",
            "input": str(source),
            "output": str(paths.destination),
            "gain_db": gain_db,
            "duration": out_info.duration,
            "size": out_info.size_formatted,
        }
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    else:
        sys.stdout.write(
            f"Adjusted volume '{source.name}' ({sign}{gain_db:.1f} dB) -> "
            f"'{paths.destination.name}' ({out_info.size_formatted})\n"
        )
    return 0


def audio_info(
    input_path: str | os.PathLike[str],
    as_json: bool = False,
    verbose: bool = False,
) -> int:
    """Inspect audio stream properties and metadata."""
    source = validate_media_input(input_path)
    info = probe_media(source)

    if as_json:
        sys.stdout.write(json.dumps(info.to_dict(), indent=2) + "\n")
        return 0

    dur_str = info.duration_formatted or "Unknown"
    if info.duration:
        dur_str += f" ({info.duration:.2f} s)"
    br_str = f"{info.bit_rate // 1000} kbps" if info.bit_rate else "Unknown"

    lines = [
        f"File:       {source.name}",
        f"Container:  {info.format_name} ({info.format_long_name})",
        f"Size:       {info.size_formatted} ({info.size_bytes} bytes)",
        f"Duration:   {dur_str}",
        f"Bitrate:    {br_str}",
    ]

    if info.audio_streams:
        lines.append("\nAudio Streams:")
        for a in info.audio_streams:
            br_str = f", {a.bit_rate // 1000} kbps" if a.bit_rate else ""
            lines.append(
                f"  Stream #{a.index}: {a.codec_name.upper()} ({a.codec_long_name}), "
                f"{a.sample_rate} Hz, {a.channels} ch ({a.channel_layout}){br_str}"
            )

    sys.stdout.write("\n".join(lines) + "\n")
    return 0
