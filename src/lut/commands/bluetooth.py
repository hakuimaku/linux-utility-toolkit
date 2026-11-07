"""Register Bluetooth command group without contacting BlueZ or hardware adapters."""


def register(parser) -> None:
    """Register Bluetooth discovery and device commands."""
    dependencies = "Python 3.11+ for help; backend: BlueZ (not checked)."
    bluetooth = parser.add_command(
        "bluetooth",
        "Inspect and manage Bluetooth devices.",
        dependencies=dependencies,
        examples=("lut bluetooth help", "lut bluetooth pair help"),
    )
    operations = (
        ("scan", "Scan for Bluetooth devices.", False),
        ("devices", "List known Bluetooth devices.", False),
        ("pair", "Pair a Bluetooth device.", True),
        ("connect", "Connect a Bluetooth device.", True),
        ("disconnect", "Disconnect a Bluetooth device.", True),
        ("remove", "Remove a saved Bluetooth device.", True),
    )
    for name, description, modifies in operations:
        example = f"lut bluetooth {name}" + (" AA:BB:CC:DD:EE:FF" if modifies else "")
        command = bluetooth.add_command(
            name,
            description,
            dependencies=dependencies,
            dry_run=modifies,
            examples=(f"{example}  # planned; not implemented",),
        )
        if modifies:
            command.add_argument("address", help="Device address.")
