"""
system_info.py — Collects general system information.

Data sources:
  /proc/version       — kernel version string
  /etc/os-release     — distribution name and version
  /proc/uptime        — system uptime in seconds
  /proc/cpuinfo       — CPU model and architecture details
  platform module     — fallback for some fields

All reads are wrapped in try/except so that a missing or
unreadable file degrades gracefully to an "unavailable" string
rather than crashing the program.
"""

import os
import platform
from typing import Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_file(path: str) -> Optional[str]:
    """Return the text content of *path*, or None on any error."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def _parse_os_release(content: str) -> dict:
    """
    Parse key=value pairs from /etc/os-release.

    Values may be quoted; surrounding quotes are stripped.
    Lines starting with '#' are ignored.
    """
    result: dict = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        # Strip surrounding single or double quotes
        value = value.strip('"').strip("'")
        result[key.strip()] = value
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_distro_info() -> dict:
    """
    Return a dict with:
      - name    : distribution name (e.g. "Alpine Linux")
      - version : version string (e.g. "3.24.0")
      - id      : short id (e.g. "alpine")

    Reads /etc/os-release (standard on Alpine) and falls back to
    /usr/lib/os-release, then platform.system() if both are missing.
    """
    for path in ("/etc/os-release", "/usr/lib/os-release"):
        content = _read_file(path)
        if content:
            data = _parse_os_release(content)
            return {
                "name": data.get("PRETTY_NAME", data.get("NAME", "Unknown")),
                "version": data.get("VERSION_ID", data.get("VERSION", "Unknown")),
                "id": data.get("ID", "unknown"),
            }

    # Final fallback
    return {
        "name": platform.system(),
        "version": platform.release(),
        "id": "unknown",
    }


def get_kernel_version() -> str:
    """
    Return the running kernel version string.

    Primary source: /proc/version (first whitespace-delimited token
    after "version"). Fallback: platform.release().
    """
    content = _read_file("/proc/version")
    if content:
        # Format: "Linux version 6.1.58-0-lts (builder@...) ..."
        parts = content.split()
        # parts[0]="Linux", parts[1]="version", parts[2]="<version>"
        if len(parts) >= 3:
            return parts[2]

    return platform.release()


def get_uptime() -> dict:
    """
    Return a dict with:
      - total_seconds : float   — total uptime in seconds
      - days          : int
      - hours         : int
      - minutes       : int
      - seconds       : int
      - human         : str     — e.g. "2 days, 3 hours, 15 minutes"

    Source: /proc/uptime — first field is uptime seconds (float).
    """
    content = _read_file("/proc/uptime")
    if content:
        try:
            total_seconds = float(content.split()[0])
            days = int(total_seconds // 86400)
            remainder = total_seconds % 86400
            hours = int(remainder // 3600)
            remainder %= 3600
            minutes = int(remainder // 60)
            secs = int(remainder % 60)

            parts = []
            if days:
                parts.append(f"{days} day{'s' if days != 1 else ''}")
            if hours:
                parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
            if minutes:
                parts.append(f"{minutes} minute{'s' if minutes != 1 else ''}")
            if not parts:
                parts.append(f"{secs} second{'s' if secs != 1 else ''}")

            return {
                "total_seconds": total_seconds,
                "days": days,
                "hours": hours,
                "minutes": minutes,
                "seconds": secs,
                "human": ", ".join(parts),
            }
        except (IndexError, ValueError):
            pass

    return {
        "total_seconds": None,
        "days": 0,
        "hours": 0,
        "minutes": 0,
        "seconds": 0,
        "human": "unavailable",
    }


def get_cpu_info() -> dict:
    """
    Return a dict with:
      - architecture : str  — e.g. "x86_64"
      - model_name   : str  — e.g. "Intel(R) Core(TM) i5-8250U"
      - num_cores    : int  — logical CPU count

    Source: /proc/cpuinfo; fallback: platform.machine().
    """
    architecture = platform.machine() or "unknown"
    model_name = "unavailable"
    num_cores = 0

    content = _read_file("/proc/cpuinfo")
    if content:
        for line in content.splitlines():
            if line.startswith("model name") and ":" in line:
                model_name = line.partition(":")[2].strip()
            if line.startswith("processor"):
                num_cores += 1

    # /proc/cpuinfo may say "Hardware" on ARM instead of "model name"
    if model_name == "unavailable" and content:
        for line in content.splitlines():
            if line.lower().startswith("hardware") and ":" in line:
                model_name = line.partition(":")[2].strip()
                break

    if num_cores == 0:
        # Last-resort fallback
        try:
            num_cores = os.cpu_count() or 0
        except Exception:
            pass

    return {
        "architecture": architecture,
        "model_name": model_name,
        "num_cores": num_cores,
    }


def collect() -> dict:
    """
    Collect all system information and return a unified dict.

    This is the primary entry-point used by reporting and CLI modules.
    """
    distro = get_distro_info()
    return {
        "distro_name": distro["name"],
        "distro_version": distro["version"],
        "distro_id": distro["id"],
        "kernel_version": get_kernel_version(),
        "uptime": get_uptime(),
        "cpu": get_cpu_info(),
    }
