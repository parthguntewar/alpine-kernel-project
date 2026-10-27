# INSTALL.md — AlpineGuard Installation Guide

Target: **Alpine Linux 3.24** running in Oracle VirtualBox.

---

## Prerequisites

Start from a clean Alpine Linux 3.24 installation. A standard setup
(installed with `setup-alpine`) with networking configured is sufficient.

---

## Step 1 — Update package list

```sh
apk update
```

---

## Step 2 — Install Python 3

Alpine 3.24 ships Python 3 in its package repository:

```sh
apk add python3 py3-pip
```

Verify:
```sh
python3 --version
pip3 --version
```

---

## Step 3 — (Optional) Install git to clone the repository

If you are working from a fresh VM without the project files:

```sh
apk add git
git clone https://github.com/parthguntewar/alpine-kernel-project.git
cd alpine-kernel-project
```

If you are transferring files from Windows via a shared folder:

```sh
# Mount the shared folder (VirtualBox guest additions required)
# or transfer via scp / USB
cd /path/to/alpine-kernel-project
```

---

## Step 4 — Install AlpineGuard

### Option A — Simple user install (recommended for demonstration)

```sh
pip3 install --user .
```

This installs the `alpineguard` command to `~/.local/bin/`.

Add `~/.local/bin` to your PATH if not already present:

```sh
export PATH="$HOME/.local/bin:$PATH"
# To make permanent, add to /etc/profile or ~/.profile
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.profile
```

### Option B — Run directly without installing (no pip required)

```sh
cd /path/to/alpine-kernel-project
python3 -m alpineguard
```

This requires no installation and is useful for quick testing.

### Option C — Virtual environment install

```sh
python3 -m venv .venv
source .venv/bin/activate
pip3 install -e .
alpineguard
```

---

## Step 5 — Verify the installation

```sh
alpineguard --version
# Expected: alpineguard 1.0.0

alpineguard --help
```

---

## Step 6 — Run a health report

```sh
alpineguard
```

You should see a colour-coded terminal report with system information,
memory, disk, CPU, and security check results.

---

## Step 7 — Run the automated tests

```sh
cd /path/to/alpine-kernel-project
python3 -m unittest discover -s tests -p "test_*.py" -v
```

All tests should pass on Alpine Linux. Tests use temporary files and
mocks where needed so they are safe to run without root privileges.

---

## Uninstall

```sh
pip3 uninstall alpineguard
```

Or if using a virtual environment, simply delete the `.venv/` directory.

---

## Troubleshooting

### `command not found: alpineguard`

Add `~/.local/bin` to your PATH:
```sh
export PATH="$HOME/.local/bin:$PATH"
```

### `pip3: command not found`

```sh
apk add py3-pip
```

### Permission denied reading `/var/log/messages`

Some security checks read authentication logs which may require root:
```sh
sudo alpineguard
```
AlpineGuard will gracefully report "unavailable" for log checks if not
run as root. All other features work without elevated privileges.

### `ModuleNotFoundError: No module named 'alpineguard'`

Ensure you are running from the project root, or install with `pip3 install --user .`

---

## Alpine Package Notes

AlpineGuard uses only Python's standard library. No additional Alpine
packages beyond `python3` are required for normal operation.

Optional packages for development:
```sh
apk add py3-pyflakes    # static analysis
```
