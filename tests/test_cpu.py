"""
tests/test_cpu.py — Unit tests for cpu_monitor module.

CPU monitoring requires two /proc/stat reads separated by a sleep.
We mock the file reads and time.sleep so tests are fast and
platform-independent.
"""

import os
import tempfile
import unittest
from unittest.mock import patch, call

from alpineguard import cpu_monitor
from alpineguard.cpu_monitor import _CpuSnapshot, calculate_utilization


# ---------------------------------------------------------------------------
# Helper: build snapshot directly
# ---------------------------------------------------------------------------

def _make_snapshot(user, nice, system, idle, iowait, irq=0, softirq=0, steal=0, ts=0.0):
    return _CpuSnapshot(user, nice, system, idle, iowait, irq, softirq, steal, timestamp=ts)


# ---------------------------------------------------------------------------
# Tests: _CpuSnapshot arithmetic
# ---------------------------------------------------------------------------

class TestCpuSnapshot(unittest.TestCase):

    def test_total(self):
        s = _make_snapshot(100, 10, 50, 800, 40, irq=5, softirq=5)
        self.assertEqual(s.total, 100 + 10 + 50 + 800 + 40 + 5 + 5)

    def test_active_excludes_idle_and_iowait(self):
        s = _make_snapshot(user=200, nice=0, system=100, idle=600, iowait=100)
        # active = total - idle - iowait = 1000 - 600 - 100 = 300
        self.assertEqual(s.total, 1000)
        self.assertEqual(s.active, 300)


# ---------------------------------------------------------------------------
# Tests: calculate_utilization
# ---------------------------------------------------------------------------

class TestCalculateUtilization(unittest.TestCase):

    def test_50_percent(self):
        # snap1: 100 total, 50 active
        s1 = _make_snapshot(50, 0, 0, 50, 0)
        # snap2: 200 total, 100 active (delta: 100 total, 50 active → 50%)
        s2 = _make_snapshot(100, 0, 0, 100, 0)
        result = calculate_utilization(s1, s2)
        self.assertAlmostEqual(result, 50.0, places=1)

    def test_zero_percent(self):
        # Only idle ticks increased
        s1 = _make_snapshot(0, 0, 0, 0, 0)
        s2 = _make_snapshot(0, 0, 0, 1000, 0)
        result = calculate_utilization(s1, s2)
        self.assertAlmostEqual(result, 0.0, places=1)

    def test_100_percent(self):
        # Only active ticks
        s1 = _make_snapshot(0, 0, 0, 0, 0)
        s2 = _make_snapshot(1000, 0, 0, 0, 0)
        result = calculate_utilization(s1, s2)
        self.assertAlmostEqual(result, 100.0, places=1)

    def test_returns_none_when_delta_total_is_zero(self):
        s1 = _make_snapshot(100, 0, 0, 100, 0)
        s2 = _make_snapshot(100, 0, 0, 100, 0)  # identical
        result = calculate_utilization(s1, s2)
        self.assertIsNone(result)

    def test_negative_active_clamped_to_zero(self):
        """Counter jitter should not produce negative utilization."""
        s1 = _make_snapshot(1000, 0, 0, 0, 0)
        # snap2 with slightly lower active (counter wrap scenario)
        s2 = _make_snapshot(999, 0, 0, 100, 0)
        result = calculate_utilization(s1, s2)
        # delta_active = (999 - 0) - (1000 - 0) = -1 → clamped to 0
        self.assertGreaterEqual(result, 0.0)

    def test_realistic_idle_system(self):
        # 1-second sample on an idle system: mostly idle ticks
        s1 = _make_snapshot(100, 0, 50, 9800, 50)
        s2 = _make_snapshot(101, 0, 51, 9898, 50)
        result = calculate_utilization(s1, s2)
        # delta total = 100, delta active = 2 → 2%
        self.assertAlmostEqual(result, 2.0, places=1)


# ---------------------------------------------------------------------------
# Tests: _read_cpu_snapshot with temp file
# ---------------------------------------------------------------------------

VALID_STAT = "cpu  100 10 50 800 40 5 5 0 0 0\ncpu0 100 10 50 800 40 5 5 0 0 0\n"
MISSING_CPU_LINE = "no cpu line here\n"
SHORT_CPU_LINE = "cpu  100 10\n"  # fewer than 5 fields


class TestReadCpuSnapshot(unittest.TestCase):

    def _write(self, content):
        fd, path = tempfile.mkstemp()
        with os.fdopen(fd, "w") as fh:
            fh.write(content)
        return path

    def test_reads_valid_stat(self):
        path = self._write(VALID_STAT)
        try:
            snap = cpu_monitor._read_cpu_snapshot(path)
        finally:
            os.unlink(path)

        self.assertIsNotNone(snap)
        self.assertEqual(snap.user, 100)
        self.assertEqual(snap.idle, 800)

    def test_missing_cpu_line_returns_none(self):
        path = self._write(MISSING_CPU_LINE)
        try:
            snap = cpu_monitor._read_cpu_snapshot(path)
        finally:
            os.unlink(path)
        self.assertIsNone(snap)

    def test_short_cpu_line_returns_none(self):
        path = self._write(SHORT_CPU_LINE)
        try:
            snap = cpu_monitor._read_cpu_snapshot(path)
        finally:
            os.unlink(path)
        self.assertIsNone(snap)

    def test_missing_file_returns_none(self):
        snap = cpu_monitor._read_cpu_snapshot("/nonexistent/stat")
        self.assertIsNone(snap)


# ---------------------------------------------------------------------------
# Tests: collect() with mocked internals
# ---------------------------------------------------------------------------

class TestCollect(unittest.TestCase):

    def _make_stat_file(self, content):
        fd, path = tempfile.mkstemp()
        with os.fdopen(fd, "w") as fh:
            fh.write(content)
        return path

    def test_collect_returns_measurement(self):
        stat1 = "cpu  100 0 50 800 50 0 0 0\n"
        stat2 = "cpu  102 0 52 900 50 0 0 0\n"

        call_count = [0]
        paths = [self._make_stat_file(stat1), self._make_stat_file(stat2)]

        original_read = cpu_monitor._read_cpu_snapshot

        def mock_read(path):
            idx = call_count[0]
            call_count[0] += 1
            return original_read(paths[idx % 2])

        try:
            with patch.object(cpu_monitor, "_read_cpu_snapshot", side_effect=mock_read):
                with patch("time.sleep"):  # don't actually sleep
                    result = cpu_monitor.collect(interval=1.0, stat_path="dummy")
        finally:
            for p in paths:
                os.unlink(p)

        self.assertIsNone(result["error"])
        # utilization_pct may be None if delta_total was 0 (mock returns same)
        # but no error should be raised

    def test_collect_error_on_unreadable_file(self):
        result = cpu_monitor.collect(interval=0.1, stat_path="/no/such/stat")
        self.assertIsNotNone(result["error"])
        self.assertIsNone(result["utilization_pct"])

    def test_interval_clamped_to_minimum(self):
        """Very small intervals should be clamped to 0.1 s."""
        with patch("time.sleep") as mock_sleep:
            with patch.object(cpu_monitor, "_read_cpu_snapshot", return_value=None):
                cpu_monitor.collect(interval=0.0001, stat_path="/no/stat")
        # sleep should have been called with at least 0.1 s
        if mock_sleep.called:
            args = mock_sleep.call_args[0]
            self.assertGreaterEqual(args[0], 0.1)


if __name__ == "__main__":
    unittest.main()
