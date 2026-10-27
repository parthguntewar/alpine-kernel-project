"""
disk_monitor.py — Filesystem usage monitoring.

Data source: os.statvfs()  (POSIX standard call, works on Alpine)

os.statvfs() returns a named-tuple-like object:
  f_bsize   — filesystem block size
  f_blocks  — total data blocks
  f_bfree   — free blocks
  f_bavail  — free blocks available to non-root user
  f_frsize  — fragment size (used for capacity math)

We use f_frsize * f_blocks for total, f_frsize * f_bavail for
available (the non-root perspective), which matches what 'df' shows.

Mountpoint discovery falls back gracefully if /proc/mounts is
unavailable.
"""

import os
from typing import Optional


def _bytes_to_gib(b: int) -> float:
    """Convert bytes to gibibytes, rounded to two decimal places."""
    return round(b / (1024 ** 3), 2)


def _bytes_to_mib(b: int) -> float:
    """Convert bytes to mebibytes, rounded to one decimal place."""
    return round(b / (1024 ** 2), 1)


def calculate_utilization(total: int, available: int) -> float:
    """
    Return disk utilization as a percentage (0.0 – 100.0).

    used = total - available
    utilization = used / total * 100

    Raises ValueError for invalid total.
    """
    if total <= 0:
        raise ValueError(f"Invalid total disk size: {total}")
    used = total - available
    return round((used / total) * 100.0, 1)


def _statvfs(mountpoint: str):
    """
    Thin wrapper around os.statvfs().

    This function exists solely to allow unit tests to mock statvfs
    on Windows, where os.statvfs does not exist and cannot be patched
    via the standard `patch("os.statvfs")` approach.
    """
    return os.statvfs(mountpoint)


def get_disk_usage(mountpoint: str = "/") -> dict:
    """
    Return usage statistics for the filesystem mounted at *mountpoint*.

    Returns a dict with:
      - mountpoint      : str
      - total_bytes     : int
      - available_bytes : int
      - used_bytes      : int
      - utilization_pct : float
      - total_gib       : float
      - available_gib   : float
      - used_gib        : float
      - error           : str | None
    """
    try:
        st = _statvfs(mountpoint)
    except (OSError, AttributeError) as exc:
        return {
            "mountpoint": mountpoint,
            "total_bytes": 0,
            "available_bytes": 0,
            "used_bytes": 0,
            "utilization_pct": 0.0,
            "total_gib": 0.0,
            "available_gib": 0.0,
            "used_gib": 0.0,
            "error": f"Cannot stat {mountpoint}: {exc}",
        }

    total = st.f_frsize * st.f_blocks
    available = st.f_frsize * st.f_bavail
    used = max(0, total - available)

    try:
        util_pct = calculate_utilization(total, available)
    except ValueError:
        util_pct = 0.0

    return {
        "mountpoint": mountpoint,
        "total_bytes": total,
        "available_bytes": available,
        "used_bytes": used,
        "utilization_pct": util_pct,
        "total_gib": _bytes_to_gib(total),
        "available_gib": _bytes_to_gib(available),
        "used_gib": _bytes_to_gib(used),
        "error": None,
    }


def get_all_mountpoints(proc_mounts: str = "/proc/mounts") -> list:
    """
    Return a list of physical mountpoints from /proc/mounts.

    Filters out pseudo-filesystems (proc, sysfs, devtmpfs, tmpfs, cgroup*,
    devpts, overlay, aufs) so we only report real storage.
    """
    PSEUDO_FS = {
        "proc", "sysfs", "devtmpfs", "devpts", "tmpfs",
        "cgroup", "cgroup2", "pstore", "mqueue", "debugfs",
        "tracefs", "securityfs", "configfs", "fusectl", "bpf",
        "hugetlbfs", "overlay", "aufs", "nsfs",
    }
    mountpoints: list = []
    try:
        with open(proc_mounts, "r", encoding="utf-8") as fh:
            for line in fh:
                parts = line.split()
                if len(parts) < 3:
                    continue
                # parts: device  mountpoint  fstype  options  dump  pass
                _, mountpoint, fstype = parts[0], parts[1], parts[2]
                if fstype.lower() not in PSEUDO_FS and not fstype.lower().startswith("cgroup"):
                    mountpoints.append(mountpoint)
    except OSError:
        # If /proc/mounts is unavailable, just check root
        mountpoints = ["/"]

    return mountpoints


def collect(mountpoints: Optional[list] = None) -> dict:
    """
    Collect disk usage for one or more mountpoints.

    If *mountpoints* is None, auto-discover from /proc/mounts and
    always include "/" as the primary target.

    Returns a dict with:
      - root    : dict  — always present, usage for "/"
      - mounts  : list  — one dict per mountpoint
    """
    if mountpoints is None:
        discovered = get_all_mountpoints()
        # Ensure "/" appears first and only once
        if "/" in discovered:
            discovered.remove("/")
        mountpoints = ["/"] + discovered

    results = []
    for mp in mountpoints:
        results.append(get_disk_usage(mp))

    root = next((r for r in results if r["mountpoint"] == "/"), results[0] if results else {})

    return {
        "root": root,
        "mounts": results,
    }
