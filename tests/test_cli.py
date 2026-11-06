"""Exercise both installed CLI entry points from outside the source tree."""

import os
import signal
import subprocess
import sys
from importlib.metadata import version
from pathlib import Path

import pytest

from lut import __version__


@pytest.fixture(params=["module", "console"])
def launcher(request):
    """Select the module launcher or console script from the active environment."""
    if request.param == "module":
        return [sys.executable, "-m", "lut"]
    return [str(Path(sys.executable).with_name("lut"))]


@pytest.fixture
def run_cli(launcher, tmp_path):
    """Run installed LUT without source-path or backend access."""
    # Keep the invocation directory valid for Unicode and shell-special paths.
    workdir = tmp_path / "thư mục LUT ; $ test"
    workdir.mkdir()
    # Exclude source overrides and executable backends from the child process.
    environment = dict(os.environ, PATH="", PYTHONPATH="")

    def run(*arguments):
        """Capture the completed command without invoking a shell."""
        return subprocess.run(
            [*launcher, *arguments],
            cwd=workdir,
            env=environment,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

    yield run
    assert list(workdir.iterdir()) == []


@pytest.mark.parametrize("arguments", [[], ["help"], ["--help"], ["help", "--all"]])
def test_help(run_cli, arguments):
    """Show real usage without backends or filesystem output."""
    # Capture help through each supported entry point.
    result = run_cli(*arguments)
    assert result.returncode == 0
    assert result.stderr == ""
    assert "usage: lut" in result.stdout
    assert "Linux Utility Toolkit" in result.stdout
    assert "Examples:" in result.stdout
    assert "Default output:" in result.stdout
    assert "Required dependencies:" in result.stdout
    if arguments == ["help", "--all"]:
        assert "not implemented" in result.stdout


def test_version(run_cli):
    """Keep installed metadata and both version entry points consistent."""
    # Read the completed version response.
    result = run_cli("--version")
    assert result.returncode == 0
    assert result.stdout == f"lut {__version__}\n"
    assert result.stderr == ""
    assert version("linux-utility-toolkit") == __version__


@pytest.mark.parametrize("arguments", [["searh"], ["--unknown"], ["--vers"], ["help", "extra"]])
def test_invalid_arguments(run_cli, arguments):
    """Reject unknown commands, options, abbreviations and extra arguments with code 2."""
    # Capture the argument error instead of allowing an unimplemented operation.
    result = run_cli(*arguments)
    assert result.returncode == 2
    assert result.stdout == ""
    assert "usage: lut" in result.stderr
    assert "error:" in result.stderr
    assert "Try 'lut --help'" in result.stderr


@pytest.mark.parametrize(
    "path, is_implemented",
    [
        (("search",), True),
        (("search", "content"), True),
        (("file",), True),
        (("file", "rename"), True),
        (("image",), False),
        (("image", "convert"), False),
    ],
)
def test_nested_help_entry_points(run_cli, path, is_implemented):
    """Keep nested help aliases equivalent through both installed entry points."""
    # Invoke both public spellings without any available backend executables.
    alias = run_cli(*path, "help")
    # Compare against argparse's native help action.
    option = run_cli(*path, "--help")
    assert alias.returncode == option.returncode == 0
    assert alias.stderr == option.stderr == ""
    assert alias.stdout == option.stdout
    assert f"usage: lut {' '.join(path)} " in alias.stdout
    if is_implemented:
        assert "help only; not implemented" not in alias.stdout
    else:
        assert "help only; not implemented" in alias.stdout


@pytest.mark.parametrize(
    "arguments",
    [
        ["archive", "compress", "backup.zip", "--dry-run"],
        ["image", "convert", "ảnh ; $.png", "--dry-run"],
        ["archive", "extract", "archive.zip", "--dry-run"],
        ["video", "compress", "movie.mp4", "--dry-run"],
        ["video", "info", "movie.mp4"],
        ["audio", "normalize", "sound.flac", "--dry-run"],
        ["wifi", "connect", "network", "--dry-run"],
        ["bluetooth", "remove", "00:11:22:33:44:55", "--dry-run"],
        ["system", "info"],
    ],
)
def test_unimplemented_entry_points(run_cli, arguments):
    """Refuse planned operations with exit 1 instead of reporting false success."""
    # Keep a visible distinction between syntax errors and unavailable operations.
    result = run_cli(*arguments)
    assert result.returncode == 1
    assert result.stdout == ""
    assert "not implemented" in result.stderr


@pytest.mark.parametrize(
    "arguments, unbuffered",
    [
        (["help", "--all"], False),
        (["--help"], False),
        (["--version"], False),
        (["image", "convert", "--help"], False),
        (["help", "--all"], True),
    ],
)
def test_closed_stdout_pipe(launcher, tmp_path, arguments, unbuffered):
    """Exit quietly for both immediate writes and buffered flushes to a closed pipe."""
    # Close the reader before launch so pipe errors do not depend on scheduling.
    reader, writer = os.pipe()
    os.close(reader)
    # Exercise both a failed write and a failure deferred until the final flush.
    environment = dict(os.environ, PYTHONPATH="")
    environment.pop("PYTHONUNBUFFERED", None)
    if unbuffered:
        environment["PYTHONUNBUFFERED"] = "1"
    with os.fdopen(writer, "wb") as output:
        # Exercise the installed entry point with a real stdout file descriptor.
        result = subprocess.run(
            [*launcher, *arguments],
            stdout=output,
            stderr=subprocess.PIPE,
            cwd=tmp_path,
            env=environment,
            text=True,
            timeout=10,
            check=False,
        )
    assert result.returncode == 128 + signal.SIGPIPE
    assert result.stderr == ""
