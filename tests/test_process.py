"""
tests/test_process.py — Unit tests for alpineguard/process_monitor.py.

All tests operate on synthetic procfs directory fixtures using tempfile,
requiring no real /proc and passing identically on Windows and Linux.
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from alpineguard import process_monitor


SAMPLE_STATUS_1 = """\
Name:\tinit
Umask:\t0000
State:\tS (sleeping)
Tgid:\t1
Ngid:\t0
Pid:\t1
PPid:\t0
Uid:\t0\t0\t0\t0
Gid:\t0\t0\t0\t0
FDSize:\t64
VmRSS:\t  4096 kB
"""

SAMPLE_STATUS_2 = """\
Name:\tpython3
State:\tR (running)
Pid:\t42
PPid:\t1
Uid:\t1000\t1000\t1000\t1000
VmRSS:\t 20480 kB
"""

SAMPLE_STAT_1 = "1 (init) S 0 1 1 0 -1 4194304 100 0 0 0 10 20 0 0 20 0 1 0 100 100000 100"
SAMPLE_STAT_2 = "42 (python3) R 1 42 42 0 -1 4194304 200 0 0 0 50 70 0 0 20 0 1 0 200 200000 200"


class TestListPids(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_finds_numeric_pids(self):
        os.makedirs(os.path.join(self.test_dir, "1"))
        os.makedirs(os.path.join(self.test_dir, "42"))
        os.makedirs(os.path.join(self.test_dir, "999"))
        os.makedirs(os.path.join(self.test_dir, "net"))  # non-numeric, ignore
        with open(os.path.join(self.test_dir, "stat"), "w") as f:
            f.write("cpu 1 2 3\n")

        pids = process_monitor._list_pids(self.test_dir)
        self.assertEqual(pids, [1, 42, 999])

    def test_empty_or_nonexistent_dir(self):
        pids = process_monitor._list_pids(os.path.join(self.test_dir, "nonexistent"))
        self.assertEqual(pids, [])


class TestParseStatus(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_parses_normal_status(self):
        p1 = os.path.join(self.test_dir, "1")
        os.makedirs(p1)
        with open(os.path.join(p1, "status"), "w") as f:
            f.write(SAMPLE_STATUS_1)

        info = process_monitor._parse_status(1, self.test_dir)
        self.assertIsNotNone(info)
        self.assertEqual(info["pid"], 1)
        self.assertEqual(info["name"], "init")
        self.assertEqual(info["state"], "S")
        self.assertEqual(info["uid"], 0)
        self.assertEqual(info["rss_bytes"], 4096 * 1024)
        self.assertEqual(info["rss_mib"], 4.0)

    def test_missing_status_returns_none(self):
        info = process_monitor._parse_status(999, self.test_dir)
        self.assertIsNone(info)


class TestParseCmdline(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_nul_delimited_cmdline(self):
        p42 = os.path.join(self.test_dir, "42")
        os.makedirs(p42)
        with open(os.path.join(p42, "cmdline"), "wb") as f:
            f.write(b"python3\x00-m\x00alpineguard\x00")

        cmd = process_monitor._parse_cmdline(42, self.test_dir)
        self.assertEqual(cmd, "python3 -m alpineguard")

    def test_empty_cmdline_returns_empty_string(self):
        p1 = os.path.join(self.test_dir, "1")
        os.makedirs(p1)
        with open(os.path.join(p1, "cmdline"), "wb") as f:
            f.write(b"")

        cmd = process_monitor._parse_cmdline(1, self.test_dir)
        self.assertEqual(cmd, "")


class TestReadProcStatTicks(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_reads_valid_stat_ticks(self):
        p42 = os.path.join(self.test_dir, "42")
        os.makedirs(p42)
        with open(os.path.join(p42, "stat"), "w") as f:
            f.write(SAMPLE_STAT_2)

        ticks = process_monitor._read_proc_stat_ticks(42, self.test_dir)
        self.assertIsNotNone(ticks)
        # utime=50, stime=70
        self.assertEqual(ticks, (50, 70))

    def test_handles_process_names_with_spaces_and_parentheses(self):
        p7 = os.path.join(self.test_dir, "7")
        os.makedirs(p7)
        with open(os.path.join(p7, "stat"), "w") as f:
            f.write("7 (worker (pool) thread) S 1 7 7 0 -1 4194304 0 0 0 0 15 25 0 0 20 0 1 0 0 0 0")

        ticks = process_monitor._read_proc_stat_ticks(7, self.test_dir)
        self.assertEqual(ticks, (15, 25))


class TestCalculateProcessCpu(unittest.TestCase):
    def test_returns_none_without_history(self):
        result = process_monitor.calculate_process_cpu(
            pid=42,
            prev_snapshots=None,
            prev_total_ticks=None,
            curr_total_ticks=None,
        )
        self.assertIsNone(result)

    def test_calculates_cpu_percentage(self):
        with patch("alpineguard.process_monitor._read_proc_stat_ticks", return_value=(30, 20)):
            # curr_proc = 50. prev_proc = 30 -> delta_proc = 20
            # prev_total = 1000, curr_total = 1100 -> delta_total = 100
            # 20 / 100 * 100 = 20.0%
            pct = process_monitor.calculate_process_cpu(
                pid=42,
                prev_snapshots={42: 30},
                prev_total_ticks=1000,
                curr_total_ticks=1100,
            )
            self.assertEqual(pct, 20.0)


class TestProcessCollect(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        p1 = os.path.join(self.test_dir, "1")
        p2 = os.path.join(self.test_dir, "42")
        os.makedirs(p1)
        os.makedirs(p2)
        with open(os.path.join(p1, "status"), "w") as f:
            f.write(SAMPLE_STATUS_1)
        with open(os.path.join(p1, "stat"), "w") as f:
            f.write(SAMPLE_STAT_1)
        with open(os.path.join(p2, "status"), "w") as f:
            f.write(SAMPLE_STATUS_2)
        with open(os.path.join(p2, "stat"), "w") as f:
            f.write(SAMPLE_STAT_2)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_collect_returns_valid_structure(self):
        result = process_monitor.collect(proc_dir=self.test_dir, top_n=10)
        self.assertIsNone(result["error"])
        self.assertEqual(result["total_visible"], 2)
        self.assertEqual(len(result["processes"]), 2)
        # Sorted descending by RSS: python3 (20MB) before init (4MB)
        self.assertEqual(result["processes"][0]["name"], "python3")
        self.assertEqual(result["processes"][1]["name"], "init")


if __name__ == "__main__":
    unittest.main()
