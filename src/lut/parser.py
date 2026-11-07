"""Build nested argparse commands with consistent help and diagnostics."""

import argparse
import sys
from collections.abc import Callable, Iterator, Sequence


class CommandParser(argparse.ArgumentParser):
    """Keep command registration and help traversal beside the argparse tree."""

    def __init__(self, *args, **kwargs):
        """Disable abbreviated options and retain inherited verbosity."""
        kwargs.setdefault("allow_abbrev", False)
        kwargs.setdefault("formatter_class", argparse.RawDescriptionHelpFormatter)
        super().__init__(*args, **kwargs)
        # Store registered children for help aliases and recursive help.
        self.commands: dict[str, CommandParser] = {}
        # Create argparse subparsers only when the first child is registered.
        self._command_group = None
        self.set_defaults(command_parser=self, handler=None)
        self.add_argument(
            "--verbose",
            action="store_true",
            default=argparse.SUPPRESS,
            help="Show command diagnostics; no files are logged.",
        )

    def add_command(
        self,
        name: str,
        description: str,
        *,
        examples: Sequence[str],
        dependencies: str = "Python 3.11+; no external backend.",
        default_output: str = "terminal text only; no files are created.",
        dry_run: bool = False,
        status: str | None = None,
        handler: Callable[[argparse.Namespace], int] | None = None,
    ) -> "CommandParser":
        """Register a child, marking commands without handlers as help only."""
        if self._command_group is None:
            self._command_group = self.add_subparsers(title="subcommands", metavar="COMMAND")
        # Label commands without handlers as help only.
        if status is None:
            status = " [help only; not implemented]" if handler is None else ""
        # Assemble the common documentation around argparse's generated usage.
        details = (
            "Arguments: listed above; command groups accept a subcommand.\n\n"
            "Examples:\n"
            + "\n".join(f"  {example}" for example in examples)
            + f"\n\nDefault output: {default_output}\n"
            + f"Required dependencies: {dependencies}"
        )
        # Keep this parser in the same tree argparse uses for dispatch.
        command = self._command_group.add_parser(
            name,
            help=description + status,
            description=description + status,
            epilog=details,
        )
        command.set_defaults(handler=handler)
        if dry_run:
            dry_run_help = (
                "Preview actions without making changes."
                if handler is not None
                else "Request a preview; this operation is not implemented yet."
            )
            command.add_argument(
                "--dry-run",
                action="store_true",
                default=argparse.SUPPRESS,
                help=dry_run_help,
            )
        self.commands[name] = command
        return command

    def walk(self) -> Iterator["CommandParser"]:
        """Visit registered parsers in their displayed command order."""
        yield self
        for command in self.commands.values():
            yield from command.walk()

    def help_alias(self, arguments: list[str]) -> list[str]:
        """Translate trailing help only while traversing command names and switches."""
        # Stop at an operand or -- so literal input named help stays input.
        command = self
        for index, argument in enumerate(arguments):
            if argument in command.commands:
                command = command.commands[argument]
            elif argument in ("--verbose", "--dry-run"):
                continue
            elif argument == "help" and all(
                value in ("--verbose", "--dry-run") for value in arguments[index + 1 :]
            ):
                return [*arguments[:index], *arguments[index + 1 :], "--help"]
            else:
                break
        return arguments

    def error(self, message: str) -> None:
        """Report syntax errors on stderr with code 2 and a contextual help hint."""
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: error: {message}\nTry '{self.prog} --help' for usage.\n")
