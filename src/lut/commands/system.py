"""Register and handle system inspection commands: info, disk, memory, process, and ports."""

import argparse

from lut.services.system_service import (
    system_disk,
    system_info,
    system_memory,
    system_ports,
    system_process,
)


def _handle_info(args: argparse.Namespace) -> int:
    """Handle system general information inspection."""
    return system_info(as_json=args.json)


def _handle_disk(args: argparse.Namespace) -> int:
    """Handle disk usage inspection."""
    return system_disk(
        path=args.path,
        all_filesystems=args.all,
        include_virtual=args.include_virtual,
        local_only=args.local_only,
        as_json=args.json,
    )


def _handle_memory(args: argparse.Namespace) -> int:
    """Handle memory and swap usage inspection."""
    return system_memory(as_json=args.json)


def _handle_process(args: argparse.Namespace) -> int:
    """Handle process list and resource inspection."""
    return system_process(
        sort_by=args.sort,
        limit=args.limit,
        pid=args.pid,
        name_filter=args.name,
        user_filter=args.user,
        as_json=args.json,
    )


def _handle_ports(args: argparse.Namespace) -> int:
    """Handle network ports inspection."""
    return system_ports(
        protocol=args.protocol,
        port=args.port,
        all_sockets=args.all,
        as_json=args.json,
    )


def register(parser) -> None:
    """Register system command group and operational subcommands."""
    dependencies = "Python 3.11+; Linux /proc (zero external runtime dependencies)."

    system = parser.add_command(
        "system",
        "Inspect system hardware, memory, disks, processes, and network ports.",
        status="",
        dependencies=dependencies,
        examples=(
            "lut system info",
            "lut system disk",
            "lut system memory",
            "lut system process",
            "lut system ports",
            "lut system help",
        ),
    )

    # 1. system info
    cmd_info = system.add_command(
        "info",
        "Inspect OS, kernel, architecture, CPU, and system uptime.",
        handler=_handle_info,
        dependencies="Python 3.11+; Linux /proc and os-release.",
        examples=(
            "lut system info",
            "lut system info --json",
        ),
    )
    cmd_info.add_argument(
        "--json",
        action="store_true",
        help="Output system information in JSON format.",
    )

    # 2. system disk
    cmd_disk = system.add_command(
        "disk",
        "Inspect filesystem capacity, used space, available space, and mount points.",
        handler=_handle_disk,
        dependencies="Python 3.11+; Linux /proc/self/mountinfo.",
        examples=(
            "lut system disk",
            "lut system disk --path /home",
            "lut system disk --all",
            "lut system disk --all --include-virtual",
            "lut system disk --all --local-only",
            "lut system disk --json",
        ),
    )
    cmd_disk.add_argument(
        "-p",
        "--path",
        default=None,
        help="Target filesystem path to inspect (default: current working directory).",
    )
    cmd_disk.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="Display all mounted storage filesystems.",
    )
    cmd_disk.add_argument(
        "--include-virtual",
        action="store_true",
        help="Include virtual and pseudo filesystems with --all.",
    )
    cmd_disk.add_argument(
        "--local-only",
        action="store_true",
        help="Skip remote/network filesystems (NFS, CIFS, SSHFS) when listing all mounts.",
    )
    cmd_disk.add_argument(
        "--json",
        action="store_true",
        help="Output disk information in JSON format.",
    )

    # 3. system memory
    cmd_memory = system.add_command(
        "memory",
        "Inspect RAM, available memory, estimated used memory, buffers, and swap.",
        handler=_handle_memory,
        dependencies="Python 3.11+; Linux /proc/meminfo.",
        examples=(
            "lut system memory",
            "lut system memory --json",
        ),
    )
    cmd_memory.add_argument(
        "--json",
        action="store_true",
        help="Output memory information in JSON format.",
    )

    # 4. system process
    cmd_process = system.add_command(
        "process",
        "List running processes with lifetime CPU utilization and RSS memory.",
        handler=_handle_process,
        dependencies="Python 3.11+; Linux /proc.",
        examples=(
            "lut system process",
            "lut system process --sort cpu",
            "lut system process --sort memory",
            "lut system process --sort pid",
            "lut system process --sort name",
            "lut system process --name python",
            "lut system process --user root",
            "lut system process --limit 10",
            "lut system process --pid 1234",
            "lut system process --json",
        ),
    )
    cmd_process.add_argument(
        "-s",
        "--sort",
        default="cpu",
        choices=["cpu", "memory", "pid", "name"],
        help="Sort processes by cpu, memory, pid, or name (default: cpu).",
    )
    cmd_process.add_argument(
        "-l",
        "--limit",
        type=int,
        default=20,
        help="Maximum number of processes to display (default: 20).",
    )
    cmd_process.add_argument(
        "-n",
        "--name",
        default=None,
        help="Filter processes by name or command line substring.",
    )
    cmd_process.add_argument(
        "-u",
        "--user",
        default=None,
        help="Filter processes by username or UID.",
    )
    cmd_process.add_argument(
        "--pid",
        type=int,
        default=None,
        help="Inspect a specific process by PID.",
    )
    cmd_process.add_argument(
        "--json",
        action="store_true",
        help="Output process information in JSON format.",
    )

    # 5. system ports
    cmd_ports = system.add_command(
        "ports",
        "Inspect open network ports and listening sockets.",
        handler=_handle_ports,
        dependencies="Python 3.11+; Linux /proc/net (optionally ss from iproute2).",
        examples=(
            "lut system ports",
            "lut system ports --protocol tcp",
            "lut system ports --protocol udp",
            "lut system ports --port 8080",
            "lut system ports --all",
            "lut system ports --json",
        ),
    )
    cmd_ports.add_argument(
        "-p",
        "--protocol",
        choices=["tcp", "udp"],
        default=None,
        help="Filter network protocol: tcp or udp (default: all protocols).",
    )
    cmd_ports.add_argument(
        "--port",
        type=int,
        default=None,
        help="Filter by local port number (1-65535).",
    )
    cmd_ports.add_argument(
        "-a",
        "--all",
        action="store_true",
        help="Display all sockets including non-listening connections.",
    )
    cmd_ports.add_argument(
        "--json",
        action="store_true",
        help="Output port information in JSON format.",
    )
