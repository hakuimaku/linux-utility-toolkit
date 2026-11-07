# Troubleshooting Guide

This guide describes common error scenarios, diagnostic steps, exit codes, and solutions for the Linux Utility Toolkit (LUT).

---

## 1. Exit Code Reference

LUT uses standardized, predictable exit codes across all commands:

| Exit Code | Classification | Cause & Meaning | Recommended Action |
|---|---|---|---|
| **`0`** | Success | Command completed successfully, or help/version was displayed. | None. |
| **`1`** | Execution Error / No Match | Operation failed during execution; no matches found in `search content`; or command has no execution handler. | Check error message on `stderr`. In search, code 1 means pattern was not found. |
| **`2`** | Syntax / Usage Error | Invalid CLI argument, unrecognized flag, or missing required parameter. | Check command usage with `lut <group> <cmd> --help`. |
| **`3`** | Dependency Error | Required external tool (`rg`, `magick`, `ffmpeg`, `7z`) is missing from `PATH`. | Install the missing backend using your distribution package manager (see [Dependency Matrix](dependencies.md)). |
| **`4`** | Input Error | Input file does not exist, file is empty/corrupt, unrecognized magic bytes, or security policy violation (path traversal, zip bomb). | Check that input file exists and has correct read permissions and supported encoding. |
| **`5`** | Output Conflict | Explicit `--output` destination already exists, or permission denied writing destination. | Specify a different destination name or omit `--output` to allow automatic numbered names. |
| **`130`** | Cancellation | Command was interrupted by user (Ctrl+C / `SIGINT`). | Normal user cancellation; staging temporary files are cleaned up automatically. |
| **`141`** | Broken Pipe | Downstream pipe reader closed before output was completely written (`SIGPIPE`). | Normal when piping into `head -n 5` or similar filters; no action needed. |

---

## 2. Common Scenarios & Remedies

### Scenario A: Missing Backend Error (Exit Code 3)
**Error Message:**
```text
lut: error: Missing dependency: rg. Install manually: pacman -S ripgrep.
```
**Cause:** The command requires an external utility that is not installed or not in the user's `$PATH`.
**Solution:**
1. Install the tool using the package manager suggested by LUT:
   - Arch Linux: `sudo pacman -S ripgrep` (or `imagemagick`, `ffmpeg`, `p7zip`)
   - Debian / Ubuntu: `sudo apt install ripgrep` (or `imagemagick`, `ffmpeg`, `p7zip-full`)
   - Fedora: `sudo dnf install ripgrep` (or `ImageMagick`, `ffmpeg`, `p7zip`)
2. Verify that the tool is available: `which rg`.

---

### Scenario B: Output Already Exists (Exit Code 5)
**Error Message:**
```text
lut: error: Output already exists: /path/to/destination.mp4
```
**Cause:** An explicit `-o` or `--output` destination already exists. LUT strictly enforces a non-overwriting policy to prevent accidental data destruction.
**Solution:**
- Specify a non-existing destination path: `-o /path/to/destination_new.mp4`.
- Or omit `-o` entirely: LUT will automatically choose a safe numbered name (e.g. `destination_2.mp4`).

---

### Scenario C: Archive Security Rejection (Exit Code 4)
**Error Message:**
```text
lut: error: Archive entry resolves outside destination staging root: ../../../etc/passwd
```
or
```text
lut: error: Archive exceeds maximum entry count limit (10000): archive.zip
```
**Cause:** The archive contains directory traversal attempts (Zip Slip), symlinks pointing to sensitive external locations, or exceeds safe unpacking limits (ZIP bomb protection: max 10,000 entries or uncompressed size > 1 GiB).
**Solution:**
- Inspect the archive safely without extracting:
  ```bash
  lut archive list archive.zip
  ```
- Test integrity without writing files:
  ```bash
  lut archive test archive.zip
  ```

---

### Scenario D: System Tools — Remote Mount or NFS Freeze
**Symptom:** `lut system disk` takes a long time or encounters unresponsive network mounts.
**Cause:** Stale or unreachable remote filesystems (NFS, CIFS, SSHFS) can enter uninterruptible kernel D-state waits when probed.
**Solution:**
- LUT isolates filesystem probes in non-blocking daemon threads with strict 0.5s timeouts.
- To inspect only local physical drives and ignore network mounts entirely:
  ```bash
  lut system disk --local-only
  ```

---

### Scenario E: Network Ports Process Names Show "Unknown"
**Symptom:** In `lut system ports`, process names and PIDs are listed as `Unknown`.
**Cause:** On Linux, reading process identifiers and socket descriptors (`/proc/<pid>/fd`) owned by other users requires root privileges or `CAP_NET_ADMIN`.
**Solution:**
- Running `lut system ports` as an unprivileged user displays all listening ports and protocol bindings.
- To inspect process owners for system-wide sockets:
  ```bash
  sudo lut system ports
  ```

---

### Scenario F: Container cgroup Quotas vs Host Hardware
**Symptom:** `lut system memory` reports different RAM than the host system.
**Explanation:** In containerized environments (Docker, Podman, Kubernetes), LUT automatically discovers cgroup v1 and cgroup v2 limits (`cpu.max`, `memory.max`) and reports container limits to help avoid unexpected Out-Of-Memory (OOM) kills.

---

### Scenario G: Wi-Fi or Bluetooth "not implemented" (Exit Code 1)
**Error Message:**
```text
lut wifi status: error: not implemented; this command provides help only.
```
**Explanation:** In version 0.1.0, the `wifi` and `bluetooth` command trees provide CLI documentation only (`handler=None`). They do not contact system daemons or modify hardware adapters. See [Wi-Fi & Bluetooth Documentation](wifi_bluetooth.md).
