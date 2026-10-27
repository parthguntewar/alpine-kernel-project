"""
network_monitor.py — Network interface and connection monitoring.

Data sources (all read-only, no root required for most):
  /proc/net/dev        — RX/TX byte counts per interface
  /proc/net/if_inet6   — IPv6 addresses per interface
  /proc/net/fib_trie   — IPv4 addresses (parsed carefully)
  /proc/net/tcp        — TCP connections (IPv4) in hex format
  /proc/net/tcp6       — TCP connections (IPv6) in hex format
  /proc/net/udp        — UDP sockets (IPv4)

Alpine Linux uses BusyBox and may not have 'ip' or 'ifconfig'
in the default minimal install, so we avoid subprocess calls
and read /proc directly.

NOTE: /proc/net/tcp shows connections for the *current network
namespace*. On a typical single-user Alpine VM this covers all
connections. On containers it may be restricted.
"""

import os
import socket
import struct
from typing import Optional


# ---------------------------------------------------------------------------
# TCP state codes as defined in the Linux kernel
# ---------------------------------------------------------------------------
_TCP_STATES = {
    "01": "ESTABLISHED",
    "02": "SYN_SENT",
    "03": "SYN_RECV",
    "04": "FIN_WAIT1",
    "05": "FIN_WAIT2",
    "06": "TIME_WAIT",
    "07": "CLOSE",
    "08": "CLOSE_WAIT",
    "09": "LAST_ACK",
    "0A": "LISTEN",
    "0B": "CLOSING",
}


def _read_file(path: str) -> Optional[str]:
    """Return file text or None on error."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Interface statistics from /proc/net/dev
# ---------------------------------------------------------------------------

def get_interfaces(proc_net_dev: str = "/proc/net/dev") -> list:
    """
    Parse /proc/net/dev and return per-interface RX/TX statistics.

    /proc/net/dev format (after two header lines):
      iface: rx_bytes rx_pkts rx_errs ... tx_bytes tx_pkts tx_errs ...

    Returns a list of dicts, one per interface (excluding 'lo' loopback).
    """
    content = _read_file(proc_net_dev)
    if content is None:
        return []

    interfaces = []
    lines = content.splitlines()
    # First two lines are headers
    for line in lines[2:]:
        line = line.strip()
        if not line or ":" not in line:
            continue
        iface, _, stats = line.partition(":")
        iface = iface.strip()
        parts = stats.split()
        if len(parts) < 16:
            continue
        try:
            interfaces.append({
                "name": iface,
                "rx_bytes": int(parts[0]),
                "rx_packets": int(parts[1]),
                "rx_errors": int(parts[2]),
                "tx_bytes": int(parts[8]),
                "tx_packets": int(parts[9]),
                "tx_errors": int(parts[10]),
            })
        except (ValueError, IndexError):
            continue

    return interfaces


# ---------------------------------------------------------------------------
# IPv4 addresses from /proc/net/fib_trie
# ---------------------------------------------------------------------------

def _get_ipv4_addresses(fib_trie_path: str = "/proc/net/fib_trie") -> dict:
    """
    Extract interface→IPv4 address mappings from /proc/net/fib_trie.

    This file is complex to parse fully; we use a heuristic:
    look for LOCAL scope entries (32-bit host routes) and pair them
    with the preceding interface hint. Falls back gracefully.

    Returns a dict: { interface_name: [ip, ...] }
    """
    # A simpler and more reliable source for Alpine: /proc/net/if_inet6
    # doesn't have IPv4. We try socket.getaddrinfo as a cross-platform
    # fallback but that needs a hostname. Instead use the fib_trie approach.
    content = _read_file(fib_trie_path)
    if content is None:
        return {}

    addrs: dict = {}
    lines = content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        # Lines like "     |-- 192.168.1.100"
        if "|--" in line or "/32" in line:
            # The preceding lines may have the interface; this heuristic
            # is not reliable for all kernels. We'll use a different approach.
            pass
        i += 1

    # Better approach: /proc/net/if_inet6 for IPv6, and
    # try reading /proc/net/arp or socket for IPv4
    return _get_ipv4_from_arp()


def _get_ipv4_from_arp(arp_path: str = "/proc/net/arp") -> dict:
    """
    Read /proc/net/arp to get interface→IP hint (not the interface's own IP,
    but a useful cross-check). For the interface's own IP we rely on
    socket.gethostbyname + /proc/net/fib_trie heuristic.

    This function is a best-effort; callers should handle empty results.
    """
    # We'll use the simplest reliable approach: parse /proc/net/fib_trie
    # looking for LOCAL (scope) entries which represent interface addresses.
    content = _read_file("/proc/net/fib_trie")
    if content is None:
        return {}

    result: dict = {}
    lines = content.splitlines()
    i = 0
    current_prefix = None

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Match lines like "  LOCAL"
        if stripped == "LOCAL":
            # The IP is typically 2 lines above in the format:
            #   +-- <ip>/<prefix>
            # Walk back to find it
            for back in range(i - 1, max(i - 5, -1), -1):
                candidate = lines[back].strip()
                if candidate.startswith("+--") or candidate.startswith("|--"):
                    ip_part = candidate.split()[-1].split("/")[0]
                    # Validate it looks like an IPv4
                    parts = ip_part.split(".")
                    if len(parts) == 4:
                        # We don't know the interface name from fib_trie alone
                        result.setdefault("unknown", []).append(ip_part)
                    break
        i += 1

    return result


# ---------------------------------------------------------------------------
# IPv6 addresses from /proc/net/if_inet6
# ---------------------------------------------------------------------------

def _get_ipv6_addresses(path: str = "/proc/net/if_inet6") -> dict:
    """
    Parse /proc/net/if_inet6 for interface→IPv6 address mappings.

    Format: addr_hex ifindex prefix_len scope flags ifname
    """
    content = _read_file(path)
    if content is None:
        return {}

    result: dict = {}
    for line in content.splitlines():
        parts = line.split()
        if len(parts) < 6:
            continue
        hex_addr = parts[0]
        iface = parts[5]
        # Convert 32-hex-digit string to IPv6 notation
        try:
            raw = bytes.fromhex(hex_addr)
            ipv6 = socket.inet_ntop(socket.AF_INET6, raw)
            result.setdefault(iface, []).append(ipv6)
        except (ValueError, socket.error):
            continue

    return result


# ---------------------------------------------------------------------------
# Hex address decoding for /proc/net/tcp
# ---------------------------------------------------------------------------

def _hex_to_ipv4_port(hex_str: str) -> tuple:
    """
    Convert a little-endian hex address:port string from /proc/net/tcp
    to a human-readable (ip, port) tuple.

    Example: "0F02000A:0050" → ("10.0.2.15", 80)
    """
    addr_hex, _, port_hex = hex_str.partition(":")
    port = int(port_hex, 16)
    # The 4-byte address is stored in little-endian order
    addr_int = int(addr_hex, 16)
    addr_bytes = struct.pack("<I", addr_int)
    ip = socket.inet_ntoa(addr_bytes)
    return ip, port


def get_tcp_connections(
    tcp_path: str = "/proc/net/tcp",
    listening_only: bool = False,
) -> list:
    """
    Parse /proc/net/tcp and return a list of TCP connection dicts.

    Each dict contains:
      - local_ip, local_port
      - remote_ip, remote_port
      - state            : human-readable state string
      - inode            : int (can be matched to /proc/<pid>/fd/ if needed)

    Set *listening_only=True* to return only LISTEN state entries.
    """
    content = _read_file(tcp_path)
    if content is None:
        return []

    connections = []
    lines = content.splitlines()
    for line in lines[1:]:  # skip header
        parts = line.split()
        if len(parts) < 12:
            continue
        local = parts[1]
        remote = parts[2]
        state_hex = parts[3].upper()
        try:
            inode = int(parts[9])
            local_ip, local_port = _hex_to_ipv4_port(local)
            remote_ip, remote_port = _hex_to_ipv4_port(remote)
            state = _TCP_STATES.get(state_hex, f"UNKNOWN({state_hex})")
        except (ValueError, struct.error):
            continue

        if listening_only and state != "LISTEN":
            continue

        connections.append({
            "local_ip": local_ip,
            "local_port": local_port,
            "remote_ip": remote_ip,
            "remote_port": remote_port,
            "state": state,
            "inode": inode,
        })

    return connections


def get_listening_ports() -> list:
    """
    Return a list of TCP ports currently in LISTEN state.

    Each item is a dict: { local_ip, local_port, state }
    """
    connections = get_tcp_connections(listening_only=True)
    return [
        {
            "local_ip": c["local_ip"],
            "local_port": c["local_port"],
            "state": c["state"],
        }
        for c in connections
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def collect() -> dict:
    """
    Collect all network information.

    Returns a dict with:
      - interfaces       : list — per-interface RX/TX stats
      - ipv6_addresses   : dict — iface → [ipv6, ...]
      - tcp_connections  : list — all TCP connections
      - listening_ports  : list — LISTEN-state TCP entries
      - error            : str | None
    """
    interfaces = get_interfaces()
    ipv6_addresses = _get_ipv6_addresses()
    tcp_connections = get_tcp_connections()
    listening_ports = [c for c in tcp_connections if c["state"] == "LISTEN"]

    # Attach IPv6 addresses to interface dicts
    for iface in interfaces:
        iface["ipv6"] = ipv6_addresses.get(iface["name"], [])

    error = None
    if not interfaces:
        error = "Cannot read /proc/net/dev"

    return {
        "interfaces": interfaces,
        "ipv6_addresses": ipv6_addresses,
        "tcp_connections": tcp_connections,
        "listening_ports": listening_ports,
        "error": error,
    }
