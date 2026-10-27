"""
process_monitor.py — Process listing and resource usage monitoring.

Data sources:
  /proc/<pid>/status   — process name, state, UID, memory (VmRSS)
  /proc/<pid>/stat     — CPU tick counters for per-process CPU %
  /proc/<pid>/cmdline  — full command line

Only processes readable by the current user are reported.
Processes that disappear mid-scan (race condition) are silently skipped.

CPU % calculation per process:
  We read utime + stime from /proc/<pid>/stat at two points separated
  by a short interval, then divide by the system-wide tick delta.
  This avoids hardcoding the clock tick rate (though 100 Hz is common,
  it must be read from os.sysconf('SC_CLK_TCK') to be correct).

  Since per-process CPU requires a two-sample approach and adding a
  sleep inside process enumeration is expensive, we instead compute a
  process-level CPU snapshot once and return "unavailable" for CPU %
  in single-shot mode. In continuous mode the previous snapshot is
  reused across calls.
"""

import os
import time
from typing import Optional


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_PROC_DIR = "/proc"
_CLK_TCK: Optional[int] = None


def _get_clk_tck() -> int:
    """Return the system clock tick rate (SC_CLK_TCK), typically 100."""
    global _CLK_TCK
    if _CLK_TCK is None:
        try:
            _CLK_TCK = os.sysconf("SC_CLK_TCK")
        except (AttributeError, ValueError):
            _CLK_TCK = 100  # safe assumption for Linux
    return _CLK_TCK


def _read_file(path: str) -> Optional[str]:
    """Return file contents as a string, or None on any error."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def _list_pids(proc_dir: str = _PROC_DIR) -> list:
    """
    Return a sorted list of integer PIDs found in /proc.

    Only directories whose names are all-digit are considered.
    """
    pids = []
    try:
        for entry in os.listdir(proc_dir):
            if entry.isdigit():
                pids.append(int(entry))
    except OSError:
        pass
    return sorted(pids)


def _parse_status(pid: int, proc_dir: str = _PROC_DIR) -> Optional[dict]:
    """
    Parse /proc/<pid>/status for a process name, state, uid, and memory.

    Returns None if the file is unreadable (process may have exited).
    """
    content = _read_file(os.path.join(proc_dir, str(pid), "status"))
    if content is None:
        return None

    data: dict = {}
    for line in content.splitlines():
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        data[key.strip()] = value.strip()

    name = data.get("Name", "unknown")
    state = data.get("State", "?")

    # VmRSS is in kB; convert to bytes
    vm_rss_str = data.get("VmRSS", "0 kB").split()[0]
    try:
        vm_rss_bytes = int(vm_rss_str) * 1024
    except ValueError:
        vm_rss_bytes = 0

    # UID line: "Uid: real  effective  saved  fs"
    uid_str = data.get("Uid", "").split()
    uid = int(uid_str[0]) if uid_str else -1

    return {
        "pid": pid,
        "name": name,
        "state": state[0] if state else "?",   # first character: R/S/D/Z/T
        "uid": uid,
        "rss_bytes": vm_rss_bytes,
        "rss_mib": round(vm_rss_bytes / (1024 ** 2), 1),
    }


def _parse_cmdline(pid: int, proc_dir: str = _PROC_DIR) -> str:
    """
    Return the command line for *pid* as a human-readable string.

    /proc/<pid>/cmdline is NUL-delimited. Kernel threads have an empty
    cmdline; for these we fall back to the name in square brackets.
    """
    path = os.path.join(proc_dir, str(pid), "cmdline")
    try:
        with open(path, "rb") as fh:
            raw = fh.read(512)  # limit to avoid huge reads
        if not raw:
            return ""
        # Replace NUL bytes with spaces
        return raw.replace(b"\x00", b" ").decode("utf-8", errors="replace").strip()
    except OSError:
        return ""


def _read_proc_stat_ticks(pid: int, proc_dir: str = _PROC_DIR) -> Optional[tuple]:
    """
    Return (utime, stime) tick counts from /proc/<pid>/stat.

    /proc/<pid>/stat format:
      pid (comm) state ppid pgroup session tty tpgid flags ...
      fields 14 and 15 (1-indexed) are utime and stime.

    The process name in parentheses may contain spaces; we find the
    last ')' to correctly split the remaining fields.
    """
    content = _read_file(os.path.join(proc_dir, str(pid), "stat"))
    if not content:
        return None
    try:
        # Find the closing paren of the comm field
        rp = content.rfind(")")
        if rp == -1:
            return None
        remaining = content[rp + 2:].split()  # skip ') '
        # utime is field 14 (index 11 in remaining, 0-indexed from after state)
        # state ppid pgrp session tty_nr tpgid flags minflt cminflt majflt cmajflt utime stime
        #  0     1    2    3       4      5     6     7      8       9      10      11    12
        utime = int(remaining[11])
        stime = int(remaining[12])
        return (utime, stime)
    except (IndexError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Per-process CPU snapshot (for two-sample CPU % calculation)
# ---------------------------------------------------------------------------

_previous_proc_snapshots: dict = {}   # pid → (utime+stime, timestamp)
_previous_total_ticks: Optional[int] = None
_previous_total_time: Optional[float] = None


def _get_total_cpu_ticks(stat_path: str = "/proc/stat") -> Optional[int]:
    """Return the total CPU tick count from /proc/stat."""
    try:
        with open(stat_path, "r", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("cpu "):
                    return sum(int(x) for x in line.split()[1:])
    except OSError:
        pass
    return None


def calculate_process_cpu(
    pid: int,
    proc_dir: str = _PROC_DIR,
    prev_snapshots: Optional[dict] = None,
    prev_total_ticks: Optional[int] = None,
    curr_total_ticks: Optional[int] = None,
) -> Optional[float]:
    """
    Calculate the CPU utilisation percentage for a single process.

    Requires both the previous process tick snapshot and the previous/current
    system-wide total tick counts. Returns None when data is unavailable.
    """
    ticks = _read_proc_stat_ticks(pid, proc_dir)
    if ticks is None:
        return None
    curr_proc = ticks[0] + ticks[1]

    if prev_snapshots is None or pid not in prev_snapshots:
        return None
    prev_proc = prev_snapshots[pid]

    if prev_total_ticks is None or curr_total_ticks is None:
        return None
    delta_total = curr_total_ticks - prev_total_ticks
    if delta_total <= 0:
        return None

    delta_proc = max(0, curr_proc - prev_proc)
    pct = (delta_proc / delta_total) * 100.0
    return round(pct, 1)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def collect(
    proc_dir: str = _PROC_DIR,
    top_n: int = 20,
    cpu_threshold: float = 5.0,
    mem_threshold_mib: float = 100.0,
) -> dict:
    """
    Collect process information and identify high-resource consumers.

    Parameters
    ----------
    proc_dir        : path to the proc filesystem (default "/proc")
    top_n           : maximum number of processes to return in the listing
    cpu_threshold   : CPU % above which a process is flagged as "high CPU"
    mem_threshold_mib : RSS MiB above which a process is flagged as "high memory"

    Returns a dict with:
      - processes           : list of process dicts (up to top_n by RSS)
      - high_cpu_processes  : list of PIDs with CPU % above threshold
      - high_mem_processes  : list of PIDs with RSS above threshold
      - total_visible       : int — total number of readable processes
      - error               : str | None
    """
    global _previous_proc_snapshots, _previous_total_ticks

    pids = _list_pids(proc_dir)
    if not pids:
        return {
            "processes": [],
            "high_cpu_processes": [],
            "high_mem_processes": [],
            "total_visible": 0,
            "error": f"Cannot list processes from {proc_dir}",
        }

    curr_total_ticks = _get_total_cpu_ticks(
        stat_path=os.path.join(proc_dir, "stat") if proc_dir != _PROC_DIR else "/proc/stat"
    )

    processes = []
    new_snapshots: dict = {}

    for pid in pids:
        status = _parse_status(pid, proc_dir)
        if status is None:
            continue  # process exited during scan

        cmdline = _parse_cmdline(pid, proc_dir)
        if not cmdline:
            # Kernel thread — display name in brackets
            cmdline = f"[{status['name']}]"

        ticks = _read_proc_stat_ticks(pid, proc_dir)
        if ticks is not None:
            new_snapshots[pid] = ticks[0] + ticks[1]

        cpu_pct = calculate_process_cpu(
            pid=pid,
            proc_dir=proc_dir,
            prev_snapshots=_previous_proc_snapshots,
            prev_total_ticks=_previous_total_ticks,
            curr_total_ticks=curr_total_ticks,
        )

        proc_info = {
            "pid": pid,
            "name": status["name"],
            "state": status["state"],
            "uid": status["uid"],
            "rss_mib": status["rss_mib"],
            "cpu_pct": cpu_pct,     # None = not yet available
            "cmdline": cmdline[:120],  # truncate very long command lines
        }
        processes.append(proc_info)

    # Update global state for next call
    _previous_proc_snapshots = new_snapshots
    _previous_total_ticks = curr_total_ticks

    # Sort by RSS descending for the top-N listing
    processes.sort(key=lambda p: p["rss_mib"], reverse=True)

    high_cpu = [
        p for p in processes
        if p["cpu_pct"] is not None and p["cpu_pct"] >= cpu_threshold
    ]
    high_mem = [
        p for p in processes
        if p["rss_mib"] >= mem_threshold_mib
    ]

    return {
        "processes": processes[:top_n],
        "high_cpu_processes": high_cpu,
        "high_mem_processes": high_mem,
        "total_visible": len(processes),
        "error": None,
    }
