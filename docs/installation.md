# Installation Guide

This guide covers installing, configuring, building, and verifying the Linux Utility Toolkit (LUT).

---

## 1. System Requirements

- **Operating System**: Linux with `/proc` and `/sys` filesystems available.
  - **Arch Linux**: **Tested and verified**.
  - **Debian / Ubuntu / Fedora**: Compatible Python 3.11+ environments.
- **Python**: Version **3.11 or newer** (tested on Python 3.11, 3.12, 3.13, and 3.14).
- **Tools**: `python3 -m venv` and `pip`.
- **Privileges**: Standard user privileges. No root or `sudo` is required to install or run LUT.
- **Dependencies**: LUT core has zero runtime dependencies outside the Python standard library.

---

## 2. Standard Installation (Virtual Environment)

The recommended installation method is inside a dedicated Python virtual environment:

### Step 1: Create and activate a virtual environment
```bash
python3 -m venv ~/.local/share/lut-venv
source ~/.local/share/lut-venv/bin/activate
```

### Step 2: Install LUT
From the project directory:
```bash
pip install .
```

### Step 3: Symlink executable to your user PATH (Optional)
To make the `lut` command accessible globally for your user without activating the venv:
```bash
mkdir -p ~/.local/bin
ln -sf ~/.local/share/lut-venv/bin/lut ~/.local/bin/lut
```
*(Ensure `~/.local/bin` is in your `$PATH` in `~/.bashrc` or `~/.zshrc`)*.

---

## 3. Development Installation

To install LUT in editable mode along with testing (`pytest`) and linting (`ruff`) tools:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

Run test suite:
```bash
pytest
```

Run linter and formatter checks:
```bash
ruff check .
ruff format --check .
```

---

## 4. Building Distribution Packages

LUT uses standard modern packaging (`pyproject.toml` with `setuptools` build backend).

### Build wheel and source distribution
```bash
pip install build
python -m build
```

This generates release artifacts in `dist/`:
- `dist/linux_utility_toolkit-0.1.0-py3-none-any.whl` (Wheel)
- `dist/linux_utility_toolkit-0.1.0.tar.gz` (Source tarball)

### Install from pre-built wheel
```bash
pip install dist/linux_utility_toolkit-0.1.0-py3-none-any.whl
```

---

## 5. Installing Optional External Backends

LUT features operate with graceful degradation. Pure Python features (file hash, file info, duplicate detection, atomic file rename, zip/tar archives, name search, and system resource inspection) work immediately without external packages.

To enable advanced media and content search capabilities, install optional backends using your package manager:

### Arch Linux (Tested Platform)
```bash
sudo pacman -S ripgrep imagemagick ffmpeg p7zip iproute2
```

### Debian / Ubuntu (Reference)
```bash
sudo apt update
sudo apt install ripgrep imagemagick ffmpeg p7zip-full iproute2
```

### Fedora (Reference)
```bash
sudo dnf install ripgrep ImageMagick ffmpeg p7zip p7zip-plugins iproute
```

---

## 6. Verification

Verify that the CLI entry points and help system work correctly:

```bash
# Check installed version
lut --version
# Expected output: lut 0.1.0

# Verify module launcher
python3 -m lut --version
# Expected output: lut 0.1.0

# Verify help tree
lut help

# Verify system inspection
lut system info
```

---

## 7. Uninstallation

To remove LUT:
```bash
pip uninstall linux-utility-toolkit
```
If you created a symlink:
```bash
rm -f ~/.local/bin/lut
```
LUT creates no hidden background services, no persistent daemons, and leaves no configuration files behind.
