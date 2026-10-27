"""
tests/test_alerts.py — Unit tests for the alerts module.

Tests cover:
  - Memory alert threshold evaluation
  - Disk alert threshold evaluation
  - CPU alert threshold evaluation
  - Security alert mapping
  - Alert summarization
  - Alert.to_dict() serialization
"""

import unittest

from alpineguard import alerts
from alpineguard.alerts import Alert, evaluate_memory, evaluate_disk, evaluate_cpu, summarize


# ---------------------------------------------------------------------------
# Helpers: build minimal data dicts for each collector
# ---------------------------------------------------------------------------

def _mem(util_pct, used_mib=500, total_mib=1000, avail_mib=500, error=None):
    return {
        "utilization_pct": util_pct,
        "used_mib": used_mib,
        "total_mib": total_mib,
        "available_mib": avail_mib,
        "used_bytes": used_mib * 1024 ** 2,
        "total_bytes": total_mib * 1024 ** 2,
        "available_bytes": avail_mib * 1024 ** 2,
        "swap_total_bytes": 0,
        "swap_used_bytes": 0,
        "swap_total_mib": 0.0,
        "swap_used_mib": 0.0,
        "error": error,
    }


def _disk(util_pct, used_gib=7.0, total_gib=10.0, avail_gib=3.0, mp="/", error=None):
    return {
        "mountpoint": mp,
        "utilization_pct": util_pct,
        "used_gib": used_gib,
        "total_gib": total_gib,
        "available_gib": avail_gib,
        "used_bytes": int(used_gib * 1024 ** 3),
        "total_bytes": int(total_gib * 1024 ** 3),
        "available_bytes": int(avail_gib * 1024 ** 3),
        "error": error,
    }


def _cpu(util_pct, error=None):
    return {
        "utilization_pct": util_pct,
        "interval_used": 1.0,
        "error": error,
    }


# ---------------------------------------------------------------------------
# Tests: evaluate_memory
# ---------------------------------------------------------------------------

class TestEvaluateMemory(unittest.TestCase):

    def test_ok_below_warning(self):
        alert = evaluate_memory(_mem(50.0), warning_pct=80.0, error_pct=95.0)
        self.assertEqual(alert.level, "OK")
        self.assertEqual(alert.category, "memory")

    def test_warning_at_threshold(self):
        alert = evaluate_memory(_mem(80.0), warning_pct=80.0, error_pct=95.0)
        self.assertEqual(alert.level, "WARNING")

    def test_warning_just_above_threshold(self):
        alert = evaluate_memory(_mem(82.5), warning_pct=80.0, error_pct=95.0)
        self.assertEqual(alert.level, "WARNING")

    def test_error_at_critical_threshold(self):
        alert = evaluate_memory(_mem(95.0), warning_pct=80.0, error_pct=95.0)
        self.assertEqual(alert.level, "ERROR")

    def test_error_above_critical_threshold(self):
        alert = evaluate_memory(_mem(99.9), warning_pct=80.0, error_pct=95.0)
        self.assertEqual(alert.level, "ERROR")

    def test_error_when_data_unavailable(self):
        alert = evaluate_memory(_mem(0.0, error="Cannot read /proc/meminfo"))
        self.assertEqual(alert.level, "ERROR")
        self.assertIn("unavailable", alert.message.lower())

    def test_custom_thresholds_lower(self):
        """Custom lower thresholds should trigger warnings earlier."""
        alert = evaluate_memory(_mem(55.0), warning_pct=50.0, error_pct=70.0)
        self.assertEqual(alert.level, "WARNING")

    def test_recommendation_present_on_warning(self):
        alert = evaluate_memory(_mem(85.0))
        self.assertNotEqual(alert.recommendation, "")

    def test_no_recommendation_on_ok(self):
        alert = evaluate_memory(_mem(40.0))
        self.assertEqual(alert.recommendation, "")


# ---------------------------------------------------------------------------
# Tests: evaluate_disk
# ---------------------------------------------------------------------------

class TestEvaluateDisk(unittest.TestCase):

    def test_ok_below_warning(self):
        alert = evaluate_disk(_disk(60.0))
        self.assertEqual(alert.level, "OK")

    def test_warning_at_threshold(self):
        alert = evaluate_disk(_disk(80.0), warning_pct=80.0, error_pct=95.0)
        self.assertEqual(alert.level, "WARNING")

    def test_error_at_critical(self):
        alert = evaluate_disk(_disk(95.0), warning_pct=80.0, error_pct=95.0)
        self.assertEqual(alert.level, "ERROR")

    def test_error_when_data_unavailable(self):
        alert = evaluate_disk(_disk(0.0, error="Cannot stat /"))
        self.assertEqual(alert.level, "ERROR")

    def test_mountpoint_in_message(self):
        alert = evaluate_disk(_disk(90.0, mp="/home"), mountpoint="/home")
        self.assertIn("/home", alert.message)


# ---------------------------------------------------------------------------
# Tests: evaluate_cpu
# ---------------------------------------------------------------------------

class TestEvaluateCpu(unittest.TestCase):

    def test_ok_below_warning(self):
        alert = evaluate_cpu(_cpu(30.0))
        self.assertEqual(alert.level, "OK")

    def test_warning_at_threshold(self):
        alert = evaluate_cpu(_cpu(85.0), warning_pct=85.0, error_pct=98.0)
        self.assertEqual(alert.level, "WARNING")

    def test_error_at_critical(self):
        alert = evaluate_cpu(_cpu(98.0), warning_pct=85.0, error_pct=98.0)
        self.assertEqual(alert.level, "ERROR")

    def test_none_util_returns_ok_with_note(self):
        """When CPU util is None (first sample), return OK with informational message."""
        alert = evaluate_cpu(_cpu(None))
        self.assertEqual(alert.level, "OK")
        self.assertIn("sample", alert.message.lower())

    def test_error_data_unavailable(self):
        alert = evaluate_cpu(_cpu(None, error="Cannot read /proc/stat"))
        self.assertEqual(alert.level, "ERROR")


# ---------------------------------------------------------------------------
# Tests: Alert.to_dict()
# ---------------------------------------------------------------------------

class TestAlertToDict(unittest.TestCase):

    def test_to_dict_fields(self):
        a = Alert(
            level="WARNING",
            category="memory",
            message="Memory warning",
            value=85.0,
            threshold=80.0,
            recommendation="Free memory",
        )
        d = a.to_dict()
        self.assertEqual(d["level"], "WARNING")
        self.assertEqual(d["category"], "memory")
        self.assertEqual(d["value"], 85.0)
        self.assertEqual(d["threshold"], 80.0)
        self.assertEqual(d["recommendation"], "Free memory")

    def test_is_ok(self):
        a = Alert("OK", "cpu", "All good")
        self.assertTrue(a.is_ok())
        self.assertFalse(a.is_warning())
        self.assertFalse(a.is_error())

    def test_is_warning(self):
        a = Alert("WARNING", "disk", "Almost full")
        self.assertTrue(a.is_warning())

    def test_is_error(self):
        a = Alert("ERROR", "memory", "Critical")
        self.assertTrue(a.is_error())


# ---------------------------------------------------------------------------
# Tests: summarize()
# ---------------------------------------------------------------------------

class TestSummarize(unittest.TestCase):

    def test_all_ok(self):
        alerts_list = [Alert("OK", "mem", "ok"), Alert("OK", "cpu", "ok")]
        s = summarize(alerts_list)
        self.assertEqual(s["overall_status"], "OK")
        self.assertEqual(s["ok_count"], 2)
        self.assertEqual(s["warning_count"], 0)
        self.assertEqual(s["error_count"], 0)

    def test_one_warning(self):
        alerts_list = [Alert("OK", "mem", "ok"), Alert("WARNING", "disk", "warn")]
        s = summarize(alerts_list)
        self.assertEqual(s["overall_status"], "WARNING")
        self.assertEqual(s["warning_count"], 1)

    def test_error_dominates(self):
        alerts_list = [
            Alert("OK", "mem", "ok"),
            Alert("WARNING", "disk", "warn"),
            Alert("ERROR", "cpu", "err"),
        ]
        s = summarize(alerts_list)
        self.assertEqual(s["overall_status"], "ERROR")
        self.assertEqual(s["error_count"], 1)

    def test_empty_list(self):
        s = summarize([])
        self.assertEqual(s["overall_status"], "OK")
        self.assertEqual(s["total"], 0)

    def test_total_count(self):
        alerts_list = [Alert("OK", "a", ""), Alert("WARNING", "b", ""), Alert("ERROR", "c", "")]
        s = summarize(alerts_list)
        self.assertEqual(s["total"], 3)


if __name__ == "__main__":
    unittest.main()
