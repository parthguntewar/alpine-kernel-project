"""
tests/test_network.py — Unit tests for alpineguard/network_monitor.py.

Tests parsing of /proc/net/dev, /proc/net/tcp, and /proc/net/if_inet6
using realistic sample data in temporary files.
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from alpineguard import network_monitor


SAMPLE_NET_DEV = """\
Inter-|   Receive                                                |  Transmit
 face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed
    lo: 1234567      50    0    0    0     0          0         0  1234567      50    0    0    0     0       0          0
  eth0: 9876543    1200    0    0    0     0          0         0  5432100     800    0    0    0     0       0          0
 wlan0: 1000000     100    1    0    0     0          0         0   500000      50    2    0    0     0       0          0
"""

# /proc/net/tcp format:
# sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
# 0100007F:0016 = 127.0.0.1:22 (SSH), state 0A = LISTEN
# 00000000:0050 = 0.0.0.0:80 (HTTP), state 0A = LISTEN
# 0F02000A:01BB = 10.0.2.15:443 -> remote 0100007F:C000 (127.0.0.1:49152), state 01 = ESTABLISHED
SAMPLE_NET_TCP = """\
  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode
   0: 0100007F:0016 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 12345 1 0000000000000000 100 0 0 10 0
   1: 00000000:0050 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 12346 1 0000000000000000 100 0 0 10 0
   2: 0F02000A:01BB 0100007F:C000 01 00000000:00000000 00:00000000 00000000  1000        0 12347 1 0000000000000000 100 0 0 10 0
"""

SAMPLE_IF_INET6 = """\
00000000000000000000000000000001 01 80 10 80       lo
fe80000000000000020c29fffe5d4a1b 02 40 20 80     eth0
"""


class TestHexToIpv4Port(unittest.TestCase):
    def test_localhost_port_22(self):
        # 0100007F in little endian hex is 127.0.0.1; 0016 in hex is 22
        ip, port = network_monitor._hex_to_ipv4_port("0100007F:0016")
        self.assertEqual(ip, "127.0.0.1")
        self.assertEqual(port, 22)

    def test_all_interfaces_port_80(self):
        ip, port = network_monitor._hex_to_ipv4_port("00000000:0050")
        self.assertEqual(ip, "0.0.0.0")
        self.assertEqual(port, 80)

    def test_virtualbox_default_ip(self):
        # 0A.00.02.0F in little endian hex:
        # byte 0: 0A (10), byte 1: 00 (0), byte 2: 02 (2), byte 3: 0F (15) -> "0F02000A"
        ip, port = network_monitor._hex_to_ipv4_port("0F02000A:01BB")
        self.assertEqual(ip, "10.0.2.15")
        self.assertEqual(port, 443)


class TestGetInterfaces(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.dev_file = os.path.join(self.test_dir, "dev")
        with open(self.dev_file, "w") as f:
            f.write(SAMPLE_NET_DEV)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_parses_interfaces(self):
        interfaces = network_monitor.get_interfaces(self.dev_file)
        names = [iface["name"] for iface in interfaces]
        self.assertIn("eth0", names)
        self.assertIn("wlan0", names)

        eth0 = next(i for i in interfaces if i["name"] == "eth0")
        self.assertEqual(eth0["rx_bytes"], 9876543)
        self.assertEqual(eth0["tx_bytes"], 5432100)
        self.assertEqual(eth0["rx_errors"], 0)

        wlan0 = next(i for i in interfaces if i["name"] == "wlan0")
        self.assertEqual(wlan0["rx_errors"], 1)
        self.assertEqual(wlan0["tx_errors"], 2)

    def test_missing_file_returns_empty_list(self):
        self.assertEqual(network_monitor.get_interfaces("/nonexistent"), [])


class TestGetIpv6Addresses(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.inet6_file = os.path.join(self.test_dir, "if_inet6")
        with open(self.inet6_file, "w") as f:
            f.write(SAMPLE_IF_INET6)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_parses_ipv6(self):
        addrs = network_monitor._get_ipv6_addresses(self.inet6_file)
        self.assertIn("lo", addrs)
        self.assertIn("eth0", addrs)
        self.assertIn("::1", addrs["lo"])
        self.assertTrue(any("fe80" in addr for addr in addrs["eth0"]))


class TestGetTcpConnections(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.tcp_file = os.path.join(self.test_dir, "tcp")
        with open(self.tcp_file, "w") as f:
            f.write(SAMPLE_NET_TCP)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_parses_all_connections(self):
        conns = network_monitor.get_tcp_connections(self.tcp_file, listening_only=False)
        self.assertEqual(len(conns), 3)

        states = [c["state"] for c in conns]
        self.assertEqual(states.count("LISTEN"), 2)
        self.assertEqual(states.count("ESTABLISHED"), 1)

    def test_listening_only(self):
        listening = network_monitor.get_tcp_connections(self.tcp_file, listening_only=True)
        self.assertEqual(len(listening), 2)
        ports = [c["local_port"] for c in listening]
        self.assertIn(22, ports)
        self.assertIn(80, ports)


class TestNetworkCollect(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.dev_file = os.path.join(self.test_dir, "dev")
        self.tcp_file = os.path.join(self.test_dir, "tcp")
        self.inet6_file = os.path.join(self.test_dir, "if_inet6")

        with open(self.dev_file, "w") as f:
            f.write(SAMPLE_NET_DEV)
        with open(self.tcp_file, "w") as f:
            f.write(SAMPLE_NET_TCP)
        with open(self.inet6_file, "w") as f:
            f.write(SAMPLE_IF_INET6)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_collect(self):
        with patch("alpineguard.network_monitor.get_interfaces", return_value=network_monitor.get_interfaces(self.dev_file)), \
             patch("alpineguard.network_monitor._get_ipv6_addresses", return_value=network_monitor._get_ipv6_addresses(self.inet6_file)), \
             patch("alpineguard.network_monitor.get_tcp_connections", return_value=network_monitor.get_tcp_connections(self.tcp_file)):

            result = network_monitor.collect()
            self.assertIsNone(result["error"])
            self.assertGreater(len(result["interfaces"]), 0)
            self.assertEqual(len(result["listening_ports"]), 2)


if __name__ == "__main__":
    unittest.main()
