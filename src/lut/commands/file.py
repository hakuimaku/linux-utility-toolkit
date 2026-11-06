"""Register and handle file inspection and organization commands."""

import argparse

from lut.services.file_service import (
    file_duplicates,
    file_hash,
    file_info,
    file_rename,
)


def _handle_hash(args: argparse.Namespace) -> int:
    """Handle file hash calculation."""
    return file_hash(
        input_path=args.input,
        algorithm=args.algorithm,
        as_json=args.json,
    )


def _handle_info(args: argparse.Namespace) -> int:
    """Handle file metadata inspection."""
    return file_info(
        input_path=args.input,
        as_json=args.json,
    )


def _handle_duplicates(args: argparse.Namespace) -> int:
    """Handle duplicate file detection."""
    return file_duplicates(
        search_path=args.path,
        min_size=args.min_size,
        max_depth=args.max_depth,
        as_json=args.json,
    )


def _handle_rename(args: argparse.Namespace) -> int:
    """Handle file rename preview or application."""
    replace_pair = tuple(args.replace) if args.replace else None
    return file_rename(
        inputs=args.input,
        prefix=args.prefix,
        suffix=args.suffix,
        replace=replace_pair,
        apply=args.apply,
        dry_run=args.dry_run,
        as_json=args.json,
    )


def register(parser) -> None:
    """Register file command group and operational subcommands."""
    file = parser.add_command(
        "file",
        "Inspect and organize files.",
        status="",
        examples=(
            "lut file hash document.pdf",
            "lut file info notes.txt",
            "lut file duplicates ./photos",
            "lut file rename photo.png --prefix old_",
            "lut file help",
        ),
    )

    # file hash
    cmd_hash = file.add_command(
        "hash",
        "Compute cryptographic checksum of a file.",
        handler=_handle_hash,
        dependencies="Python 3.11+ hashlib; no external backend.",
        examples=(
            "lut file hash document.pdf",
            "lut file hash archive.zip --algorithm sha512",
            'lut file hash "my file.txt"',
        ),
    )
    cmd_hash.add_argument("input", help="File to compute checksum for.")
    cmd_hash.add_argument(
        "-a",
        "--algorithm",
        default="sha256",
        choices=["sha256", "sha512", "sha1", "md5"],
        help="Hash algorithm (default: sha256).",
    )
    cmd_hash.add_argument("--json", action="store_true", help="Output result in JSON format.")

    # file info
    cmd_info = file.add_command(
        "info",
        "Inspect file or directory metadata and permissions.",
        handler=_handle_info,
        dependencies="Python 3.11+ standard library; no external backend.",
        examples=(
            "lut file info document.pdf",
            "lut file info ./photos",
            'lut file info "my file.txt"',
        ),
    )
    cmd_info.add_argument("input", help="File or directory path to inspect.")
    cmd_info.add_argument("--json", action="store_true", help="Output result in JSON format.")

    # file duplicates
    cmd_duplicates = file.add_command(
        "duplicates",
        "Find identical content files in a directory tree.",
        handler=_handle_duplicates,
        dependencies="Python 3.11+ standard library; no external backend.",
        examples=(
            "lut file duplicates",
            "lut file duplicates ./Downloads",
            "lut file duplicates ./Documents --min-size 1024",
        ),
    )
    cmd_duplicates.add_argument(
        "path", nargs="?", default=".", help="Directory to search (default: cwd)."
    )
    cmd_duplicates.add_argument(
        "--min-size",
        type=int,
        default=1,
        metavar="BYTES",
        help="Minimum file size in bytes to consider (default: 1).",
    )
    cmd_duplicates.add_argument(
        "--max-depth", type=int, metavar="N", help="Limit directory traversal depth."
    )
    cmd_duplicates.add_argument("--json", action="store_true", help="Output result in JSON format.")

    # file rename
    cmd_rename = file.add_command(
        "rename",
        "Safely preview or batch rename files.",
        handler=_handle_rename,
        dry_run=True,
        default_output="terminal preview by default; modifies files only with --apply.",
        dependencies="Python 3.11+; libc renameat2 for atomic non-overwriting rename.",
        examples=(
            "lut file rename photo.png --prefix old_",
            "lut file rename photo.png --suffix _backup",
            "lut file rename ./photos --replace IMG_ photo_",
            "lut file rename *.txt --prefix doc_ --apply",
        ),
    )
    cmd_rename.add_argument(
        "input",
        nargs="+",
        help="One or more files, or a directory whose files will be renamed.",
    )
    cmd_rename.add_argument("--prefix", metavar="PREFIX", help="String to prepend to the filename.")
    cmd_rename.add_argument(
        "--suffix",
        metavar="SUFFIX",
        help="String to append to the filename (before extension).",
    )
    cmd_rename.add_argument(
        "--replace",
        nargs=2,
        metavar=("OLD", "NEW"),
        help="Substring replacement: replace OLD with NEW in filename.",
    )
    cmd_rename.add_argument(
        "--apply",
        action="store_true",
        help="Execute the renames (default runs in preview mode).",
    )
    cmd_rename.add_argument(
        "--json", action="store_true", help="Output plan or result in JSON format."
    )
