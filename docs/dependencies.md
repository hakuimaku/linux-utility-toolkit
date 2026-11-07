# Dependency Matrix

This document provides a comprehensive matrix of LUT runtime requirements, external backend utilities, package mappings across Linux distributions, and behavior when backends are missing.

---

## 1. Core Principles

- **No Third-Party Python Dependencies**: LUT's runtime codebase (`lut.*`) relies exclusively on the Python standard library. It requires **Python >= 3.11**.
- **On-Demand Discovery**: External binaries are searched via `lut.core.dependencies.require_executable` only when a command requiring that specific binary is executed.
- **Zero Startup Checks**: `lut --help`, `lut --version`, and all command help pages (`lut <group> <cmd> help`) never check `PATH`, start processes, or require any external backend.
- **No Automatic Installation**: LUT never invokes package managers, downloads binaries, or modifies system configurations. When a backend is missing, it exits with code `3` and prints the exact manual installation command for your distribution.

---

## 2. Command vs Backend Matrix

| Command Group | Command / Feature | Backend Required | Standard Library Fallback? | Behavior if Missing |
|---|---|---|---|---|
| **Core / Help** | `lut --version`, `lut help`, `lut <cmd> help` | None | N/A | Always works |
| **Search** | `lut search content` | `ripgrep` (`rg`) | No | Exits with code `3` |
| **Search** | `lut search name` | None (Python `os.scandir`) | Built-in | Always works |
| **File** | `lut file hash` | None (Python `hashlib`) | Built-in | Always works |
| **File** | `lut file info` | None (Python `os.stat`) | Built-in | Always works |
| **File** | `lut file duplicates` | None (Python `os.scandir` + `hashlib`) | Built-in | Always works |
| **File** | `lut file rename` | None (Linux `renameat2`) | Built-in | Always works |
| **Archive** | `archive compress/extract/list/test` (ZIP) | None (Python `zipfile`) | Built-in | Always works |
| **Archive** | `archive compress/extract/list/test` (TAR, TAR.GZ, TAR.XZ) | None (Python `tarfile`, `gzip`, `lzma`) | Built-in | Always works |
| **Archive** | `archive compress/list/test` (7Z) | `7z` / `7zz` / `7za` | No | Exits with code `3` |
| **Image** | `image convert/compress/resize/crop/rotate/metadata` | ImageMagick (`magick` or `convert`/`identify`) | No | Exits with code `3` |
| **Video** | `video convert/compress/resize/trim/frames/gif` | FFmpeg (`ffmpeg`) & FFprobe (`ffprobe`) | No | Exits with code `3` |
| **Video** | `video info` | FFprobe (`ffprobe`) | No | Exits with code `3` |
| **Audio** | `audio convert/trim/normalize/volume` | FFmpeg (`ffmpeg`) & FFprobe (`ffprobe`) | No | Exits with code `3` |
| **Audio** | `audio info` | FFprobe (`ffprobe`) | No | Exits with code `3` |
| **System** | `system info/disk/memory/process` | None (Linux `/proc`, `/sys/fs/cgroup`) | Built-in | Always works |
| **System** | `system ports` | `ss` (from `iproute2`) | **Yes**: falls back to pure Python `/proc/net` | Seamless fallback (code `0`) |
| **Wi-Fi / BT**| `wifi *`, `bluetooth *` | Help only (no backend executed) | Built-in | Exits with code `1` |

---

## 3. Distribution Package Mapping Matrix

> [!IMPORTANT]
> **Testing Scope Disclaimer**:
> LUT 0.1.0 has been **formally tested and verified on Arch Linux**.
> The package mappings below for Ubuntu/Debian and Fedora are provided for user reference based on standard upstream packaging conventions; they are not claimed as fully tested or certified distributions until native test runs are performed.

| Backend Binary | Arch Linux (Tested) | Debian / Ubuntu (Reference) | Fedora (Reference) | Minimum Version |
|---|---|---|---|---|
| **Python** | `pacman -S python` | `apt install python3 python3-pip python3-venv` | `dnf install python3 python3-pip` | >= 3.11 |
| **ripgrep** (`rg`) | `pacman -S ripgrep` | `apt install ripgrep` | `dnf install ripgrep` | Any stable |
| **ImageMagick** (`magick`) | `pacman -S imagemagick` | `apt install imagemagick` | `dnf install ImageMagick` | 6.x or 7.x |
| **FFmpeg** (`ffmpeg`, `ffprobe`) | `pacman -S ffmpeg` | `apt install ffmpeg` | `dnf install ffmpeg` | >= 4.0 |
| **7-Zip** (`7z`, `7zz`, `7za`) | `pacman -S p7zip` | `apt install p7zip-full` | `dnf install p7zip p7zip-plugins` | Any stable |
| **iproute2** (`ss`) | `pacman -S iproute2` | `apt install iproute2` | `dnf install iproute` | Any stable |

---

## 4. Error Handling When Dependencies Are Missing

When an external backend is required but absent from `PATH`:
1. LUT intercepts `FileNotFoundError` or executable discovery failure.
2. It queries distribution metadata from `/etc/os-release` via `platform.freedesktop_os_release()`.
3. It prints a formatted error message to `stderr`:
   ```text
   lut: error: Missing dependency: <backend>. Install manually: <package-manager-command>.
   ```
4. It halts immediately with standard exit code **`3`** (`DependencyError`), ensuring no corrupt or partial output is written.
