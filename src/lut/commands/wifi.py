"""Register Wi-Fi command group without modifying network services or credentials."""


def register(parser) -> None:
    """Register Wi-Fi queries and connection commands."""
    dependencies = "Python 3.11+ for help; backend: NetworkManager or iwd (not checked)."
    wifi = parser.add_command(
        "wifi",
        "Inspect and manage Wi-Fi connections.",
        dependencies=dependencies,
        examples=("lut wifi help", "lut wifi connect help"),
    )
    operations = (
        ("list", "List nearby networks.", False),
        ("status", "Inspect Wi-Fi connection status.", False),
        ("connect", "Connect to a network.", True),
        ("disconnect", "Disconnect a network.", True),
        ("saved", "List saved network profiles.", False),
    )
    for name, description, modifies in operations:
        example = f"lut wifi {name}" + (' "Home Wi-Fi"' if name == "connect" else "")
        command = wifi.add_command(
            name,
            description,
            dependencies=dependencies,
            dry_run=modifies,
            examples=(f"{example}  # planned; not implemented",),
        )
        if name == "connect":
            command.add_argument("ssid", help="Network name.")
