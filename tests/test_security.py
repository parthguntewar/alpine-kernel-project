"""
tests/test_security.py — Unit tests for alpineguard/security_checks.py.

Tests failed SSH authentication detection, risky listening port checks,
world-writable permissions inspection, and unified security collection.
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from alpineguard import security_checks


SAMPLE_AUTH_LOG_CLEAN = """\
Oct 27 10:00:00 alpine sshd[100]: Server listening on 0.0.0.0 port 22.
Oct 27 10:01:00 alpine sshd[105]: Accepted publickey for parth from 192.168.1.50 port 54321 ssh2
"""

SAMPLE_AUTH_LOG_FAILED = """\
Oct 27 10:00:00 alpine sshd[100]: Server listening on 0.0.0.0 port 22.
Oct 27 10:02:15 alpine sshd[110]: Failed password for root from 203.0.113.195 port 42100 ssh2
Oct 27 10:02:18 alpine sshd[111]: Failed password for invalid user admin from 203.0.113.195 port 42102 ssh2
Oct 27 10:02:22 alpine sshd[112]: Invalid user test from 198.51.100.44 port 33111
Oct 27 10:02:25 alpine sshd[113]: authentication failure; logname= uid=0 euid=0 tty=NODEVssh ruser= rhost=203.0.113.195
"""


class TestCheckAuthLogs(unittest.TestCase):
    def test_no_log_file_readable(self):
        with patch("alpineguard.security_checks._read_log_tail", return_value=None):
            result = security_checks.check_auth_logs()
            self.assertEqual(result["severity"], "note")
            self.assertIn("No authentication log found", result["message"])

    def test_clean_auth_log(self):
        with patch("alpineguard.security_checks._read_log_tail", return_value=SAMPLE_AUTH_LOG_CLEAN.splitlines()):
            result = security_checks.check_auth_logs()
            self.assertEqual(result["severity"], "ok")
            self.assertEqual(result["failed_attempts"], 0)
            self.assertEqual(len(result["source_ips"]), 0)

    def test_failed_attempts_parsed(self):
        with patch("alpineguard.security_checks._read_log_tail", return_value=SAMPLE_AUTH_LOG_FAILED.splitlines()):
            result = security_checks.check_auth_logs()
            self.assertEqual(result["failed_attempts"], 4)
            self.assertEqual(result["severity"], "note")  # < 10 attempts is "note"
            self.assertIn("203.0.113.195", result["source_ips"])
            self.assertIn("198.51.100.44", result["source_ips"])
            self.assertEqual(len(result["sample_lines"]), 4)

    def test_high_volume_failed_attempts_triggers_warning(self):
        many_failures = ["Failed password for root from 1.2.3.4 port 100\n"] * 55
        with patch("alpineguard.security_checks._read_log_tail", return_value=many_failures):
            result = security_checks.check_auth_logs()
            self.assertEqual(result["severity"], "warning")
            self.assertEqual(result["failed_attempts"], 55)


class TestCheckListeningPorts(unittest.TestCase):
    def test_no_ports(self):
        with patch("alpineguard.security_checks.get_listening_ports", return_value=[]):
            result = security_checks.check_listening_ports()
            self.assertEqual(result["severity"], "note")

    def test_safe_ports(self):
        safe_ports = [
            {"local_ip": "127.0.0.1", "local_port": 22, "state": "LISTEN"},
            {"local_ip": "0.0.0.0", "local_port": 80, "state": "LISTEN"},
        ]
        with patch("alpineguard.security_checks.get_listening_ports", return_value=safe_ports):
            result = security_checks.check_listening_ports()
            self.assertEqual(result["severity"], "ok")
            self.assertEqual(len(result["high_risk_ports"]), 0)

    def test_high_risk_port_on_all_interfaces(self):
        risky_ports = [
            {"local_ip": "0.0.0.0", "local_port": 23, "state": "LISTEN"},    # Telnet
            {"local_ip": "0.0.0.0", "local_port": 6379, "state": "LISTEN"},  # Redis unauthenticated
        ]
        with patch("alpineguard.security_checks.get_listening_ports", return_value=risky_ports):
            result = security_checks.check_listening_ports()
            self.assertEqual(result["severity"], "warning")
            self.assertEqual(len(result["high_risk_ports"]), 2)
            services = [p["service"] for p in result["high_risk_ports"]]
            self.assertIn("Telnet", services)
            self.assertIn("Redis", services)


class TestCheckWorldWritable(unittest.TestCase):
    def test_clean_permissions(self):
        mock_stat = MagicMock()
        mock_stat.st_mode = 0o755  # rwxr-xr-x (not world writable)

        with patch("os.stat", return_value=mock_stat):
            result = security_checks.check_world_writable(["/etc/passwd", "/etc/shadow"])
            self.assertEqual(result["severity"], "ok")
            self.assertEqual(len(result["world_writable"]), 0)

    def test_detects_world_writable_path(self):
        def side_effect(path):
            mock = MagicMock()
            if path == "/tmp/open":
                mock.st_mode = 0o777  # world writable
            else:
                mock.st_mode = 0o644
            return mock

        with patch("os.stat", side_effect=side_effect):
            result = security_checks.check_world_writable(["/tmp/open", "/etc/passwd"])
            self.assertEqual(result["severity"], "warning")
            self.assertEqual(result["world_writable"], ["/tmp/open"])


class TestSecurityCollect(unittest.TestCase):
    def test_collect_combines_checks(self):
        with patch("alpineguard.security_checks.check_auth_logs", return_value={"severity": "ok"}), \
             patch("alpineguard.security_checks.check_listening_ports", return_value={"severity": "ok"}), \
             patch("alpineguard.security_checks.check_world_writable", return_value={"severity": "warning"}):

            result = security_checks.collect()
            self.assertEqual(result["overall_severity"], "warning")
            self.assertIn("auth_logs", result)
            self.assertIn("listening_ports", result)
            self.assertIn("world_writable", result)


if __name__ == "__main__":
    unittest.main()
