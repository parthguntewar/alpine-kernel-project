# AlpineGuard — Lightweight OS Health and Security Monitor

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/)
[![Platform: Alpine Linux](https://img.shields.io/badge/platform-Alpine%20Linux-blue.svg)](https://alpinelinux.org/)

---

## Overview

**AlpineGuard** is a lightweight, user-space system health and security monitoring utility built for Alpine Linux. It reads information about your running system directly from standard Linux kernel interfaces—`/proc`, `/sys`, and POSIX filesystem calls—and presents a clear, readable health report in the terminal.

> **Important:** AlpineGuard does **not** modify the Linux kernel, kernel modules, firewall rules, user accounts, or any system configuration. It is a pure read-only observer.

---

## Problem Being Solved

Alpine Linux is used as a minimal base for containers, embedded systems, and lightweight VMs. Its default installation has no GUI, no continuous monitoring, and minimal pre-installed tooling. Administrators and students need a quick way to answer:

- How much memory and disk is being used right now?
- Is the system under CPU load?
- Are there unusual patterns in authentication logs?
- Which ports are listening, and do any pose a risk?

AlpineGuard answers all of these from a single `alpineguard` command.

---

## Why Alpine Linux?

| Property | Why it matters |
|---|---|
| Minimal default install | Forces the tool to be self-sufficient with no assumed tooling |
| BusyBox utilities | No GNU-specific assumptions; works with posix-compatible tools |
| OpenRC (no systemd) | Demonstrates compatibility beyond Ubuntu-style systems |
| /proc filesystem | All Linux kernels expose this; it is the most portable interface |
| Lightweight footprint | The tool itself must be equally lightweight (stdlib only) |

---

## Project Objectives

1. Extend Alpine Linux with a useful user-space feature without OS modification.
2. Demonstrate reading Linux kernel data via `/proc` and POSIX APIs.
3. Implement configurable alert thresholds and honest security reporting.
4. Provide automated tests that run on any OS (Windows, Linux, macOS).
5. Document the project thoroughly for academic demonstration.

---

## Architecture

```
alpineguard/
├── __init__.py       Version metadata
├── __main__.py      python -m alpineguard entry point
├── main.py           Entry point delegator
├── cli.py            Argument parsing + orchestration
├── system_info.py    /proc/version, /etc/os-release, /proc/uptime, /proc/cpuinfo
├── cpu_monitor.py    /proc/stat (two-sample delta method)
├── memory_monitor.py /proc/meminfo
├── disk_monitor.py   os.statvfs() + /proc/mounts
├── process_monitor.py/proc/<pid>/status, /proc/<pid>/stat
├── network_monitor.py/proc/net/dev, /proc/net/tcp, /proc/net/if_inet6
├── security_checks.py/var/log/messages, /proc/net/tcp, filesystem checks
├── alerts.py         Pure threshold evaluation (no I/O)
└── reporting.py      Terminal + JSON output (no data collection)
```

**Data flow:**
```
Linux kernel interfaces (/proc, /sys, os.statvfs)
        ↓
  Monitor modules (collect raw data)
        ↓
  alerts.py (evaluate thresholds → Alert objects)
        ↓
  reporting.py (render terminal report or JSON)
        ↓
  cli.py (parse args, call above, print, exit)
```

---

## Module Responsibilities

| Module | Responsibility |
|---|---|
| `system_info` | Distribution name/version, kernel version, uptime, CPU info |
| `memory_monitor` | RAM/swap utilization from `/proc/meminfo` |
| `disk_monitor` | Filesystem usage via `os.statvfs()` and `/proc/mounts` |
| `cpu_monitor` | CPU % via two-sample `/proc/stat` delta |
| `process_monitor` | Process list, per-process RSS and CPU from `/proc/<pid>/` |
| `network_monitor` | Interface stats, TCP connections, listening ports |
| `security_checks` | Auth log analysis, high-risk port detection, filesystem checks |
| `alerts` | Pure threshold evaluation — no I/O |
| `reporting` | Terminal ANSI rendering and JSON serialization — no collection |
| `cli` | Argument parsing, orchestration, exit codes |

---

## How Data is Collected

### Memory (`/proc/meminfo`)
```
MemTotal:        2048000 kB   ← total physical RAM
MemAvailable:     768000 kB   ← available to user-space (kernel's best estimate)
SwapTotal:        512000 kB
SwapFree:         256000 kB
```
`utilization = (MemTotal - MemAvailable) / MemTotal × 100`

### CPU (`/proc/stat`)
A single snapshot is meaningless (cumulative counters). We take **two snapshots** 1 second apart and compute:
```
delta_active = (snap2.user + snap2.system + ...) - (snap1.user + snap1.system + ...)
delta_total  = sum(snap2.fields) - sum(snap1.fields)
utilization  = delta_active / delta_total × 100
```

### Disk (`os.statvfs()`)
```python
st = os.statvfs("/")
total     = st.f_frsize * st.f_blocks
available = st.f_frsize * st.f_bavail   # non-root perspective
used      = total - available
```

### Network (`/proc/net/`)
- `/proc/net/dev` → per-interface RX/TX byte counters
- `/proc/net/tcp` → TCP connections in hex (decoded to IP:port + state)
- `/proc/net/if_inet6` → IPv6 addresses

---

## Alert Thresholds

| Metric | Default Warning | Default Critical |
|---|---|---|
| Memory | 80% | 95% |
| Disk | 80% | 95% |
| CPU | 85% | 98% |

All thresholds are configurable via CLI flags (`--mem-warn`, `--disk-warn`, etc.).

---

## Installation on Alpine Linux

See [INSTALL.md](INSTALL.md) for step-by-step instructions on a clean Alpine 3.24 VM.

**Quick install:**
```sh
# On Alpine Linux
apk add python3
cd /path/to/alpine-kernel-project
pip3 install --user .
alpineguard
```

---

## Usage Examples

```sh
# Full health report (default)
alpineguard

# JSON output
alpineguard --json

# Export JSON report to file
alpineguard --json --output report.json

# Custom thresholds
alpineguard --mem-warn 70 --disk-crit 90

# Demo: trigger warnings with very low thresholds
alpineguard --mem-warn 1 --disk-warn 1

# Disable colour (for piping)
alpineguard --no-color | tee health.txt

# Show version
alpineguard --version

# Show help
alpineguard --help
```

---

## Sample Output

```
════════════════════════════════════════════════════════════════════════
  AlpineGuard v1.0.0 — System Health & Security Report
  Generated: 2026-10-27 16:30:00 UTC
════════════════════════════════════════════════════════════════════════

  SYSTEM INFORMATION
  ──────────────────────────────────────────────────────────────────────
  Distribution  : Alpine Linux v3.24
  Kernel        : 6.1.58-0-lts
  Architecture  : x86_64
  Uptime        : 2 hours, 15 minutes

  MEMORY
  ──────────────────────────────────────────────────────────────────────
  Utilization : [████████░░░░░░░░░░░░] 42.0%
  Used        : 860.0 MiB
  Available   : 1188.0 MiB
  Total       : 2048.0 MiB

  CPU
  ──────────────────────────────────────────────────────────────────────
  Utilization : [███░░░░░░░░░░░░░░░░░] 15.2% (over 1.0s)

  ALERT SUMMARY
  ──────────────────────────────────────────────────────────────────────
  [  OK  ] Memory OK — 42.0% used
  [  OK  ] Disk OK [/] — 55.0% used
  [  OK  ] CPU OK — 15.2% utilization
  ──────────────────────────────────────────────────────────────────────
  Overall Status : OK
════════════════════════════════════════════════════════════════════════
```

---

## Testing

### Run unit tests (Windows or Linux):
```sh
python -m unittest discover -s tests -p "test_*.py" -v
```

### Run via Makefile (Linux):
```sh
make test
```

### Tests cover (128 automated unit tests):
- Memory utilization calculation & fallback handling
- Disk utilization calculation & multi-mount parsing
- CPU two-sample delta calculation and clock jitter edge cases
- Process enumeration, status parsing, and per-process CPU %
- Network interface stats, IPv6 addresses, and TCP socket decoding
- Security checks (failed SSH login parsing, listening port risks, world-writable files)
- Alert threshold evaluation across OK, WARNING, and ERROR levels
- Handling missing `/proc` files (returns errors, doesn't crash)
- Handling malformed data
- JSON report structure and schema validation
- CLI argument parsing

See [docs/TESTING.md](docs/TESTING.md) for integration test procedures on the Alpine VM.

---

## Limitations and Compatibility Notes

| Issue | Notes |
|---|---|
| Per-process CPU % requires two runs | First-run CPU shows `n/a` — this is correct, not a bug |
| Auth logs may require root | `/var/log/messages` is often root-only on Alpine |
| IPv4 address detection | Best-effort from `/proc/net/fib_trie`; may not always resolve interface ↔ IP |
| `/proc/net/tcp6` not parsed | IPv6 TCP connections not yet included |
| Container networking | `/proc/net/` shows the namespace's view only |
| `os.statvfs()` not on Windows | Disk monitor uses mocks in Windows tests |

---

## Security and Privacy

- AlpineGuard reads system state; it **never writes** to system files.
- No network connections are made.
- No passwords, keys, tokens, or secrets are read or displayed.
- Log analysis only counts failure events — it does **not** extract credentials.
- Authentication log access may require elevated privileges; if unavailable, AlpineGuard reports "unavailable" rather than failing.

---

## Future Improvements

- Continuous monitoring mode (loop with configurable interval)
- Per-process CPU tracking across multiple samples
- IPv6 TCP connection decoding (`/proc/net/tcp6`)
- Persistent alert history (simple JSON log)
- Email/webhook notification on threshold breach
- TUI dashboard (curses-based)
- Alpine package manager (`apk`) integration check
- Systemd journal reader fallback for auth logs

---

## Repository Structure

```
alpine-kernel-project/
├── alpineguard/          Python package (all source modules)
├── tests/                Automated unit tests
├── docs/                 Architecture, testing, and viva docs
├── examples/             Sample JSON output and demo script
├── README.md             This file
├── INSTALL.md            Alpine-specific installation guide
├── Makefile              Common development targets
├── pyproject.toml        Build configuration (pip install .)
├── requirements.txt      No runtime dependencies (stdlib only)
└── LICENSE               MIT
```

---

## License

MIT — see [LICENSE](LICENSE).
