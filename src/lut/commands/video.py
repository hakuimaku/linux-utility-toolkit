"""Register video help without launching FFmpeg or FFprobe."""


def register(parser) -> None:
    """Describe planned video transformations and information commands."""
    # State future backend requirements without probing executables.
    dependencies = "Python 3.11+ for help; planned backends: FFmpeg and FFprobe (not checked)."
    # Group every video operation under its own subparser.
    video = parser.add_command(
        "video",
        "Transform and inspect video.",
        dependencies=dependencies,
        examples=("lut video help", "lut video extract-audio help"),
    )
    # Information is read-only; the other operations would produce output files.
    operations = (
        ("convert", "Convert a video format."),
        ("compress", "Compress a video."),
        ("resize", "Resize video frames."),
        ("trim", "Trim a video time range."),
        ("extract-audio", "Extract a video audio stream."),
        ("frames", "Extract video frames."),
        ("gif", "Create a GIF from video."),
        ("info", "Inspect video streams."),
    )
    for name, description in operations:
        # Leave execution unavailable while keeping help and flag scope testable.
        command = video.add_command(
            name,
            description,
            dependencies=dependencies,
            dry_run=name != "info",
            examples=(f'lut video {name} "movie clip.mp4"  # planned; not implemented',),
        )
        command.add_argument("input", help="Input video path (planned input).")
