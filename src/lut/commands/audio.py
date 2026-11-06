"""Register audio help without launching media backends."""


def register(parser) -> None:
    """Describe planned audio transformations and information commands."""
    # Mention future backends without introducing installation requirements for help.
    dependencies = "Python 3.11+ for help; planned backends: FFmpeg and FFprobe (not checked)."
    # Keep audio syntax independent of video syntax.
    audio = parser.add_command(
        "audio",
        "Transform and inspect audio.",
        dependencies=dependencies,
        examples=("lut audio help", "lut audio normalize help"),
    )
    # Information commands do not accept mutation preview options.
    operations = (
        ("convert", "Convert an audio format."),
        ("trim", "Trim an audio time range."),
        ("normalize", "Normalize audio loudness."),
        ("volume", "Adjust audio volume."),
        ("info", "Inspect audio streams."),
    )
    for name, description in operations:
        # Register documentation without adding a processing handler.
        command = audio.add_command(
            name,
            description,
            dependencies=dependencies,
            dry_run=name != "info",
            examples=(f'lut audio {name} "recording.flac"  # planned; not implemented',),
        )
        command.add_argument("input", help="Input audio path (planned input).")
