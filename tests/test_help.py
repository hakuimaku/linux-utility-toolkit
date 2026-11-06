"""Validate the complete help tree, module registration and CLI flag scope."""

import shlex
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from lut import cli, commands

# Derive cases from the real registry so new modules inherit help coverage.
COMMAND_PATHS = [tuple(parser.prog.split()[1:]) for parser in cli.build_parser().walk()]

# Cover every planned leaf while leaving the working help command unchanged.
UTILITY_PATHS = [
    tuple(parser.prog.split()[1:])
    for parser in cli.build_parser().walk()
    if not parser.commands and parser.get_default("handler") is None
]


@pytest.fixture
def invoke(capsys):
    """Capture main's returned codes and argparse's SystemExit consistently."""

    def run(arguments):
        """Invoke the CLI directly without a shell or external process."""
        try:
            # Record dispatch results from help handlers and unavailable commands.
            code = cli.main(arguments)
        except SystemExit as error:
            code = error.code
        # Consume only output from the current invocation.
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return run


@pytest.mark.parametrize("path", COMMAND_PATHS)
def test_every_help_level(path, invoke, monkeypatch):
    """Document every registered parser without executable discovery or launch."""

    def forbidden(*args, **kwargs):
        """Fail immediately if help attempts a backend check or process launch."""
        pytest.fail("Help must not inspect or launch backends")

    monkeypatch.setattr(shutil, "which", forbidden)
    monkeypatch.setattr(subprocess, "Popen", forbidden)
    # Resolve both help spellings at the same command depth.
    alias = invoke([*path, "help"])
    # Require the alias to produce exactly the native help text.
    option = invoke([*path, "--help"])
    assert alias == option
    # Check complete help content independently of argparse's line wrapping.
    code, output, errors = alias
    assert code == 0 and errors == ""
    for section in ("usage:", "Arguments:", "options:", "Examples:", "Required dependencies:"):
        assert section in output
    assert "Default output:" in output
    implemented_paths = {
        ("search",),
        ("search", "content"),
        ("search", "name"),
        ("file",),
        ("file", "hash"),
        ("file", "info"),
        ("file", "duplicates"),
        ("file", "rename"),
        ("archive",),
        ("archive", "compress"),
        ("archive", "extract"),
        ("archive", "list"),
        ("archive", "test"),
        ("image",),
        ("image", "convert"),
        ("image", "compress"),
        ("image", "resize"),
        ("image", "crop"),
        ("image", "rotate"),
        ("image", "metadata"),
        ("help",),
    }
    if path in implemented_paths:
        assert "help only; not implemented" not in output
    else:
        assert "help only; not implemented" in output


def test_all_help(invoke):
    """Print help for every registered parser, including nested operations."""
    # Count real parser pages instead of relying on a fixed module count.
    pages = list(cli.build_parser().walk())
    # Exercise argparse's dedicated help command option.
    code, output, errors = invoke(["help", "--all"])
    assert code == 0 and errors == ""
    assert output.count("usage:") == len(pages)
    for parser in pages:
        assert f"usage: {parser.prog} " in output


@pytest.mark.parametrize("path", UTILITY_PATHS)
def test_planned_examples_match_syntax(path, invoke):
    """Keep leaf examples concise, explicitly planned and valid under the current parser."""
    # Inspect the same examples users see instead of duplicating them in fixtures.
    code, output, errors = invoke([*path, "--help"])
    assert code == 0 and errors == ""
    # Separate the examples from the following output and dependency sections.
    examples = output.split("Examples:\n", 1)[1].split("\n\n", 1)[0].splitlines()
    assert 1 <= len(examples) <= 3
    for example in examples:
        assert "planned; not implemented" in example
        # Parse shell quoting and comments without running a shell or a backend.
        arguments = shlex.split(example, comments=True)
        assert arguments[: len(path) + 1] == ["lut", *path]
        assert "help" not in arguments and "--help" not in arguments
        # Syntax must be accepted while every utility still refuses execution.
        result, stdout, stderr = invoke(arguments[1:])
        assert result == 1 and stdout == ""
        assert "not implemented" in stderr


def test_planned_commands_have_no_handlers():
    """Ensure planned utility commands (M6-M9) remain unavailable without handlers."""
    implemented_progs = {
        "lut help",
        "lut search content",
        "lut search name",
        "lut file hash",
        "lut file info",
        "lut file duplicates",
        "lut file rename",
        "lut archive compress",
        "lut archive extract",
        "lut archive list",
        "lut archive test",
        "lut image convert",
        "lut image compress",
        "lut image resize",
        "lut image crop",
        "lut image rotate",
        "lut image metadata",
    }
    for parser in cli.build_parser().walk():
        if parser.prog in implemented_progs:
            assert parser.get_default("handler") is not None
        else:
            assert parser.get_default("handler") is None


@pytest.mark.parametrize(
    "arguments",
    [
        ["--verbose", "image", "convert", "help"],
        ["image", "convert", "help", "--verbose"],
        ["image", "convert", "--dry-run", "help"],
        ["image", "convert", "help", "--dry-run"],
    ],
)
def test_help_with_switches(arguments, invoke):
    """Resolve command help before required operands even when switches surround help."""
    assert invoke(arguments) == invoke(["image", "convert", "--help"])


@pytest.mark.parametrize(
    "arguments, context",
    [
        (["unknown"], "lut"),
        (["archive", "unknown"], "lut archive"),
        (["image", "unknown"], "lut image"),
        (["search", "content"], "lut search content"),
        (["image", "convert"], "lut image convert"),
        (["image", "convert", "input.png", "--unknown"], "lut"),
        (["--dry-run", "image", "convert", "input.png"], "lut"),
        (["search", "content", "word", "--dry-run"], "lut"),
        (["image", "metadata", "input.png", "--dry-run"], "lut"),
        (["image", "convert", "input.png", "--dry"], "lut"),
        (["search", "--version"], "lut"),
        (["help", "extra"], "lut"),
        (["--all"], "lut"),
    ],
)
def test_syntax_errors(arguments, context, invoke):
    """Return code 2 with stderr usage and a help hint for invalid syntax."""
    # Preserve argument errors instead of treating them as backend failures.
    code, output, errors = invoke(arguments)
    assert code == 2 and output == ""
    assert f"usage: {context} " in errors
    assert "error:" in errors
    assert f"Try '{context} --help'" in errors


@pytest.mark.parametrize(
    "arguments",
    [
        ["--verbose", "video", "compress", "private.mp4", "--dry-run"],
        ["video", "--verbose", "compress", "private.mp4", "--dry-run"],
        ["video", "compress", "private.mp4", "--verbose", "--dry-run"],
    ],
)
def test_verbose_and_dry_run_scope(arguments, invoke):
    """Retain flags across subparsers without executing a preview or logging operands."""
    # Ensure child defaults do not erase the verbosity set on a parent parser.
    code, output, errors = invoke(arguments)
    assert code == 1 and output == ""
    assert "selected command: lut video compress; dry-run: True" in errors
    assert "private.mp4" not in errors
    assert "not implemented" in errors


@pytest.mark.parametrize(
    "arguments",
    [["video", "compress", "--", "help"], ["video", "compress", "--dry-run", "--", "help"]],
)
def test_literal_help_operands(arguments, invoke):
    """Treat help after -- or another operand as input, not as a help alias."""
    # Avoid rewriting filenames and search terms once operand parsing has started.
    code, output, errors = invoke(arguments)
    assert code == 1 and output == ""
    assert "not implemented" in errors


def test_literal_help_operand_implemented_search(invoke):
    """Literal 'help' operand is treated as search keyword, not a help switch."""
    code, output, errors = invoke(["search", "content", "--", "help"])
    # Should execute content search for keyword "help" instead of displaying help
    assert "usage: lut search content" not in output
    assert "Try 'lut search content --help'" not in errors


def test_literal_help_operand_implemented_archive(tmp_path, invoke):
    """Literal 'help' operand is treated as filename for archive compress."""
    (tmp_path / "help").write_text("content", encoding="utf-8")
    code, out, err = invoke(["archive", "compress", str(tmp_path / "help"), "--dry-run"])
    assert code == 0
    assert "usage: lut archive compress" not in out


def test_literal_help_operand_implemented_image(invoke):
    """Literal 'help' operand is treated as filename for image metadata, not a help switch."""
    code, out, err = invoke(["image", "metadata", "--", "help"])
    # Should execute metadata for file named "help" (code 4 because file not found)
    # instead of displaying help
    assert "usage: lut image metadata" not in out
    assert "Try 'lut image metadata --help'" not in err
    assert code == 4


def test_register_new_module_without_cli_changes(monkeypatch, invoke):
    """Add and dispatch a module by changing only the module registry."""
    # Record parsed values delivered through the normal handler contract.
    received = {}

    def handle(arguments):
        """Capture arguments without performing any utility operation."""
        received.update(value=arguments.value, verbose=arguments.verbose, dry_run=arguments.dry_run)
        return 0

    def register(parser):
        """Register a small fixture command through the same public module API."""
        # Give the fixture a handler to distinguish it from documentation-only commands.
        command = parser.add_command(
            "fixture",
            "Exercise registration.",
            examples=("lut fixture value",),
            handler=handle,
            dry_run=True,
        )
        command.add_argument("value")

    monkeypatch.setattr(
        commands, "MODULES", (*commands.MODULES, SimpleNamespace(register=register))
    )
    assert invoke(["--verbose", "fixture", "value", "--dry-run"]) == (0, "", "")
    assert received == {"value": "value", "verbose": True, "dry_run": True}
    # Check that registration automatically includes the new module in recursive help.
    code, output, errors = invoke(["help", "--all"])
    assert code == 0 and errors == ""
    assert "usage: lut fixture " in output


def test_interrupt(monkeypatch, invoke):
    """Convert a user interruption into exit code 130 without a traceback."""

    def interrupt():
        """Simulate Ctrl+C while the CLI is being prepared."""
        raise KeyboardInterrupt

    monkeypatch.setattr(cli, "build_parser", interrupt)
    assert invoke([]) == (130, "", "lut: interrupted.\n")
