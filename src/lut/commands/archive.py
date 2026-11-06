"""Register and handle archive compression, extraction, listing, and testing."""

import argparse

from lut.services.archive_service import (
    archive_compress,
    archive_extract,
    archive_list,
    archive_test,
)


def _handle_compress(args: argparse.Namespace) -> int:
    """Handle archive compression."""
    return archive_compress(
        inputs=args.input,
        fmt=args.format,
        output=args.output,
        level=args.level,
        dry_run=args.dry_run,
        as_json=args.json,
        verbose=args.verbose,
    )


def _handle_extract(args: argparse.Namespace) -> int:
    """Handle archive extraction."""
    return archive_extract(
        archive_path=args.input,
        output=args.output,
        dry_run=args.dry_run,
        as_json=args.json,
        verbose=args.verbose,
    )


def _handle_list(args: argparse.Namespace) -> int:
    """Handle archive listing."""
    return archive_list(
        archive_path=args.input,
        as_json=args.json,
        verbose=args.verbose,
    )


def _handle_test(args: argparse.Namespace) -> int:
    """Handle archive integrity testing."""
    return archive_test(
        archive_path=args.input,
        as_json=args.json,
        verbose=args.verbose,
    )


def register(parser) -> None:
    """Register archive command group and operational subcommands."""
    dependencies = "Python 3.11+ standard library (ZIP/TAR); optional 7z backend for 7Z format."

    archive = parser.add_command(
        "archive",
        "Create and inspect archives.",
        status="",
        dependencies=dependencies,
        examples=(
            "lut archive compress myfolder/",
            "lut archive extract backup.zip",
            "lut archive list backup.zip",
            "lut archive test backup.zip",
            "lut archive help",
        ),
    )

    # archive compress
    cmd_compress = archive.add_command(
        "compress",
        "Compress files or directories into an archive.",
        handler=_handle_compress,
        dry_run=True,
        dependencies=dependencies,
        default_output="<input>.zip beside input; collisions numbered (<input>_2.zip)",
        examples=(
            "lut archive compress myfolder/",
            "lut archive compress document.pdf",
            "lut archive compress myfolder/ --format tar.gz",
            "lut archive compress myfolder/ --level 9",
            "lut archive compress myfolder/ --output backup.zip",
            "lut archive compress myfolder/ --dry-run",
        ),
    )
    cmd_compress.add_argument(
        "input",
        nargs="+",
        help="Input file(s) or directory to compress.",
    )
    cmd_compress.add_argument(
        "-f",
        "--format",
        choices=["zip", "tar", "tar.gz", "tar.xz", "7z"],
        default=None,
        help="Archive format (default: zip or inferred from --output).",
    )
    cmd_compress.add_argument(
        "-l",
        "--level",
        type=int,
        default=None,
        help="Compression level (0-9 where supported by backend).",
    )
    cmd_compress.add_argument(
        "-o",
        "--output",
        default=None,
        help="Override default output archive path.",
    )
    cmd_compress.add_argument(
        "--json",
        action="store_true",
        help="Output result in JSON format.",
    )

    # archive extract
    cmd_extract = archive.add_command(
        "extract",
        "Extract an archive safely into a directory (ZIP, TAR, TAR.GZ, TAR.XZ).",
        handler=_handle_extract,
        dry_run=True,
        dependencies=dependencies,
        default_output="<name>_extracted/ beside archive; collisions numbered",
        examples=(
            "lut archive extract backup.zip",
            "lut archive extract project.tar.gz",
            "lut archive extract project.tar.xz",
            "lut archive extract backup.zip --output ./restored",
            "lut archive extract backup.zip --dry-run",
        ),
    )
    cmd_extract.add_argument(
        "input",
        help="Archive file to extract (ZIP, TAR, TAR.GZ, TAR.XZ).",
    )
    cmd_extract.add_argument(
        "-o",
        "--output",
        default=None,
        help="Override default output directory.",
    )
    cmd_extract.add_argument(
        "--json",
        action="store_true",
        help="Output result in JSON format.",
    )

    # archive list
    cmd_list = archive.add_command(
        "list",
        "List archive entries without extracting.",
        handler=_handle_list,
        dependencies=dependencies,
        examples=(
            "lut archive list backup.zip",
            "lut archive list project.tar.gz",
            "lut archive list files.7z --json",
        ),
    )
    cmd_list.add_argument(
        "input",
        help="Archive file to list entries from.",
    )
    cmd_list.add_argument(
        "--json",
        action="store_true",
        help="Output result in JSON format.",
    )

    # archive test
    cmd_test = archive.add_command(
        "test",
        "Check archive integrity without extracting.",
        handler=_handle_test,
        dependencies=dependencies,
        examples=(
            "lut archive test backup.zip",
            "lut archive test project.tar.gz",
            "lut archive test files.7z",
        ),
    )
    cmd_test.add_argument(
        "input",
        help="Archive file to test integrity.",
    )
    cmd_test.add_argument(
        "--json",
        action="store_true",
        help="Output result in JSON format.",
    )
