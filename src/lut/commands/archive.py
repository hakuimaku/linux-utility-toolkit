"""Register archive help without reading or creating an archive."""


def register(parser) -> None:
    """Describe compression, extraction, listing and archive checks."""
    # Describe optional backends without requiring them for documentation.
    dependencies = "Python 3.11+; planned ZIP/TAR: standard library; 7Z: optional 7z backend."
    # Keep archive operations below a single namespace.
    archive = parser.add_command(
        "archive",
        "Create and inspect archives.",
        dependencies=dependencies,
        examples=("lut archive help", "lut archive extract help"),
    )
    # Only compression and extraction can request a future preview.
    operations = (
        ("compress", "Compress files or directories.", True),
        ("extract", "Extract an archive.", True),
        ("list", "List archive entries.", False),
        ("test", "Check archive integrity.", False),
    )
    for name, description, modifies in operations:
        # Show multiple inputs only where the current parser accepts them.
        example = '"report.txt" "photos"' if name == "compress" else '"backup.tar.gz"'
        # Register syntax only; no archive members are opened or extracted.
        command = archive.add_command(
            name,
            description,
            dependencies=dependencies,
            dry_run=modifies,
            examples=(f"lut archive {name} {example}  # planned; not implemented",),
        )
        command.add_argument(
            "input",
            nargs="+" if name == "compress" else None,
            help="Input path (planned input; compression accepts multiple paths).",
        )
