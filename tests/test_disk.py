"""
tests/test_disk.py — Unit tests for disk_monitor module.

os.statvfs() is not available on Windows, so disk_monitor.get_disk_usage()
is tested via a mock. calculate_utilization() is tested directly since it
is pure arithmetic.
"""

import unittest
from unittest.mock import patch, MagicMock
import os
import tempfile

from alpineguard import disk_monitor


# ---------------------------------------------------------------------------
# Tests: calculate_utilization
# ---------------------------------------------------------------------------

class TestCalculateUtilization(unittest.TestCase):

    def test_25_percent(self):
        pct = disk_monitor.calculate_utilization(100_000, 75_000)
        self.assertAlmostEqual(pct, 25.0, places=1)

    def test_zero_used(self):
        pct = disk_monitor.calculate_utilization(100_000, 100_000)
        self.assertAlmostEqual(pct, 0.0, places=1)

    def test_fully_used(self):
        pct = disk_monitor.calculate_utilization(100_000, 0)
        self.assertAlmostEqual(pct, 100.0, places=1)

    def test_raises_on_zero_total(self):
        with self.assertRaises(ValueError):
            disk_monitor.calculate_utilization(0, 0)

    def test_raises_on_negative_total(self):
        with self.assertRaises(ValueError):
            disk_monitor.calculate_utilization(-500, 100)

    def test_rounding(self):
        # 1/3 → 66.7%
        pct = disk_monitor.calculate_utilization(3, 1)
        self.assertEqual(pct, 66.7)


# ---------------------------------------------------------------------------
# Tests: get_disk_usage() with mocked statvfs
# ---------------------------------------------------------------------------

class _FakeStatVFS:
    """Minimal stand-in for the os.statvfs_result named tuple."""
    def __init__(self, frsize, blocks, bfree, bavail):
        self.f_frsize = frsize
        self.f_blocks = blocks
        self.f_bfree = bfree
        self.f_bavail = bavail


class TestGetDiskUsage(unittest.TestCase):
    """Patch disk_monitor.os.statvfs (not os.statvfs) because on Windows
    the os module is frozen and mock cannot add the missing attribute."""

    def test_normal_usage(self):
        # 10 GiB total, 3 GiB available → ~70% used
        frsize = 4096
        blocks = (10 * 1024 ** 3) // frsize
        bavail = (3 * 1024 ** 3) // frsize

        with patch("alpineguard.disk_monitor._statvfs",
                   return_value=_FakeStatVFS(frsize, blocks, 0, bavail)):
            result = disk_monitor.get_disk_usage("/")

        self.assertIsNone(result["error"])
        self.assertAlmostEqual(result["total_gib"], 10.0, delta=0.1)
        self.assertAlmostEqual(result["available_gib"], 3.0, delta=0.1)
        self.assertAlmostEqual(result["utilization_pct"], 70.0, delta=0.5)

    def test_statvfs_not_available(self):
        """On Windows os.statvfs doesn't exist — test graceful handling."""
        with patch("alpineguard.disk_monitor._statvfs",
                   side_effect=AttributeError("not available")):
            result = disk_monitor.get_disk_usage("/")

        self.assertIsNotNone(result["error"])
        self.assertEqual(result["total_bytes"], 0)
        self.assertEqual(result["utilization_pct"], 0.0)

    def test_oserror_on_missing_mountpoint(self):
        with patch("alpineguard.disk_monitor._statvfs",
                   side_effect=OSError(2, "No such file or directory")):
            result = disk_monitor.get_disk_usage("/nonexistent")

        self.assertIsNotNone(result["error"])
        self.assertEqual(result["mountpoint"], "/nonexistent")

    def test_full_disk(self):
        frsize = 512
        blocks = 1000
        bavail = 0

        with patch("alpineguard.disk_monitor._statvfs",
                   return_value=_FakeStatVFS(frsize, blocks, 0, bavail)):
            result = disk_monitor.get_disk_usage("/")

        self.assertAlmostEqual(result["utilization_pct"], 100.0, places=1)
        self.assertEqual(result["available_bytes"], 0)


# ---------------------------------------------------------------------------
# Tests: get_all_mountpoints()
# ---------------------------------------------------------------------------

SAMPLE_MOUNTS = """\
sysfs /sys sysfs rw,nosuid,nodev,noexec,relatime 0 0
proc /proc proc rw,nosuid,nodev,noexec,relatime 0 0
devtmpfs /dev devtmpfs rw,nosuid,size=10240k,nr_inodes=4096,mode=755 0 0
/dev/sda1 / ext4 rw,relatime 0 0
/dev/sda2 /home ext4 rw,relatime 0 0
tmpfs /run tmpfs rw,nosuid,nodev,mode=755 0 0
"""


class TestGetAllMountpoints(unittest.TestCase):

    def test_filters_pseudo_filesystems(self):
        fd, path = tempfile.mkstemp()
        try:
            with os.fdopen(fd, "w") as fh:
                fh.write(SAMPLE_MOUNTS)
            result = disk_monitor.get_all_mountpoints(proc_mounts=path)
        finally:
            os.unlink(path)

        # Only real filesystems should appear
        self.assertIn("/", result)
        self.assertIn("/home", result)
        # Pseudo filesystems should be excluded
        self.assertNotIn("/sys", result)
        self.assertNotIn("/proc", result)
        self.assertNotIn("/dev", result)
        self.assertNotIn("/run", result)

    def test_missing_mounts_file_falls_back_to_root(self):
        result = disk_monitor.get_all_mountpoints(proc_mounts="/nonexistent/mounts")
        self.assertEqual(result, ["/"])


if __name__ == "__main__":
    unittest.main()
