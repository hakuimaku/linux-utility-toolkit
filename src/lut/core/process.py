"""Run argument lists with bounded capture, progress and owned-process cleanup."""

import codecs
import math
import os
import selectors
import signal
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from lut.core.errors import (
    CancelledError,
    DependencyError,
    InputError,
    OutputError,
    ProcessError,
    ProcessTimeout,
    UsageError,
)
from lut.core.logging import logger


@dataclass(frozen=True)
class ProcessResult:
    """Return completed backend data without exposing it in a default repr."""

    returncode: int
    stdout: str = field(repr=False)
    stderr: str = field(repr=False)
    executed: bool = True


def _stop(process: subprocess.Popen) -> None:
    """Terminate the owned session, kill remaining descendants and reap the leader."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=0.5)
    except (ProcessLookupError, subprocess.TimeoutExpired, KeyboardInterrupt):
        pass
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        while True:
            try:
                process.wait()
                break
            except KeyboardInterrupt:
                continue


def run_process(
    arguments: Sequence[str | os.PathLike[str]],
    *,
    timeout: float | None = None,
    cwd: str | os.PathLike[str] | None = None,
    env: Mapping[str, str] | None = None,
    dry_run: bool = False,
    progress: Callable[[str, str], None] | None = None,
    capture_limit: int = 4 * 1024 * 1024,
) -> ProcessResult:
    """Run a noninteractive backend; progress receives (stream name, UTF-8 text chunk)."""
    if isinstance(arguments, (str, bytes)) or not arguments:
        raise UsageError("Process arguments must be a nonempty argument list.")
    try:
        # Keep shell syntax and Unicode operands as literal arguments, never command text.
        command = [os.fspath(argument) for argument in arguments]
        if (
            not command
            or not command[0]
            or any(not isinstance(value, str) or "\0" in value for value in command)
        ):
            raise ValueError
        if timeout is not None and (
            isinstance(timeout, bool) or not math.isfinite(timeout) or timeout <= 0
        ):
            raise ValueError
        if type(capture_limit) is not int or capture_limit <= 0:
            raise ValueError
        if env is not None and not isinstance(env, Mapping):
            raise ValueError
        if env is not None and any(
            not isinstance(key, str)
            or not isinstance(value, str)
            or "\0" in key
            or "\0" in value
            or "=" in key
            for key, value in env.items()
        ):
            raise ValueError
        if cwd is not None and (not isinstance(os.fspath(cwd), str) or "\0" in os.fspath(cwd)):
            raise ValueError
    except (TypeError, ValueError):
        raise UsageError(
            "Invalid process arguments, environment, timeout or capture limit."
        ) from None
    if dry_run:
        logger.debug("Dry run: process not started.")
        return ProcessResult(0, "", "", executed=False)
    if cwd is not None and not Path(cwd).is_dir():
        raise InputError("Process working directory does not exist.")
    # Allocate capture state before creating a child that would require cleanup.
    buffers = {"stdout": bytearray(), "stderr": bytearray()}
    # Incremental decoders preserve Unicode split between progress chunks.
    decoders = {name: codecs.getincrementaldecoder("utf-8")("replace") for name in buffers}
    # Use one deadline for pipe draining and the final process wait.
    deadline = None if timeout is None else time.monotonic() + timeout
    # Bound combined output before adding each received chunk to a collector.
    captured = 0
    try:
        # A new session lets cancellation stop descendants as well as the direct child.
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=env,
            start_new_session=True,
            bufsize=0,
        )
    except FileNotFoundError:
        raise DependencyError("Process executable was not found on PATH.") from None
    except PermissionError:
        raise OutputError("Permission denied while starting the backend.") from None
    except OSError:
        raise ProcessError("Cannot start the backend.") from None
    try:
        logger.debug("Process started.")
        # Drain both streams fairly so a full stderr pipe cannot block stdout reads.
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ, "stdout")
            selector.register(process.stderr, selectors.EVENT_READ, "stderr")
            while selector.get_map():
                if deadline is not None and time.monotonic() >= deadline:
                    raise ProcessTimeout("Backend timed out.")
                for key, _ in selector.select(0.05):
                    # A ready descriptor can supply a bounded chunk without blocking.
                    chunk = os.read(key.fd, 65536)
                    # Route progress separately from logging; backend data is never logged.
                    stream = key.data
                    if not chunk:
                        selector.unregister(key.fileobj)
                    else:
                        captured += len(chunk)
                        if captured > capture_limit:
                            raise ProcessError("Backend output exceeded the capture limit.")
                        buffers[stream].extend(chunk)
                    if progress is not None:
                        # Flush a partial character only when this stream reaches EOF.
                        text = decoders[stream].decode(chunk, final=not chunk)
                        if text:
                            progress(stream, text)
        try:
            process.wait(timeout=None if deadline is None else max(0, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            raise ProcessTimeout("Backend timed out.") from None
        logger.debug("Process finished with status %d.", process.returncode)
        if process.returncode != 0:
            raise ProcessError(
                f"Backend failed with exit code {process.returncode}.", process.returncode
            )
        return ProcessResult(
            process.returncode,
            buffers["stdout"].decode("utf-8", errors="replace"),
            buffers["stderr"].decode("utf-8", errors="replace"),
        )
    except KeyboardInterrupt:
        _stop(process)
        raise CancelledError("Operation cancelled.") from None
    except BaseException:
        _stop(process)
        raise
    finally:
        process.stdout.close()
        process.stderr.close()
