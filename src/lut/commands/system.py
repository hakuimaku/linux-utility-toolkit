"""Register system-information help without inspecting the host."""


def register(parser) -> None:
    """Describe read-only system queries without requiring a system manager."""
    # State platform requirements without selecting a backend.
    dependencies = "Python 3.11+ for help; planned system backends depend on the platform."
    # Keep system commands read-only and free of preview flags.
    system = parser.add_command(
        "system",
        "Inspect system resources.",
        dependencies=dependencies,
        examples=("lut system help", "lut system memory help"),
    )
    # Register only query names and descriptions, with no host access.
    operations = (
        ("info", "Inspect system information."),
        ("disk", "Inspect disk usage."),
        ("memory", "Inspect memory usage."),
        ("process", "List running processes."),
        ("ports", "Inspect listening ports."),
    )
    for name, description in operations:
        system.add_command(
            name,
            description,
            dependencies=dependencies,
            examples=(f"lut system {name}  # planned; not implemented",),
        )
