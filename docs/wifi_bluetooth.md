# Wi-Fi & Bluetooth Module Documentation

This document describes the CLI syntax, registered subcommands, and operational scope of the `wifi` and `bluetooth` command groups in Linux Utility Toolkit (LUT).

---

## 1. Operational Scope in Release 0.1.0

In LUT version 0.1.0:
- The `wifi` and `bluetooth` command trees are registered to provide a standardized CLI help interface.
- Commands do **not** register execution handlers (`handler=None`).
- **Help is fully functional**: `lut wifi help`, `lut wifi --help`, `lut bluetooth help`, and subcommands provide usage syntax, parameter documentation, and examples.
- **Fail-Safe Execution**: Invocations of operational commands (e.g., `lut wifi status`, `lut bluetooth devices`) safely return exit code `1` with:
  ```text
  lut wifi status: error: not implemented; this command provides help only.
  ```
- **Non-Invasive Security Guarantee**: LUT never accesses network services (NetworkManager, iwd, wpa_supplicant), BlueZ, or kernel adapters, and never requests or stores passwords, keys, or user credentials.

---

## 2. Wi-Fi CLI Reference (`lut wifi`)

### Command Group Help
```bash
lut wifi help
lut wifi --help
```

### Subcommands
| Subcommand | Syntax | Description | Modifies State |
|---|---|---|---|
| `list` | `lut wifi list` | List nearby detected Wi-Fi networks | No |
| `status` | `lut wifi status` | Inspect current Wi-Fi connection and interface status | No |
| `connect` | `lut wifi connect <ssid>` | Connect to a Wi-Fi network by SSID | Yes (`--dry-run` supported) |
| `disconnect`| `lut wifi disconnect` | Disconnect from active Wi-Fi connection | Yes (`--dry-run` supported) |
| `saved` | `lut wifi saved` | List saved Wi-Fi network connection profiles | No |

### Notes on Credentials
- Password arguments are intentionally excluded from CLI command arguments to prevent exposing credentials in process lists (`/proc/<pid>/cmdline`), shell history (`.bash_history`), or system logs.

---

## 3. Bluetooth CLI Reference (`lut bluetooth`)

### Command Group Help
```bash
lut bluetooth help
lut bluetooth --help
```

### Subcommands
| Subcommand | Syntax | Description | Modifies State |
|---|---|---|---|
| `scan` | `lut bluetooth scan` | Scan for nearby discoverable Bluetooth devices | No |
| `devices` | `lut bluetooth devices` | List known, paired, or connected Bluetooth devices | No |
| `pair` | `lut bluetooth pair <address>` | Pair with a Bluetooth device by MAC address | Yes (`--dry-run` supported) |
| `connect` | `lut bluetooth connect <address>` | Connect to a paired Bluetooth device | Yes (`--dry-run` supported) |
| `disconnect`| `lut bluetooth disconnect <address>` | Disconnect from a Bluetooth device | Yes (`--dry-run` supported) |
| `remove` | `lut bluetooth remove <address>` | Remove a paired Bluetooth device from known list | Yes (`--dry-run` supported) |

---

## 4. Hardware Verification & Real-World Testing

Verification performed on live Arch Linux hardware with active wireless and Bluetooth controllers:
- **Host Hardware**:
  - Wi-Fi: Intel Wi-Fi 6 AX201 (`wlo1`), managed by NetworkManager, actively connected.
  - Bluetooth: Intel Bluetooth controller (`hci0`), initialized and unblocked via `rfkill`.
- **Test Results**:
  - `lut wifi status`, `lut wifi list`, `lut wifi connect "SSID"`: correctly refused execution with exit code `1`, without interrupting active network traffic or altering network interfaces.
  - `lut bluetooth devices`, `lut bluetooth scan`: correctly refused execution with exit code `1`, without touching BlueZ daemon or active Bluetooth pairings.
  - `lut wifi help`, `lut bluetooth help`: displayed complete, properly formatted CLI documentation without starting any background daemon or backend service.
