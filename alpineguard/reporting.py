"""
reporting.py — Terminal and JSON report generation.

This module is purely about output formatting. It receives already-
collected data and Alert objects and renders them to:
  - Terminal (ANSI colour codes, graceful fallback if not a TTY)
  - JSON string (for --json mode and file export)

Design principle: no data collection happens here. This keeps the
output layer testable independently of the Linux-specific collectors.
"""

import json
import sys
import os
from datetime import datetime, timezone
from typing import Optional

from . import __version__
from .alerts import Alert


# ---------------------------------------------------------------------------
# ANSI colour helpers
# ---------------------------------------------------------------------------

_RESET  = "\033[0m"
_BOLD   = "\033[1m"
_RED    = "\033[91m"
_YELLOW = "\033[93m"
_GREEN  = "\033[92m"
_CYAN   = "\033[96m"
_WHITE  = "\033[97m"
_DIM    = "\033[2m"


def _supports_color() -> bool:
    """Return True if stdout appears to support ANSI colour codes."""
    if not hasattr(sys.stdout, "isatty"):
        return False
    if not sys.stdout.isatty():
        return False
    # Honour NO_COLOR env var (https://no-color.org/)
    if os.environ.get("NO_COLOR"):
        return False
    return True


def _supports_unicode() -> bool:
    """Return True if stdout can encode box-drawing and extended Unicode characters."""
    try:
        encoding = getattr(sys.stdout, "encoding", "ascii") or "ascii"
        "─═—█░↳".encode(encoding)
        return True
    except (UnicodeEncodeError, LookupError):
        return False


_USE_COLOR = _supports_color()
_UNICODE = _supports_unicode()

_BOX_H = "─" if _UNICODE else "-"
_BOX_D = "═" if _UNICODE else "="
_EM_DASH = "—" if _UNICODE else "--"
_ARROW = "↳" if _UNICODE else "->"
_WARN_ICON = "⚠" if _UNICODE else "[!]"


def _c(text: str, *codes: str) -> str:
    """Wrap *text* in ANSI codes if colour is supported."""
    if not _USE_COLOR:
        return text
    return "".join(codes) + text + _RESET


def _level_color(level: str) -> str:
    """Return a coloured badge string for an alert level."""
    if level == "OK":
        return _c("  OK  ", _GREEN, _BOLD)
    if level == "WARNING":
        return _c(" WARN ", _YELLOW, _BOLD)
    if level == "ERROR":
        return _c(" ERR  ", _RED, _BOLD)
    return f"[{level}]"


def _divider(char: Optional[str] = None, width: int = 72) -> str:
    if char is None:
        char = _BOX_H
    elif char == "═" and not _UNICODE:
        char = "="
    elif char == "─" and not _UNICODE:
        char = "-"
    return _c(char * width, _DIM)


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------

def _render_header(timestamp: str) -> str:
    lines = [
        _divider("═"),
        _c(f"  AlpineGuard v{__version__} {_EM_DASH} System Health & Security Report", _BOLD, _CYAN),
        _c(f"  Generated: {timestamp}", _DIM),
        _divider("═"),
    ]
    return "\n".join(lines)


def _render_system_info(data: dict) -> str:
    cpu = data.get("cpu", {})
    uptime = data.get("uptime", {})
    lines = [
        _c("  SYSTEM INFORMATION", _BOLD, _WHITE),
        _divider(),
        f"  Distribution  : {data.get('distro_name', 'unavailable')} {data.get('distro_version', '')}",
        f"  Kernel        : {data.get('kernel_version', 'unavailable')}",
        f"  Architecture  : {cpu.get('architecture', 'unavailable')}",
        f"  CPU Model     : {cpu.get('model_name', 'unavailable')}",
        f"  CPU Cores     : {cpu.get('num_cores', 'unavailable')}",
        f"  Uptime        : {uptime.get('human', 'unavailable')}",
    ]
    return "\n".join(lines)


def _render_memory(data: dict) -> str:
    if data.get("error"):
        return f"  MEMORY  : {_c('unavailable', _DIM)} {_EM_DASH} {data['error']}"

    util = data["utilization_pct"]
    bar = _progress_bar(util)
    lines = [
        _c("  MEMORY", _BOLD, _WHITE),
        _divider(),
        f"  Utilization : {bar} {util}%",
        f"  Used        : {data['used_mib']} MiB",
        f"  Available   : {data['available_mib']} MiB",
        f"  Total       : {data['total_mib']} MiB",
    ]
    if data.get("swap_total_bytes", 0) > 0:
        lines.append(
            f"  Swap        : {data['swap_used_mib']} / {data['swap_total_mib']} MiB used"
        )
    else:
        lines.append("  Swap        : none configured")
    return "\n".join(lines)


def _render_disk(data: dict) -> str:
    lines = [_c("  DISK", _BOLD, _WHITE), _divider()]
    mounts = data.get("mounts", [])
    if not mounts:
        lines.append("  No disk data available")
        return "\n".join(lines)

    for mp in mounts:
        if mp.get("error"):
            lines.append(f"  {mp['mountpoint']:20s}: {_c('unavailable', _DIM)}")
            continue
        util = mp["utilization_pct"]
        bar = _progress_bar(util)
        lines.append(
            f"  {mp['mountpoint']:20s}: {bar} {util}%  "
            f"({mp['used_gib']}/{mp['total_gib']} GiB, {mp['available_gib']} GiB free)"
        )
    return "\n".join(lines)


def _render_cpu(data: dict) -> str:
    lines = [_c("  CPU", _BOLD, _WHITE), _divider()]
    if data.get("error"):
        lines.append(f"  Utilization : {_c('unavailable', _DIM)} {_EM_DASH} {data['error']}")
        return "\n".join(lines)

    util = data.get("utilization_pct")
    if util is None:
        lines.append(f"  Utilization : (first sample {_EM_DASH} re-run for a reading)")
    else:
        bar = _progress_bar(util)
        lines.append(f"  Utilization : {bar} {util}% (over {data.get('interval_used', 1.0):.1f}s)")
    return "\n".join(lines)


def _render_processes(data: dict) -> str:
    lines = [_c("  TOP PROCESSES (by memory)", _BOLD, _WHITE), _divider()]

    procs = data.get("processes", [])
    if not procs:
        lines.append("  No process data available")
        return "\n".join(lines)

    lines.append(
        f"  {'PID':>7}  {'NAME':<20}  {'ST':2}  {'RSS (MiB)':>10}  {'CPU %':>6}  COMMAND"
    )
    lines.append("  " + "-" * 68)

    for p in procs[:15]:
        cpu_str = f"{p['cpu_pct']:5.1f}" if p["cpu_pct"] is not None else "  n/a"
        cmd = p.get("cmdline", "")[:35]
        lines.append(
            f"  {p['pid']:>7}  {p['name']:<20}  {p['state']:2}  "
            f"{p['rss_mib']:>10.1f}  {cpu_str:>6}  {cmd}"
        )

    total = data.get("total_visible", 0)
    shown = min(15, len(procs))
    lines.append(_c(f"\n  Showing {shown} of {total} visible processes", _DIM))

    if data.get("high_mem_processes"):
        names = ", ".join(p["name"] for p in data["high_mem_processes"][:5])
        lines.append(_c(f"  High-memory processes: {names}", _YELLOW))

    return "\n".join(lines)


def _render_network(data: dict) -> str:
    lines = [_c("  NETWORK", _BOLD, _WHITE), _divider()]

    ifaces = data.get("interfaces", [])
    if not ifaces:
        lines.append("  No network interface data available")
    else:
        for iface in ifaces:
            ipv6 = ", ".join(iface.get("ipv6", [])[:2]) or "-"
            lines.append(
                f"  {iface['name']:12s}  RX: {_human_bytes(iface['rx_bytes']):<10}  "
                f"TX: {_human_bytes(iface['tx_bytes']):<10}  IPv6: {ipv6}"
            )

    tcp = data.get("tcp_connections", [])
    listening = data.get("listening_ports", [])
    lines.append(f"\n  TCP connections  : {len(tcp)}")
    lines.append(f"  Listening ports  : {len(listening)}")
    if listening:
        port_list = ", ".join(str(p["local_port"]) for p in listening[:10])
        lines.append(f"  Ports in LISTEN  : {port_list}")

    return "\n".join(lines)


def _render_security(data: dict) -> str:
    lines = [_c("  SECURITY CHECKS", _BOLD, _WHITE), _divider()]

    auth = data.get("auth_logs", {})
    lines.append(f"  Auth log         : {auth.get('message', 'unavailable')}")
    if auth.get("log_path"):
        lines.append(f"  Log source       : {auth['log_path']}")
    if auth.get("note"):
        lines.append(_c(f"  Note             : {auth['note']}", _DIM))

    ports = data.get("listening_ports", {})
    lines.append(f"\n  Listening ports  : {ports.get('message', 'unavailable')}")
    if ports.get("high_risk_ports"):
        for p in ports["high_risk_ports"]:
            lines.append(_c(
                f"  {_WARN_ICON} Port {p['local_port']} ({p.get('service', '?')}) {_EM_DASH} {p.get('reason', '')}",
                _YELLOW
            ))

    ww = data.get("world_writable", {})
    lines.append(f"\n  World-writable   : {ww.get('message', 'unavailable')}")
    if ww.get("world_writable"):
        for path in ww["world_writable"]:
            lines.append(_c(f"    {path}", _YELLOW))

    return "\n".join(lines)


def _render_alerts_summary(alerts: list, summary: dict) -> str:
    lines = [
        _divider("═"),
        _c("  ALERT SUMMARY", _BOLD, _WHITE),
        _divider(),
    ]

    for alert in alerts:
        badge = _level_color(alert.level)
        lines.append(f"  [{badge}] {alert.message}")
        if alert.recommendation:
            lines.append(_c(f"           {_ARROW} {alert.recommendation}", _DIM))

    overall = summary["overall_status"]
    color = _GREEN if overall == "OK" else (_YELLOW if overall == "WARNING" else _RED)
    lines += [
        _divider(),
        f"  Overall Status : {_c(overall, color, _BOLD)}",
        f"  Checks: {summary['ok_count']} OK  |  "
        f"{summary['warning_count']} Warning  |  {summary['error_count']} Error",
        _divider("═"),
    ]

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def _progress_bar(pct: float, width: int = 20) -> str:
    """Render a simple text progress bar.

    Uses Unicode block characters on UTF-8 terminals, falls back to
    ASCII '#' and '.' on consoles that cannot encode them.
    """
    filled_char, empty_char = ("█", "░") if _UNICODE else ("#", ".")
    filled = int(min(pct, 100) / 100 * width)
    bar = filled_char * filled + empty_char * (width - filled)
    if pct >= 95:
        return _c(f"[{bar}]", _RED)
    if pct >= 80:
        return _c(f"[{bar}]", _YELLOW)
    return _c(f"[{bar}]", _GREEN)


def _human_bytes(b: int) -> str:
    """Format bytes as a human-readable string."""
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(b) < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PiB"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_report(collected: dict) -> str:
    """
    Build a complete terminal report from collected data.

    Parameters
    ----------
    collected : dict with keys:
        system_info, memory, disk, cpu, processes, network, security,
        alerts (list of Alert), alert_summary (dict)

    Returns the full report as a string.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    sections = [
        _render_header(now),
        "",
        _render_system_info(collected.get("system_info", {})),
        "",
        _render_memory(collected.get("memory", {})),
        "",
        _render_disk(collected.get("disk", {})),
        "",
        _render_cpu(collected.get("cpu", {})),
        "",
        _render_processes(collected.get("processes", {})),
        "",
        _render_network(collected.get("network", {})),
        "",
        _render_security(collected.get("security", {})),
        "",
        _render_alerts_summary(
            collected.get("alerts", []),
            collected.get("alert_summary", {}),
        ),
    ]

    return "\n".join(sections) + "\n"


def build_json_report(collected: dict) -> str:
    """
    Serialize all collected data and alerts to a JSON string.

    The JSON report is suitable for machine consumption and export.
    Alert objects are converted to dicts via Alert.to_dict().

    Returns a pretty-printed JSON string.
    """
    now = datetime.now(timezone.utc).isoformat()

    # Make alerts JSON-serializable
    alerts_raw = collected.get("alerts", [])
    alerts_dicts = [
        a.to_dict() if isinstance(a, Alert) else a
        for a in alerts_raw
    ]

    payload = {
        "alpineguard_version": __version__,
        "generated_at": now,
        "system_info": collected.get("system_info", {}),
        "memory": collected.get("memory", {}),
        "disk": collected.get("disk", {}),
        "cpu": collected.get("cpu", {}),
        "processes": {
            "total_visible": collected.get("processes", {}).get("total_visible", 0),
            "top_processes": collected.get("processes", {}).get("processes", []),
            "high_cpu_processes": collected.get("processes", {}).get("high_cpu_processes", []),
            "high_mem_processes": collected.get("processes", {}).get("high_mem_processes", []),
        },
        "network": collected.get("network", {}),
        "security": collected.get("security", {}),
        "alerts": alerts_dicts,
        "alert_summary": collected.get("alert_summary", {}),
    }

    return json.dumps(payload, indent=2, default=str)
