"""Register and handle search commands for file content and names."""

import argparse

from lut.services.search_service import search_content, search_name


def _handle_content(args: argparse.Namespace) -> int:
    """Execute content search using the ripgrep backend."""
    return search_content(
        keyword=args.keyword,
        path=args.path,
        ignore_case=args.ignore_case,
        extension=args.ext,
        files_only=args.files_only,
        count_only=args.count,
        is_regex=args.regex,
        hidden=args.hidden,
        no_ignore=args.no_ignore,
        glob_pattern=args.glob,
        max_depth=args.max_depth,
        as_json=args.json,
    )


def _handle_name(args: argparse.Namespace) -> int:
    """Execute filename search using filesystem traversal."""
    return search_name(
        pattern=args.pattern,
        path=args.path,
        files_only=args.files,
        dirs_only=args.dirs,
        hidden=args.hidden,
        no_ignore=args.no_ignore,
        max_depth=args.max_depth,
        as_json=args.json,
    )


def register(parser) -> None:
    """Register search command group and operational content and name subcommands."""
    # Command group search is operational
    search = parser.add_command(
        "search",
        "Search file contents or names.",
        status="",
        dependencies="Python 3.11+; backend: ripgrep (checked on content search).",
        examples=(
            'lut search "database"',
            'lut search content "TODO" ./src',
            'lut search name "*.py"',
            "lut search help",
        ),
    )

    # Operational content search
    content = search.add_command(
        "content",
        "Search text file contents.",
        handler=_handle_content,
        dependencies="ripgrep (rg) required on PATH.",
        examples=(
            'lut search content "database"',
            'lut search content "TODO" ./src',
            'lut search content "hello" -i',
            'lut search content "error" -e py',
            'lut search content "warning" -l',
            'lut search content -- help  # search literal "help"',
        ),
    )
    content.add_argument("keyword", help="Text or pattern to search for.")
    content.add_argument(
        "path", nargs="?", default=".", help="Search directory or file (default: cwd)."
    )
    content.add_argument(
        "-i", "--ignore-case", action="store_true", help="Case-insensitive search."
    )
    content.add_argument(
        "-e", "--ext", metavar="EXT", help="Only search files with given extension."
    )
    content.add_argument(
        "-l", "--files-only", action="store_true", help="Only display files with matches."
    )
    content.add_argument("-c", "--count", action="store_true", help="Display match count.")
    content.add_argument(
        "--regex",
        action="store_true",
        help="Treat keyword as a regular expression (default: literal text).",
    )
    content.add_argument(
        "--hidden", action="store_true", help="Search hidden files and directories."
    )
    content.add_argument(
        "--no-ignore", action="store_true", help="Do not respect .gitignore or ignore files."
    )
    content.add_argument("--glob", metavar="PATTERN", help="Filter paths matching glob pattern.")
    content.add_argument("--max-depth", type=int, metavar="N", help="Limit search depth.")
    content.add_argument("--json", action="store_true", help="Output results in JSON format.")

    # Operational name search
    name = search.add_command(
        "name",
        "Search file and directory names.",
        handler=_handle_name,
        dependencies="Python 3.11+; standard library filesystem traversal.",
        examples=(
            'lut search name "*.py"',
            'lut search name "*.json" ./src',
            'lut search name "*config*"',
            'lut search name "README*"',
        ),
    )
    name.add_argument("pattern", help="Filename glob pattern.")
    name.add_argument("path", nargs="?", default=".", help="Search directory (default: cwd).")
    group = name.add_mutually_exclusive_group()
    group.add_argument("--files", action="store_true", help="Only match files.")
    group.add_argument("--dirs", action="store_true", help="Only match directories.")
    name.add_argument("--hidden", action="store_true", help="Include hidden files and directories.")
    name.add_argument(
        "--no-ignore",
        action="store_true",
        help="Do not ignore VCS directories like .git (combine with --hidden for dotfiles).",
    )
    name.add_argument("--max-depth", type=int, metavar="N", help="Limit search depth.")
    name.add_argument("--json", action="store_true", help="Output results in JSON format.")
