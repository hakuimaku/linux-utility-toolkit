"""Check only requested executables, versions and caller-defined service probes."""

import os
import platform
import re
import shlex
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path

from lut.core.errors import DependencyError, ProcessError, ServiceUnavailable, UsageError
from lut.core.process import run_process


def installation_hint(executable: str, packages: Mapping[str, str] | None = None) -> str:
    """Suggest a package-manager command only when the caller supplies a package mapping."""
    try:
        # Python reads os-release without executing a distro-specific program.
        release = platform.freedesktop_os_release()
    except OSError:
        release = {}
    # Consider derivatives after the distribution's own ID.
    families = [release.get("ID", ""), *release.get("ID_LIKE", "").split()]
    # These are printed suggestions, never executable actions.
    managers = {
        "arch": "pacman -S",
        "debian": "apt install",
        "ubuntu": "apt install",
        "fedora": "dnf install",
    }
    for family in families:
        if packages and family in packages and family in managers:
            return f"Install manually: {managers[family]} {shlex.quote(packages[family])}."
    return (
        f"Install the package providing {executable!r} using your distribution's package manager."
    )


def require_executable(
    name: str,
    *,
    packages: Mapping[str, str] | None = None,
    minimum_version: tuple[int, ...] | None = None,
    version_args: Sequence[str] = ("--version",),
) -> Path:
    """Find an executable on PATH and optionally check its dotted numeric version."""
    if not name or "\0" in name:
        raise UsageError("Executable name must be nonempty and contain no NUL character.")
    # No search is performed until a feature explicitly requests this executable.
    found = shutil.which(name)
    if found is None:
        raise DependencyError(f"Missing dependency: {name}. {installation_hint(name, packages)}")
    if minimum_version is not None:
        if not minimum_version or any(
            type(part) is not int or part < 0 for part in minimum_version
        ):
            raise UsageError("Minimum version must contain nonnegative integers.")
        try:
            # Version probes have a deadline and the runner's bounded output contract.
            result = run_process([found, *version_args], timeout=5)
        except ProcessError:
            raise DependencyError(f"Cannot verify backend version: {name}.") from None
        # This API handles dotted numeric banners, not arbitrary prerelease ordering.
        banner = result.stdout or result.stderr
        # Accept the first dotted numeric release, not a guessed prerelease ordering.
        match = re.search(r"\d+(?:\.\d+)+", banner)
        if match is None:
            raise DependencyError(f"Cannot parse backend version: {name}.")
        if match.end() < len(banner) and (
            banner[match.end()].isalnum() or banner[match.end()] in ".+-_"
        ):
            raise DependencyError(f"Unsupported backend version format: {name}.")
        # Pad components so 2.0 and 2.0.0 compare equally.
        actual = tuple(map(int, match.group().split(".")))
        # Compare the complete numeric version, including patch components if present.
        width = max(len(actual), len(minimum_version))
        if actual + (0,) * (width - len(actual)) < minimum_version + (0,) * (
            width - len(minimum_version)
        ):
            raise DependencyError(f"Backend version is too old: {name}.")
    return Path(os.path.abspath(found))


def require_service(
    name: str,
    probe: Sequence[str | os.PathLike[str]],
    *,
    expected_output: str | None = None,
    timeout: float = 5,
) -> None:
    """Check a supplied health probe without assuming systemd or starting a service."""
    try:
        # The feature chooses a probe appropriate to its backend and service manager.
        result = run_process(probe, timeout=timeout)
    except ProcessError:
        raise ServiceUnavailable(f"Service unavailable or not running: {name}.") from None
    if expected_output is not None and result.stdout.strip() != expected_output:
        raise ServiceUnavailable(f"Service unavailable or not running: {name}.")
