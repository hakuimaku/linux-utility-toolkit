# Installation Guide

This guide provides simple, step-by-step instructions to install and start using the **Linux Utility Toolkit (`lut`)**.

---

## 🚀 Quick Start (Choose Your Preferred Method)

LUT is a pure Python application that requires **Python 3.11 or newer**. It does not require root privileges or complex setup.

### Option A: Using `pipx` (Recommended for End Users)

[`pipx`](https://pypa.github.io/pipx/) installs CLI tools in isolated environments while making their executables directly accessible from your terminal anywhere.

1. **Install with a single command:**
   ```bash
   pipx install .
   ```
   *(Or install a pre-built wheel: `pipx install linux_utility_toolkit-0.1.0-py3-none-any.whl`)*

2. **Verify immediately:**
   ```bash
   lut --version
   lut system info
   ```
   You can now run `lut` from any directory without needing to activate a virtual environment.

> [!TIP]
> If you do not have `pipx` installed yet:
> - **Arch Linux**: `sudo pacman -S python-pipx && pipx ensurepath`
> - **Debian / Ubuntu**: `sudo apt install pipx && pipx ensurepath`
> - **Fedora**: `sudo dnf install pipx && pipx ensurepath`

---

### Option B: Using a Standard Virtual Environment (`venv`)

If you prefer using Python's built-in `venv` inside the project folder:

1. **Create and activate a virtual environment:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. **Install LUT:**
   ```bash
   pip install .
   ```

3. **Verify installation:**
   ```bash
   lut --version
   lut help
   ```

> [!NOTE]
> When using `venv`, remember to run `source .venv/bin/activate` in new terminal sessions, or invoke the binary directly via `./.venv/bin/lut`.

---

### Option C: Developer / Editable Installation

If you plan to modify LUT's source code, run the test suite, or contribute:

1. **Create virtual environment and install in editable mode with development tools:**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -e '.[dev]'
   ```

2. **Run tests and linters:**
   ```bash
   # Run all unit and integration tests
   pytest

   # Run code quality and formatting checks
   ruff check .
   ruff format --check .
   ```

---

## ⚡ Optional Backend Tools (Install as Needed)

LUT works out of the box with zero external dependencies for most daily tasks:
- System inspection (`lut system info`, `lut system disk`, `lut system memory`)
- File hashing and metadata (`lut file hash`, `lut file info`, `lut file rename`)
- Archive creation & extraction (`lut archive` for ZIP, TAR, TAR.GZ, TAR.XZ)
- Filename search (`lut search name`)

To enable advanced media transcoding, image conversion, or high-speed regex search, install the optional backends using your package manager:

### Arch Linux (Tested & Verified)
```bash
sudo pacman -S ripgrep imagemagick ffmpeg p7zip
```

### Debian / Ubuntu (Reference)
```bash
sudo apt update
sudo apt install ripgrep imagemagick ffmpeg p7zip-full
```

### Fedora (Reference)
```bash
sudo dnf install ripgrep ImageMagick ffmpeg p7zip
```

> [!NOTE]
> If you run a command that requires a backend you have not yet installed (e.g. `lut video convert` without `ffmpeg`), LUT will immediately tell you exactly which package to install.

---

## 🔍 Verifying Your Installation

Run these quick commands to confirm everything is working properly:

```bash
# 1. Check version
lut --version
# Output: lut 0.1.0

# 2. Inspect host system resources (works with zero backends)
lut system info

# 3. View available command groups
lut help
```

---

## 📦 Building Distribution Packages (Advanced)

To generate standalone distribution archives (`.whl` and `.tar.gz`):

```bash
pip install build
python -m build
```

The resulting packages will be saved in the `dist/` directory:
- `dist/linux_utility_toolkit-0.1.0-py3-none-any.whl`
- `dist/linux_utility_toolkit-0.1.0.tar.gz`

You can distribute or install this `.whl` file on any compatible Linux system.

---

## 🗑️ Uninstallation

Removing LUT is straightforward and leaves no background daemons or configuration files:

- **If installed with `pipx`:**
  ```bash
  pipx uninstall linux-utility-toolkit
  ```
- **If installed in a `venv`:**
  ```bash
  pip uninstall linux-utility-toolkit
  # (Or simply delete the .venv directory)
  ```
