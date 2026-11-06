"""Register Bluetooth help without contacting BlueZ or adapters."""


def register(parser) -> None:
    """Describe discovery and explicit device actions without executing them."""
    # Document the future service requirement without probing its availability.
    dependencies = "Python 3.11+ for help; planned backend: BlueZ (not checked)."
    # Keep all device-related syntax under the Bluetooth namespace.
    bluetooth = parser.add_command(
        "bluetooth",
        "Inspect and manage Bluetooth devices.",
        dependencies=dependencies,
        examples=("lut bluetooth help", "lut bluetooth pair help"),
    )
    # Device actions need an address; discovery commands do not.
    operations = (
        ("scan", "Scan for Bluetooth devices.", False),
        ("devices", "List known Bluetooth devices.", False),
        ("pair", "Pair a Bluetooth device.", True),
        ("connect", "Connect a Bluetooth device.", True),
        ("disconnect", "Disconnect a Bluetooth device.", True),
        ("remove", "Remove a saved Bluetooth device.", True),
    )
    for name, description, modifies in operations:
        # Provide a device address only for commands that accept one.
        example = f"lut bluetooth {name}" + (" AA:BB:CC:DD:EE:FF" if modifies else "")
        # Describe device actions without installing an execution handler.
        command = bluetooth.add_command(
            name,
            description,
            dependencies=dependencies,
            dry_run=modifies,
            examples=(f"{example}  # planned; not implemented",),
        )
        if modifies:
            command.add_argument("address", help="Device address (planned input).")
