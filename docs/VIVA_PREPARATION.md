# docs/VIVA_PREPARATION.md — Viva Questions and Answers

This document is a study guide for the AlpineGuard project demonstration.
It covers every module, key functions, design decisions, and anticipated
professor questions with technically accurate answers.

---

## Project Summary in One Sentence

AlpineGuard is a user-space Python utility that reads Linux kernel-exported
interfaces (`/proc`, `/sys`, POSIX calls) to monitor system health and
basic security indicators on Alpine Linux, without modifying the kernel,
requiring root, or installing additional packages.

---

## Module-by-Module Explanation

### `__init__.py`
Declares the package version (`1.0.0`). This single source of truth is
imported by `cli.py` and `reporting.py` so the version only needs to be
updated in one place.

### `system_info.py`
**What it does:** Collects OS name, kernel version, uptime, and CPU info.

**Key functions:**
- `get_distro_info()` → reads `/etc/os-release` (standard freedesktop spec)
- `get_kernel_version()` → reads `/proc/version`, extracts field [2]
- `get_uptime()` → reads `/proc/uptime` (first field = seconds since boot)
- `get_cpu_info()` → parses `/proc/cpuinfo` for model name and core count
- `collect()` → calls all four and returns unified dict

**Why /proc?** The `/proc` pseudo-filesystem is always present on Linux
regardless of which tools are installed. It requires no system calls
beyond `open()` + `read()`.

---

### `memory_monitor.py`
**What it does:** Reports total/used/available RAM and swap from `/proc/meminfo`.

**Key function:** `calculate_utilization(total, available)`
```python
used = total - available
return (used / total) * 100
```
This raises `ValueError` for `total <= 0` rather than returning 0 or dividing by zero silently.

**Why MemAvailable, not MemFree?**
`MemFree` = completely unused pages.
`MemAvailable` = kernel's estimate of pages freeable without swapping
(includes reclaimable cache). `MemAvailable` is what `free -h` shows
in the "available" column and is more useful for capacity planning.

---

### `disk_monitor.py`
**What it does:** Reports filesystem usage using `os.statvfs()`.

**Key function:** `calculate_utilization(total, available)` (same logic as memory).

**os.statvfs() fields:**
- `f_frsize` × `f_blocks` = total bytes
- `f_frsize` × `f_bavail` = available to non-root users (matches `df -h`)
- `f_frsize` × `f_bfree` = total free (root perspective, larger)

**get_all_mountpoints()** reads `/proc/mounts` and filters out pseudo-filesystems
(proc, sysfs, tmpfs, devtmpfs, etc.) using a hardcoded exclusion set.

---

### `cpu_monitor.py`
**What it does:** Measures CPU utilization using a two-sample delta from `/proc/stat`.

**The first-sample problem:** A single `/proc/stat` reading gives cumulative
ticks since boot, not current utilization. We must take two readings and
compute the difference. On the first call, there is no previous sample
— returning `None` is the honest response.

**Key class:** `_CpuSnapshot`
- `.total` = sum of all tick fields
- `.active` = `total - idle - iowait`

**Key function:** `calculate_utilization(snap1, snap2)`
```python
delta_total = snap2.total - snap1.total
delta_active = max(0, snap2.active - snap1.active)
return (delta_active / delta_total) * 100
```
The `max(0, ...)` guards against counter wraparound or jitter.

---

### `process_monitor.py`
**What it does:** Lists running processes with PID, name, state, RSS memory,
and CPU percentage.

**Key source files:**
- `/proc/<pid>/status` — name, state (R/S/D/Z), uid, VmRSS (memory in kB)
- `/proc/<pid>/stat` — utime + stime (CPU tick counts for this process)
- `/proc/<pid>/cmdline` — NUL-delimited command line

**Per-process CPU %:** Requires comparing process tick counts across two calls
(same two-sample approach as system CPU). The first call returns `None` for
CPU % — this is correct behavior.

**Race condition handling:** Processes can exit between when we list PIDs
and when we read their `/proc/<pid>/` files. All reads return `None` on
`OSError`, and the process is silently skipped.

**Permission handling:** Processes owned by other users may have unreadable
`/proc/<pid>/` entries. Same `OSError` handling applies.

---

### `network_monitor.py`
**What it does:** Reports network interfaces, IPv6 addresses, and TCP connections.

**Data sources:**
- `/proc/net/dev` → interface names, RX/TX byte counts
- `/proc/net/if_inet6` → interface IPv6 addresses (hex format, decoded via `socket.inet_ntop`)
- `/proc/net/tcp` → TCP connections in hex format

**Hex address decoding in `/proc/net/tcp`:**
The local/remote addresses are stored as little-endian 32-bit hex integers.
Example: `0F02000A:0050` → port 80 at IP 10.0.2.15.
```python
addr_int = int("0F02000A", 16)
addr_bytes = struct.pack("<I", addr_int)   # little-endian
ip = socket.inet_ntoa(addr_bytes)          # "10.0.2.15"
```

**TCP state codes:** Defined in the Linux kernel source. "0A" = LISTEN.

---

### `security_checks.py`
**What it does:** Checks auth logs, listing ports, and world-writable paths.

**Honest evidence standard:**
- Failed logins are reported as a count + sample lines
- The report explicitly states this is NOT sufficient evidence of an attack
- High-risk ports are flagged based on well-known port numbers
- World-writable checks use `os.stat()` and the `S_IWOTH` bit (0o002)

**Why not report "attack detected"?**
Log evidence alone cannot confirm an attack without correlating with:
- Successful login following failures
- Geographic anomaly
- Time patterns
Claiming an attack from log counts alone would be misleading.

---

### `alerts.py`
**What it does:** Pure threshold evaluation — no I/O.

**`Alert` dataclass fields:** `level`, `category`, `message`, `value`, `threshold`, `recommendation`

**`_pct_level(pct, warning, error)`:**
```python
if pct >= error:   return "ERROR"
if pct >= warning: return "WARNING"
return "OK"
```

**`summarize(alerts)`:** Returns overall status as the worst level across all alerts.

---

### `reporting.py`
**What it does:** Pure output formatting — no data collection.

**Terminal output:** Uses ANSI escape codes for colour, with graceful fallback
when stdout is not a TTY or `NO_COLOR` env var is set.

**Progress bars:** ASCII art using `█` (filled) and `░` (empty) characters,
coloured green/yellow/red based on the percentage.

**JSON output:** Standard `json.dumps()` with `default=str` to handle any
non-serializable types gracefully.

---

### `cli.py`
**What it does:** Entry point — parses args, calls collectors, calls reporting.

**`collect_all(args)`:** Calls each module's `collect()` function and assembles
the unified dict passed to reporting.

**Exit codes:**
- `0` — all checks OK or WARNING
- `1` — at least one ERROR-level alert
- `2` — fatal error during data collection

---

## Why Is This Project Useful?

1. **Practical sysadmin tool** — one command gives a complete picture of system health
2. **Security awareness** — surface potential issues without expensive dedicated tools
3. **Demonstrates Linux internals** — shows how `/proc` works to a student or recruiter
4. **Portable design pattern** — the monitor/alert/report separation is used in production monitoring systems (Prometheus, Nagios)
5. **Alpine-compatible** — specifically designed for the constraints of a minimal Linux install

---

## Technical Design Decisions

| Decision | Rationale |
|---|---|
| Standard library only | Alpine may not have pip; avoids dependency management |
| `/proc` over subprocess | More portable; no shell injection; works on BusyBox Alpine |
| Two-sample CPU | Correct measurement; avoids fabricated first-sample readings |
| MemAvailable over MemFree | Matches kernel's own assessment of available memory |
| f_bavail over f_bfree | Matches `df` output; non-root perspective |
| Monitor/Alert/Report separation | Testability; each layer independently verifiable |
| Exit code 1 on ERROR | Standard Unix convention for monitoring tools |
| JSON export | Machine-readable; composable with other tools |

---

## Anticipated Viva Questions

### Q: Does AlpineGuard modify the Linux kernel?
**A:** No. AlpineGuard is a user-space application. It only reads data that
the kernel already exposes through `/proc` and POSIX syscalls. It makes no
system calls that write to kernel state (`sysctl`, `ioctl` for configuration,
module loading, etc.). The kernel is not aware of AlpineGuard's existence.

### Q: How does your CPU measurement work?
**A:** `/proc/stat` contains cumulative CPU tick counts since boot. A single
reading is meaningless. We take two snapshots 1 second apart, compute the
delta of active ticks (user+nice+system+irq+softirq) and divide by the delta
of total ticks. This is the same method used by `top`, `htop`, and `mpstat`.

### Q: Why did you choose Alpine Linux?
**A:** Alpine uses BusyBox, OpenRC, musl libc, and has no systemd — none of
the Ubuntu-specific assumptions apply. Targeting Alpine demonstrates that the
tool is genuinely portable rather than dependent on a common rich environment.
It's also the most widely used base image for Docker containers.

### Q: What happens if `/proc/meminfo` is missing?
**A:** Every file read in AlpineGuard is wrapped in `try/except OSError`.
If the file is missing or unreadable, the collector returns a dict with
`"error"` set to a descriptive string. The alert module sees this and
generates an ERROR alert. The report shows the error message rather than
fabricated data. The program always completes; it never crashes on a missing file.

### Q: Could a malicious process write fake data to `/proc`?
**A:** Processes cannot write arbitrary data to `/proc` files that belong to
other processes or the kernel. The `/proc` virtual filesystem is populated by
the kernel itself. A process CAN write to `/proc/self/` (its own entries) but
this would only affect AlpineGuard's reading of that specific process's data,
not system-wide metrics like memory or CPU.

### Q: How does security_checks.py avoid false positives?
**A:** By being explicit about what is and is not known. Failed SSH attempts
are reported as a count with an explicit note that "failed logins occur
normally on networked systems" and that the count alone is not evidence of
an attack. High-risk ports are flagged with "reason" fields explaining the
specific concern. No severity above WARNING is generated from log evidence alone.

### Q: What is the exit code strategy?
**A:** Following Unix convention for monitoring tools:
- `0` = healthy or warnings only (monitoring tool ran successfully)
- `1` = at least one ERROR-level alert (for scripting and cron alerting)
- `2` = program error (collection failed, bad arguments)

This makes AlpineGuard composable in shell scripts:
```sh
if ! alpineguard; then
    send_alert "System has critical issues"
fi
```

### Q: How do you handle the first-sample CPU problem?
**A:** The function `calculate_utilization()` returns `None` when the two
snapshots are identical (zero delta) or when no previous snapshot exists.
The alert evaluator treats `None` CPU as an OK (informational) alert with
a message saying "first sample — re-run for a reading." We never report
a fabricated number.

### Q: What testing approach did you use?
**A:** Unit tests use Python's built-in `unittest` module. Tests are designed
to run on Windows by:
1. Using temporary files instead of `/proc/meminfo` etc.
2. Mocking `os.statvfs()` (not available on Windows)
3. Mocking `time.sleep()` so CPU tests run fast
4. Mocking `collect_all()` in CLI tests to test exit codes and JSON output

The business logic (utilization calculation, alert thresholds) is completely
isolated from OS dependencies, making it 100% testable everywhere.

### Q: Why is `reporting.py` separate from the monitor modules?
**A:** This is the Model-View separation principle. The monitor modules (Model)
only know how to collect data. The reporting module (View) only knows how to
display it. This means:
- You can test the display logic without collecting real data
- You can add a web API, email report, or Prometheus exporter without
  touching the monitor modules
- The data can be inspected (JSON) without rendering it to the terminal

---

## Limitations and Possible Improvements

### Limitations
| Limitation | Root Cause |
|---|---|
| First-run CPU shows `n/a` | Fundamental: requires two samples |
| Auth logs often need root | Alpine's default syslog permissions |
| IPv4 interface addresses unreliable | `/proc/net/fib_trie` is complex to parse; not using `ip addr` |
| No IPv6 TCP connection decoding | `/proc/net/tcp6` not yet implemented |
| Process CPU on first run | Same two-sample requirement as system CPU |

### Possible Improvements
- Continuous monitoring mode with configurable interval
- Persistent alert history in a JSON file
- Email or webhook notification on ERROR status
- curses-based TUI for live dashboard
- IPv6 TCP connection decoding
- Systemd journal reader for auth logs on non-Alpine systems
- Package update check via `apk version` output parsing

---

## Demonstration Script

```sh
# ── Step 1: Verify installation
alpineguard --version

# ── Step 2: Full health report
alpineguard

# ── Step 3: Demonstrate configurable warnings (no resource exhaustion needed)
alpineguard --mem-warn 1 --disk-warn 1 --cpu-warn 1

# ── Step 4: Export JSON report
alpineguard --json --output /tmp/ag_report.json

# ── Step 5: Inspect JSON report
python3 -m json.tool /tmp/ag_report.json | head -40

# ── Step 6: Run automated tests
python3 -m unittest discover -s tests -p "test_*.py" -v

# ── Step 7: Show that no system changes were made
# (Nothing in /proc/, /etc/, or /var/ was modified by AlpineGuard)
echo "No system files were modified. AlpineGuard is read-only."
```
