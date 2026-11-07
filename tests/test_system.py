"""Tests for system tools: info, disk, memory, process, and ports."""

import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import mock_open, patch

import pytest

from lut import cli
from lut.core.errors import DependencyError, InputError, OutputError, UsageError
from lut.core.process import ProcessResult
from lut.services.system_service import (
    _decode_mount_path,
    _format_uptime,
    _get_cpu_model,
    _get_os_release,
    _get_uptime_seconds,
    _parse_meminfo,
    _parse_mountinfo,
    _parse_proc_stat_line,
    _parse_ss_address_port,
    _parse_ss_process_field,
    _stat_filesystem,
    system_disk,
    system_info,
    system_memory,
    system_ports,
    system_process,
)


@pytest.fixture
def invoke(capsys):
    """Invoke CLI and capture exit code, stdout, and stderr."""

    def run(arguments):
        try:
            code = cli.main(arguments)
        except SystemExit as error:
            code = error.code
        captured = capsys.readouterr()
        return code, captured.out, captured.err

    return run


# =====================================================================
# Unit Tests: System Info
# =====================================================================


def test_format_uptime():
    """Verify human-readable uptime formatting across granularities."""
    assert _format_uptime(45) == "45s"
    assert _format_uptime(125) == "2m"
    assert _format_uptime(3665) == "1h 1m"
    assert _format_uptime(86400) == "1d 0h 0m"
    assert _format_uptime(90060) == "1d 1h 1m"
    assert _format_uptime(183720) == "2d 3h 2m"


def test_get_os_release_fallback(monkeypatch, tmp_path):
    """Parse /etc/os-release when platform.freedesktop_os_release fails."""
    fake_release = tmp_path / "os-release"
    fake_release.write_text(
        'NAME="Custom Linux"\nVERSION="2026.1"\nID=custom\nVERSION_ID="2026.1"\n',
        encoding="utf-8",
    )

    monkeypatch.setattr("platform.freedesktop_os_release", lambda: (_ for _ in ()).throw(OSError))
    with (
        patch("lut.services.system_service.Path.is_file") as mock_isfile,
        patch("builtins.open", mock_open(read_data=fake_release.read_text())),
    ):
        mock_isfile.return_value = True
        info = _get_os_release()
        assert info["NAME"] == "Custom Linux"
        assert info["VERSION_ID"] == "2026.1"


def test_get_cpu_model_variants():
    """Test CPU model parsing across x86, ARM, RISC-V, and missing cpuinfo."""
    x86_data = "processor\t: 0\nvendor_id\t: GenuineIntel\nmodel name\t: Intel Core i7-9700K\n"
    with patch("builtins.open", mock_open(read_data=x86_data)):
        assert _get_cpu_model() == "Intel Core i7-9700K"

    arm_data = "processor\t: 0\nHardware\t: BCM2835\nProcessor\t: ARMv7 Processor rev 4\n"
    with patch("builtins.open", mock_open(read_data=arm_data)):
        assert _get_cpu_model() in ("ARMv7 Processor rev 4", "BCM2835")

    riscv_data = "processor\t: 0\nhart\t: 0\nisa\t: rv64imafdc\nmmu\t: sv39\nmodel\t: unknown\n"
    with patch("builtins.open", mock_open(read_data=riscv_data)):
        assert _get_cpu_model() is None

    with patch("builtins.open", side_effect=OSError):
        assert _get_cpu_model() is None


def test_get_uptime_seconds_success_and_error():
    """Test reading uptime from /proc/uptime and fallback on error."""
    with patch("builtins.open", mock_open(read_data="12345.67 89101.12\n")):
        assert _get_uptime_seconds() == 12345.67

    with patch("builtins.open", mock_open(read_data="")):
        assert _get_uptime_seconds() is None

    with patch("builtins.open", side_effect=OSError):
        assert _get_uptime_seconds() is None


def test_system_info_text_and_json(monkeypatch):
    """Test system_info in text and JSON formats."""
    monkeypatch.setattr("platform.system", lambda: "Linux")
    monkeypatch.setattr(
        "os.uname",
        lambda: SimpleNamespace(
            release="6.12.0-mock",
            machine="x86_64",
            nodename="mock-host",
        ),
    )
    monkeypatch.setattr("lut.services.system_service._get_cpu_model", lambda: "Mock CPU 3.0GHz")
    monkeypatch.setattr("lut.services.system_service._get_uptime_seconds", lambda: 7384.0)
    monkeypatch.setattr("os.cpu_count", lambda: 8)
    monkeypatch.setattr(
        "lut.services.system_service._get_os_release",
        lambda: {"NAME": "MockOS", "VERSION_ID": "1.0"},
    )

    out_text = io.StringIO()
    code = system_info(as_json=False, stdout_stream=out_text)
    assert code == 0
    text = out_text.getvalue()
    assert "System Information" in text
    assert "OS:           MockOS" in text
    assert "Kernel:       6.12.0-mock" in text
    assert "Architecture: x86_64" in text
    assert "Hostname:     mock-host" in text
    assert "CPU:          Mock CPU 3.0GHz" in text
    assert "CPU Threads:  8" in text
    assert "Uptime:       2h 3m" in text

    out_json = io.StringIO()
    code = system_info(as_json=True, stdout_stream=out_json)
    assert code == 0
    data = json.loads(out_json.getvalue())
    assert data["command"] == "system.info"
    assert data["data"]["os_name"] == "MockOS"
    assert data["data"]["os_version"] == "1.0"
    assert data["data"]["kernel_version"] == "6.12.0-mock"
    assert data["data"]["architecture"] == "x86_64"
    assert data["data"]["hostname"] == "mock-host"
    assert data["data"]["cpu_model"] == "Mock CPU 3.0GHz"
    assert data["data"]["cpu_threads"] == 8
    assert data["data"]["uptime_seconds"] == 7384.0


# =====================================================================
# Unit Tests: Disk Information
# =====================================================================


def test_decode_mount_path():
    """Verify octal decoding in mount paths."""
    assert _decode_mount_path(r"/mnt/my\040data") == "/mnt/my data"
    assert _decode_mount_path(r"/mnt/tab\011dir") == "/mnt/tab\tdir"
    assert _decode_mount_path(r"/plain/path") == "/plain/path"


def test_stat_filesystem_calculations():
    """Verify statvfs conversion to total, used, available, and percentage."""
    # Simulate a statvfs object:
    # 100 blocks total, 20 free (including 10 reserved for root), 10 available to user
    # used = 100 - 20 = 80
    # user_space = used (80) + available (10) = 90
    # percent = 80 / 90 * 100 = 88.9%
    mock_st = SimpleNamespace(
        f_frsize=4096,
        f_bsize=4096,
        f_blocks=100,
        f_bfree=20,
        f_bavail=10,
    )
    with patch("os.statvfs", return_value=mock_st):
        info = _stat_filesystem(
            "/mock/mount", mount_point="/mock/mount", device="/dev/sda1", fs_type="ext4"
        )
        assert info is not None
        assert info["total_bytes"] == 100 * 4096
        assert info["used_bytes"] == 80 * 4096
        assert info["available_bytes"] == 10 * 4096
        assert info["usage_percent"] == 88.9


def test_stat_filesystem_zero_total():
    """Handle zero-capacity filesystem without division by zero."""
    mock_st = SimpleNamespace(
        f_frsize=4096,
        f_bsize=4096,
        f_blocks=0,
        f_bfree=0,
        f_bavail=0,
    )
    with patch("os.statvfs", return_value=mock_st):
        info = _stat_filesystem("/proc", mount_point="/proc", device="proc", fs_type="proc")
        assert info is not None
        assert info["total_bytes"] == 0
        assert info["used_bytes"] == 0
        assert info["available_bytes"] == 0
        assert info["usage_percent"] == 0.0


def test_system_disk_invalid_path():
    """Raise InputError when target path does not exist."""
    with pytest.raises(InputError) as exc_info:
        system_disk(path="/nonexistent/directory/that/does/not/exist")
    assert "Path not found" in str(exc_info.value)


def test_parse_mountinfo_octal_and_dedup():
    """Parse /proc/self/mountinfo with octal escaping and duplicate mount points."""
    sample_mountinfo = (
        r"26 32 0:24 / /proc rw shared:5 - proc proc rw"
        "\n"
        r"32 2 259:6 / / rw shared:1 - ext4 /dev/nvme0n1p6 rw"
        "\n"
        r"40 32 0:30 / /mnt/my\040disk rw shared:14 - ext4 /dev/sdb1 rw"
        "\n"
        r"45 32 0:30 / /mnt/my\040disk rw shared:14 - ext4 /dev/sdb1 rw"
        "\n"
    )
    with (
        patch("pathlib.Path.is_file", return_value=True),
        patch("builtins.open", mock_open(read_data=sample_mountinfo)),
    ):
        mounts = _parse_mountinfo()
        assert len(mounts) == 4
        assert mounts[2]["mount_point"] == "/mnt/my disk"


def test_system_disk_all_and_json(monkeypatch):
    """Test system_disk --all and JSON serialization."""
    mock_mounts = [
        {"mount_point": "/", "filesystem_type": "ext4", "device": "/dev/nvme0n1p1"},
        {"mount_point": "/boot", "filesystem_type": "vfat", "device": "/dev/nvme0n1p2"},
        {"mount_point": "/sys", "filesystem_type": "sysfs", "device": "sys"},
    ]
    monkeypatch.setattr("lut.services.system_service._parse_mountinfo", lambda: mock_mounts)

    def fake_stat(target_path, mount_point=None, device=None, fs_type=None):
        if fs_type == "sysfs":
            return {
                "mount_point": mount_point,
                "device": device,
                "filesystem_type": fs_type,
                "total_bytes": 0,
                "used_bytes": 0,
                "available_bytes": 0,
                "usage_percent": 0.0,
            }
        return {
            "mount_point": mount_point,
            "device": device,
            "filesystem_type": fs_type,
            "total_bytes": 1000000000,
            "used_bytes": 400000000,
            "available_bytes": 600000000,
            "usage_percent": 40.0,
        }

    monkeypatch.setattr("lut.services.system_service._stat_filesystem", fake_stat)

    out_text = io.StringIO()
    code = system_disk(
        all_filesystems=True, include_virtual=False, as_json=False, stdout_stream=out_text
    )
    assert code == 0
    text = out_text.getvalue()
    assert "Mounted Filesystems" in text
    assert "/dev/nvme0n1p1" in text
    assert "/dev/nvme0n1p2" in text
    assert "sysfs" not in text

    out_json = io.StringIO()
    code = system_disk(
        all_filesystems=True, include_virtual=False, as_json=True, stdout_stream=out_json
    )
    assert code == 0
    data = json.loads(out_json.getvalue())
    assert data["command"] == "system.disk"
    assert data["data"]["total_filesystems"] == 2
    assert len(data["data"]["filesystems"]) == 2


# =====================================================================
# Unit Tests: Memory Information
# =====================================================================


def test_parse_meminfo_valid():
    """Parse meminfo fields into bytes and detect invalid values."""
    mem_sample = (
        "MemTotal:       16000000 kB\n"
        "MemFree:         4000000 kB\n"
        "MemAvailable:    8000000 kB\n"
        "Buffers:          500000 kB\n"
        "Cached:          3500000 kB\n"
        "SwapTotal:       4000000 kB\n"
        "SwapFree:        3000000 kB\n"
    )
    with patch("builtins.open", mock_open(read_data=mem_sample)):
        parsed = _parse_meminfo()
        assert parsed["MemTotal"] == 16000000 * 1024
        assert parsed["MemFree"] == 4000000 * 1024
        assert parsed["MemAvailable"] == 8000000 * 1024
        assert parsed["Buffers"] == 500000 * 1024
        assert parsed["Cached"] == 3500000 * 1024
        assert parsed["SwapTotal"] == 4000000 * 1024
        assert parsed["SwapFree"] == 3000000 * 1024


def test_parse_meminfo_negative_value():
    """Raise OutputError if negative value is encountered in /proc/meminfo."""
    mem_sample = "MemTotal:       -16000 kB\n"
    with patch("builtins.open", mock_open(read_data=mem_sample)):
        with pytest.raises(OutputError):
            _parse_meminfo()


def test_system_memory_calculation_and_fallback(monkeypatch):
    """Verify MemAvailable fallback to Free + Buffers + Cached when missing."""
    mem_without_available = {
        "MemTotal": 16000 * 1024,
        "MemFree": 4000 * 1024,
        "Buffers": 1000 * 1024,
        "Cached": 3000 * 1024,
        "SwapTotal": 0,
        "SwapFree": 0,
    }
    monkeypatch.setattr("lut.services.system_service._parse_meminfo", lambda: mem_without_available)

    out_json = io.StringIO()
    code = system_memory(as_json=True, stdout_stream=out_json)
    assert code == 0
    data = json.loads(out_json.getvalue())
    ram = data["data"]["ram"]
    # Fallback available = 4000 + 1000 + 3000 = 8000 kB
    assert ram["available_bytes"] == 8000 * 1024
    assert ram["total_bytes"] == 16000 * 1024
    assert ram["used_estimated_bytes"] == 8000 * 1024
    assert ram["usage_percent"] == 50.0

    swap = data["data"]["swap"]
    assert swap["total_bytes"] == 0
    assert swap["used_bytes"] == 0
    assert swap["free_bytes"] == 0
    assert swap["usage_percent"] == 0.0


# =====================================================================
# Unit Tests: Process Information
# =====================================================================


def test_parse_proc_stat_line_special_names():
    """Parse /proc/<pid>/stat with spaces and parentheses in process names."""
    # 3:state, 4:ppid, 5-13: 9 fields, 14:utime, 15:stime, 16-21: 6 fields, 22:starttime
    z9 = "0 " * 9
    line1 = f"1234 (bash) S 100 {z9}10 20 0 0 0 0 0 0 500 1000 200 0 0 0 0"
    parsed1 = _parse_proc_stat_line(line1)
    assert parsed1 is not None
    assert parsed1[0] == 1234
    assert parsed1[1] == "bash"
    assert parsed1[2] == "S"
    assert parsed1[3] == 100
    assert parsed1[4] == 10
    assert parsed1[5] == 20
    assert parsed1[6] == 500

    # Process with space and paren in comm: (Web (Worker) 1)
    line2 = f"5678 (Web (Worker) 1) R 1 {z9}30 40 0 0 0 0 0 0 1000 2000 400 0 0 0 0"
    parsed2 = _parse_proc_stat_line(line2)
    assert parsed2 is not None
    assert parsed2[0] == 5678
    assert parsed2[1] == "Web (Worker) 1"
    assert parsed2[2] == "R"
    assert parsed2[3] == 1


def test_system_process_invalid_args():
    """Reject invalid sort, limit, or PID parameters."""
    with pytest.raises(UsageError):
        system_process(sort_by="invalid_field")

    with pytest.raises(UsageError):
        system_process(limit=0)

    with pytest.raises(UsageError):
        system_process(pid=-1)


def test_system_process_vanished_process(monkeypatch):
    """Do not crash if a process vanishes between directory listing and file read."""
    monkeypatch.setattr("os.listdir", lambda path: ["100", "200", "300"])
    monkeypatch.setattr("lut.services.system_service._get_uptime_seconds", lambda: 1000.0)

    def fake_open(filename, *args, **kwargs):
        if "200" in str(filename):
            raise FileNotFoundError("Process vanished")
        # Return stat for 100 and 300
        line = "100 (init) S 0 0 0 0 0 0 0 0 1 1 0 0 0 0 0 0 10 100 10 0 0 0 0 0 0 0 0 0 0 0 0 0 0"
        return io.StringIO(line)

    with (
        patch("builtins.open", fake_open),
        patch("lut.services.system_service._get_process_status", return_value=(1000, 1048576)),
    ):
        out = io.StringIO()
        code = system_process(as_json=True, stdout_stream=out)
        assert code == 0
        data = json.loads(out.getvalue())
        # Process 200 was gracefully ignored
        pids = [p["pid"] for p in data["data"]["processes"]]
        assert 200 not in pids


def test_system_process_sort_and_limit(monkeypatch):
    """Verify sorting by cpu, memory, pid, name and limit truncation."""
    fake_procs = [
        {
            "pid": 10,
            "ppid": 1,
            "name": "charlie",
            "user": "user1",
            "uid": 1000,
            "state": "S",
            "cpu_percent": 1.0,
            "memory_rss_bytes": 3000,
        },
        {
            "pid": 20,
            "ppid": 1,
            "name": "alpha",
            "user": "user1",
            "uid": 1000,
            "state": "R",
            "cpu_percent": 10.0,
            "memory_rss_bytes": 1000,
        },
        {
            "pid": 30,
            "ppid": 1,
            "name": "bravo",
            "user": "user1",
            "uid": 1000,
            "state": "S",
            "cpu_percent": 5.0,
            "memory_rss_bytes": 5000,
        },
    ]

    monkeypatch.setattr("os.listdir", lambda path: ["10", "20", "30"])
    monkeypatch.setattr("lut.services.system_service._get_uptime_seconds", lambda: 1000.0)

    def mock_stat_line(pid):
        for p in fake_procs:
            if p["pid"] == pid:
                z = "0 " * 8
                return f"{pid} ({p['name']}) {p['state']} 1 {z}10 10 0 0 0 0 0 0 100 1000 10"
        return ""

    def mock_status(pid):
        for p in fake_procs:
            if p["pid"] == pid:
                return p["uid"], p["memory_rss_bytes"]
        return None, None

    def mock_open_proc(path, *a, **k):
        path_str = str(path)
        pid_val = int(path_str.split("/")[2])
        if path_str.endswith("/cmdline"):
            for p in fake_procs:
                if p["pid"] == pid_val:
                    return io.StringIO(f"{p['name']}\x00")
            return io.StringIO("")
        return io.StringIO(mock_stat_line(pid_val))

    with (
        patch("builtins.open", mock_open_proc),
        patch("lut.services.system_service._get_process_status", side_effect=mock_status),
    ):
        # Sort by memory
        out_mem = io.StringIO()
        system_process(sort_by="memory", limit=2, as_json=True, stdout_stream=out_mem)
        data = json.loads(out_mem.getvalue())["data"]
        assert len(data["processes"]) == 2
        assert data["processes"][0]["pid"] == 30  # 5000 bytes
        assert data["processes"][1]["pid"] == 10  # 3000 bytes

        # Sort by name
        out_name = io.StringIO()
        system_process(sort_by="name", limit=3, as_json=True, stdout_stream=out_name)
        data = json.loads(out_name.getvalue())["data"]
        names = [p["name"] for p in data["processes"]]
        assert names == ["alpha", "bravo", "charlie"]


# =====================================================================
# Unit Tests: Ports
# =====================================================================


def test_parse_ss_address_port():
    """Verify safe address and port separation including canonical IPv6 and interfaces."""
    assert _parse_ss_address_port("127.0.0.1:8080") == ("127.0.0.1", 8080)
    assert _parse_ss_address_port("0.0.0.0:53") == ("0.0.0.0", 53)
    assert _parse_ss_address_port("[::]:22") == ("::", 22)
    assert _parse_ss_address_port("*:5353") == ("0.0.0.0", 5353)
    assert _parse_ss_address_port("[fe80::1%eth0]:443") == ("fe80::1%eth0", 443)
    assert _parse_ss_address_port("invalid_address") == ("invalid_address", None)


def test_parse_ss_process_field():
    """Parse PID and process name from users: field."""
    line_with_proc = 'tcp LISTEN 0 128 127.0.0.1:5037 0.0.0.0:* users:(("adb",pid=1015195,fd=4))'
    proc, pid = _parse_ss_process_field(line_with_proc)
    assert proc == "adb"
    assert pid == 1015195

    line_no_proc = "tcp LISTEN 0 4096 127.0.0.53%lo:53 0.0.0.0:*"
    proc, pid = _parse_ss_process_field(line_no_proc)
    assert proc is None
    assert pid is None


def test_system_ports_validation():
    """Validate invalid port and protocol arguments."""
    with pytest.raises(UsageError):
        system_ports(protocol="http")

    with pytest.raises(UsageError):
        system_ports(port=0)

    with pytest.raises(UsageError):
        system_ports(port=70000)


def test_system_ports_missing_ss_and_proc_net(monkeypatch):
    """Raise DependencyError when ss executable is missing on PATH and /proc/net is unavailable."""
    monkeypatch.setattr("shutil.which", lambda name: None)
    monkeypatch.setattr("pathlib.Path.is_file", lambda self: False)
    with pytest.raises(DependencyError) as exc_info:
        system_ports()
    assert "Missing dependency: ss" in str(exc_info.value)


def test_system_ports_proc_net_fallback(monkeypatch):
    """Succeed using /proc/net fallback when ss executable is missing."""
    monkeypatch.setattr("shutil.which", lambda name: None)
    out = io.StringIO()
    code = system_ports(as_json=True, stdout_stream=out)
    assert code == 0
    data = json.loads(out.getvalue())
    assert data["command"] == "system.ports"
    assert "ports" in data["data"]


def test_system_ports_mock_output(monkeypatch):
    """Verify parsing and filtering of ss output in text and JSON."""
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/ss")

    ss_output = (
        'udp UNCONN 0 0 0.0.0.0:5353 0.0.0.0:* users:(("avahi",pid=500,fd=12))\n'
        'tcp LISTEN 0 128 127.0.0.1:8080 0.0.0.0:* users:(("server",pid=1234,fd=3))\n'
        'tcp LISTEN 0 4096 [::]:22 [::]:* users:(("sshd",pid=800,fd=4))\n'
    )

    fake_result = ProcessResult(returncode=0, stdout=ss_output, stderr="")
    monkeypatch.setattr("lut.services.system_service.run_process", lambda *a, **k: fake_result)

    # Test filtering by protocol tcp
    out_tcp = io.StringIO()
    code = system_ports(protocol="tcp", as_json=True, stdout_stream=out_tcp)
    assert code == 0
    data = json.loads(out_tcp.getvalue())["data"]
    assert data["total_ports"] == 2
    for p in data["ports"]:
        assert p["protocol"] == "tcp"

    # Test filtering by port 8080
    out_port = io.StringIO()
    code = system_ports(port=8080, as_json=True, stdout_stream=out_port)
    assert code == 0
    data = json.loads(out_port.getvalue())["data"]
    assert data["total_ports"] == 1
    assert data["ports"][0]["local_port"] == 8080
    assert data["ports"][0]["process"] == "server"
    assert data["ports"][0]["pid"] == 1234


# =====================================================================
# Integration Tests: CLI & Help
# =====================================================================


def test_cli_system_help_levels(invoke):
    """Verify help is displayed cleanly at every system command depth."""
    for cmd in (
        ["system"],
        ["system", "help"],
        ["system", "--help"],
        ["system", "info", "help"],
        ["system", "info", "--help"],
        ["system", "disk", "help"],
        ["system", "disk", "--help"],
        ["system", "memory", "help"],
        ["system", "memory", "--help"],
        ["system", "process", "help"],
        ["system", "process", "--help"],
        ["system", "ports", "help"],
        ["system", "ports", "--help"],
    ):
        code, out, err = invoke(cmd)
        assert code == 0
        assert err == ""
        assert "usage: lut system" in out
        assert "Examples:" in out
        assert "Required dependencies:" in out


def test_cli_system_info_real(invoke):
    """Run real system info query and check outputs."""
    code, out, err = invoke(["system", "info"])
    assert code == 0
    assert err == ""
    assert "System Information" in out
    assert "Kernel:" in out
    assert "Architecture:" in out

    code, out, err = invoke(["system", "info", "--json"])
    assert code == 0
    assert err == ""
    data = json.loads(out)
    assert data["command"] == "system.info"
    assert "kernel_version" in data["data"]
    assert "cpu_threads" in data["data"]


def test_cli_system_disk_real(invoke):
    """Run real system disk query on cwd and all filesystems."""
    code, out, err = invoke(["system", "disk"])
    assert code == 0
    assert err == ""
    assert "Disk Usage" in out
    assert "Mount Point:" in out

    code, out, err = invoke(["system", "disk", "--all"])
    assert code == 0
    assert err == ""
    assert "Mounted Filesystems" in out

    code, out, err = invoke(["system", "disk", "--json"])
    assert code == 0
    assert err == ""
    data = json.loads(out)
    assert data["command"] == "system.disk"
    assert "total_bytes" in data["data"]
    assert isinstance(data["data"]["total_bytes"], int)


def test_cli_system_memory_real(invoke):
    """Run real memory query and verify non-negative integer bytes."""
    code, out, err = invoke(["system", "memory"])
    assert code == 0
    assert err == ""
    assert "Memory" in out
    assert "RAM Total:" in out
    assert "RAM Available:" in out

    code, out, err = invoke(["system", "memory", "--json"])
    assert code == 0
    assert err == ""
    data = json.loads(out)
    assert data["command"] == "system.memory"
    ram = data["data"]["ram"]
    assert ram["total_bytes"] > 0
    assert ram["available_bytes"] > 0
    assert ram["used_estimated_bytes"] >= 0


def test_cli_system_process_real(invoke):
    """Run real process query and PID lookup."""
    code, out, err = invoke(["system", "process", "--limit", "5"])
    assert code == 0
    assert err == ""
    assert "Processes (sorted by cpu, limit 5)" in out

    # Inspect current process PID
    current_pid = os.getpid()
    code, out, err = invoke(["system", "process", "--pid", str(current_pid), "--json"])
    assert code == 0
    assert err == ""
    data = json.loads(out)
    assert data["command"] == "system.process"
    assert data["data"]["total_processes"] == 1
    assert data["data"]["processes"][0]["pid"] == current_pid


def test_cli_system_ports_real(invoke):
    """Run real ports query if ss is available."""
    import shutil

    if not shutil.which("ss"):
        pytest.skip("ss executable not available in environment")

    code, out, err = invoke(["system", "ports", "--limit", "5"] if False else ["system", "ports"])
    assert code == 0
    assert err == ""
    assert "Open Network Ports" in out

    code, out, err = invoke(["system", "ports", "--json"])
    assert code == 0
    assert err == ""
    data = json.loads(out)
    assert data["command"] == "system.ports"
    assert isinstance(data["data"]["ports"], list)


# =====================================================================
# Additional Tests: Bugfixes and Enhancements based on Review
# =====================================================================


def test_system_disk_longest_prefix_order_independence(monkeypatch, tmp_path):
    """Verify longest-prefix mount matching is order-independent (Operator Precedence Bug fix)."""
    # Create target directory
    test_dir = tmp_path / "mnt" / "data" / "nvme" / "project"
    test_dir.mkdir(parents=True)

    # Case A: Child (/mnt/data/nvme) listed BEFORE Parent (/mnt)
    mounts_a = [
        {
            "mount_point": str(tmp_path / "mnt" / "data" / "nvme"),
            "device": "/dev/nvme0n1",
            "filesystem_type": "ext4",
        },
        {"mount_point": str(tmp_path / "mnt"), "device": "/dev/sda1", "filesystem_type": "ext4"},
        {"mount_point": "/", "device": "/dev/root", "filesystem_type": "ext4"},
    ]
    monkeypatch.setattr("lut.services.system_service._parse_mountinfo", lambda: mounts_a)

    out_a = io.StringIO()
    system_disk(path=test_dir, as_json=True, stdout_stream=out_a)
    data_a = json.loads(out_a.getvalue())["data"]
    assert data_a["mount_point"] == str(tmp_path / "mnt" / "data" / "nvme")
    assert data_a["device"] == "/dev/nvme0n1"

    # Case B: Parent (/mnt) listed BEFORE Child (/mnt/data/nvme)
    mounts_b = [
        {"mount_point": str(tmp_path / "mnt"), "device": "/dev/sda1", "filesystem_type": "ext4"},
        {
            "mount_point": str(tmp_path / "mnt" / "data" / "nvme"),
            "device": "/dev/nvme0n1",
            "filesystem_type": "ext4",
        },
        {"mount_point": "/", "device": "/dev/root", "filesystem_type": "ext4"},
    ]
    monkeypatch.setattr("lut.services.system_service._parse_mountinfo", lambda: mounts_b)

    out_b = io.StringIO()
    system_disk(path=test_dir, as_json=True, stdout_stream=out_b)
    data_b = json.loads(out_b.getvalue())["data"]
    assert data_b["mount_point"] == str(tmp_path / "mnt" / "data" / "nvme")
    assert data_b["device"] == "/dev/nvme0n1"


def test_system_disk_flags_validation():
    """Raise UsageError when combining invalid disk flags."""
    with pytest.raises(UsageError) as exc_info:
        system_disk(path="/home", all_filesystems=True)
    assert "Cannot combine --path and --all" in str(exc_info.value)

    with pytest.raises(UsageError) as exc_info:
        system_disk(include_virtual=True, all_filesystems=False)
    assert "--include-virtual can only be used in combination with --all" in str(exc_info.value)


def test_system_disk_local_only_skips_network(monkeypatch):
    """Verify --local-only skips network mounts such as NFS and CIFS."""
    raw_mounts = [
        {"mount_point": "/mnt/local", "device": "/dev/sda1", "filesystem_type": "ext4"},
        {"mount_point": "/mnt/nfs", "device": "192.168.1.100:/export", "filesystem_type": "nfs4"},
    ]
    monkeypatch.setattr("lut.services.system_service._parse_mountinfo", lambda: raw_mounts)

    def fake_stat(target, mount_point=None, device=None, fs_type=None):
        return {
            "mount_point": mount_point,
            "device": device,
            "filesystem_type": fs_type,
            "total_bytes": 1000000,
            "used_bytes": 500000,
            "available_bytes": 500000,
            "usage_percent": 50.0,
        }

    monkeypatch.setattr("lut.services.system_service._stat_filesystem", fake_stat)

    # When local_only=True, NFS is skipped
    out_local = io.StringIO()
    system_disk(all_filesystems=True, local_only=True, as_json=True, stdout_stream=out_local)
    data_local = json.loads(out_local.getvalue())["data"]
    assert data_local["total_filesystems"] == 1
    assert data_local["filesystems"][0]["mount_point"] == "/mnt/local"


def test_system_process_lru_cache():
    """Verify _get_username uses LRU cache to avoid repeated NSS/LDAP lookups."""
    from lut.services.system_service import _get_username

    _get_username.cache_clear()
    uid = os.getuid()
    name1 = _get_username(uid)
    name2 = _get_username(uid)
    assert name1 == name2
    info = _get_username.cache_info()
    assert info.hits >= 1


def test_system_process_multi_threading_cpu(monkeypatch):
    """Verify worker threads are aggregated into total process CPU%."""
    from lut.services.system_service import _get_process_cpu_times

    monkeypatch.setattr("os.listdir", lambda path: ["101", "102"])

    def fake_open(path, *a, **k):
        # 2 worker threads, each with utime=50, stime=50
        stat_line = "100 (worker) S 1 0 0 0 0 0 0 0 0 0 50 50 0 0 0 0 0 0 100 1000 10"
        return io.StringIO(stat_line)

    with patch("builtins.open", fake_open):
        total_utime, total_stime = _get_process_cpu_times(
            100, main_utime=10, main_stime=10, thread_count=2
        )
        assert total_utime == 100  # 50 + 50
        assert total_stime == 100  # 50 + 50


def test_system_process_name_and_user_filters(monkeypatch):
    """Verify process filtering by --name and --user."""
    fake_procs = [
        {"pid": 100, "comm": "python3", "name": "python3", "user": "alice", "uid": 1001},
        {"pid": 200, "comm": "postgres", "name": "postgres", "user": "postgres", "uid": 999},
        {"pid": 300, "comm": "bash", "name": "bash", "user": "alice", "uid": 1001},
    ]

    monkeypatch.setattr("os.listdir", lambda path: ["100", "200", "300"])
    monkeypatch.setattr("lut.services.system_service._get_uptime_seconds", lambda: 1000.0)

    def mock_stat_line(pid):
        for p in fake_procs:
            if p["pid"] == pid:
                z = "0 " * 8
                return f"{pid} ({p['comm']}) S 1 {z}10 10 0 0 0 0 0 0 100 1000 10"
        return ""

    def mock_status(pid):
        for p in fake_procs:
            if p["pid"] == pid:
                return p["uid"], 1048576, 1
        return None, None, 1

    def mock_cmdline(pid, comm):
        for p in fake_procs:
            if p["pid"] == pid:
                return p["name"], f"/usr/bin/{p['name']} --arg"
        return comm, comm

    monkeypatch.setattr("lut.services.system_service._get_process_status", mock_status)
    monkeypatch.setattr("lut.services.system_service._get_process_cmdline", mock_cmdline)

    def mock_open_proc(path, *a, **k):
        pid_val = int(str(path).split("/")[2])
        return io.StringIO(mock_stat_line(pid_val))

    def mock_get_user(uid):
        return "postgres" if uid == 999 else "alice"

    with (
        patch("builtins.open", mock_open_proc),
        patch("lut.services.system_service._get_username", mock_get_user),
    ):
        # Filter by name "postgres"
        out_name = io.StringIO()
        system_process(name_filter="postgres", as_json=True, stdout_stream=out_name)
        data_name = json.loads(out_name.getvalue())["data"]
        assert data_name["total_processes"] == 1
        assert data_name["processes"][0]["pid"] == 200

        # Filter by user "alice"
        out_user = io.StringIO()
        system_process(user_filter="alice", as_json=True, stdout_stream=out_user)
        data_user = json.loads(out_user.getvalue())["data"]
        assert data_user["total_processes"] == 2
        assert {p["pid"] for p in data_user["processes"]} == {100, 300}


def test_system_memory_cgroup_container_limit(monkeypatch):
    """Verify container cgroup memory limits are reported when active."""
    monkeypatch.setattr(
        "lut.services.system_service._parse_meminfo",
        lambda: {
            "MemTotal": 32000000 * 1024,
            "MemFree": 16000000 * 1024,
            "MemAvailable": 24000000 * 1024,
        },
    )
    # 512 MiB container limit on 32 GiB host
    monkeypatch.setattr(
        "lut.services.system_service._get_cgroup_memory_limit",
        lambda: (536870912, 134217728),
    )

    out = io.StringIO()
    system_memory(as_json=True, stdout_stream=out)
    data = json.loads(out.getvalue())["data"]
    assert data["cgroup"] is not None
    assert data["cgroup"]["limit_bytes"] == 536870912
    assert data["cgroup"]["usage_bytes"] == 134217728

    out_text = io.StringIO()
    system_memory(as_json=False, stdout_stream=out_text)
    text = out_text.getvalue()
    assert "Container Limit:" in text
    assert "Container Used:" in text


def test_cgroup_nested_candidate_paths(monkeypatch):
    """Verify cgroup resolver maps /proc/self/cgroup nested container slices."""
    from lut.services.system_service import _get_cgroup_candidate_paths

    mock_cgroup = "0::/docker/nested123\n"
    with patch("builtins.open", mock_open(read_data=mock_cgroup)):
        candidates = _get_cgroup_candidate_paths("memory")
        assert Path("/sys/fs/cgroup/docker/nested123") in candidates


def test_cgroup_invalid_or_permission_denied(monkeypatch):
    """Gracefully return None when cgroup files are malformed or unreadable."""
    from lut.services.system_service import _get_cgroup_cpu_quota

    monkeypatch.setattr("pathlib.Path.is_file", lambda self: True)
    monkeypatch.setattr("pathlib.Path.read_text", lambda self, *a, **k: "invalid_quota_format")
    assert _get_cgroup_cpu_quota() is None


def test_system_disk_shadowed_overmount(monkeypatch, tmp_path):
    """Verify shadowed over-mounts with equal length correctly pick the latest mount."""
    mount_dir = tmp_path / "mnt"
    mount_dir.mkdir()

    # Two mounts on the exact same mount_point, latest is tmpfs
    mounts = [
        {"mount_point": str(mount_dir), "device": "/dev/sda1", "filesystem_type": "ext4"},
        {"mount_point": str(mount_dir), "device": "tmpfs", "filesystem_type": "tmpfs"},
    ]
    monkeypatch.setattr("lut.services.system_service._parse_mountinfo", lambda: mounts)

    out = io.StringIO()
    system_disk(path=mount_dir, as_json=True, stdout_stream=out)
    data = json.loads(out.getvalue())["data"]
    assert data["filesystem_type"] == "tmpfs"
    assert data["device"] == "tmpfs"


def test_system_disk_filters_snap_and_credentials(monkeypatch):
    """Verify snap squashfs loops and systemd credentials are filtered out from --all."""
    mounts = [
        {"mount_point": "/", "device": "/dev/sda1", "filesystem_type": "ext4"},
        {"mount_point": "/snap/core/123", "device": "/dev/loop0", "filesystem_type": "squashfs"},
        {
            "mount_point": "/run/credentials/systemd-journald.service",
            "device": "tmpfs",
            "filesystem_type": "tmpfs",
        },
    ]
    monkeypatch.setattr("lut.services.system_service._parse_mountinfo", lambda: mounts)

    def fake_stat(target, mount_point=None, device=None, fs_type=None):
        return {
            "mount_point": mount_point,
            "device": device,
            "filesystem_type": fs_type,
            "total_bytes": 1000000,
            "used_bytes": 500000,
            "available_bytes": 500000,
            "usage_percent": 50.0,
        }

    monkeypatch.setattr("lut.services.system_service._stat_filesystem", fake_stat)

    out = io.StringIO()
    system_disk(all_filesystems=True, include_virtual=False, as_json=True, stdout_stream=out)
    data = json.loads(out.getvalue())["data"]
    # Only the root ext4 mount should be present
    assert data["total_filesystems"] == 1
    assert data["filesystems"][0]["mount_point"] == "/"


def test_system_process_excludes_self():
    """Verify system_process excludes its own PID during global scanning."""
    out = io.StringIO()
    code = system_process(limit=50, as_json=True, stdout_stream=out)
    assert code == 0
    data = json.loads(out.getvalue())["data"]
    current_pid = os.getpid()
    scanned_pids = [p["pid"] for p in data["processes"]]
    assert current_pid not in scanned_pids


def test_system_process_smart_interpreter_command():
    """Verify smart interpreter resolution extracts script name."""
    from lut.services.system_service import _get_process_cmdline

    with patch(
        "builtins.open",
        mock_open(read_data=b"/usr/bin/python3\x00/app/worker.py\x00--threads\x004"),
    ):
        display_name, full_cmd = _get_process_cmdline(1234, "python3")
        assert display_name == "python3 worker.py"
        assert "/app/worker.py" in full_cmd


def test_system_process_kernel_thread():
    """Verify kernel threads with empty cmdline gracefully display [comm]."""
    from lut.services.system_service import _get_process_cmdline

    with patch("builtins.open", mock_open(read_data=b"")):
        display_name, full_cmd = _get_process_cmdline(2, "kworker/u16:0")
        assert display_name == "kworker/u16:0"
        assert full_cmd == "[kworker/u16:0]"


def test_system_process_space_separated_cmdline():
    """Verify space-separated cmdlines (Chromium/Electron/setproctitle) extract true binary name."""
    from lut.services.system_service import _get_process_cmdline

    raw_electron = b"/usr/share/code/code --type=renderer --app-path=/usr/share/code/resources/app"
    with patch("builtins.open", mock_open(read_data=raw_electron)):
        display_name, full_cmd = _get_process_cmdline(1234, "code")
        assert display_name == "code"
        assert "resources/app" in full_cmd


def test_normalize_scoped_ipv6_address():
    """Verify scoped IPv6 addresses strip brackets cleanly without stray closing bracket."""
    from lut.services.system_service import _normalize_network_address

    assert _normalize_network_address("[fe80::1]%wlo1") == "fe80::1%wlo1"
    assert _normalize_network_address("[::]") == "::"
    assert _normalize_network_address("127.0.0.53%lo") == "127.0.0.53%lo"
