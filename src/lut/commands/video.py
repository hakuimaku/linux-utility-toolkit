"""Register and handle video conversion, compression, resize, trim, extraction, and info."""

import argparse

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


def _handle_convert(args: argparse.Namespace) -> int:
    """Handle video conversion."""
    return video_convert(
        input_path=args.input,
        fmt=args.format,
        codec=args.codec,
        audio_codec=args.audio_codec,
        output=args.output,
        dry_run=args.dry_run,
        as_json=args.json,
        verbose=args.verbose,
    )


def _handle_compress(args: argparse.Namespace) -> int:
    """Handle video compression."""
    return video_compress(
        input_path=args.input,
        quality=args.quality,
        crf=args.crf,
        preset=args.preset,
        codec=args.codec,
        output=args.output,
        dry_run=args.dry_run,
        as_json=args.json,
        verbose=args.verbose,
    )


def _handle_resize(args: argparse.Namespace) -> int:
    """Handle video resizing."""
    return video_resize(
        input_path=args.input,
        width=args.width,
        height=args.height,
        allow_upscale=args.allow_upscale,
        output=args.output,
        dry_run=args.dry_run,
        as_json=args.json,
        verbose=args.verbose,
    )


def _handle_trim(args: argparse.Namespace) -> int:
    """Handle video trimming."""
    return video_trim(
        input_path=args.input,
        start=args.start,
        end=args.end,
        copy=args.copy,
        output=args.output,
        dry_run=args.dry_run,
        as_json=args.json,
        verbose=args.verbose,
    )


def _handle_extract_audio(args: argparse.Namespace) -> int:
    """Handle audio extraction from video."""
    return video_extract_audio(
        input_path=args.input,
        fmt=args.format,
        stream=args.stream,
        output=args.output,
        dry_run=args.dry_run,
        as_json=args.json,
        verbose=args.verbose,
    )


def _handle_frames(args: argparse.Namespace) -> int:
    """Handle video frame extraction."""
    return video_frames(
        input_path=args.input,
        fps=args.fps,
        fmt=args.format,
        max_frames=args.max_frames,
        output=args.output,
        dry_run=args.dry_run,
        as_json=args.json,
        verbose=args.verbose,
    )


def _handle_gif(args: argparse.Namespace) -> int:
    """Handle GIF creation from video."""
    return video_gif(
        input_path=args.input,
        start=args.start,
        duration=args.duration,
        fps=args.fps,
        width=args.width,
        output=args.output,
        dry_run=args.dry_run,
        as_json=args.json,
        verbose=args.verbose,
    )


def _handle_info(args: argparse.Namespace) -> int:
    """Handle video inspection."""
    return video_info(
        input_path=args.input,
        as_json=args.json,
        verbose=args.verbose,
    )


def register(parser) -> None:
    """Register video command group and operational subcommands."""
    dependencies = "Python 3.11+; FFmpeg and FFprobe."

    video = parser.add_command(
        "video",
        "Convert, compress, resize, trim, extract, and inspect videos.",
        status="",
        dependencies=dependencies,
        examples=(
            "lut video convert movie.mkv --format mp4",
            "lut video compress clip.mp4 --quality medium",
            "lut video resize recording.mp4 --width 1280",
            "lut video trim presentation.mp4 --start 01:00 --end 02:30",
            "lut video extract-audio concert.mp4 --format mp3",
            "lut video frames animation.mp4 --fps 1",
            "lut video gif reaction.mp4 --start 5 --duration 3",
            "lut video info movie.mp4",
            "lut video help",
        ),
    )

    # 1. video convert
    cmd_convert = video.add_command(
        "convert",
        "Convert a video container format and codecs.",
        handler=_handle_convert,
        dry_run=True,
        dependencies=dependencies,
        default_output="<input>.<format> beside input; collisions numbered (<input>_2.<format>)",
        examples=(
            "lut video convert clip.mkv --format mp4",
            "lut video convert clip.mp4 --format webm",
            "lut video convert clip.avi --format mp4 --codec h264",
            "lut video convert clip.mp4 --format mkv --codec copy",
            "lut video convert clip.mkv --output out.mp4",
            "lut video convert clip.mkv --format mp4 --dry-run",
        ),
    )
    cmd_convert.add_argument("input", help="Input video file path.")
    cmd_convert.add_argument(
        "-f",
        "--format",
        choices=["mp4", "mkv", "webm", "avi", "mov"],
        default=None,
        help="Target container format (default: inferred from --output).",
    )
    cmd_convert.add_argument(
        "-c",
        "--codec",
        default=None,
        help="Target video codec (e.g. h264, hevc, vp8, vp9, av1, copy).",
    )
    cmd_convert.add_argument(
        "--audio-codec",
        default=None,
        help="Target audio codec (e.g. aac, opus, vorbis, mp3, flac, copy).",
    )
    cmd_convert.add_argument(
        "-o",
        "--output",
        default=None,
        help="Override default output video destination path.",
    )
    cmd_convert.add_argument(
        "--json",
        action="store_true",
        help="Output result in JSON format.",
    )

    # 2. video compress
    cmd_compress = video.add_command(
        "compress",
        "Compress a video to reduce file size.",
        handler=_handle_compress,
        dry_run=True,
        dependencies=dependencies,
        default_output="<input>_compressed.mp4 beside input; collisions numbered",
        examples=(
            "lut video compress movie.mp4",
            "lut video compress movie.mp4 --quality low",
            "lut video compress movie.mp4 --crf 28 --preset slow",
            "lut video compress movie.mp4 --output small.mp4",
            "lut video compress movie.mp4 --dry-run",
        ),
    )
    cmd_compress.add_argument("input", help="Input video file path to compress.")
    cmd_compress.add_argument(
        "-q",
        "--quality",
        choices=["low", "medium", "high"],
        default="medium",
        help="Quality profile (low=CRF 28, medium=CRF 23, high=CRF 20; default: medium).",
    )
    cmd_compress.add_argument(
        "--crf",
        type=int,
        default=None,
        help="Explicit Constant Rate Factor (0-51; overrides --quality).",
    )
    cmd_compress.add_argument(
        "--preset",
        choices=[
            "ultrafast",
            "superfast",
            "veryfast",
            "faster",
            "fast",
            "medium",
            "slow",
            "slower",
            "veryslow",
        ],
        default="medium",
        help="Encoder speed/efficiency preset (default: medium).",
    )
    cmd_compress.add_argument(
        "-c",
        "--codec",
        default=None,
        help="Video encoder codec (e.g. h264, hevc, vp9; default: h264).",
    )
    cmd_compress.add_argument(
        "-o",
        "--output",
        default=None,
        help="Override default output destination path.",
    )
    cmd_compress.add_argument(
        "--json",
        action="store_true",
        help="Output result in JSON format.",
    )

    # 3. video resize
    cmd_resize = video.add_command(
        "resize",
        "Resize video frame dimensions.",
        handler=_handle_resize,
        dry_run=True,
        dependencies=dependencies,
        default_output="<input>_resized.<ext> beside input; collisions numbered",
        examples=(
            "lut video resize clip.mp4 --width 1280",
            "lut video resize clip.mp4 --height 720",
            "lut video resize clip.mp4 --width 1920 --height 1080",
            "lut video resize clip.mp4 --width 2560 --allow-upscale",
            "lut video resize clip.mp4 --width 1280 --dry-run",
        ),
    )
    cmd_resize.add_argument("input", help="Input video file path to resize.")
    cmd_resize.add_argument(
        "-w",
        "--width",
        type=int,
        default=None,
        help="Target video width in pixels (aspect ratio maintained if height omitted).",
    )
    cmd_resize.add_argument(
        "--height",
        type=int,
        default=None,
        help="Target video height in pixels (aspect ratio maintained if width omitted).",
    )
    cmd_resize.add_argument(
        "--allow-upscale",
        action="store_true",
        help="Permit enlarging video beyond original dimensions.",
    )
    cmd_resize.add_argument(
        "-o",
        "--output",
        default=None,
        help="Override default output destination path.",
    )
    cmd_resize.add_argument(
        "--json",
        action="store_true",
        help="Output result in JSON format.",
    )

    # 4. video trim
    cmd_trim = video.add_command(
        "trim",
        "Trim a video time range.",
        handler=_handle_trim,
        dry_run=True,
        dependencies=dependencies,
        default_output="<input>_trimmed.<ext> beside input; collisions numbered",
        examples=(
            "lut video trim clip.mp4 --start 10 --end 30",
            "lut video trim clip.mp4 --start 01:15 --end 02:45",
            "lut video trim clip.mp4 --start 00:01:00 --end 00:02:00",
            "lut video trim clip.mp4 --start 5 --end 15 --copy",
            "lut video trim clip.mp4 --start 10 --end 20 --dry-run",
        ),
    )
    cmd_trim.add_argument("input", help="Input video file path to trim.")
    cmd_trim.add_argument(
        "-s",
        "--start",
        default="0",
        help="Start timestamp in seconds, MM:SS, or HH:MM:SS (default: 0).",
    )
    cmd_trim.add_argument(
        "-e",
        "--end",
        required=True,
        help="End timestamp in seconds, MM:SS, or HH:MM:SS (required).",
    )
    cmd_trim.add_argument(
        "--copy",
        action="store_true",
        help="Fast keyframe stream copy without re-encoding (cuts at nearest I-frames).",
    )
    cmd_trim.add_argument(
        "-o",
        "--output",
        default=None,
        help="Override default output destination path.",
    )
    cmd_trim.add_argument(
        "--json",
        action="store_true",
        help="Output result in JSON format.",
    )

    # 5. video extract-audio
    cmd_extract = video.add_command(
        "extract-audio",
        "Extract an audio stream from video.",
        handler=_handle_extract_audio,
        dry_run=True,
        dependencies=dependencies,
        default_output="<input>.<format> beside input; collisions numbered (<input>_2.<format>)",
        examples=(
            "lut video extract-audio clip.mp4",
            "lut video extract-audio clip.mp4 --format wav",
            "lut video extract-audio clip.mkv --format flac --stream 1",
            "lut video extract-audio clip.mp4 --output audio.mp3",
            "lut video extract-audio clip.mp4 --dry-run",
        ),
    )
    cmd_extract.add_argument("input", help="Input video file path.")
    cmd_extract.add_argument(
        "-f",
        "--format",
        choices=["mp3", "wav", "flac", "opus"],
        default="mp3",
        help="Target audio format (default: mp3).",
    )
    cmd_extract.add_argument(
        "--stream",
        type=int,
        default=0,
        help="Index of audio stream to extract (0-indexed; default: 0).",
    )
    cmd_extract.add_argument(
        "-o",
        "--output",
        default=None,
        help="Override default output destination path.",
    )
    cmd_extract.add_argument(
        "--json",
        action="store_true",
        help="Output result in JSON format.",
    )

    # 6. video frames
    cmd_frames = video.add_command(
        "frames",
        "Extract video frames as sequence of image files.",
        handler=_handle_frames,
        dry_run=True,
        dependencies=dependencies,
        default_output="<input>_frames/ directory beside input; collisions numbered",
        examples=(
            "lut video frames clip.mp4 --fps 1",
            "lut video frames clip.mp4 --fps 0.5 --format jpg",
            "lut video frames clip.mp4 --fps 2 --max-frames 500",
            "lut video frames clip.mp4 --output ./my_frames",
            "lut video frames clip.mp4 --fps 1 --dry-run",
        ),
    )
    cmd_frames.add_argument("input", help="Input video file path.")
    cmd_frames.add_argument(
        "--fps",
        type=float,
        default=1.0,
        help="Frame extraction rate in frames per second (default: 1.0).",
    )
    cmd_frames.add_argument(
        "-f",
        "--format",
        choices=["png", "jpg", "jpeg"],
        default="png",
        help="Output image format for extracted frames (default: png).",
    )
    cmd_frames.add_argument(
        "--max-frames",
        type=int,
        default=1000,
        help="Safety ceiling for extracted frame count (default: 1000).",
    )
    cmd_frames.add_argument(
        "-o",
        "--output",
        default=None,
        help="Override default output directory path.",
    )
    cmd_frames.add_argument(
        "--json",
        action="store_true",
        help="Output result in JSON format.",
    )

    # 7. video gif
    cmd_gif = video.add_command(
        "gif",
        "Create an animated GIF from a video clip.",
        handler=_handle_gif,
        dry_run=True,
        dependencies=dependencies,
        default_output="<input>_gif.gif beside input; collisions numbered",
        examples=(
            "lut video gif clip.mp4 --start 5 --duration 3",
            "lut video gif clip.mp4 --start 00:10 --duration 2.5 --fps 20",
            "lut video gif clip.mp4 --start 2 --duration 4 --width 320",
            "lut video gif clip.mp4 --start 0 --duration 3 --output reaction.gif",
            "lut video gif clip.mp4 --start 5 --duration 3 --dry-run",
        ),
    )
    cmd_gif.add_argument("input", help="Input video file path.")
    cmd_gif.add_argument(
        "-s",
        "--start",
        default="0",
        help="Start timestamp in seconds, MM:SS, or HH:MM:SS (default: 0).",
    )
    cmd_gif.add_argument(
        "-d",
        "--duration",
        type=float,
        default=3.0,
        help="GIF duration in seconds (default: 3.0; max: 30.0).",
    )
    cmd_gif.add_argument(
        "--fps",
        type=int,
        default=15,
        help="GIF frame rate in frames per second (default: 15).",
    )
    cmd_gif.add_argument(
        "-w",
        "--width",
        type=int,
        default=480,
        help="GIF width in pixels; height preserves aspect ratio (default: 480).",
    )
    cmd_gif.add_argument(
        "-o",
        "--output",
        default=None,
        help="Override default output GIF destination path.",
    )
    cmd_gif.add_argument(
        "--json",
        action="store_true",
        help="Output result in JSON format.",
    )

    # 8. video info
    cmd_info = video.add_command(
        "info",
        "Inspect video streams and container metadata.",
        handler=_handle_info,
        dependencies=dependencies,
        examples=(
            "lut video info movie.mp4",
            "lut video info movie.mkv --json",
        ),
    )
    cmd_info.add_argument("input", help="Input video file path to inspect.")
    cmd_info.add_argument(
        "--json",
        action="store_true",
        help="Output result in JSON format.",
    )
