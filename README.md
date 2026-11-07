# Linux Utility Toolkit (LUT)

**Linux Utility Toolkit (LUT)** is a fast, modular, and dependable command-line utility toolkit designed for Linux systems.

LUT provides a unified CLI interface for everyday system administration, file operations, media transcoding, archive management, content search, and hardware resource inspection.

> [!NOTE]
> **Release 0.1.0 Status & Platform Support**:
> - Version: `0.1.0`
> - **Platform Verification**: Tested and verified on **Arch Linux** (Linux kernel 7.x, Python 3.11–3.14).
> - Package mappings for Debian/Ubuntu and Fedora are provided for reference, but full compatibility is currently certified only on Arch Linux where tests have been executed.

---

## Key Principles & Guarantees

- **Zero Runtime Dependencies**: The core package and entry points rely strictly on the Python standard library. No third-party Python packages are required at runtime.
- **Fail-Safe & Non-Destructive**: Destructive overrides are prevented by default. Modifying commands implement preview (`--dry-run`), preflight collision detection, and atomic staging.
- **On-Demand Backend Probing**: External CLI tools (`ripgrep`, `ImageMagick`, `FFmpeg`, `7z`, `iproute2`) are discovered on-demand only when a command requiring them is executed. Help and version commands never check or start backends.
- **Graceful Degradation**: Pure Python commands always function even when external tools are absent. When an optional tool is missing, LUT halts with exit code `3` and prints the exact package manager command for your system.

---

## Quick Start & Installation

LUT requires **Python 3.11 or newer**. No root privileges are needed.

```bash
# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install the toolkit
pip install .

# Verify installation
lut --version
lut help
```

For complete instructions (including development setup, wheel building, and distribution packages), see the [Installation Guide](docs/installation.md).

---

## Command Modules Overview

| Module | Operational Commands | Backend | Documentation |
|---|---|---|---|
| **Search** | `search content`, `search name` | `ripgrep` (content), Standard Library (name) | [Search Documentation](docs/search.md) |
| **File** | `file hash`, `file info`, `file duplicates`, `file rename` | Standard Library (`hashlib`, `renameat2`) | [File Documentation](docs/file.md) |
| **Archive** | `archive compress`, `archive extract`, `archive list`, `archive test` | Standard Library (ZIP/TAR), `p7zip` (7Z) | [Archive Documentation](docs/archive.md) |
| **Image** | `image convert`, `image compress`, `image resize`, `image crop`, `image rotate`, `image metadata` | ImageMagick (`magick` or `convert`) | [Image Documentation](docs/image.md) |
| **Video** | `video convert`, `video compress`, `video resize`, `video trim`, `video extract-audio`, `video frames`, `video gif`, `video info` | FFmpeg & FFprobe | [Video Documentation](docs/video.md) |
| **Audio** | `audio convert`, `audio trim`, `audio normalize`, `audio volume`, `audio info` | FFmpeg & FFprobe | [Audio Documentation](docs/audio.md) |
| **System** | `system info`, `system disk`, `system memory`, `system process`, `system ports` | Standard Library (`/proc`, `/sys`), `ss` (optional) | [System Documentation](docs/system.md) |
| **Wi-Fi / BT**| `wifi *`, `bluetooth *` (CLI help tree) | Help-only interface in v0.1.0 | [Wi-Fi & Bluetooth Documentation](docs/wifi_bluetooth.md) |

---

## Module Summaries

### 1. Search Tools
- `lut search content <keyword> [path] [options]` (alias: `lut search <keyword>`):
  High-performance regex or literal text search powered by `ripgrep` with streaming output, ignore-file support, and JSON output.
- `lut search name <pattern> [path] [options]`:
  Recursive glob search across files and directories (including empty dirs) using Python filesystem traversal without external dependencies.

See [Search Documentation](docs/search.md).

### 2. File Tools
- `lut file hash <file> [-a algo]`:
  Chunked cryptographic checksums (SHA-256, SHA-512, SHA-1, MD5) with bounded memory usage.
- `lut file info <path>`:
  Metadata, permissions, file size, timestamps, and symlink target inspection.
- `lut file duplicates [path]`:
  Identifies duplicate files with inode-aware wasted space calculation.
- `lut file rename <inputs> [--prefix] [--suffix] [--replace] [--apply]`:
  Preview-by-default safe batch renaming with preflight collision checks and atomic non-overwriting execution (`renameat2`).

See [File Documentation](docs/file.md).

### 3. Archive Tools
- `lut archive compress <input> [--format zip|tar|tar.gz|tar.xz|7z] [-o output]`:
  Safe compression with directory structure preservation, external symlink blocking, and atomic publication.
- `lut archive extract <archive> [-o destination]`:
  Safe extraction with path traversal protection (anti-Zip Slip), symlink blocking, ZIP bomb thresholds, and atomic directory publication.
- `lut archive list <archive> [--json]`:
  Lists archive entries and metadata with control-character sanitization without unpacking.
- `lut archive test <archive> [--json]`:
  Internal CRC and stream decompression verification without disk writes.

See [Archive Documentation](docs/archive.md).

### 4. Image Tools
- `lut image convert <input> [--format FORMAT] [-o OUTPUT]`:
  Safe image format conversion across JPEG, PNG, WebP, BMP, TIFF, and GIF with explicit transparency handling.
- `lut image compress <input> [-q QUALITY] [-o OUTPUT]`:
  Reduces file size with lossy quality controls for JPEG/WebP and lossless optimization for PNG.
- `lut image resize <input> [--width N] [--height N] [--allow-upscale]`:
  Dimension scaling preserving aspect ratio by default.
- `lut image crop <input> --x N --y N --width N --height N`:
  Pixel region cropping with boundary validation and virtual canvas reset.
- `lut image rotate <input> --angle N`:
  Clockwise rotation expanding canvas without corner cropping.
- `lut image metadata <input> [--json]`:
  Read-only inspection of format, dimensions, colorspace, alpha channels, and orientation.

See [Image Documentation](docs/image.md).

### 5. Video & Audio Tools
- `lut video convert <input> [--format FORMAT] [-o OUTPUT]`:
  Container and codec conversion using FFmpeg.
- `lut video compress <input> [-q low|medium|high] [--crf N] [--preset PRESET]`:
  Bitrate and CRF compression for videos.
- `lut video resize <input> [--width N] [--height N]`:
  Frame dimension scaling with even-dimension enforcement.
- `lut video trim <input> --start TIME --end TIME [--copy]`:
  Temporal cutting with accurate seek or fast packet copying.
- `lut video extract-audio <input> [--format FORMAT] [--stream N]`:
  Extracts audio streams from video files.
- `lut video frames <input> [--fps N] [--format png|jpg]`:
  Extracts video frames as image sequences into a directory.
- `lut video gif <input> [--start S] [--duration S] [--fps N] [--width N]`:
  Generates animated GIFs using high-quality two-pass palette filters.
- `lut video info <input> [--json]`:
  Inspects codecs, resolution, framerate, duration, and stream details.
- `lut audio convert <input> [--format FORMAT] [-b BITRATE]`:
  Transcodes audio between MP3, WAV, FLAC, OGG, and Opus.
- `lut audio trim <input> --start TIME --end TIME`:
  Trims audio by timestamp.
- `lut audio normalize <input> [--target-lufs N]`:
  Broadcast loudness normalization using EBU R128 (`loudnorm`).
- `lut audio volume <input> --db N`:
  Adjusts audio gain in decibels.
- `lut audio info <input> [--json]`:
  Inspects sample rates, bit rates, channels, and duration.

See [Video Documentation](docs/video.md) and [Audio Documentation](docs/audio.md).

### 6. System Tools
- `lut system info [--json]`:
  Inspects OS distribution, kernel version, architecture, hostname, CPU model, thread count, container CPU quotas, and uptime.
- `lut system disk [--path PATH] [--local-only] [--json]`:
  Inspects filesystems, total/used/free space, and mount points with non-blocking daemon protection against hung NFS mounts.
- `lut system memory [--json]`:
  Inspects RAM, available memory, swap, and container cgroup v1/v2 memory limits.
- `lut system process [--sort cpu|memory|pid|name] [--limit N] [--pid N] [--json]`:
  Lists running processes with CPU usage, memory RSS, user, state, and script name resolution.
- `lut system ports [--protocol tcp|udp] [--port N] [--json]`:
  Inspects open and listening network ports via `ss` with automatic fallback to `/proc/net`.

See [System Documentation](docs/system.md).

### 7. Wi-Fi & Bluetooth (CLI Help Scope)
In release 0.1.0, the `wifi` and `bluetooth` command groups provide CLI syntax documentation (`handler=None`). Operational invocations exit safely with code `1` without accessing network services or adapters.

See [Wi-Fi & Bluetooth Documentation](docs/wifi_bluetooth.md).

---

## Dependency Matrix

LUT core relies strictly on Python 3.11+. External CLI tools are optional and discovered on-demand:

| External Tool | Used By | Arch Linux (Tested) | Debian / Ubuntu (Reference) | Fedora (Reference) | Fallback Behavior |
|---|---|---|---|---|---|
| **Python >= 3.11** | Core Runtime | `pacman -S python` | `apt install python3` | `dnf install python3` | Required |
| **ripgrep** (`rg`) | `search content` | `pacman -S ripgrep` | `apt install ripgrep` | `dnf install ripgrep` | Exit code `3` if missing |
| **ImageMagick** | `image *` | `pacman -S imagemagick` | `apt install imagemagick` | `dnf install ImageMagick` | Exit code `3` if missing |
| **FFmpeg & FFprobe** | `video *`, `audio *` | `pacman -S ffmpeg` | `apt install ffmpeg` | `dnf install ffmpeg` | Exit code `3` if missing |
| **7-Zip** (`7z`) | `archive` (7Z format) | `pacman -S p7zip` | `apt install p7zip-full` | `dnf install p7zip p7zip-plugins` | Exit code `3` if missing |
| **iproute2** (`ss`) | `system ports` | `pacman -S iproute2` | `apt install iproute2` | `dnf install iproute` | Falls back to `/proc/net` |

See [Dependency Matrix](docs/dependencies.md) for complete details.

---

## Global CLI Options & Exit Codes

### Global Options
- `--version`: Displays the installed LUT version.
- `--help`, `-h`: Shows contextual help for any command or group.
- `help`, `help --all`: Subcommand help; `lut help --all` outputs the entire command tree.
- `--verbose`: Emits diagnostic details to `stderr`.
- `--dry-run`: Previews modifying actions without making filesystem changes.
- `--json`: Formats output as structured JSON.

### Standard Exit Codes

| Exit Code | Meaning |
|---|---|
| `0` | Success or help/version displayed |
| `1` | Execution error; no search matches; or command without execution handler |
| `2` | Syntax error, unrecognized argument, or missing required parameter |
| `3` | Missing external dependency backend |
| `4` | Input error (missing file, invalid format, zip bomb threshold exceeded) |
| `5` | Output conflict (destination exists on explicit `-o`) or access error |
| `130` | Interrupted by user (Ctrl+C / `SIGINT`) |
| `141` | Stdout pipe closed by reader (`SIGPIPE`) |

For comprehensive error scenarios and remedies, see the [Troubleshooting Guide](docs/troubleshooting.md).

---

## Testing & Verification

Install development dependencies:
```bash
pip install -e '.[dev]'
```

Run unit and integration test suite:
```bash
pytest
```

Run code quality and format checks:
```bash
ruff check .
ruff format --check .
```

Verify backend isolation by executing tests with `PATH=""`:
```bash
PATH="" lut system info
PATH="" lut file hash pyproject.toml
```

---

## Repository Structure

```text
linux-utility-toolkit/
├── pyproject.toml
├── README.md
├── LICENSE
├── docs/
│   ├── archive.md
│   ├── audio.md
│   ├── core.md
│   ├── dependencies.md
│   ├── file.md
│   ├── image.md
│   ├── installation.md
│   ├── search.md
│   ├── system.md
│   ├── troubleshooting.md
│   ├── video.md
│   └── wifi_bluetooth.md
├── src/lut/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── parser.py
│   ├── commands/
│   │   ├── __init__.py
│   │   ├── archive.py
│   │   ├── audio.py
│   │   ├── bluetooth.py
│   │   ├── file.py
│   │   ├── image.py
│   │   ├── search.py
│   │   ├── system.py
│   │   ├── video.py
│   │   └── wifi.py
│   ├── services/
│   │   ├── archive_service.py
│   │   ├── audio_service.py
│   │   ├── file_service.py
│   │   ├── image_service.py
│   │   ├── media_service.py
│   │   ├── search_service.py
│   │   ├── system_service.py
│   │   └── video_service.py
│   └── core/
│       ├── config.py
│       ├── dependencies.py
│       ├── errors.py
│       ├── logging.py
│       ├── output.py
│       └── process.py
└── tests/
    ├── test_cli.py
    ├── test_help.py
    ├── test_search.py
    ├── test_file.py
    ├── test_archive.py
    ├── test_image.py
    ├── test_video.py
    ├── test_audio.py
    ├── test_media.py
    ├── test_system.py
    └── core/
```

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
