"""
tests/test_memory.py — Unit tests for memory_monitor module.

All tests use temporary files or in-memory data so they run on
Windows without requiring /proc/meminfo.
"""

import os
import tempfile
import unittest

from alpineguard import memory_monitor


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

TYPICAL_MEMINFO = """\
MemTotal:        2048000 kB
MemFree:          512000 kB
MemAvailable:     768000 kB
Buffers:          128000 kB
Cached:           256000 kB
SwapCached:            0 kB
SwapTotal:        512000 kB
SwapFree:         256000 kB
"""

MINIMAL_MEMINFO = """\
MemTotal:        1024000 kB
MemAvailable:    1024000 kB
"""

# MemAvailable missing — should fall back to MemFree
NO_MEMAVAILABLE = """\
MemTotal:        1024000 kB
MemFree:          512000 kB
SwapTotal:             0 kB
SwapFree:              0 kB
"""

MALFORMED_MEMINFO = """\
MemTotal: NOT_A_NUMBER kB
MemAvailable: also_bad
"""

EMPTY_MEMINFO = ""


def _write_temp(content: str) -> str:
    """Write *content* to a temporary file and return its path."""
    fd, path = tempfile.mkstemp(suffix=".meminfo")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(content)
    except Exception:
        os.close(fd)
        raise
    return path


# ---------------------------------------------------------------------------
# Tests: _read_meminfo
# ---------------------------------------------------------------------------

class TestReadMeminfo(unittest.TestCase):

    def test_reads_typical_meminfo(self):
        path = _write_temp(TYPICAL_MEMINFO)
        try:
            result = memory_monitor._read_meminfo(path)
        finally:
            os.unlink(path)

        self.assertIsNotNone(result)
        self.assertEqual(result["MemTotal"], 2048000 * 1024)
        self.assertEqual(result["MemAvailable"], 768000 * 1024)
        self.assertEqual(result["SwapTotal"], 512000 * 1024)
        self.assertEqual(result["SwapFree"], 256000 * 1024)

    def test_returns_none_for_missing_file(self):
        result = memory_monitor._read_meminfo("/nonexistent/path/meminfo")
        self.assertIsNone(result)

    def test_skips_malformed_lines(self):
        path = _write_temp(MALFORMED_MEMINFO)
        try:
            result = memory_monitor._read_meminfo(path)
        finally:
            os.unlink(path)
        # When ALL lines have non-integer values, the dict is empty.
        # _read_meminfo returns None for an empty dict.
        # This is the expected graceful-degradation behavior.
        self.assertIsNone(result)

    def test_empty_file_returns_none(self):
        path = _write_temp(EMPTY_MEMINFO)
        try:
            result = memory_monitor._read_meminfo(path)
        finally:
            os.unlink(path)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# Tests: calculate_utilization
# ---------------------------------------------------------------------------

class TestCalculateUtilization(unittest.TestCase):

    def test_50_percent(self):
        total = 2_000_000
        available = 1_000_000
        pct = memory_monitor.calculate_utilization(total, available)
        self.assertAlmostEqual(pct, 50.0, places=1)

    def test_zero_used(self):
        pct = memory_monitor.calculate_utilization(1_000_000, 1_000_000)
        self.assertAlmostEqual(pct, 0.0, places=1)

    def test_fully_used(self):
        pct = memory_monitor.calculate_utilization(1_000_000, 0)
        self.assertAlmostEqual(pct, 100.0, places=1)

    def test_raises_on_zero_total(self):
        with self.assertRaises(ValueError):
            memory_monitor.calculate_utilization(0, 0)

    def test_raises_on_negative_total(self):
        with self.assertRaises(ValueError):
            memory_monitor.calculate_utilization(-1, 0)

    def test_result_rounds_to_one_decimal(self):
        # 1/3 → 33.3%
        pct = memory_monitor.calculate_utilization(3, 2)
        self.assertEqual(pct, 33.3)


# ---------------------------------------------------------------------------
# Tests: collect()
# ---------------------------------------------------------------------------

class TestCollect(unittest.TestCase):

    def test_collect_typical(self):
        path = _write_temp(TYPICAL_MEMINFO)
        try:
            result = memory_monitor.collect(meminfo_path=path)
        finally:
            os.unlink(path)

        self.assertIsNone(result["error"])
        self.assertGreater(result["total_bytes"], 0)
        self.assertGreater(result["total_mib"], 0)
        self.assertGreaterEqual(result["utilization_pct"], 0.0)
        self.assertLessEqual(result["utilization_pct"], 100.0)

    def test_collect_missing_file_returns_error(self):
        result = memory_monitor.collect(meminfo_path="/no/such/file")
        self.assertIsNotNone(result["error"])
        self.assertEqual(result["total_bytes"], 0)

    def test_collect_no_memavailable_falls_back_to_memfree(self):
        path = _write_temp(NO_MEMAVAILABLE)
        try:
            result = memory_monitor.collect(meminfo_path=path)
        finally:
            os.unlink(path)

        self.assertIsNone(result["error"])
        # MemFree was 512 000 kB = 512 MiB; used = total - free = 512 MiB
        self.assertAlmostEqual(result["utilization_pct"], 50.0, places=1)

    def test_collect_swap_not_configured(self):
        path = _write_temp(MINIMAL_MEMINFO)
        try:
            result = memory_monitor.collect(meminfo_path=path)
        finally:
            os.unlink(path)
        self.assertEqual(result["swap_total_bytes"], 0)

    def test_collect_swap_usage(self):
        path = _write_temp(TYPICAL_MEMINFO)
        try:
            result = memory_monitor.collect(meminfo_path=path)
        finally:
            os.unlink(path)
        # SwapTotal=512000 kB, SwapFree=256000 kB → used=256000 kB
        self.assertEqual(result["swap_used_bytes"], 256000 * 1024)


if __name__ == "__main__":
    unittest.main()
