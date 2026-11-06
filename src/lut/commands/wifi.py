"""Register Wi-Fi help without touching network services or credentials."""


def register(parser) -> None:
    """Describe planned Wi-Fi queries and connection changes."""
    # Show backend names without selecting or starting a service.
    dependencies = "Python 3.11+ for help; planned backend: NetworkManager or iwd (not checked)."
    # Group networking documentation without querying the current host.
    wifi = parser.add_command(
        "wifi",
        "Inspect and manage Wi-Fi connections.",
        dependencies=dependencies,
        examples=("lut wifi help", "lut wifi connect help"),
    )
    # Password arguments are intentionally absent from the planned connection syntax.
    operations = (
        ("list", "List nearby networks.", False),
        ("status", "Inspect Wi-Fi connection status.", False),
        ("connect", "Connect to a network.", True),
        ("disconnect", "Disconnect a network.", True),
        ("saved", "List saved network profiles.", False),
    )
    for name, description, modifies in operations:
        # Include the SSID only for the connection command's required operand.
        example = f"lut wifi {name}" + (' "Home Wi-Fi"' if name == "connect" else "")
        # Accept no credentials and perform no network actions.
        command = wifi.add_command(
            name,
            description,
            dependencies=dependencies,
            dry_run=modifies,
            examples=(f"{example}  # planned; not implemented",),
        )
        if name == "connect":
            command.add_argument("ssid", help="Network name (planned input).")
