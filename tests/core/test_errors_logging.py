"""Validate public error codes, private logs and CLI error integration."""

import os
import stat
from types import SimpleNamespace

import pytest

from lut import cli, commands
from lut.core.errors import (
    CancelledError,
    DependencyError,
    InputError,
    LutError,
    OutputError,
    UsageError,
    report_error,
)
from lut.core.logging import logger, logging_context


@pytest.mark.parametrize(
    "error, code",
    [
        (LutError("execution failed"), 1),
        (UsageError("invalid parameter"), 2),
        (DependencyError("missing backend"), 3),
        (InputError("bad input"), 4),
        (OutputError("output conflict"), 5),
        (CancelledError("cancelled"), 130),
    ],
)
def test_expected_error_codes(error, code, capsys):
    """Print stable typed errors to stderr without a traceback."""
    assert report_error(error) == code
    # Error reporting must never contaminate normal stdout.
    output = capsys.readouterr()
    assert output.out == "" and output.err == f"lut: error: {error}\n"


def test_logging_is_scoped_private_and_restored(tmp_path, capsys):
    """Create a private log only when requested and restore the caller's logger."""
    # Preserve both handler identity and settings across nested library use.
    previous = logger.handlers[:], logger.level, logger.propagate
    # File logging explicitly owns this path, never a first-run default.
    path = tmp_path / "state/lut.log"
    with logging_context(log_file=path) as log:
        log.debug("hidden")
        log.info("visible")
    assert path.read_text() == "lut: INFO: visible\n"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert (logger.handlers, logger.level, logger.propagate) == previous
    assert capsys.readouterr().err == "lut: INFO: visible\n"


def test_logging_does_not_follow_symlinks_or_open_fifos(tmp_path):
    """Prevent an opt-in log destination from redirecting writes or blocking startup."""
    # Keep the unrelated target unchanged even when the requested log is a symlink.
    target = tmp_path / "keep.txt"
    target.write_text("original")
    # Both symlinks and nonregular files must be rejected before any log output.
    link = tmp_path / "link.log"
    link.symlink_to(target)
    with pytest.raises(OutputError):
        with logging_context(log_file=link):
            pytest.fail("A symlink must not become a log stream")
    assert target.read_text() == "original"
    # Nonblocking open ensures this case cannot wait for another FIFO endpoint.
    fifo = tmp_path / "fifo.log"
    os.mkfifo(fifo)
    with pytest.raises(OutputError):
        with logging_context(log_file=fifo):
            pytest.fail("A FIFO must not become a log stream")


def test_logging_preserves_body_errors_and_default_creates_no_files(tmp_path, monkeypatch):
    """Do not misclassify a caller's OSError as a log-file setup failure."""
    monkeypatch.chdir(tmp_path)
    with pytest.raises(FileNotFoundError):
        with logging_context():
            raise FileNotFoundError("caller failure")
    assert list(tmp_path.iterdir()) == []


def test_logging_refuses_ignored_private_permissions(tmp_path, monkeypatch):
    """Do not append logs when a filesystem silently ignores chmod, as some FUSE mounts do."""
    # Model an existing readable file on a mount that cannot enforce Unix mode bits.
    path = tmp_path / "public.log"
    path.write_text("unchanged")
    path.chmod(0o666)
    monkeypatch.setattr(os, "fchmod", lambda *args: None)
    with pytest.raises(OutputError):
        with logging_context(log_file=path):
            pytest.fail("A public file must not receive private log events")
    assert path.read_text() == "unchanged"


@pytest.mark.parametrize(
    "error, code, message",
    [
        (DependencyError("backend missing"), 3, "backend missing"),
        (OutputError("destination occupied"), 5, "destination occupied"),
        (RuntimeError("private-password"), 1, "Unexpected execution failure."),
    ],
)
def test_cli_reports_core_errors(monkeypatch, capsys, error, code, message):
    """Use the existing module handler contract to exercise real CLI error handling."""

    def fail(arguments):
        """Simulate a core failure without adding a utility implementation."""
        raise error

    def register(parser):
        """Register only a test fixture, leaving all production utility handlers empty."""
        parser.add_command("fixture", "Exercise errors.", examples=("lut fixture",), handler=fail)

    monkeypatch.setattr(
        commands, "MODULES", (*commands.MODULES, SimpleNamespace(register=register))
    )
    assert cli.main(["fixture"]) == code
    # Unexpected exception text must not expose an argument or password.
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err == f"lut: error: {message}\n"
    assert "private-password" not in output.err


def test_cli_help_never_reads_config_or_creates_logs(tmp_path, monkeypatch, capsys):
    """Keep help independent of malformed config and unwritable state locations."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    # Importing/configuring core support must not cause configuration reads during help.
    monkeypatch.setattr(
        "lut.core.config.load_config", lambda *args: pytest.fail("Help read config")
    )
    assert cli.main(["help", "--all"]) == 0
    assert "usage: lut" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []
