"""
alerts.py — Threshold evaluation and alert generation.

This module takes collected metric data and compares values against
configurable thresholds to produce structured Alert objects.

Alert levels:
  OK      — metric is within normal bounds
  WARNING — metric has crossed a warning threshold
  ERROR   — metric has crossed a critical threshold

Thresholds can be configured via environment variables or passed
directly as arguments. Defaults are conservative and suitable for
a general-purpose Linux system.

No I/O is performed here — this module only evaluates values that
have already been collected by the monitor modules.
"""

from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Default threshold constants
# ---------------------------------------------------------------------------

DEFAULT_MEM_WARNING_PCT = 80.0
DEFAULT_MEM_ERROR_PCT = 95.0

DEFAULT_DISK_WARNING_PCT = 80.0
DEFAULT_DISK_ERROR_PCT = 95.0

DEFAULT_CPU_WARNING_PCT = 85.0
DEFAULT_CPU_ERROR_PCT = 98.0


# ---------------------------------------------------------------------------
# Alert data class
# ---------------------------------------------------------------------------

@dataclass
class Alert:
    """
    Represents a single monitoring alert.

    Attributes
    ----------
    level       : "OK" | "WARNING" | "ERROR"
    category    : e.g. "memory", "disk", "cpu", "security", "network"
    message     : human-readable description of the finding
    value       : the measured value that triggered this alert (or None)
    threshold   : the threshold that was crossed (or None for informational)
    recommendation : optional actionable advice
    """
    level: str
    category: str
    message: str
    value: Optional[float] = None
    threshold: Optional[float] = None
    recommendation: str = ""

    def is_ok(self) -> bool:
        return self.level == "OK"

    def is_warning(self) -> bool:
        return self.level == "WARNING"

    def is_error(self) -> bool:
        return self.level == "ERROR"

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "category": self.category,
            "message": self.message,
            "value": self.value,
            "threshold": self.threshold,
            "recommendation": self.recommendation,
        }


# ---------------------------------------------------------------------------
# Threshold evaluation helpers
# ---------------------------------------------------------------------------

def _pct_level(
    pct: float,
    warning: float,
    error: float,
) -> str:
    """Return "OK", "WARNING", or "ERROR" based on percentage thresholds."""
    if pct >= error:
        return "ERROR"
    if pct >= warning:
        return "WARNING"
    return "OK"


# ---------------------------------------------------------------------------
# Per-category alert generators
# ---------------------------------------------------------------------------

def evaluate_memory(
    mem_data: dict,
    warning_pct: float = DEFAULT_MEM_WARNING_PCT,
    error_pct: float = DEFAULT_MEM_ERROR_PCT,
) -> Alert:
    """
    Evaluate memory utilization and return an Alert.

    Parameters
    ----------
    mem_data    : dict returned by memory_monitor.collect()
    warning_pct : utilization % above which WARNING is raised
    error_pct   : utilization % above which ERROR is raised
    """
    if mem_data.get("error"):
        return Alert(
            level="ERROR",
            category="memory",
            message=f"Memory data unavailable: {mem_data['error']}",
            recommendation="Check that /proc/meminfo is readable.",
        )

    util = mem_data["utilization_pct"]
    level = _pct_level(util, warning_pct, error_pct)

    used_mib = mem_data["used_mib"]
    total_mib = mem_data["total_mib"]
    avail_mib = mem_data["available_mib"]

    if level == "OK":
        msg = f"Memory OK — {util}% used ({used_mib} MiB / {total_mib} MiB, {avail_mib} MiB available)"
        rec = ""
    elif level == "WARNING":
        msg = f"Memory WARNING — {util}% used ({used_mib} MiB / {total_mib} MiB)"
        rec = "Consider closing unused applications or adding swap space."
    else:
        msg = f"Memory CRITICAL — {util}% used ({used_mib} MiB / {total_mib} MiB, only {avail_mib} MiB available)"
        rec = "Immediate action needed: free memory, kill unnecessary processes, or add swap."

    return Alert(
        level=level,
        category="memory",
        message=msg,
        value=util,
        threshold=warning_pct if level == "WARNING" else (error_pct if level == "ERROR" else None),
        recommendation=rec,
    )


def evaluate_disk(
    disk_data: dict,
    warning_pct: float = DEFAULT_DISK_WARNING_PCT,
    error_pct: float = DEFAULT_DISK_ERROR_PCT,
    mountpoint: str = "/",
) -> Alert:
    """
    Evaluate disk utilization for a single mountpoint and return an Alert.

    Parameters
    ----------
    disk_data   : one mountpoint dict from disk_monitor.collect()["root"] or ["mounts"][i]
    warning_pct : utilization % above which WARNING is raised
    error_pct   : utilization % above which ERROR is raised
    mountpoint  : label for the alert message
    """
    if disk_data.get("error"):
        return Alert(
            level="ERROR",
            category="disk",
            message=f"Disk data unavailable for {mountpoint}: {disk_data['error']}",
            recommendation="Check filesystem health with 'df -h'.",
        )

    util = disk_data["utilization_pct"]
    used_gib = disk_data["used_gib"]
    total_gib = disk_data["total_gib"]
    avail_gib = disk_data["available_gib"]
    level = _pct_level(util, warning_pct, error_pct)

    if level == "OK":
        msg = f"Disk OK [{mountpoint}] — {util}% used ({used_gib} GiB / {total_gib} GiB, {avail_gib} GiB free)"
        rec = ""
    elif level == "WARNING":
        msg = f"Disk WARNING [{mountpoint}] — {util}% used ({avail_gib} GiB remaining)"
        rec = f"Consider cleaning up {mountpoint} — run 'du -sh /*' to find large directories."
    else:
        msg = f"Disk CRITICAL [{mountpoint}] — {util}% used (only {avail_gib} GiB remaining)"
        rec = f"Urgent: {mountpoint} is nearly full. Remove large files or expand the volume."

    return Alert(
        level=level,
        category="disk",
        message=msg,
        value=util,
        threshold=warning_pct if level == "WARNING" else (error_pct if level == "ERROR" else None),
        recommendation=rec,
    )


def evaluate_cpu(
    cpu_data: dict,
    warning_pct: float = DEFAULT_CPU_WARNING_PCT,
    error_pct: float = DEFAULT_CPU_ERROR_PCT,
) -> Alert:
    """
    Evaluate CPU utilization and return an Alert.

    Parameters
    ----------
    cpu_data    : dict returned by cpu_monitor.collect()
    warning_pct : utilization % above which WARNING is raised
    error_pct   : utilization % above which ERROR is raised
    """
    if cpu_data.get("error"):
        return Alert(
            level="ERROR",
            category="cpu",
            message=f"CPU data unavailable: {cpu_data['error']}",
            recommendation="Check that /proc/stat is readable.",
        )

    util = cpu_data.get("utilization_pct")
    if util is None:
        return Alert(
            level="OK",
            category="cpu",
            message="CPU utilization measurement requires two samples — reading in progress.",
            recommendation="Re-run after the first measurement interval completes.",
        )

    level = _pct_level(util, warning_pct, error_pct)

    if level == "OK":
        msg = f"CPU OK — {util}% utilization"
        rec = ""
    elif level == "WARNING":
        msg = f"CPU WARNING — {util}% utilization (above {warning_pct}% threshold)"
        rec = "Investigate high-CPU processes with the process report."
    else:
        msg = f"CPU CRITICAL — {util}% utilization (above {error_pct}% threshold)"
        rec = "System under heavy load. Check process list for runaway processes."

    return Alert(
        level=level,
        category="cpu",
        message=msg,
        value=util,
        threshold=warning_pct if level == "WARNING" else (error_pct if level == "ERROR" else None),
        recommendation=rec,
    )


def evaluate_security(sec_data: dict) -> list:
    """
    Convert security check results into a list of Alerts.

    Parameters
    ----------
    sec_data : dict returned by security_checks.collect()

    Returns a list of Alert objects (one per sub-check).
    """
    alerts = []

    _SEV_MAP = {"ok": "OK", "note": "OK", "warning": "WARNING", "error": "ERROR"}

    # Auth log check
    auth = sec_data.get("auth_logs", {})
    auth_level = _SEV_MAP.get(auth.get("severity", "note"), "OK")
    alerts.append(Alert(
        level=auth_level,
        category="security",
        message=auth.get("message", "Auth log check unavailable"),
        recommendation=(
            "Review authentication logs manually for suspicious patterns."
            if auth_level != "OK" else ""
        ),
    ))

    # Listening ports check
    ports = sec_data.get("listening_ports", {})
    port_level = _SEV_MAP.get(ports.get("severity", "ok"), "OK")
    alerts.append(Alert(
        level=port_level,
        category="network/ports",
        message=ports.get("message", "Port check unavailable"),
        recommendation=(
            "Disable or firewall services that should not be publicly accessible."
            if port_level == "WARNING" else ""
        ),
    ))

    # World-writable check
    ww = sec_data.get("world_writable", {})
    ww_level = _SEV_MAP.get(ww.get("severity", "ok"), "OK")
    alerts.append(Alert(
        level=ww_level,
        category="filesystem",
        message=ww.get("message", "Filesystem check unavailable"),
        recommendation=(
            "Review world-writable paths: " + ", ".join(ww.get("world_writable", []))
            if ww_level == "WARNING" else ""
        ),
    ))

    return alerts


# ---------------------------------------------------------------------------
# Aggregate summary
# ---------------------------------------------------------------------------

def summarize(alerts: list) -> dict:
    """
    Produce an overall summary from a list of Alert objects.

    Returns a dict with:
      - total     : int
      - ok_count  : int
      - warning_count : int
      - error_count   : int
      - overall_status : "OK" | "WARNING" | "ERROR"
    """
    ok = sum(1 for a in alerts if a.level == "OK")
    warn = sum(1 for a in alerts if a.level == "WARNING")
    err = sum(1 for a in alerts if a.level == "ERROR")

    if err > 0:
        overall = "ERROR"
    elif warn > 0:
        overall = "WARNING"
    else:
        overall = "OK"

    return {
        "total": len(alerts),
        "ok_count": ok,
        "warning_count": warn,
        "error_count": err,
        "overall_status": overall,
    }
