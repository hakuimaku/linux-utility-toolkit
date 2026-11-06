"""Validate demand-driven dependencies and side-effect-free XDG config loading."""

import os
import sys

import pytest

from lut.core import config, dependencies
from lut.core.errors import DependencyError, InputError, OutputError, ServiceUnavailable


@pytest.mark.parametrize(
    "variable, function, default",
    [
        ("XDG_CONFIG_HOME", config.config_file, ".config/lut/config.toml"),
        ("XDG_CACHE_HOME", config.cache_dir, ".cache/lut"),
        ("XDG_STATE_HOME", config.state_dir, ".local/state/lut"),
    ],
)
def test_xdg_defaults_and_absolute_overrides(tmp_path, monkeypatch, variable, function, default):
    """Use absolute overrides and ignore relative or empty XDG values."""
    monkeypatch.setenv("HOME", str(tmp_path))
    for value in ("", "relative/path"):
        monkeypatch.setenv(variable, value)
        assert function() == tmp_path / default
    # Config is a file under the override; cache and state are directories under it.
    override = tmp_path / "đường dẫn ; $"
    monkeypatch.setenv(variable, str(override))
    assert function() == override / ("lut/config.toml" if variable == "XDG_CONFIG_HOME" else "lut")
    assert list(tmp_path.iterdir()) == []


def test_optional_config_and_explicit_missing_file(tmp_path, monkeypatch):
    """A missing default needs no first-run write; an explicit missing file is an error."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    assert config.load_config() == {}
    assert not (tmp_path / "config").exists()
    with pytest.raises(InputError):
        config.load_config(tmp_path / "explicit.toml")


def test_config_toml_errors_and_access(tmp_path, monkeypatch):
    """Read valid TOML while distinguishing malformed data and filesystem failures."""
    # Use a Unicode filename and literal characters without a shell.
    path = tmp_path / "cấu hình ; $.toml"
    path.write_text('[tool]\nname = "LUT"\n')
    assert config.load_config(path) == {"tool": {"name": "LUT"}}
    path.write_text('secret = "private-password"\ninvalid = [')
    with pytest.raises(InputError) as failure:
        config.load_config(path)
    assert "private-password" not in str(failure.value)

    def denied(*args, **kwargs):
        """Inject an access failure independently of root permission bypass."""
        raise PermissionError

    monkeypatch.setattr(type(path), "open", denied)
    with pytest.raises(OutputError):
        config.load_config(path)


def test_config_rejects_directories_and_fifos_without_blocking(tmp_path):
    """Reject nonregular config inputs before attempting a potentially blocking read."""
    with pytest.raises(InputError):
        config.load_config(tmp_path)
    # A FIFO must never wait for a writer during configuration loading.
    fifo = tmp_path / "config.toml"
    os.mkfifo(fifo)
    with pytest.raises(InputError):
        config.load_config(fifo)


@pytest.mark.parametrize(
    "release, family, manager",
    [
        ({"ID": "arch"}, "arch", "pacman -S"),
        ({"ID": "manjaro", "ID_LIKE": "arch"}, "arch", "pacman -S"),
        ({"ID": "ubuntu", "ID_LIKE": "debian"}, "debian", "apt install"),
        ({"ID": "debian"}, "debian", "apt install"),
        ({"ID": "fedora"}, "fedora", "dnf install"),
    ],
)
def test_missing_dependency_only_suggests_installation(monkeypatch, release, family, manager):
    """Provide distro-specific instructions without executing a package manager."""
    monkeypatch.setattr(dependencies.platform, "freedesktop_os_release", lambda: release)
    monkeypatch.setattr(dependencies.shutil, "which", lambda name: None)

    def forbidden(*args, **kwargs):
        """Treat any process launch as an unauthorized automatic installation."""
        pytest.fail("A missing dependency must not launch a process")

    monkeypatch.setattr(dependencies, "run_process", forbidden)
    with pytest.raises(DependencyError) as failure:
        dependencies.require_executable("backend", packages={family: "package-name"})
    assert f"{manager} package-name" in str(failure.value)
    assert failure.value.exit_code == 3


def test_unknown_distribution_has_a_generic_hint(monkeypatch):
    """Avoid guessing package names or managers on an unknown distro."""
    monkeypatch.setattr(dependencies.platform, "freedesktop_os_release", lambda: {"ID": "other"})
    assert "distribution's package manager" in dependencies.installation_hint("backend")


def test_path_lookup_and_optional_numeric_version(tmp_path, monkeypatch):
    """Check an explicitly requested version, including zero-padded components."""
    # A PATH entry with Unicode and spaces still resolves to a literal executable path.
    backend = tmp_path / "bộ xử lý"
    backend.symlink_to(sys.executable)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert dependencies.require_executable(backend.name) == backend
    assert (
        dependencies.require_executable(
            backend.name, minimum_version=(2, 0, 0), version_args=("-c", "print('backend 2.0')")
        )
        == backend
    )
    with pytest.raises(DependencyError, match="too old"):
        dependencies.require_executable(
            backend.name, minimum_version=(3, 0), version_args=("-c", "print('backend 2.9')")
        )
    with pytest.raises(DependencyError, match="parse"):
        dependencies.require_executable(
            backend.name, minimum_version=(1,), version_args=("-c", "print('unknown')")
        )
    with pytest.raises(DependencyError, match="Unsupported"):
        dependencies.require_executable(
            backend.name,
            minimum_version=(2, 0),
            version_args=("-c", "print('backend 2.0rc1')"),
        )


def test_service_missing_backend_and_inactive_service_are_distinct(tmp_path):
    """Keep a missing probe executable at code 3 and an unhealthy service at code 1."""
    with pytest.raises(DependencyError):
        dependencies.require_service("example", [str(tmp_path / "missing")])
    with pytest.raises(ServiceUnavailable) as failure:
        dependencies.require_service("example", [sys.executable, "-c", "import sys; sys.exit(1)"])
    assert failure.value.exit_code == 1
    with pytest.raises(ServiceUnavailable):
        dependencies.require_service(
            "example",
            [sys.executable, "-c", "print('stopped')"],
            expected_output="running",
        )
    dependencies.require_service(
        "example",
        [sys.executable, "-c", "print('running')"],
        expected_output="running",
    )


def test_version_probe_failure_and_service_timeout():
    """Classify failed version checks and stalled services without claiming readiness."""
    with pytest.raises(DependencyError, match="verify"):
        dependencies.require_executable(
            sys.executable,
            minimum_version=(1,),
            version_args=("-c", "import sys; sys.exit(1)"),
        )
    with pytest.raises(ServiceUnavailable):
        dependencies.require_service(
            "example",
            [sys.executable, "-c", "import time; time.sleep(30)"],
            timeout=0.1,
        )
