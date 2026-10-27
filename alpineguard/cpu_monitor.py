"""
cpu_monitor.py — CPU utilization monitoring.

Data source: /proc/stat

/proc/stat line format (first line, aggregate across all CPUs):
  cpu <user> <nice> <system> <idle> <iowait> <irq> <softirq> [steal] [guest] [guest_nice]

CPU utilization is defined as:
  utilization = (total_active_ticks / total_ticks) * 100

where:
  total_ticks  = sum of ALL fields
  active_ticks = total_ticks - idle - iowait

A single snapshot gives no meaningful reading because the kernel
counts cumulative ticks since boot. We must take TWO snapshots
separated by a brief interval and compute the DELTA.

The first-sample problem: if the caller requests a reading with
no prior snapshot, we return None (indicating "not yet available")
rather than reporting a fabricated or misleading value.
"""

import time
from typing import Optional


_STAT_PATH = "/proc/stat"


class _CpuSnapshot:
    """A point-in-time snapshot of /proc/stat CPU tick counters."""

    __slots__ = ("user", "nice", "system", "idle", "iowait",
                 "irq", "softirq", "steal", "timestamp")

    def __init__(self, user, nice, system, idle, iowait,
                 irq, softirq, steal, timestamp):
        self.user = user
        self.nice = nice
        self.system = system
        self.idle = idle
        self.iowait = iowait
        self.irq = irq
        self.softirq = softirq
        self.steal = steal
        self.timestamp = timestamp

    @property
    def total(self) -> int:
        return (self.user + self.nice + self.system + self.idle +
                self.iowait + self.irq + self.softirq + self.steal)

    @property
    def active(self) -> int:
        """Active ticks = total − idle − iowait."""
        return self.total - self.idle - self.iowait


def _read_cpu_snapshot(stat_path: str = _STAT_PATH) -> Optional[_CpuSnapshot]:
    """
    Read the first 'cpu' line from /proc/stat and return a snapshot.

    Returns None if the file cannot be read or the format is unexpected.
    """
    try:
        with open(stat_path, "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("cpu "):
                    parts = line.split()
                    # parts[0] = "cpu", parts[1..] = tick counters
                    if len(parts) < 5:
                        return None
                    values = [int(p) for p in parts[1:]]
                    # Pad to 8 fields if shorter (older kernels may omit steal etc.)
                    while len(values) < 8:
                        values.append(0)
                    return _CpuSnapshot(
                        user=values[0],
                        nice=values[1],
                        system=values[2],
                        idle=values[3],
                        iowait=values[4],
                        irq=values[5],
                        softirq=values[6],
                        steal=values[7],
                        timestamp=time.monotonic(),
                    )
    except (OSError, ValueError):
        pass
    return None


def calculate_utilization(snap1: _CpuSnapshot, snap2: _CpuSnapshot) -> Optional[float]:
    """
    Calculate CPU utilization percentage between two snapshots.

    Returns a float in [0.0, 100.0] or None if the delta is zero
    (which would indicate no time passed or identical reads).
    """
    delta_total = snap2.total - snap1.total
    delta_active = snap2.active - snap1.active

    if delta_total <= 0:
        return None

    # Guard against weird counter wraps or jitter producing negative active
    delta_active = max(0, delta_active)
    return round((delta_active / delta_total) * 100.0, 1)


def collect(interval: float = 1.0, stat_path: str = _STAT_PATH) -> dict:
    """
    Measure CPU utilization over *interval* seconds.

    Takes two snapshots separated by *interval* and computes the delta.
    Returns a dict with:
      - utilization_pct : float | None — None if measurement failed
      - interval_used   : float        — actual measurement interval
      - error           : str | None

    The minimum meaningful interval is 0.1 seconds; values below this
    are clamped to avoid unreliable readings.
    """
    interval = max(0.1, float(interval))

    snap1 = _read_cpu_snapshot(stat_path)
    if snap1 is None:
        return {
            "utilization_pct": None,
            "interval_used": 0.0,
            "error": f"Cannot read {stat_path}",
        }

    time.sleep(interval)

    snap2 = _read_cpu_snapshot(stat_path)
    if snap2 is None:
        return {
            "utilization_pct": None,
            "interval_used": 0.0,
            "error": f"Cannot read {stat_path} for second sample",
        }

    util = calculate_utilization(snap1, snap2)
    actual_interval = snap2.timestamp - snap1.timestamp

    return {
        "utilization_pct": util,
        "interval_used": round(actual_interval, 3),
        "error": None,
    }
