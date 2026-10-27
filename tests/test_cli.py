"""
tests/test_cli.py — Unit tests for CLI argument parsing and JSON output.

Tests run on Windows; actual data collection is mocked out so the
tests focus on:
  - Argument parsing correctness
  - JSON report structure and valid JSON
  - Exit code behavior
  - --output file writing
"""

import argparse
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from alpineguard import cli, reporting
from alpineguard.alerts import Alert


# ---------------------------------------------------------------------------
# Minimal stub data for mocking collect_all
# ---------------------------------------------------------------------------

def _make_collected():
    """Return a minimal but structurally complete collected dict."""
    return {
        "system_info": {
            "distro_name": "Alpine Linux",
            "distro_version": "3.24.0",
            "distro_id": "alpine",
            "kernel_version": "6.1.58-0-lts",
            "uptime": {"human": "1 hour, 5 minutes"},
            "cpu": {"architecture": "x86_64", "model_name": "Test CPU", "num_cores": 2},
        },
        "memory": {
            "utilization_pct": 45.0,
            "used_mib": 450.0,
            "total_mib": 1000.0,
            "available_mib": 550.0,
            "used_bytes": 450 * 1024 ** 2,
            "total_bytes": 1000 * 1024 ** 2,
            "available_bytes": 550 * 1024 ** 2,
            "swap_total_bytes": 0,
            "swap_used_bytes": 0,
            "swap_total_mib": 0.0,
            "swap_used_mib": 0.0,
            "error": None,
        },
        "disk": {
            "root": {
                "mountpoint": "/",
                "utilization_pct": 55.0,
                "used_gib": 5.5,
                "total_gib": 10.0,
                "available_gib": 4.5,
                "used_bytes": 0,
                "total_bytes": 0,
                "available_bytes": 0,
                "error": None,
            },
            "mounts": [],
        },
        "cpu": {
            "utilization_pct": 10.0,
            "interval_used": 1.0,
            "error": None,
        },
        "processes": {
            "processes": [],
            "high_cpu_processes": [],
            "high_mem_processes": [],
            "total_visible": 0,
            "error": None,
        },
        "network": {
            "interfaces": [],
            "ipv6_addresses": {},
            "tcp_connections": [],
            "listening_ports": [],
            "error": None,
        },
        "security": {
            "auth_logs": {
                "log_path": None,
                "failed_attempts": 0,
                "source_ips": [],
                "sample_lines": [],
                "severity": "note",
                "message": "No auth log found",
                "note": "test",
            },
            "listening_ports": {
                "ports": [],
                "high_risk_ports": [],
                "severity": "ok",
                "message": "No listening ports",
            },
            "world_writable": {
                "checked_paths": [],
                "world_writable": [],
                "severity": "ok",
                "message": "OK",
            },
            "overall_severity": "note",
        },
        "alerts": [Alert("OK", "memory", "Memory OK", 45.0)],
        "alert_summary": {
            "total": 1,
            "ok_count": 1,
            "warning_count": 0,
            "error_count": 0,
            "overall_status": "OK",
        },
    }


# ---------------------------------------------------------------------------
# Tests: argument parser
# ---------------------------------------------------------------------------

class TestArgParser(unittest.TestCase):

    def setUp(self):
        self.parser = cli.build_arg_parser()

    def test_defaults(self):
        args = self.parser.parse_args([])
        self.assertFalse(args.json)
        self.assertIsNone(args.output)
        self.assertFalse(args.no_color)
        self.assertEqual(args.mem_warn, 80.0)
        self.assertEqual(args.mem_crit, 95.0)
        self.assertEqual(args.disk_warn, 80.0)
        self.assertEqual(args.disk_crit, 95.0)
        self.assertEqual(args.cpu_warn, 85.0)
        self.assertEqual(args.cpu_crit, 98.0)
        self.assertEqual(args.cpu_interval, 1.0)

    def test_json_flag(self):
        args = self.parser.parse_args(["--json"])
        self.assertTrue(args.json)

    def test_custom_thresholds(self):
        args = self.parser.parse_args([
            "--mem-warn", "70",
            "--mem-crit", "90",
            "--disk-warn", "75",
            "--cpu-interval", "2.5",
        ])
        self.assertEqual(args.mem_warn, 70.0)
        self.assertEqual(args.mem_crit, 90.0)
        self.assertEqual(args.disk_warn, 75.0)
        self.assertEqual(args.cpu_interval, 2.5)

    def test_output_flag(self):
        args = self.parser.parse_args(["--output", "report.json"])
        self.assertEqual(args.output, "report.json")

    def test_no_color_flag(self):
        args = self.parser.parse_args(["--no-color"])
        self.assertTrue(args.no_color)


# ---------------------------------------------------------------------------
# Tests: JSON report structure
# ---------------------------------------------------------------------------

class TestJsonReport(unittest.TestCase):

    def test_valid_json(self):
        collected = _make_collected()
        json_str = reporting.build_json_report(collected)
        # Should not raise
        data = json.loads(json_str)
        self.assertIsInstance(data, dict)

    def test_json_contains_required_keys(self):
        collected = _make_collected()
        data = json.loads(reporting.build_json_report(collected))
        for key in ("alpineguard_version", "generated_at", "system_info",
                    "memory", "disk", "cpu", "processes", "network",
                    "security", "alerts", "alert_summary"):
            self.assertIn(key, data, f"Missing key: {key}")

    def test_alerts_are_serialized_as_dicts(self):
        collected = _make_collected()
        data = json.loads(reporting.build_json_report(collected))
        for a in data["alerts"]:
            self.assertIsInstance(a, dict)
            self.assertIn("level", a)

    def test_generated_at_is_iso_string(self):
        from datetime import datetime
        collected = _make_collected()
        data = json.loads(reporting.build_json_report(collected))
        # Should parse without error
        ts = data["generated_at"]
        self.assertIsInstance(ts, str)
        self.assertGreater(len(ts), 10)

    def test_version_in_report(self):
        from alpineguard import __version__
        collected = _make_collected()
        data = json.loads(reporting.build_json_report(collected))
        self.assertEqual(data["alpineguard_version"], __version__)


# ---------------------------------------------------------------------------
# Tests: CLI run() function
# ---------------------------------------------------------------------------

class TestCliRun(unittest.TestCase):

    def _run_with_mock(self, argv=None, collected=None):
        if collected is None:
            collected = _make_collected()
        # Suppress stdout output in tests to avoid Windows cp1252 encoding
        # errors caused by Unicode block characters (█, ░) in progress bars.
        import io
        with patch.object(cli, "collect_all", return_value=collected):
            with patch("time.sleep"):
                with patch("sys.stdout", io.StringIO()):
                    return cli.run(argv or [])

    def test_run_returns_zero_on_ok(self):
        code = self._run_with_mock([])
        self.assertEqual(code, 0)

    def test_run_returns_one_on_error_status(self):
        collected = _make_collected()
        collected["alert_summary"]["overall_status"] = "ERROR"
        collected["alert_summary"]["error_count"] = 1
        collected["alerts"] = [Alert("ERROR", "memory", "Critical")]
        code = self._run_with_mock([], collected=collected)
        self.assertEqual(code, 1)

    def test_run_json_mode(self):
        """--json should produce valid JSON output."""
        import io
        buf = io.StringIO()
        collected = _make_collected()
        with patch.object(cli, "collect_all", return_value=collected):
            with patch("sys.stdout", buf):
                with patch("time.sleep"):
                    cli.run(["--json"])
        output = buf.getvalue()
        data = json.loads(output)
        self.assertIn("alpineguard_version", data)

    def test_run_output_file(self):
        """--output FILE should write JSON to the file."""
        fd, path = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        try:
            self._run_with_mock(["--output", path])
            with open(path, "r") as fh:
                data = json.load(fh)
            self.assertIn("alpineguard_version", data)
        finally:
            if os.path.exists(path):
                os.unlink(path)

    def test_collect_error_returns_exit_code_2(self):
        with patch.object(cli, "collect_all", side_effect=RuntimeError("boom")):
            code = cli.run([])
        self.assertEqual(code, 2)


if __name__ == "__main__":
    unittest.main()
