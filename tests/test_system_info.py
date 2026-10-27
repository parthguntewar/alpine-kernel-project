"""
tests/test_system_info.py — Unit tests for system_info module.

Uses temporary files to simulate /etc/os-release, /proc/version,
/proc/uptime, and /proc/cpuinfo without needing a Linux environment.
"""

import os
import tempfile
import unittest

from alpineguard import system_info


def _write_temp(content: str) -> str:
    fd, path = tempfile.mkstemp()
    with os.fdopen(fd, "w") as fh:
        fh.write(content)
    return path


# ---------------------------------------------------------------------------
# Tests: _parse_os_release
# ---------------------------------------------------------------------------

class TestParseOsRelease(unittest.TestCase):

    def test_typical_alpine(self):
        content = (
            'ID=alpine\n'
            'VERSION_ID=3.24.0\n'
            'PRETTY_NAME="Alpine Linux v3.24"\n'
        )
        result = system_info._parse_os_release(content)
        self.assertEqual(result["ID"], "alpine")
        self.assertEqual(result["VERSION_ID"], "3.24.0")
        self.assertEqual(result["PRETTY_NAME"], "Alpine Linux v3.24")

    def test_strips_quotes(self):
        content = 'NAME="Ubuntu"\nVERSION_ID="22.04"\n'
        result = system_info._parse_os_release(content)
        self.assertEqual(result["NAME"], "Ubuntu")
        self.assertEqual(result["VERSION_ID"], "22.04")

    def test_ignores_comments(self):
        content = '# This is a comment\nID=alpine\n'
        result = system_info._parse_os_release(content)
        self.assertNotIn("# This is a comment", result)
        self.assertEqual(result["ID"], "alpine")

    def test_empty_content(self):
        result = system_info._parse_os_release("")
        self.assertEqual(result, {})


# ---------------------------------------------------------------------------
# Tests: get_distro_info
# ---------------------------------------------------------------------------

class TestGetDistroInfo(unittest.TestCase):

    def test_reads_os_release(self):
        content = 'ID=alpine\nVERSION_ID=3.24.0\nPRETTY_NAME="Alpine Linux v3.24"\n'
        path = _write_temp(content)
        try:
            # Monkey-patch the function to use our temp file
            original = system_info._read_file
            def patched(p):
                if p in ("/etc/os-release", "/usr/lib/os-release"):
                    return original(path)
                return original(p)

            import unittest.mock as mock
            with mock.patch.object(system_info, "_read_file", side_effect=patched):
                result = system_info.get_distro_info()
        finally:
            os.unlink(path)

        self.assertEqual(result["id"], "alpine")
        self.assertIn("Alpine", result["name"])


# ---------------------------------------------------------------------------
# Tests: get_kernel_version
# ---------------------------------------------------------------------------

class TestGetKernelVersion(unittest.TestCase):

    def test_parses_proc_version(self):
        content = "Linux version 6.1.58-0-lts (buildozer@build-3-22-x86_64) ...\n"
        path = _write_temp(content)
        try:
            import unittest.mock as mock
            with mock.patch.object(system_info, "_read_file", return_value=content):
                version = system_info.get_kernel_version()
        finally:
            os.unlink(path)
        self.assertEqual(version, "6.1.58-0-lts")

    def test_missing_proc_version_falls_back(self):
        import unittest.mock as mock
        with mock.patch.object(system_info, "_read_file", return_value=None):
            version = system_info.get_kernel_version()
        # Should return something (platform.release()) not raise
        self.assertIsInstance(version, str)

    def test_malformed_proc_version(self):
        import unittest.mock as mock
        with mock.patch.object(system_info, "_read_file", return_value="no version here"):
            version = system_info.get_kernel_version()
        self.assertIsInstance(version, str)


# ---------------------------------------------------------------------------
# Tests: get_uptime
# ---------------------------------------------------------------------------

class TestGetUptime(unittest.TestCase):

    def test_parses_uptime(self):
        import unittest.mock as mock
        # 2 days, 3 hours, 15 minutes, 30 seconds
        seconds = 2 * 86400 + 3 * 3600 + 15 * 60 + 30
        content = f"{seconds}.00 1234.56\n"
        with mock.patch.object(system_info, "_read_file", return_value=content):
            result = system_info.get_uptime()

        self.assertEqual(result["days"], 2)
        self.assertEqual(result["hours"], 3)
        self.assertEqual(result["minutes"], 15)
        self.assertIn("2 days", result["human"])
        self.assertIn("3 hours", result["human"])

    def test_missing_file_returns_unavailable(self):
        import unittest.mock as mock
        with mock.patch.object(system_info, "_read_file", return_value=None):
            result = system_info.get_uptime()
        self.assertEqual(result["human"], "unavailable")
        self.assertIsNone(result["total_seconds"])

    def test_sub_one_minute_uptime(self):
        import unittest.mock as mock
        content = "45.00 12.00\n"
        with mock.patch.object(system_info, "_read_file", return_value=content):
            result = system_info.get_uptime()
        self.assertIn("second", result["human"])


# ---------------------------------------------------------------------------
# Tests: get_cpu_info
# ---------------------------------------------------------------------------

SAMPLE_CPUINFO = """\
processor       : 0
model name      : Intel(R) Core(TM) i5-8250U CPU @ 1.60GHz
cpu MHz         : 1600.000
cache size      : 6144 KB

processor       : 1
model name      : Intel(R) Core(TM) i5-8250U CPU @ 1.60GHz
cpu MHz         : 1600.000
"""


class TestGetCpuInfo(unittest.TestCase):

    def test_parses_cpu_info(self):
        import unittest.mock as mock
        with mock.patch.object(system_info, "_read_file", return_value=SAMPLE_CPUINFO):
            result = system_info.get_cpu_info()

        self.assertIn("i5-8250U", result["model_name"])
        self.assertEqual(result["num_cores"], 2)

    def test_missing_cpuinfo_returns_defaults(self):
        import unittest.mock as mock
        with mock.patch.object(system_info, "_read_file", return_value=None):
            result = system_info.get_cpu_info()
        self.assertIsInstance(result["architecture"], str)


if __name__ == "__main__":
    unittest.main()
