"""
cli.py — Command-line interface for AlpineGuard.

Entry point logic: parses arguments, orchestrates data collection,
evaluates alerts, and dispatches to the reporting layer.

Supported flags:
  --help / -h    : show usage
  --version      : print version and exit
  --once         : run a single report and exit (default behaviour)
  --json         : output report as JSON instead of terminal text
  --output FILE  : write JSON report to FILE in addition to stdout
  --mem-warn N   : memory warning threshold % (default 80)
  --mem-crit N   : memory critical threshold % (default 95)
  --disk-warn N  : disk warning threshold % (default 80)
  --disk-crit N  : disk critical threshold % (default 95)
  --cpu-warn N   : cpu warning threshold % (default 85)
  --cpu-crit N   : cpu critical threshold % (default 98)
  --cpu-interval N : seconds between CPU samples (default 1.0)
  --no-color     : disable ANSI colours
"""

import argparse
import os
import sys
from typing import Optional

from . import __version__
from . import system_info, memory_monitor, disk_monitor, cpu_monitor
from . import process_monitor, network_monitor, security_checks
from . import alerts as alert_module
from . import reporting


def build_arg_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser for AlpineGuard."""
    parser = argparse.ArgumentParser(
        prog="alpineguard",
        description=(
            "AlpineGuard — Lightweight OS Health and Security Monitor\n"
            "Monitors system health by reading Linux kernel interfaces (/proc, /sys).\n"
            "No kernel modifications. No root required for core features."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  alpineguard                     # run a full health report\n"
            "  alpineguard --json              # JSON output to stdout\n"
            "  alpineguard --json --output report.json\n"
            "  alpineguard --mem-warn 70 --disk-crit 90\n"
            "  alpineguard --once              # same as default (single run)\n"
        ),
    )

    parser.add_argument(
        "--version", "-V",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    parser.add_argument(
        "--once",
        action="store_true",
        default=True,
        help="Run a single report and exit (default behaviour)",
    )

    parser.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output the report in JSON format",
    )

    parser.add_argument(
        "--output",
        metavar="FILE",
        default=None,
        help="Write JSON report to FILE (implies --json)",
    )

    parser.add_argument(
        "--no-color",
        action="store_true",
        default=False,
        help="Disable ANSI colour output",
    )

    # Thresholds
    thresh = parser.add_argument_group("thresholds")

    thresh.add_argument(
        "--mem-warn",
        type=float,
        default=alert_module.DEFAULT_MEM_WARNING_PCT,
        metavar="PCT",
        help=f"Memory warning threshold %% (default: {alert_module.DEFAULT_MEM_WARNING_PCT})",
    )
    thresh.add_argument(
        "--mem-crit",
        type=float,
        default=alert_module.DEFAULT_MEM_ERROR_PCT,
        metavar="PCT",
        help=f"Memory critical threshold %% (default: {alert_module.DEFAULT_MEM_ERROR_PCT})",
    )
    thresh.add_argument(
        "--disk-warn",
        type=float,
        default=alert_module.DEFAULT_DISK_WARNING_PCT,
        metavar="PCT",
        help=f"Disk warning threshold %% (default: {alert_module.DEFAULT_DISK_WARNING_PCT})",
    )
    thresh.add_argument(
        "--disk-crit",
        type=float,
        default=alert_module.DEFAULT_DISK_ERROR_PCT,
        metavar="PCT",
        help=f"Disk critical threshold %% (default: {alert_module.DEFAULT_DISK_ERROR_PCT})",
    )
    thresh.add_argument(
        "--cpu-warn",
        type=float,
        default=alert_module.DEFAULT_CPU_WARNING_PCT,
        metavar="PCT",
        help=f"CPU warning threshold %% (default: {alert_module.DEFAULT_CPU_WARNING_PCT})",
    )
    thresh.add_argument(
        "--cpu-crit",
        type=float,
        default=alert_module.DEFAULT_CPU_ERROR_PCT,
        metavar="PCT",
        help=f"CPU critical threshold %% (default: {alert_module.DEFAULT_CPU_ERROR_PCT})",
    )
    thresh.add_argument(
        "--cpu-interval",
        type=float,
        default=1.0,
        metavar="SEC",
        help="Seconds between CPU measurement samples (default: 1.0)",
    )

    return parser


def collect_all(args: argparse.Namespace) -> dict:
    """
    Run all data collectors and return a unified dict.

    This is the orchestration function — it calls each monitor module
    and gathers results into a single structure passed to reporting.
    """
    sys_info = system_info.collect()
    mem_data = memory_monitor.collect()
    disk_data = disk_monitor.collect()
    cpu_data = cpu_monitor.collect(interval=args.cpu_interval)
    proc_data = process_monitor.collect()
    net_data = network_monitor.collect()
    sec_data = security_checks.collect()

    # Build alerts list
    all_alerts = [
        alert_module.evaluate_memory(mem_data, args.mem_warn, args.mem_crit),
        alert_module.evaluate_disk(disk_data["root"], args.disk_warn, args.disk_crit),
        alert_module.evaluate_cpu(cpu_data, args.cpu_warn, args.cpu_crit),
    ]

    # Disk alerts for non-root mountpoints
    for mp in disk_data.get("mounts", [])[1:]:
        all_alerts.append(
            alert_module.evaluate_disk(mp, args.disk_warn, args.disk_crit, mp["mountpoint"])
        )

    all_alerts.extend(alert_module.evaluate_security(sec_data))

    summary = alert_module.summarize(all_alerts)

    return {
        "system_info": sys_info,
        "memory": mem_data,
        "disk": disk_data,
        "cpu": cpu_data,
        "processes": proc_data,
        "network": net_data,
        "security": sec_data,
        "alerts": all_alerts,
        "alert_summary": summary,
    }


def run(args: Optional[list] = None) -> int:
    """
    Main entry point for the AlpineGuard CLI.

    Parameters
    ----------
    args : list of strings, or None to use sys.argv

    Returns an exit code (0 = OK/WARNING, 1 = ERROR status, 2 = usage error).
    """
    parser = build_arg_parser()
    parsed = parser.parse_args(args)

    # Disable colour if requested
    if parsed.no_color:
        os.environ["NO_COLOR"] = "1"
        reporting._USE_COLOR = False  # type: ignore[attr-defined]

    # --output implies --json
    if parsed.output:
        parsed.json = True

    try:
        collected = collect_all(parsed)
    except Exception as exc:
        print(f"alpineguard: fatal error during data collection: {exc}", file=sys.stderr)
        return 2

    if parsed.json:
        output = reporting.build_json_report(collected)
    else:
        output = reporting.build_report(collected)

    try:
        sys.stdout.write(output)
        sys.stdout.flush()
    except UnicodeEncodeError:
        encoding = getattr(sys.stdout, "encoding", "ascii") or "ascii"
        sys.stdout.buffer.write(output.encode(encoding, errors="replace"))
        sys.stdout.buffer.flush()

    # Write to file if --output was given
    if parsed.output:
        try:
            with open(parsed.output, "w", encoding="utf-8") as fh:
                fh.write(reporting.build_json_report(collected))
            print(f"\nReport written to: {parsed.output}", file=sys.stderr)
        except OSError as exc:
            print(f"alpineguard: cannot write to {parsed.output}: {exc}", file=sys.stderr)
            return 2

    # Exit with code 1 if any ERROR-level alerts fired
    summary = collected.get("alert_summary", {})
    if summary.get("overall_status") == "ERROR":
        return 1
    return 0


