"""Configure scoped stderr logging and explicit private log files."""

import logging
import os
import stat
import sys
from contextlib import contextmanager
from pathlib import Path

from lut.core.errors import OutputError

# Library calls stay silent until the application chooses a logging context.
logger = logging.getLogger("lut")
logger.addHandler(logging.NullHandler())


class _PrivateFileHandler(logging.FileHandler):
    """Open regular log files without following symlinks or blocking on FIFOs."""

    def _open(self):
        """Own a private append-only stream that FileHandler closes normally."""
        # Prevent a log path from redirecting writes to another file or a device.
        descriptor = os.open(
            self.baseFilename,
            os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK,
            0o600,
        )
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode) or os.fstat(descriptor).st_nlink != 1:
                raise OSError("Log destination must be a regular file")
            os.fchmod(descriptor, 0o600)
            if stat.S_IMODE(os.fstat(descriptor).st_mode) != 0o600:
                raise OSError("Filesystem cannot enforce private log permissions")
            return os.fdopen(descriptor, "a", encoding="utf-8")
        except BaseException:
            os.close(descriptor)
            raise


@contextmanager
def logging_context(*, verbose: bool = False, log_file: str | os.PathLike[str] | None = None):
    """Temporarily configure LUT's logger; file logging is strictly opt-in."""
    # Restore caller-owned handlers and levels after each embedded CLI invocation.
    previous = logger.handlers[:], logger.level, logger.propagate
    # Stderr is the only default destination; help never creates state directories.
    handlers = [logging.StreamHandler(sys.stderr)]
    try:
        try:
            if log_file is not None:
                # Only explicit file logging creates the chosen parent directory.
                path = Path(log_file)
                path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                handlers.append(_PrivateFileHandler(path, encoding="utf-8"))
        except OSError:
            raise OutputError(
                "Cannot create a private regular log file at the requested path."
            ) from None
        for handler in handlers:
            handler.setFormatter(logging.Formatter("lut: %(levelname)s: %(message)s"))
        logger.handlers = handlers
        logger.propagate = False
        logger.setLevel(logging.DEBUG if verbose else logging.INFO)
        yield logger
    finally:
        for handler in handlers:
            handler.close()
        logger.handlers, logger.level, logger.propagate = previous
