"""Register and handle audio conversion, trimming, normalization, volume, and stream inspection."""

import argparse

from lut.services.audio_service import (
    audio_convert,
    audio_info,
    audio_normalize,
    audio_trim,
    audio_volume,
)


def _handle_convert(args: argparse.Namespace) -> int:
    """Handle audio format conversion."""
    return audio_convert(
        input_path=args.input,
        fmt=args.format,
        bitrate=args.bitrate,
        output=args.output,
        dry_run=args.dry_run,
        as_json=args.json,
        verbose=args.verbose,
    )


def _handle_trim(args: argparse.Namespace) -> int:
    """Handle audio trimming."""
    return audio_trim(
        input_path=args.input,
        start=args.start,
        end=args.end,
        copy=args.copy,
        output=args.output,
        dry_run=args.dry_run,
        as_json=args.json,
        verbose=args.verbose,
    )


def _handle_normalize(args: argparse.Namespace) -> int:
    """Handle audio loudness normalization."""
    return audio_normalize(
        input_path=args.input,
        target_lufs=args.target_lufs,
        output=args.output,
        dry_run=args.dry_run,
        as_json=args.json,
        verbose=args.verbose,
    )


def _handle_volume(args: argparse.Namespace) -> int:
    """Handle audio volume adjustment."""
    return audio_volume(
        input_path=args.input,
        db=args.db,
        output=args.output,
        dry_run=args.dry_run,
        as_json=args.json,
        verbose=args.verbose,
    )


def _handle_info(args: argparse.Namespace) -> int:
    """Handle audio metadata inspection."""
    return audio_info(
        input_path=args.input,
        as_json=args.json,
        verbose=args.verbose,
    )


def register(parser) -> None:
    """Register audio command group and operational subcommands."""
    dependencies = "Python 3.11+; FFmpeg and FFprobe."

    audio = parser.add_command(
        "audio",
        "Convert, trim, normalize, adjust volume, and inspect audio.",
        status="",
        dependencies=dependencies,
        examples=(
            "lut audio convert track.flac --format mp3",
            "lut audio trim podcast.mp3 --start 01:00 --end 05:00",
            "lut audio normalize voice.wav",
            "lut audio volume recording.mp3 --db 3.0",
            "lut audio info track.mp3",
            "lut audio help",
        ),
    )

    # 1. audio convert
    cmd_convert = audio.add_command(
        "convert",
        "Convert an audio format and codec.",
        handler=_handle_convert,
        dry_run=True,
        dependencies=dependencies,
        default_output="<input>.<format> beside input; collisions numbered (<input>_2.<format>)",
        examples=(
            "lut audio convert song.wav --format mp3",
            "lut audio convert podcast.wav --format mp3 --bitrate 192k",
            "lut audio convert song.mp3 --format flac",
            "lut audio convert track.flac --format ogg --bitrate 160k",
            "lut audio convert song.wav --output out.opus",
            "lut audio convert song.wav --format mp3 --dry-run",
        ),
    )
    cmd_convert.add_argument("input", help="Input audio file path.")
    cmd_convert.add_argument(
        "-f",
        "--format",
        choices=["mp3", "wav", "flac", "ogg", "opus"],
        default=None,
        help="Target audio format (default: inferred from --output).",
    )
    cmd_convert.add_argument(
        "-b",
        "--bitrate",
        default=None,
        help="Target audio bitrate for lossy formats (e.g. 128k, 192k, 320k).",
    )
    cmd_convert.add_argument(
        "-o",
        "--output",
        default=None,
        help="Override default output destination path.",
    )
    cmd_convert.add_argument(
        "--json",
        action="store_true",
        help="Output result in JSON format.",
    )

    # 2. audio trim
    cmd_trim = audio.add_command(
        "trim",
        "Trim an audio time range.",
        handler=_handle_trim,
        dry_run=True,
        dependencies=dependencies,
        default_output="<input>_trimmed.<ext> beside input; collisions numbered",
        examples=(
            "lut audio trim voice.mp3 --start 10 --end 30",
            "lut audio trim podcast.mp3 --start 01:30 --end 04:00",
            "lut audio trim sample.wav --start 00:00:15 --end 00:00:45",
            "lut audio trim podcast.mp3 --start 10 --end 60 --copy",
            "lut audio trim voice.mp3 --start 5 --end 25 --dry-run",
        ),
    )
    cmd_trim.add_argument("input", help="Input audio file path to trim.")
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
        help="Fast stream copy without re-encoding (cuts at packet boundaries).",
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

    # 3. audio normalize
    cmd_norm = audio.add_command(
        "normalize",
        "Normalize audio loudness using EBU R128 (loudnorm).",
        handler=_handle_normalize,
        dry_run=True,
        dependencies=dependencies,
        default_output="<input>_normalized.<ext> beside input; collisions numbered",
        examples=(
            "lut audio normalize voice.wav",
            "lut audio normalize podcast.mp3 --target-lufs -14.0",
            "lut audio normalize voice.wav --output master.wav",
            "lut audio normalize voice.wav --dry-run",
        ),
    )
    cmd_norm.add_argument("input", help="Input audio file path to normalize.")
    cmd_norm.add_argument(
        "--target-lufs",
        type=float,
        default=-16.0,
        help="Integrated loudness target in LUFS (-70.0 to -5.0; default: -16.0).",
    )
    cmd_norm.add_argument(
        "-o",
        "--output",
        default=None,
        help="Override default output destination path.",
    )
    cmd_norm.add_argument(
        "--json",
        action="store_true",
        help="Output result in JSON format.",
    )

    # 4. audio volume
    cmd_vol = audio.add_command(
        "volume",
        "Adjust audio volume gain by decibels (dB).",
        handler=_handle_volume,
        dry_run=True,
        dependencies=dependencies,
        default_output="<input>_volume.<ext> beside input; collisions numbered",
        examples=(
            "lut audio volume recording.mp3 --db 3.0",
            "lut audio volume song.wav --db -6.0",
            "lut audio volume track.flac --db +2.5 --output louder.flac",
            "lut audio volume recording.mp3 --db 3.0 --dry-run",
        ),
    )
    cmd_vol.add_argument("input", help="Input audio file path to adjust.")
    cmd_vol.add_argument(
        "--db",
        type=float,
        required=True,
        help="Volume adjustment gain in dB (e.g. -3.0 or +6.0).",
    )
    cmd_vol.add_argument(
        "-o",
        "--output",
        default=None,
        help="Override default output destination path.",
    )
    cmd_vol.add_argument(
        "--json",
        action="store_true",
        help="Output result in JSON format.",
    )

    # 5. audio info
    cmd_info = audio.add_command(
        "info",
        "Inspect audio stream properties and metadata.",
        handler=_handle_info,
        dependencies=dependencies,
        examples=(
            "lut audio info track.mp3",
            "lut audio info song.flac --json",
        ),
    )
    cmd_info.add_argument("input", help="Input audio file path to inspect.")
    cmd_info.add_argument(
        "--json",
        action="store_true",
        help="Output result in JSON format.",
    )
