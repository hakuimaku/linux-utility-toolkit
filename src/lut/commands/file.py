"""Register file-tool help without accessing user files."""


def register(parser) -> None:
    """Describe rename, hash, duplicate search and file information commands."""
    # Keep filesystem operations grouped under the file namespace.
    file = parser.add_command(
        "file",
        "Inspect and organize files.",
        examples=("lut file help", "lut file rename help"),
    )
    # Describe operand cardinality without inspecting or modifying any path.
    operations = (
        (
            "rename",
            "Rename files.",
            "input",
            "+",
            True,
            '"draft one.txt" "draft two.txt" --dry-run',
        ),
        ("hash", "Compute a file content hash.", "input", None, False, '"notes.txt"'),
        ("duplicates", "Find files with identical content.", "path", "?", False, '"my files"'),
        ("info", "Inspect a file.", "input", None, False, '"notes.txt"'),
    )
    for name, description, operand, count, modifies, example in operations:
        # Register input syntax without installing an execution handler.
        command = file.add_command(
            name,
            description,
            dry_run=modifies,
            examples=(f"lut file {name} {example}  # planned; not implemented",),
        )
        command.add_argument(
            operand,
            nargs=count,
            default="." if operand == "path" else None,
            help="Input path (planned input; duplicate search defaults to cwd).",
        )
