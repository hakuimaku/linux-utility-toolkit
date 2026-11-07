"""Video service for conversion, compression, resize, trim, audio extraction, frames, and gif."""

import json
import math
import os
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
    COMPRESSION_PRESETS,
    SUPPORTED_AUDIO_FORMATS,
    SUPPORTED_VIDEO_FORMATS,
    VIDEO_CODEC_MAP,
    format_duration,
    format_size,
    get_backend,
    parse_timestamp,
    probe_media,
    resolve_media_output,
    run_ffmpeg,
    validate_media_input,
    verify_staging_media,
)


def video_convert(
    input_path: str | os.PathLike[str],
    fmt: str | None = None,
    codec: str | None = None,
    audio_codec: str | None = None,
    output: str | None = None,
    dry_run: bool = False,
    as_json: bool = False,
    verbose: bool = False,
) -> int:
    """Convert a video to a different container format or codec."""
    source = validate_media_input(input_path)
    info = probe_media(source)

    if not info.video_streams:
        raise InputError(f"Input file '{source.name}' contains no video streams.")

    if fmt is None and output is None:
        raise UsageError("Target format must be specified via --format or inferred from --output.")

    if fmt is None and output is not None:
        target_ext = Path(output).suffix.lstrip(".").lower()
        if not target_ext:
            raise UsageError("Cannot infer format from --output without a file extension.")
        target_fmt = target_ext
    else:
        target_fmt = str(fmt).lower()

    if target_fmt not in SUPPORTED_VIDEO_FORMATS:
        allowed = ", ".join(SUPPORTED_VIDEO_FORMATS)
        raise UsageError(f"Unsupported video format: {target_fmt!r}. Supported: {allowed}")

    # Codec compatibility checks
    vcodec = codec.lower() if codec else None
    acodec = audio_codec.lower() if audio_codec else None

    if vcodec and vcodec not in VIDEO_CODEC_MAP:
        allowed = ", ".join(sorted(VIDEO_CODEC_MAP.keys()))
        raise UsageError(f"Unsupported video codec: {codec!r}. Supported: {allowed}")

    if target_fmt == "webm":
        if vcodec and vcodec not in ("vp8", "vp9", "av1", "copy"):
            msg = f"WebM container does not support '{vcodec}' video codec (use vp9, vp8, or av1)."
            raise UsageError(msg)
        if vcodec == "copy":
            src_vcodec = info.video_streams[0].codec_name.lower()
            if src_vcodec not in ("vp8", "vp9", "av1"):
                msg = f"Cannot copy '{src_vcodec}' video into WebM (requires VP8, VP9, or AV1)."
                raise UsageError(msg)
        if acodec and acodec not in ("opus", "vorbis", "copy"):
            msg = f"WebM container does not support '{acodec}' audio codec (use opus or vorbis)."
            raise UsageError(msg)
        if acodec == "copy" and info.audio_streams:
            src_acodec = info.audio_streams[0].codec_name.lower()
            if src_acodec not in ("opus", "vorbis"):
                msg = f"Cannot copy '{src_acodec}' audio into WebM (requires Opus or Vorbis)."
                raise UsageError(msg)

    # Prevent no-op conversion (same container and same or copy codec)
    src_ext = source.suffix.lstrip(".").lower()
    is_same_v = vcodec == "copy" or vcodec is None
    is_same_a = acodec == "copy" or acodec is None
    if src_ext == target_fmt and is_same_v and is_same_a:
        msg = (
            f"Input is already in {target_fmt.upper()} format. Specify a different format or codec."
        )
        raise UsageError(msg)

    # Determine default encoders
    if vcodec:
        video_encoder = VIDEO_CODEC_MAP[vcodec]
    elif target_fmt == "webm":
        video_encoder = "libvpx-vp9"
    elif target_fmt == "avi":
        video_encoder = "mpeg4"
    else:
        video_encoder = "libx264"

    if acodec:
        audio_encoder = AUDIO_CODEC_MAP.get(acodec, acodec)
    elif target_fmt == "webm":
        audio_encoder = "libopus"
    elif target_fmt == "avi":
        audio_encoder = "libmp3lame"
    else:
        audio_encoder = "aac"

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
                "video_codec": video_encoder,
                "audio_codec": audio_encoder,
            }
            sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        else:
            sys.stdout.write(
                f"[dry-run] Would convert '{source.name}' to {target_fmt.upper()} at: {dest}\n"
            )
        return 0

    backend = get_backend()
    cmd = [
        str(backend.ffmpeg_path),
        "-nostdin",
        "-y",
        "-i",
        str(source),
        "-c:v",
        video_encoder,
    ]

    if info.audio_streams:
        cmd.extend(["-c:a", audio_encoder])

    # Handle subtitles for MP4 / WebM containers safely
    if info.subtitle_streams:
        if target_fmt == "mp4":
            cmd.extend(["-c:s", "mov_text"])
        elif target_fmt == "webm":
            cmd.append("-sn")

    with atomic_output(source, "converted", extension=f".{target_fmt}", output=dest) as paths:
        temp_file = paths.temporary
        if temp_file is None:
            raise OutputError("Staging temporary file could not be created.")

        exec_cmd = [*cmd, str(temp_file)]
        res = run_ffmpeg(exec_cmd, total_duration=info.duration, as_json=as_json)
        if res.returncode != 0:
            raise ProcessError(f"Video conversion failed with exit code {res.returncode}.")

        verify_staging_media(temp_file, expected_type="video")

    final_info = probe_media(paths.destination)
    if as_json:
        payload = {
            "status": "success",
            "input": str(source),
            "output": str(paths.destination),
            "format": target_fmt,
            "duration": final_info.duration,
            "size_bytes": final_info.size_bytes,
            "size": final_info.size_formatted,
        }
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    else:
        sys.stdout.write(
            f"Converted '{source.name}' -> '{paths.destination.name}' "
            f"({target_fmt.upper()}, {final_info.size_formatted})\n"
        )
    return 0


def video_compress(
    input_path: str | os.PathLike[str],
    quality: str = "medium",
    crf: int | None = None,
    preset: str = "medium",
    codec: str | None = None,
    output: str | None = None,
    dry_run: bool = False,
    as_json: bool = False,
    verbose: bool = False,
) -> int:
    """Compress video using CRF and preset parameters."""
    source = validate_media_input(input_path)
    info = probe_media(source)

    if not info.video_streams:
        raise InputError(f"Input file '{source.name}' contains no video streams.")

    q_lower = quality.lower()
    if q_lower not in ("low", "medium", "high"):
        raise UsageError(f"Invalid quality: {quality!r}. Choose from: low, medium, high.")

    preset_lower = preset.lower()
    if preset_lower not in COMPRESSION_PRESETS:
        allowed = ", ".join(COMPRESSION_PRESETS)
        raise UsageError(f"Invalid preset: {preset!r}. Choose from: {allowed}")

    if crf is not None:
        if crf < 0 or crf > 51:
            raise UsageError(f"CRF must be an integer between 0 and 51: {crf}")
        actual_crf = crf
    else:
        crf_map = {"high": 20, "medium": 23, "low": 28}
        actual_crf = crf_map[q_lower]

    vcodec_name = codec.lower() if codec else "h264"
    if vcodec_name not in ("h264", "x264", "hevc", "h265", "x265", "vp9"):
        raise UsageError(f"Unsupported compression codec: {codec!r}. Choose h264, hevc, or vp9.")
    vcodec = VIDEO_CODEC_MAP[vcodec_name]

    # Destination defaults to MP4
    target_ext = ".mp4" if output is None else Path(output).suffix
    if not target_ext:
        target_ext = ".mp4"

    dest = resolve_media_output(source, output, suffix="compressed", target_ext=target_ext)

    if dry_run:
        if as_json:
            payload = {
                "dry_run": True,
                "input": str(source),
                "destination": str(dest),
                "quality": q_lower,
                "crf": actual_crf,
                "preset": preset_lower,
                "codec": vcodec,
            }
            sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        else:
            sys.stdout.write(
                f"[dry-run] Would compress '{source.name}' (CRF {actual_crf}, "
                f"preset {preset_lower}) at: {dest}\n"
            )
        return 0

    backend = get_backend()
    cmd = [
        str(backend.ffmpeg_path),
        "-nostdin",
        "-y",
        "-i",
        str(source),
        "-c:v",
        vcodec,
        "-crf",
        str(actual_crf),
        "-preset",
        preset_lower,
    ]

    if info.audio_streams:
        cmd.extend(["-c:a", "aac", "-b:a", "128k"])

    with atomic_output(source, "compressed", extension=target_ext, output=dest) as paths:
        temp_file = paths.temporary
        if temp_file is None:
            raise OutputError("Staging temporary file could not be created.")

        exec_cmd = [*cmd, str(temp_file)]
        res = run_ffmpeg(exec_cmd, total_duration=info.duration, as_json=as_json)
        if res.returncode != 0:
            raise ProcessError(f"Video compression failed with exit code {res.returncode}.")

        verify_staging_media(temp_file, expected_type="video")

    out_stat = paths.destination.stat()
    in_size = info.size_bytes
    out_size = out_stat.st_size
    diff = in_size - out_size
    reduction_pct = (diff / in_size) * 100.0 if in_size > 0 else 0.0

    if as_json:
        payload = {
            "status": "success",
            "input": str(source),
            "output": str(paths.destination),
            "original_size_bytes": in_size,
            "compressed_size_bytes": out_size,
            "original_size": format_size(in_size),
            "compressed_size": format_size(out_size),
            "size_reduction_bytes": diff,
            "size_reduction_percent": round(reduction_pct, 1),
            "is_smaller": out_size < in_size,
        }
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    else:
        msg = (
            f"Compressed '{source.name}' -> '{paths.destination.name}' "
            f"({format_size(in_size)} -> {format_size(out_size)}"
        )
        if diff > 0:
            msg += f", -{reduction_pct:.1f}%)\n"
        else:
            note_str = format_size(out_size)
            orig_str = format_size(in_size)
            msg += (
                f")\nNote: Compressed file size ({note_str}) "
                f"is not smaller than original ({orig_str}).\n"
            )
        sys.stdout.write(msg)
    return 0


def video_resize(
    input_path: str | os.PathLike[str],
    width: int | None = None,
    height: int | None = None,
    allow_upscale: bool = False,
    output: str | None = None,
    dry_run: bool = False,
    as_json: bool = False,
    verbose: bool = False,
) -> int:
    """Resize video dimensions while preserving aspect ratio."""
    source = validate_media_input(input_path)
    info = probe_media(source)

    if not info.video_streams:
        raise InputError(f"Input file '{source.name}' contains no video streams.")

    if width is None and height is None:
        raise UsageError("At least one dimension (--width or --height) must be specified.")

    if width is not None and width <= 0:
        raise UsageError(f"Width must be a positive integer: {width}")
    if height is not None and height <= 0:
        raise UsageError(f"Height must be a positive integer: {height}")

    src_v = info.video_streams[0]
    orig_w, orig_h = src_v.width, src_v.height

    if not allow_upscale:
        if width is not None and width > orig_w:
            msg = (
                f"Target width ({width}px) exceeds original width ({orig_w}px). "
                f"Use --allow-upscale to permit enlarging."
            )
            raise UsageError(msg)
        if height is not None and height > orig_h:
            msg = (
                f"Target height ({height}px) exceeds original height ({orig_h}px). "
                f"Use --allow-upscale to permit enlarging."
            )
            raise UsageError(msg)

    # Scaling filter with even dimension enforcement (-2)
    if width is not None and height is None:
        scale_filter = f"scale={width}:-2"
    elif height is not None and width is None:
        scale_filter = f"scale=-2:{height}"
    else:
        # Both width and height: fit within box preserving aspect ratio, even dims
        scale_filter = (
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"scale=trunc(iw/2)*2:trunc(ih/2)*2"
        )

    ext = source.suffix if output is None else Path(output).suffix
    if not ext:
        ext = source.suffix or ".mp4"

    dest = resolve_media_output(source, output, suffix="resized", target_ext=ext)

    if dry_run:
        if as_json:
            payload = {
                "dry_run": True,
                "input": str(source),
                "destination": str(dest),
                "original_dimensions": f"{orig_w}x{orig_h}",
                "target_width": width,
                "target_height": height,
                "scale_filter": scale_filter,
            }
            sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        else:
            sys.stdout.write(
                f"[dry-run] Would resize '{source.name}' ({orig_w}x{orig_h}) "
                f"using filter '{scale_filter}' at: {dest}\n"
            )
        return 0

    backend = get_backend()
    cmd = [
        str(backend.ffmpeg_path),
        "-nostdin",
        "-y",
        "-i",
        str(source),
        "-vf",
        scale_filter,
        "-c:v",
        "libx264",
    ]

    if info.audio_streams:
        cmd.extend(["-c:a", "copy"])

    with atomic_output(source, "resized", extension=ext, output=dest) as paths:
        temp_file = paths.temporary
        if temp_file is None:
            raise OutputError("Staging temporary file could not be created.")

        exec_cmd = [*cmd, str(temp_file)]
        res = run_ffmpeg(exec_cmd, total_duration=info.duration, as_json=as_json)
        if res.returncode != 0:
            raise ProcessError(f"Video resize failed with exit code {res.returncode}.")

        out_info = verify_staging_media(temp_file, expected_type="video")

    final_v = out_info.video_streams[0]
    if as_json:
        payload = {
            "status": "success",
            "input": str(source),
            "output": str(paths.destination),
            "original_dimensions": f"{orig_w}x{orig_h}",
            "new_dimensions": f"{final_v.width}x{final_v.height}",
            "size": out_info.size_formatted,
        }
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    else:
        sys.stdout.write(
            f"Resized '{source.name}' ({orig_w}x{orig_h}) -> '{paths.destination.name}' "
            f"({final_v.width}x{final_v.height}, {out_info.size_formatted})\n"
        )
    return 0


def video_trim(
    input_path: str | os.PathLike[str],
    start: str | float | None = "0",
    end: str | float | None = None,
    copy: bool = False,
    output: str | None = None,
    dry_run: bool = False,
    as_json: bool = False,
    verbose: bool = False,
) -> int:
    """Trim a video time range accurately or using stream copy."""
    source = validate_media_input(input_path)
    info = probe_media(source)

    if not info.video_streams:
        raise InputError(f"Input file '{source.name}' contains no video streams.")

    if end is None:
        raise UsageError("--end timestamp is required for video trim.")

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
            msg = f"Start time ({start_sec:.2f}s) exceeds video duration ({info.duration:.2f}s)."
            raise UsageError(msg)
        if end_sec > info.duration:
            msg = f"End time ({end_sec:.2f}s) exceeds video duration ({info.duration:.2f}s)."
            raise UsageError(msg)

    target_duration = end_sec - start_sec
    ext = source.suffix if output is None else Path(output).suffix
    if not ext:
        ext = source.suffix or ".mp4"

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
    # Seeking before -i enables fast and accurate seek with -to
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
    ]

    if copy:
        cmd.extend(["-c", "copy"])
    else:
        cmd.extend(["-c:v", "libx264"])
        if info.audio_streams:
            cmd.extend(["-c:a", "aac"])

    with atomic_output(source, "trimmed", extension=ext, output=dest) as paths:
        temp_file = paths.temporary
        if temp_file is None:
            raise OutputError("Staging temporary file could not be created.")

        exec_cmd = [*cmd, str(temp_file)]
        res = run_ffmpeg(exec_cmd, total_duration=target_duration, as_json=as_json)
        if res.returncode != 0:
            raise ProcessError(f"Video trim failed with exit code {res.returncode}.")

        out_info = verify_staging_media(temp_file, expected_type="video")

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
        note = (
            "\nNote: Trimming with --copy cuts at nearest keyframes and "
            "may not match exact timestamps."
            if copy
            else ""
        )
        s_fmt = format_duration(start_sec)
        e_fmt = format_duration(end_sec)
        sys.stdout.write(
            f"Trimmed '{source.name}' [{s_fmt} -> {e_fmt}] -> "
            f"'{paths.destination.name}' ({out_info.duration_formatted}, "
            f"{out_info.size_formatted}){note}\n"
        )
    return 0


def video_extract_audio(
    input_path: str | os.PathLike[str],
    fmt: str = "mp3",
    stream: int = 0,
    output: str | None = None,
    dry_run: bool = False,
    as_json: bool = False,
    verbose: bool = False,
) -> int:
    """Extract an audio stream from a video into an audio file."""
    source = validate_media_input(input_path)
    info = probe_media(source)

    if not info.audio_streams:
        raise InputError(f"Video '{source.name}' contains no audio streams.")

    if stream < 0 or stream >= len(info.audio_streams):
        count = len(info.audio_streams)
        msg = (
            f"Audio stream index {stream} out of range "
            f"(found {count} audio stream(s); 0 to {count - 1})."
        )
        raise UsageError(msg)

    target_fmt = fmt.lower()
    if target_fmt not in SUPPORTED_AUDIO_FORMATS:
        allowed = ", ".join(SUPPORTED_AUDIO_FORMATS)
        raise UsageError(f"Unsupported audio format: {fmt!r}. Supported: {allowed}")

    audio_codec = AUDIO_CODEC_MAP[target_fmt]
    dest = resolve_media_output(
        source, output, suffix="extracted", target_ext=f".{target_fmt}", is_convert=True
    )

    if dry_run:
        if as_json:
            payload = {
                "dry_run": True,
                "input": str(source),
                "destination": str(dest),
                "audio_stream_index": stream,
                "format": target_fmt,
                "codec": audio_codec,
            }
            sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        else:
            sys.stdout.write(
                f"[dry-run] Would extract audio stream #{stream} from '{source.name}' "
                f"to {target_fmt.upper()} at: {dest}\n"
            )
        return 0

    backend = get_backend()
    cmd = [
        str(backend.ffmpeg_path),
        "-nostdin",
        "-y",
        "-i",
        str(source),
        "-map",
        f"0:a:{stream}",
        "-vn",
        "-c:a",
        audio_codec,
    ]

    with atomic_output(source, "extracted", extension=f".{target_fmt}", output=dest) as paths:
        temp_file = paths.temporary
        if temp_file is None:
            raise OutputError("Staging temporary file could not be created.")

        exec_cmd = [*cmd, str(temp_file)]
        res = run_ffmpeg(exec_cmd, total_duration=info.duration, as_json=as_json)
        if res.returncode != 0:
            raise ProcessError(f"Audio extraction failed with exit code {res.returncode}.")

        out_info = verify_staging_media(temp_file, expected_type="audio")

    src_codec = info.audio_streams[stream].codec_name.lower()
    lossy_src = src_codec in ("aac", "mp3", "vorbis", "opus")
    lossless_tgt = target_fmt in ("flac", "wav")
    is_lossy_to_lossless = lossy_src and lossless_tgt

    if as_json:
        payload = {
            "status": "success",
            "input": str(source),
            "output": str(paths.destination),
            "stream_index": stream,
            "format": target_fmt,
            "duration": out_info.duration,
            "size": out_info.size_formatted,
            "lossy_to_lossless": is_lossy_to_lossless,
        }
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    else:
        note = (
            "\nNote: Extracting lossy audio to a lossless container "
            "does not improve audio fidelity."
            if is_lossy_to_lossless
            else ""
        )
        sys.stdout.write(
            f"Extracted audio #{stream} from '{source.name}' -> '{paths.destination.name}' "
            f"({target_fmt.upper()}, {out_info.size_formatted}){note}\n"
        )
    return 0


def video_frames(
    input_path: str | os.PathLike[str],
    fps: float = 1.0,
    fmt: str = "png",
    max_frames: int = 1000,
    output: str | None = None,
    dry_run: bool = False,
    as_json: bool = False,
    verbose: bool = False,
) -> int:
    """Extract video frames into sequentially numbered image files."""
    source = validate_media_input(input_path)
    info = probe_media(source)

    if not info.video_streams:
        raise InputError(f"Input file '{source.name}' contains no video streams.")

    if fps <= 0 or not math.isfinite(fps):
        raise UsageError(f"FPS must be a positive number: {fps}")

    frame_fmt = fmt.lower()
    if frame_fmt not in ("png", "jpg", "jpeg"):
        raise UsageError(f"Unsupported frame format: {fmt!r}. Supported: png, jpg")
    frame_ext = "jpg" if frame_fmt in ("jpg", "jpeg") else "png"

    if max_frames <= 0:
        raise UsageError(f"Max frames limit must be positive: {max_frames}")

    if info.duration is not None and info.duration > 0:
        est_frames = int(math.ceil(info.duration * fps))
        if est_frames > max_frames:
            msg = (
                f"Estimated frame count ({est_frames}) exceeds limit of {max_frames}. "
                f"Use a lower --fps or specify a higher --max-frames."
            )
            raise UsageError(msg)

    dest = resolve_media_output(source, output, suffix="frames", target_ext="", directory=True)

    est_frames = (
        int(math.ceil(info.duration * fps))
        if (info.duration is not None and info.duration > 0)
        else None
    )

    if dry_run:
        if as_json:
            payload = {
                "dry_run": True,
                "input": str(source),
                "destination_directory": str(dest),
                "fps": fps,
                "format": frame_ext,
                "max_frames": max_frames,
                "estimated_frames": est_frames,
            }
            sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        else:
            est_str = f" (estimated: {est_frames})" if est_frames is not None else ""
            sys.stdout.write(
                f"[dry-run] Would extract frames at {fps} FPS ({frame_ext.upper()}) "
                f"from '{source.name}' to directory: {dest} (max {max_frames} frames){est_str}\n"
            )
        return 0

    backend = get_backend()
    with atomic_output(source, "frames", directory=True, output=dest) as paths:
        temp_dir = paths.temporary
        if temp_dir is None:
            raise OutputError("Staging temporary directory could not be created.")

        frame_pattern = str(temp_dir / f"frame_%04d.{frame_ext}")
        cmd = [
            str(backend.ffmpeg_path),
            "-nostdin",
            "-y",
            "-i",
            str(source),
            "-vf",
            f"fps={fps}",
            "-frames:v",
            str(max_frames),
            frame_pattern,
        ]

        res = run_ffmpeg(cmd, total_duration=info.duration, as_json=as_json)
        if res.returncode != 0:
            raise ProcessError(f"Frame extraction failed with exit code {res.returncode}.")

        extracted = sorted(temp_dir.glob(f"frame_*.{frame_ext}"))
        if not extracted:
            raise ProcessError("No frames were extracted by FFmpeg.")
        if len(extracted) > max_frames:
            raise ProcessError(
                f"Extracted frames ({len(extracted)}) exceeded limit ({max_frames})."
            )

    count = len(extracted)
    if as_json:
        payload = {
            "status": "success",
            "input": str(source),
            "output_directory": str(paths.destination),
            "frame_count": count,
            "format": frame_ext,
            "fps": fps,
        }
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    else:
        sys.stdout.write(
            f"Extracted {count} frame(s) from '{source.name}' -> '{paths.destination.name}/' "
            f"({fps} FPS, {frame_ext.upper()})\n"
        )
    return 0


def video_gif(
    input_path: str | os.PathLike[str],
    start: str | float | None = "0",
    duration: float = 3.0,
    fps: int = 15,
    width: int = 480,
    output: str | None = None,
    dry_run: bool = False,
    as_json: bool = False,
    verbose: bool = False,
) -> int:
    """Create a high-quality GIF using two-pass palette generation."""
    source = validate_media_input(input_path)
    info = probe_media(source)

    if not info.video_streams:
        raise InputError(f"Input file '{source.name}' contains no video streams.")

    start_sec = parse_timestamp(start if start is not None else 0)
    dur_sec = float(duration)

    if start_sec < 0:
        raise UsageError(f"Start time must be >= 0: {start_sec}")
    if dur_sec <= 0 or not math.isfinite(dur_sec):
        raise UsageError(f"Duration must be a positive number: {dur_sec}")
    if dur_sec > 30.0:
        raise UsageError(f"GIF duration cannot exceed 30 seconds (requested: {dur_sec}s).")

    if fps <= 0 or fps > 60:
        raise UsageError(f"FPS must be between 1 and 60: {fps}")
    if width <= 0:
        raise UsageError(f"Width must be a positive integer: {width}")

    if info.duration is not None and info.duration > 0:
        if start_sec >= info.duration:
            msg = f"Start time ({start_sec:.2f}s) exceeds video duration ({info.duration:.2f}s)."
            raise UsageError(msg)
        if start_sec + dur_sec > info.duration:
            msg = (
                f"Requested interval ({start_sec:.2f}s + {dur_sec:.2f}s) exceeds "
                f"video duration ({info.duration:.2f}s)."
            )
            raise UsageError(msg)

    dest = resolve_media_output(source, output, suffix="gif", target_ext=".gif")

    if dry_run:
        if as_json:
            payload = {
                "dry_run": True,
                "input": str(source),
                "destination": str(dest),
                "start": start_sec,
                "duration": dur_sec,
                "fps": fps,
                "width": width,
            }
            sys.stdout.write(json.dumps(payload, indent=2) + "\n")
        else:
            sys.stdout.write(
                f"[dry-run] Would generate GIF from '{source.name}' [{format_duration(start_sec)}, "
                f"duration {dur_sec}s, {width}px, {fps}fps] at: {dest}\n"
            )
        return 0

    backend = get_backend()
    filter_graph = (
        f"[0:v] fps={fps},scale={width}:-1:flags=lanczos,split [a][b]; "
        f"[a] palettegen [p]; [b][p] paletteuse"
    )

    cmd = [
        str(backend.ffmpeg_path),
        "-nostdin",
        "-y",
        "-ss",
        f"{start_sec:.3f}",
        "-t",
        f"{dur_sec:.3f}",
        "-i",
        str(source),
        "-filter_complex",
        filter_graph,
    ]

    with atomic_output(source, "gif", extension=".gif", output=dest) as paths:
        temp_file = paths.temporary
        if temp_file is None:
            raise OutputError("Staging temporary file could not be created.")

        exec_cmd = [*cmd, str(temp_file)]
        res = run_ffmpeg(exec_cmd, total_duration=dur_sec, as_json=as_json)
        if res.returncode != 0:
            raise ProcessError(f"GIF generation failed with exit code {res.returncode}.")

        verify_staging_media(temp_file, min_size=10)

    out_stat = paths.destination.stat()
    if as_json:
        payload = {
            "status": "success",
            "input": str(source),
            "output": str(paths.destination),
            "start": start_sec,
            "duration": dur_sec,
            "fps": fps,
            "width": width,
            "size_bytes": out_stat.st_size,
            "size": format_size(out_stat.st_size),
        }
        sys.stdout.write(json.dumps(payload, indent=2) + "\n")
    else:
        sys.stdout.write(
            f"Created GIF '{source.name}' -> '{paths.destination.name}' "
            f"({dur_sec}s, {width}px, {format_size(out_stat.st_size)})\n"
        )
    return 0


def video_info(
    input_path: str | os.PathLike[str],
    as_json: bool = False,
    verbose: bool = False,
) -> int:
    """Inspect video streams, container metadata, and properties."""
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

    if info.video_streams:
        lines.append("\nVideo Streams:")
        for v in info.video_streams:
            fps_str = f"{v.fps:.2f} fps" if v.fps else "variable fps"
            br_str = f", {v.bit_rate // 1000} kbps" if v.bit_rate else ""
            lines.append(
                f"  Stream #{v.index}: {v.codec_name.upper()} ({v.codec_long_name}), "
                f"{v.width}x{v.height} ({v.aspect_ratio or 'N/A'}), {fps_str}, "
                f"{v.pixel_format}{br_str}"
            )

    if info.audio_streams:
        lines.append("\nAudio Streams:")
        for a in info.audio_streams:
            br_str = f", {a.bit_rate // 1000} kbps" if a.bit_rate else ""
            lines.append(
                f"  Stream #{a.index}: {a.codec_name.upper()} ({a.codec_long_name}), "
                f"{a.sample_rate} Hz, {a.channels} ch ({a.channel_layout}){br_str}"
            )

    if info.subtitle_streams:
        lines.append("\nSubtitle Streams:")
        for s in info.subtitle_streams:
            lang_str = f" [{s.language}]" if s.language else ""
            lines.append(f"  Stream #{s.index}: {s.codec_name.upper()}{lang_str}")

    sys.stdout.write("\n".join(lines) + "\n")
    return 0
