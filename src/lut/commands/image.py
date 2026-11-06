"""Register image documentation without invoking ImageMagick."""


def register(parser) -> None:
    """Describe planned image operations and their input arguments."""
    # List future operations and allow preview flags only for modifying commands.
    operations = (
        ("convert", "Convert an image format.", True),
        ("compress", "Compress an image.", True),
        ("resize", "Resize an image.", True),
        ("crop", "Crop an image.", True),
        ("rotate", "Rotate an image.", True),
        ("metadata", "Inspect image metadata.", False),
    )
    # State backend requirements as documentation rather than executable checks.
    dependencies = "Python 3.11+ for help; planned backend: ImageMagick (not checked)."
    # Group all image help under a nested argparse command.
    image = parser.add_command(
        "image",
        "Convert and inspect images.",
        dependencies=dependencies,
        examples=("lut image help", "lut image convert help"),
    )
    for name, description, modifies in operations:
        # Register metadata only; no callable handler means execution is unavailable.
        command = image.add_command(
            name,
            description,
            dependencies=dependencies,
            dry_run=modifies,
            examples=(f'lut image {name} "holiday photo.png"  # planned; not implemented',),
        )
        command.add_argument("input", help="Input image path (planned input).")
