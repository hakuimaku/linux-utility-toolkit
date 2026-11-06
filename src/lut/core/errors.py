"""Represent expected failures with the CLI's stable exit codes."""

import sys


class LutError(Exception):
    """Describe an execution failure safe to show to the user."""

    exit_code = 1


class UsageError(LutError):
    """Reject invalid operation parameters."""

    exit_code = 2


class DependencyError(LutError):
    """Report an unavailable executable or unsupported backend version."""

    exit_code = 3


class InputError(LutError):
    """Report missing or malformed input."""

    exit_code = 4


class OutputError(LutError):
    """Report an output conflict or filesystem access failure."""

    exit_code = 5


class CancelledError(LutError):
    """Report cancellation after owned resources have been cleaned up."""

    exit_code = 130


class ProcessError(LutError):
    """Report backend failure without exposing its arguments or output."""

    def __init__(self, message: str, returncode: int | None = None):
        """Retain the backend status for callers without printing backend data."""
        super().__init__(message)
        # Preserve the actual backend code separately from LUT's exit code.
        self.returncode = returncode


class ProcessTimeout(ProcessError):
    """Report a backend that exceeded its deadline."""


class ServiceUnavailable(LutError):
    """Distinguish an installed backend from an unavailable service."""


def report_error(error: Exception) -> int:
    """Print expected diagnostics and hide arbitrary exception data from the CLI."""
    # Unexpected exceptions can contain credentials or complete subprocess arguments.
    message = str(error) if isinstance(error, LutError) else "Unexpected execution failure."
    print(f"lut: error: {message}", file=sys.stderr)
    return error.exit_code if isinstance(error, LutError) else 1
