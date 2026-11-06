"""Register search documentation without invoking a search backend."""


def register(parser) -> None:
    """Describe content and filename searches as unavailable operations."""
    # Show the intended backend without probing PATH during help.
    dependencies = "Python 3.11+ for help; planned backend: ripgrep (not checked)."
    # Keep search operations below their own argparse subparser.
    search = parser.add_command(
        "search",
        "Search file contents or names.",
        dependencies=dependencies,
        examples=("lut search help", "lut search content --help", "lut search name --help"),
    )
    # Document content search inputs while leaving execution unavailable.
    content = search.add_command(
        "content",
        "Search text file contents.",
        dependencies=dependencies,
        examples=(
            'lut search content "TODO" ./src  # planned; not implemented',
            'lut search content "xin chào" "my files"  # planned; not implemented',
        ),
    )
    content.add_argument("keyword", help="Text to find (planned input).")
    content.add_argument("path", nargs="?", default=".", help="Search directory (default: cwd).")
    # Document filename search inputs without adding a second execution path.
    name = search.add_command(
        "name",
        "Search file names.",
        dependencies=dependencies,
        examples=(
            'lut search name "*.py" ./src  # planned; not implemented',
            'lut search name "*.md"  # planned; not implemented',
        ),
    )
    name.add_argument("pattern", help="Filename glob (planned input).")
    name.add_argument("path", nargs="?", default=".", help="Search directory (default: cwd).")
