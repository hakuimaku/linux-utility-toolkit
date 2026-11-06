"""Locate XDG directories and load optional TOML without creating files."""

import os
import stat
import tomllib
from pathlib import Path

from lut.core.errors import InputError, OutputError


def _xdg_home(variable: str, fallback: str) -> Path:
    """Ignore relative XDG overrides as required by the XDG specification."""
    # Environment overrides must be nonempty absolute paths.
    override = os.environ.get(variable, "")
    return Path(override) if override and Path(override).is_absolute() else Path.home() / fallback


def config_file() -> Path:
    """Return the user config path without creating it."""
    return _xdg_home("XDG_CONFIG_HOME", ".config") / "lut/config.toml"


def cache_dir() -> Path:
    """Return the cache directory without creating it."""
    return _xdg_home("XDG_CACHE_HOME", ".cache") / "lut"


def state_dir() -> Path:
    """Return the state and log directory without creating it."""
    return _xdg_home("XDG_STATE_HOME", ".local/state") / "lut"


def load_config(path: str | os.PathLike[str] | None = None) -> dict:
    """Read TOML; an absent default config means defaults, not a first-run write."""
    # An explicitly requested file must exist; the default file is optional.
    source = config_file() if path is None else Path(path)
    try:
        if not stat.S_ISREG(source.stat().st_mode):
            raise InputError(f"Config must be a regular file: {source}")
        with source.open("rb") as stream:
            return tomllib.load(stream)
    except FileNotFoundError:
        if path is None:
            return {}
        raise InputError(f"Config file not found: {source}") from None
    except (tomllib.TOMLDecodeError, UnicodeError):
        raise InputError(f"Invalid TOML config: {source}") from None
    except OSError:
        raise OutputError(f"Cannot read config file: {source}") from None
