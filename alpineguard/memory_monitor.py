"""
memory_monitor.py — RAM usage monitoring.

Data source: /proc/meminfo

/proc/meminfo contains lines in the format:
    FieldName:   <value> kB

Key fields used:
  MemTotal      — total physical RAM installed
  MemAvailable  — RAM available to user-space without swapping
                  (more accurate than MemFree for "free" on modern kernels)
  SwapTotal     — total swap space
  SwapFree      — unused swap space

All arithmetic is done in bytes internally and converted to MiB/GiB
for display. Division-by-zero is guarded against.
"""

from typing import Optional


def _read_meminfo(path: str = "/proc/meminfo") -> Optional[dict]:
    """
    Parse /proc/meminfo and return a dict mapping field names to
    integer values in bytes.

    Returns None if the file cannot be read or is malformed.
    """
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return None

    result: dict = {}
    for line in lines:
        parts = line.split()
        if len(parts) < 2:
            continue
        key = parts[0].rstrip(":")
        try:
            value_kb = int(parts[1])
        except ValueError:
            continue
        # Convert kB → bytes
        result[key] = value_kb * 1024

    return result if result else None


def calculate_utilization(total: int, available: int) -> float:
    """
    Return memory utilization as a percentage (0.0 – 100.0).

    used = total - available
    utilization = used / total * 100

    Raises ValueError if total <= 0 to indicate invalid input.
    """
    if total <= 0:
        raise ValueError(f"Invalid total memory value: {total}")
    used = total - available
    return round((used / total) * 100.0, 1)


def _bytes_to_mib(b: int) -> float:
    """Convert bytes to mebibytes, rounded to one decimal place."""
    return round(b / (1024 ** 2), 1)


def collect(meminfo_path: str = "/proc/meminfo") -> dict:
    """
    Collect RAM and swap statistics.

    Returns a dict with:
      - total_bytes       : int
      - available_bytes   : int
      - used_bytes        : int
      - utilization_pct   : float   — 0.0 to 100.0
      - total_mib         : float
      - available_mib     : float
      - used_mib          : float
      - swap_total_bytes  : int
      - swap_used_bytes   : int
      - swap_total_mib    : float
      - swap_used_mib     : float
      - error             : str | None — set if data is unavailable
    """
    data = _read_meminfo(meminfo_path)

    if data is None:
        return {
            "total_bytes": 0,
            "available_bytes": 0,
            "used_bytes": 0,
            "utilization_pct": 0.0,
            "total_mib": 0.0,
            "available_mib": 0.0,
            "used_mib": 0.0,
            "swap_total_bytes": 0,
            "swap_used_bytes": 0,
            "swap_total_mib": 0.0,
            "swap_used_mib": 0.0,
            "error": "Cannot read /proc/meminfo",
        }

    total = data.get("MemTotal", 0)
    available = data.get("MemAvailable", data.get("MemFree", 0))
    swap_total = data.get("SwapTotal", 0)
    swap_free = data.get("SwapFree", 0)
    swap_used = max(0, swap_total - swap_free)
    used = max(0, total - available)

    try:
        util_pct = calculate_utilization(total, available)
    except ValueError:
        util_pct = 0.0

    return {
        "total_bytes": total,
        "available_bytes": available,
        "used_bytes": used,
        "utilization_pct": util_pct,
        "total_mib": _bytes_to_mib(total),
        "available_mib": _bytes_to_mib(available),
        "used_mib": _bytes_to_mib(used),
        "swap_total_bytes": swap_total,
        "swap_used_bytes": swap_used,
        "swap_total_mib": _bytes_to_mib(swap_total),
        "swap_used_mib": _bytes_to_mib(swap_used),
        "error": None,
    }
