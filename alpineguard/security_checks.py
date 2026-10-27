"""
security_checks.py — Basic security indicator checks.

What this module does (and does NOT do):
  ✓ Inspects authentication logs for failed login patterns
  ✓ Lists listening network ports
  ✓ Checks for world-writable directories in sensitive paths
  ✓ Reports findings with transparent, explainable rules

  ✗ Does NOT claim to detect an ongoing attack from log evidence alone
  ✗ Does NOT modify firewall rules, accounts, or system configuration
  ✗ Does NOT expose passwords, keys, or secrets
  ✗ Does NOT require root for the base checks (log access may need it)

Data sources:
  /var/log/messages       — Alpine's default syslog (BusyBox syslogd)
  /var/log/auth.log       — if present (not always on Alpine)
  /proc/net/tcp           — listening ports (via network_monitor)
  Filesystem checks via os.stat()

Security philosophy:
  Every finding is labeled with WHY it is flagged and HOW CONFIDENT
  we are. Weak evidence produces informational notes, not alarms.
"""

import os
import re
from typing import Optional

from .network_monitor import get_listening_ports


# ---------------------------------------------------------------------------
# Log paths (Alpine Linux uses BusyBox syslogd by default)
# ---------------------------------------------------------------------------

_AUTH_LOG_CANDIDATES = [
    "/var/log/auth.log",       # Debian-style if present
    "/var/log/messages",       # Alpine/BusyBox default
    "/var/log/syslog",         # sometimes present
]

# Regex for common SSH failure messages
_SSH_FAIL_PATTERNS = [
    re.compile(r"Failed password for (invalid user )?(\S+) from (\S+)", re.IGNORECASE),
    re.compile(r"Invalid user (\S+) from (\S+)", re.IGNORECASE),
    re.compile(r"authentication failure.*rhost=(\S+)", re.IGNORECASE),
    re.compile(r"Connection closed by authenticating user (\S+) (\S+) \[preauth\]", re.IGNORECASE),
    re.compile(r"Disconnected from authenticating user (\S+) (\S+) \[preauth\]", re.IGNORECASE),
]

# Well-known privileged/sensitive listening ports
_SENSITIVE_PORTS = {
    21: "FTP",
    22: "SSH",
    23: "Telnet",
    25: "SMTP",
    53: "DNS",
    80: "HTTP",
    110: "POP3",
    143: "IMAP",
    443: "HTTPS",
    445: "SMB",
    3306: "MySQL",
    5432: "PostgreSQL",
    6379: "Redis",
    27017: "MongoDB",
}

# Ports considered high-risk when listening on 0.0.0.0
_HIGH_RISK_PORTS = {21, 23, 445, 3306, 5432, 6379, 27017}


def _read_log_tail(path: str, max_lines: int = 1000) -> Optional[list]:
    """
    Read the last *max_lines* lines of a log file.

    Returns a list of strings, or None if the file cannot be read.
    Large log files are read from the end using a simple line buffer.
    """
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
        return lines[-max_lines:]
    except OSError:
        return None


def check_auth_logs() -> dict:
    """
    Inspect authentication logs for failed login patterns.

    Returns a dict with:
      - log_path         : str | None  — which log was read
      - failed_attempts  : int         — count of failure lines found
      - source_ips       : list        — unique IPs seen in failures
      - sample_lines     : list        — up to 5 representative failure lines
      - severity         : str         — "ok" | "warning" | "note"
      - message          : str         — human-readable summary
      - note             : str         — caveat about confidence

    Interpretation note:
      Failed logins are NORMAL on internet-facing systems. This check
      reports a count and samples — it does NOT claim an attack is
      occurring. Context (total attempts, rate, geographic origin)
      would be needed for that conclusion.
    """
    log_path = None
    lines = None

    for candidate in _AUTH_LOG_CANDIDATES:
        result = _read_log_tail(candidate, max_lines=2000)
        if result is not None:
            log_path = candidate
            lines = result
            break

    if lines is None:
        return {
            "log_path": None,
            "failed_attempts": 0,
            "source_ips": [],
            "sample_lines": [],
            "severity": "note",
            "message": "No authentication log found or readable",
            "note": (
                "Common Alpine log locations were checked: "
                + ", ".join(_AUTH_LOG_CANDIDATES)
                + ". Root privileges may be required to read these files."
            ),
        }

    failed_lines = []
    source_ips: set = set()

    for line in lines:
        for pattern in _SSH_FAIL_PATTERNS:
            m = pattern.search(line)
            if m:
                failed_lines.append(line.strip())
                # Try to extract an IP address from the match groups
                for group in m.groups():
                    if group and re.match(r"\d+\.\d+\.\d+\.\d+", group):
                        source_ips.add(group)
                break  # one match per line is enough

    count = len(failed_lines)
    if count == 0:
        severity = "ok"
        message = f"No failed login patterns detected in {log_path}"
    elif count < 10:
        severity = "note"
        message = f"{count} failed login event(s) found in {log_path}"
    elif count < 50:
        severity = "warning"
        message = f"{count} failed login events found — elevated activity"
    else:
        severity = "warning"
        message = f"{count} failed login events found — high volume (review recommended)"

    return {
        "log_path": log_path,
        "failed_attempts": count,
        "source_ips": sorted(source_ips),
        "sample_lines": failed_lines[:5],
        "severity": severity,
        "message": message,
        "note": (
            "Failed logins occur normally on networked systems. "
            "This count alone does not confirm an attack. "
            "Review the log manually for context."
        ),
    }


def check_listening_ports() -> dict:
    """
    Inspect listening TCP ports and flag high-risk services.

    Returns a dict with:
      - ports            : list — all listening port dicts
      - high_risk_ports  : list — ports in the high-risk set
      - severity         : str
      - message          : str
    """
    ports = get_listening_ports()

    high_risk = []
    for p in ports:
        port_num = p["local_port"]
        if port_num in _HIGH_RISK_PORTS and p["local_ip"] in ("0.0.0.0", "::"):
            high_risk.append({
                **p,
                "service": _SENSITIVE_PORTS.get(port_num, "unknown"),
                "reason": f"Port {port_num} is classified as high-risk when exposed on all interfaces",
            })

    if not ports:
        severity = "note"
        message = "No TCP listening ports detected (or /proc/net/tcp unreadable)"
    elif high_risk:
        severity = "warning"
        message = f"{len(high_risk)} high-risk port(s) listening on all interfaces"
    else:
        severity = "ok"
        message = f"{len(ports)} listening port(s) — none classified as high-risk"

    return {
        "ports": ports,
        "high_risk_ports": high_risk,
        "severity": severity,
        "message": message,
    }


def check_world_writable(paths: Optional[list] = None) -> dict:
    """
    Check for world-writable files/directories in sensitive locations.

    Only checks the provided paths (not a recursive scan) to keep
    execution fast and avoid touching sensitive data.

    Returns a dict with:
      - checked_paths       : list
      - world_writable      : list — paths that are world-writable
      - severity            : str
      - message             : str
    """
    if paths is None:
        paths = ["/tmp", "/var/tmp", "/etc", "/etc/passwd", "/etc/shadow"]

    world_writable = []
    checked = []

    for path in paths:
        try:
            st = os.stat(path)
            checked.append(path)
            # World-writable bit: S_IWOTH = 0o002
            if st.st_mode & 0o002:
                world_writable.append(path)
        except OSError:
            pass  # path doesn't exist or permission denied — skip silently

    if not world_writable:
        severity = "ok"
        message = "No world-writable files found in checked paths"
    else:
        severity = "warning"
        message = f"{len(world_writable)} world-writable path(s) found"

    return {
        "checked_paths": checked,
        "world_writable": world_writable,
        "severity": severity,
        "message": message,
    }


def collect() -> dict:
    """
    Run all security checks and return a unified report.

    Returns a dict with keys:
      - auth_logs      : dict — from check_auth_logs()
      - listening_ports: dict — from check_listening_ports()
      - world_writable : dict — from check_world_writable()
      - overall_severity: str — worst severity across all checks
    """
    auth = check_auth_logs()
    ports = check_listening_ports()
    writable = check_world_writable()

    severity_rank = {"ok": 0, "note": 1, "warning": 2, "error": 3}
    worst = max(
        auth["severity"], ports["severity"], writable["severity"],
        key=lambda s: severity_rank.get(s, 0)
    )

    return {
        "auth_logs": auth,
        "listening_ports": ports,
        "world_writable": writable,
        "overall_severity": worst,
    }
