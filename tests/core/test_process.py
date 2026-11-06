"""Exercise real process completion, progress, failures and cancellation."""

import json
import os
import selectors
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from lut.core.errors import (
    CancelledError,
    DependencyError,
    InputError,
    OutputError,
    ProcessError,
    ProcessTimeout,
    UsageError,
)
from lut.core.logging import logging_context
from lut.core.output import atomic_output
from lut.core.process import run_process


def test_literal_arguments_unicode_and_completion(tmp_path):
    """Keep shell syntax literal and wait until backend output is complete."""
    # A shell would create a file if this operand were interpolated into command text.
    operand = 'ảnh ; $(touch marker) $HOME "quoted"'
    # The backend emits a delayed result only after processing its full argument list.
    result = run_process(
        [
            sys.executable,
            "-c",
            "import json,sys,time; time.sleep(.05); print(json.dumps(sys.argv[1:]))",
            operand,
        ],
        cwd=tmp_path,
        timeout=3,
    )
    assert json.loads(result.stdout) == [operand]
    assert result.returncode == 0 and result.executed
    assert not (tmp_path / "marker").exists()


def test_progress_and_dual_stream_drain():
    """Drain stderr while preserving split UTF-8 progress characters on stdout."""
    # Preserve streamed chunks independently from the captured final result.
    events = {"stdout": [], "stderr": []}
    # Split a Unicode code point across writes and fill stderr beyond pipe capacity.
    program = (
        "import os,time; os.write(1,b'\\xe1'); time.sleep(.02); "
        "os.write(2,b'x'*200000); os.write(1,b'\\xba\\xa3nh')"
    )
    # Incremental decoding must yield the same text as complete capture.
    result = run_process(
        [sys.executable, "-c", program],
        timeout=3,
        progress=lambda stream, text: events[stream].append(text),
    )
    assert result.stdout == "ảnh"
    assert result.stderr == "x" * 200000
    assert "".join(events["stdout"]) == result.stdout
    assert "".join(events["stderr"]) == result.stderr


def test_nonzero_status_does_not_publish_partial_output(tmp_path):
    """A failed backend must roll back output and expose its actual status safely."""
    # The original remains separate from the backend's private destination.
    source = tmp_path / "original.txt"
    source.write_text("original")
    with pytest.raises(ProcessError) as failure:
        with atomic_output(source, "result") as output:
            run_process(
                [
                    sys.executable,
                    "-c",
                    "from pathlib import Path; import sys; "
                    "Path(sys.argv[1]).write_text('partial'); sys.exit(7)",
                    output.temporary,
                ]
            )
    assert failure.value.returncode == 7
    assert source.read_text() == "original"
    assert not output.destination.exists() and not output.temporary.exists()


def test_timeout_after_pipes_close():
    """Apply the deadline even when the backend closes both pipes before exiting."""
    with pytest.raises(ProcessTimeout):
        run_process(
            [sys.executable, "-c", "import os,time; os.close(1); os.close(2); time.sleep(30)"],
            timeout=0.1,
        )


def test_output_capture_is_bounded():
    """Stop a backend whose combined output exceeds the requested memory budget."""
    with pytest.raises(ProcessError, match="capture limit"):
        run_process(
            [sys.executable, "-c", "import os; os.write(1,b'x'*200000)"], capture_limit=1024
        )


def _not_running(pid):
    """Treat a vanished process or an exited orphan awaiting init as stopped."""
    try:
        return Path(f"/proc/{pid}/stat").read_text().split(")", 1)[1].split()[0] == "Z"
    except FileNotFoundError:
        return True


def _wait_stopped(pid):
    """Allow the kernel to deliver SIGKILL to descendants the runner cannot reap."""
    # The leader is reaped synchronously; an orphan's exit notification is asynchronous.
    deadline = time.monotonic() + 2
    while not _not_running(pid) and time.monotonic() < deadline:
        time.sleep(0.01)
    return _not_running(pid)


def test_timeout_stops_descendants(monkeypatch):
    """Terminate descendants that outlive their session leader or ignore SIGTERM."""
    # Control the runner's deadline clock to trigger timeout deterministically
    # only after the descendant has confirmed readiness.
    real_monotonic = time.monotonic
    clock_offset = 0.0

    def controlled_monotonic():
        return real_monotonic() + clock_offset

    monkeypatch.setattr("lut.core.process.time.monotonic", controlled_monotonic)

    child_pid = []
    stdout_buffer = ""

    def capture_pid(stream, text):
        nonlocal clock_offset, stdout_buffer
        if stream == "stdout":
            stdout_buffer += text
            while "\n" in stdout_buffer:
                line, stdout_buffer = stdout_buffer.split("\n", 1)
                line = line.strip()
                if line.isdigit():
                    child_pid.append(int(line))
                    # Descendant is verified ready with PID captured.
                    # Advance the deadline clock to trigger ProcessTimeout on next selector turn.
                    clock_offset += 100.0

    # Descendant installs SIGTERM ignore handler and confirms with 'ready\n'.
    # Parent waits for handshake before publishing the PID, guaranteeing the signal
    # handler is active before any termination signal is delivered.
    descendant_cmd = (
        "import signal, sys, time; "
        "signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        "sys.stdout.write('ready\\n'); sys.stdout.flush(); "
        "time.sleep(30)"
    )
    program = (
        "import subprocess, sys, time; "
        f"cmd = [sys.executable, '-c', {descendant_cmd!r}]; "
        "p = subprocess.Popen(cmd, stdout=subprocess.PIPE); "
        "assert p.stdout.readline() == b'ready\\n'; "
        "print(p.pid, flush=True); "
        "time.sleep(30)"
    )
    try:
        # A generous wall-clock deadline provides safety against hangs, while the
        # controlled clock triggers the timeout path immediately once ready.
        with pytest.raises(ProcessTimeout):
            run_process(
                [sys.executable, "-c", program],
                timeout=8.0,
                progress=capture_pid,
            )
        assert child_pid and _wait_stopped(child_pid[0])
    finally:
        if child_pid and not _not_running(child_pid[0]):
            os.kill(child_pid[0], signal.SIGKILL)


def test_callback_failure_and_interrupt_cleanup():
    """Clean up before propagating callback errors or cancellation."""

    def interrupt(stream, text):
        """Simulate a user interruption after the backend starts writing."""
        raise KeyboardInterrupt

    with pytest.raises(CancelledError) as failure:
        run_process(
            [sys.executable, "-c", "import time; print('ready',flush=True); time.sleep(30)"],
            progress=interrupt,
        )
    assert failure.value.exit_code == 130


def test_real_sigint_returns_130_and_reaps_backend(tmp_path):
    """Send real Ctrl+C to a separate runner and verify its owned backend exits."""
    # A ready PID is emitted only after the nested backend is running.
    program = (
        "import sys\nfrom lut.core.process import run_process\n"
        "from lut.core.errors import CancelledError\n"
        "try:\n"
        " run_process([sys.executable,'-c','import os,time; "
        "print(os.getpid(),flush=True); time.sleep(30)'], "
        "progress=lambda stream,text: print(text.strip(),flush=True))\n"
        "except CancelledError as error:\n sys.exit(error.exit_code)\n"
    )
    # Isolate the harness so its SIGINT cannot reach the pytest process.
    harness = subprocess.Popen(
        [sys.executable, "-c", program],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=tmp_path,
        start_new_session=True,
    )
    # Retain the backend PID for cleanup even if an assertion fails.
    backend = None
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(harness.stdout, selectors.EVENT_READ)
            assert selector.select(5), "Runner did not report a ready backend"
        backend = int(harness.stdout.readline().strip())
        harness.send_signal(signal.SIGINT)
        # ProcessRunner must handle the signal without a Python traceback.
        stdout, stderr = harness.communicate(timeout=5)
        assert harness.returncode == 130 and stderr == ""
        assert _wait_stopped(backend)
    finally:
        if harness.poll() is None:
            harness.kill()
        harness.communicate()
        if backend is not None and not _not_running(backend):
            os.kill(backend, signal.SIGKILL)


def test_secret_data_is_not_logged(tmp_path, capsys):
    """Keep arguments, environment and captured backend output out of diagnostics."""
    # Place the same secret in every channel a careless runner could log.
    secret = "private-password-271828"
    # Enable both verbose stderr and a private file log to inspect their complete content.
    log = tmp_path / "logs/lut.log"
    with logging_context(verbose=True, log_file=log):
        # Captured data belongs to the caller; the logger sees only lifecycle events.
        result = run_process(
            [
                sys.executable,
                "-c",
                "import os,sys; print(sys.argv[1]); print(os.environ['SECRET'],file=sys.stderr)",
                secret,
            ],
            env=dict(os.environ, SECRET=secret),
        )
        with pytest.raises(ProcessError) as failure:
            run_process([sys.executable, "-c", "import sys; sys.exit(9)", secret])
        assert secret not in str(failure.value)
    assert secret in result.stdout and secret in result.stderr
    assert secret not in repr(result)
    assert secret not in capsys.readouterr().err
    assert secret not in log.read_text()


@pytest.mark.parametrize(
    "arguments, options",
    [
        ("echo text", {}),
        ([], {}),
        ([""], {}),
        (["x\0"], {}),
        (["x"], {"timeout": 0}),
        (["x"], {"timeout": float("nan")}),
        (["x"], {"capture_limit": 0}),
        (["x"], {"env": {"BAD=KEY": "value"}}),
    ],
)
def test_invalid_process_requests(arguments, options):
    """Reject malformed requests before starting an executable."""
    with pytest.raises(UsageError):
        run_process(arguments, **options)


def test_missing_backend_and_invalid_working_directory(tmp_path):
    """Distinguish missing executables from invalid operation input."""
    with pytest.raises(DependencyError):
        run_process([str(tmp_path / "absent")])
    with pytest.raises(InputError):
        run_process([sys.executable], cwd=tmp_path / "absent")
    # Existing files without executable permission are access errors, not missing backends.
    nonexecutable = tmp_path / "not-executable"
    nonexecutable.write_text("no executable permission")
    nonexecutable.chmod(0o600)
    with pytest.raises(OutputError):
        run_process([nonexecutable])


def test_repeated_processes_do_not_leak_descriptors():
    """Close selectors and both pipes across repeated completed operations."""
    # Compare at the same point in the test without involving other components.
    before = len(list(Path("/proc/self/fd").iterdir()))
    for _ in range(10):
        run_process([sys.executable, "-c", "pass"])
    assert len(list(Path("/proc/self/fd").iterdir())) == before
