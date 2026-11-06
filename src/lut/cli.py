"""Register command modules and dispatch the Linux Utility Toolkit CLI."""

import argparse
import os
import signal
import sys

from lut import __version__, commands
from lut.core.errors import report_error
from lut.core.logging import logging_context
from lut.parser import CommandParser


def build_parser() -> CommandParser:
    """Create the CLI tree without checking backends or running utility operations."""
    # Share verbosity and preview defaults without child parsers resetting them.
    parser = CommandParser(
        prog="lut",
        description="Linux Utility Toolkit (LUT) - simplified Linux CLI operations.",
        epilog=(
            "Arguments: choose a listed command; no command shows this help.\n\n"
            "Examples:\n"
            "  lut help\n"
            "  lut help --all\n"
            '  lut search content "database"\n'
            '  lut search name "*.py"\n'
            "  lut file hash document.pdf\n"
            "  lut --version\n"
            "\n"
            "Default output: terminal text only; no files are created.\n"
            "Required dependencies: Python 3.11+; ripgrep for content search.\n\n"
            "Exit codes: 0 success/help; 1 execution error or unimplemented command;\n"
            "2 invalid syntax; 3 missing backend; 4 invalid input; 5 output/access error;\n"
            "130 interrupted; 141 stdout pipe closed."
        ),
    )
    parser.set_defaults(verbose=False, dry_run=False)
    parser.add_argument("--version", action="version", version=f"lut {__version__}")

    def show_help(arguments: argparse.Namespace) -> int:
        """Display the root help or every registered command's help."""
        for command in parser.walk() if arguments.all else (parser,):
            command.print_help()
            if arguments.all:
                print()
        return 0

    # Keep help as a real command so --all and invalid operands are parsed normally.
    help_command = parser.add_command(
        "help",
        "Show command help.",
        handler=show_help,
        examples=("lut help", "lut help --all", "lut help --help"),
    )
    help_command.add_argument("--all", action="store_true", help="Show help for every command.")
    commands.register_commands(parser)
    return parser


def _normalize_search_alias(arguments: list[str]) -> list[str]:
    """Normalize 'lut search <keyword>' into 'lut search content <keyword>'."""
    args = list(arguments)
    try:
        idx = args.index("search")
    except ValueError:
        return args

    after = args[idx + 1 :]
    if not after:
        return args

    first = after[0]
    if first in ("--help", "-h", "help", "content", "name"):
        return args

    if first.startswith("--vers"):
        return args

    content_flags = (
        "-i",
        "--ignore-case",
        "-e",
        "--ext",
        "-l",
        "--files-only",
        "-c",
        "--count",
        "--regex",
        "--hidden",
        "--no-ignore",
        "--glob",
        "--max-depth",
        "--json",
    )

    if first == "--" or not first.startswith("-"):
        args.insert(idx + 1, "content")
        return args

    if first in content_flags:
        args.insert(idx + 1, "content")
        return args

    return args


def _dispatch(argv: list[str] | None = None) -> int:
    """Dispatch help and handlers while refusing unimplemented operations."""
    try:
        # Normalize help aliases before argparse validates required operands.
        parser = build_parser()
        # Preserve explicit argument lists for embedded callers and unit tests.
        arguments = list(sys.argv[1:] if argv is None else argv)
        arguments = _normalize_search_alias(arguments)
        # Select the deepest parser and its module-provided handler.
        options = parser.parse_args(parser.help_alias(arguments))
        # Read the selected parser without reconstructing the command path.
        selected = options.command_parser
        if options.handler is not None:
            with logging_context(verbose=options.verbose):
                return options.handler(options)
        if selected is parser or selected.commands:
            selected.print_help()
            return 0
        if options.verbose:
            print(
                f"lut: selected command: {selected.prog}; dry-run: {options.dry_run}",
                file=sys.stderr,
            )
        print(
            f"{selected.prog}: error: not implemented; this command provides help only.",
            file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        print("lut: interrupted.", file=sys.stderr)
        return 130
    except BrokenPipeError:
        raise
    except Exception as error:
        return report_error(error)


def main(argv: list[str] | None = None) -> int:
    """Run either CLI entry point without noisy errors when a pipe reader exits."""
    try:
        try:
            return _dispatch(argv)
        finally:
            # Catch buffered writes before interpreter shutdown can replace the exit code.
            sys.stdout.flush()
    except BrokenPipeError:
        # Prevent Python's shutdown flush from writing to the broken pipe again.
        with open(os.devnull, "w") as sink:
            os.dup2(sink.fileno(), sys.stdout.fileno())
        return 128 + signal.SIGPIPE
