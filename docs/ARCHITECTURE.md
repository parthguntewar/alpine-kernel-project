# docs/ARCHITECTURE.md — AlpineGuard Design and Data Flow

---

## Design Philosophy

AlpineGuard follows three core principles:

1. **Read-only** — Never write to system files, change configuration, or execute destructive commands.
2. **Honest reporting** — Only report values that have been actually measured. Never fabricate, estimate, or extrapolate metrics without disclosure.
3. **Graceful degradation** — If a data source is unavailable (missing file, permission denied, unexpected format), report "unavailable" with a clear reason rather than crashing.

---

## Module Dependency Graph

```
cli.py (orchestration)
├── system_info.py      ← /proc/version, /etc/os-release, /proc/uptime, /proc/cpuinfo
├── memory_monitor.py   ← /proc/meminfo
├── disk_monitor.py     ← os.statvfs(), /proc/mounts
├── cpu_monitor.py      ← /proc/stat (two-sample)
├── process_monitor.py  ← /proc/<pid>/status, /proc/<pid>/stat, /proc/<pid>/cmdline
├── network_monitor.py  ← /proc/net/dev, /proc/net/tcp, /proc/net/if_inet6
├── security_checks.py  ← /var/log/messages, network_monitor.get_listening_ports()
│
├── alerts.py           ← Pure functions: evaluate thresholds on collected data
└── reporting.py        ← Pure functions: render terminal output or JSON
```

No module at or below `cli.py` imports from `cli.py`. The dependency
graph is a strict DAG (directed acyclic graph) with no cycles.

---

## Data Flow

```
┌──────────────────────────────────────────────────────────────────────┐
│   Linux Kernel Interfaces                                            │
│   /proc/meminfo  /proc/stat  /proc/net/tcp  /var/log/messages  ...  │
└──────────────────────────────────┬───────────────────────────────────┘
                                   │ read-only
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│   Monitor Modules                                                    │
│   system_info  memory_monitor  cpu_monitor  disk_monitor             │
│   process_monitor  network_monitor  security_checks                  │
│                                                                      │
│   Output: plain Python dicts with numeric values, strings, None     │
└──────────────────────────────────┬───────────────────────────────────┘
                                   │ dicts
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│   alerts.py                                                          │
│   evaluate_memory()  evaluate_disk()  evaluate_cpu()                 │
│   evaluate_security()  summarize()                                   │
│                                                                      │
│   Output: list[Alert], summary dict                                  │
└──────────────────────────────────┬───────────────────────────────────┘
                                   │ Alert objects
                                   ▼
┌──────────────────────────────────────────────────────────────────────┐
│   reporting.py                                                       │
│   build_report()  → terminal string with ANSI colour codes           │
│   build_json_report() → JSON string                                  │
└──────────────────────────────────┬───────────────────────────────────┘
                                   │ string
                                   ▼
                              stdout / file
```

---

## Key Design Decisions

### Why read `/proc` directly instead of calling system commands?

Calling `ps`, `free`, `df`, `netstat`, etc. requires these utilities to
be installed. Alpine's minimal install may not have them (or may have
BusyBox versions with different output formats). Reading `/proc` is:
- Always available on any Linux kernel
- No subprocess overhead or shell injection risk
- Consistent format across kernel versions

### CPU measurement: two-sample delta

`/proc/stat` contains cumulative CPU tick counts since boot. A single
reading is therefore meaningless for utilization percentage. The correct
approach is:
```
sample1 = read /proc/stat ticks
sleep(interval)
sample2 = read /proc/stat ticks
utilization = (delta_active / delta_total) × 100
```
This is exactly what tools like `top` and `mpstat` do internally.

### Memory: MemAvailable vs MemFree

`MemFree` is the count of completely unused pages. `MemAvailable` is the
kernel's estimate of how much memory *could* be freed without swapping
(taking reclaimable cache into account). `MemAvailable` is the correct
field for "how much memory is the system actually using" and was
introduced in Linux 3.14. AlpineGuard uses `MemAvailable` with a
fallback to `MemFree` for compatibility.

### Disk: f_bavail vs f_bfree

`os.statvfs()` returns both `f_bfree` (total free blocks) and `f_bavail`
(blocks available to non-privileged users). Root always has more because
the kernel reserves a fraction of the disk. AlpineGuard uses `f_bavail`
to match what `df -h` shows to regular users.

### Alert levels: three tiers

- **OK** — no action needed
- **WARNING** — approaching a threshold; monitor closely
- **ERROR** — threshold exceeded; action required

There is no "INFO" level to avoid ambiguity. Security findings that are
not actionable are tagged with a "note" in the data but still map to
"OK" in the alert level, avoiding alert fatigue.

### Security: honest evidence standards

The security module explicitly labels every finding with:
- What was detected
- Why it is flagged
- What confidence level applies

It never states that an attack is occurring based on log evidence alone.
Failed SSH logins are reported as counts with the explicit caveat that
they are normal on internet-facing machines.

---

## Error Handling Strategy

Every external I/O operation is wrapped in a `try/except OSError` block.
The catch returns a structured error result (dict with `"error"` key set)
rather than propagating the exception. This means:

1. The program always completes and produces a report
2. The report clearly indicates which sections are unavailable
3. Upstream callers (alerts, reporting) check for `error` key

The only uncaught exceptions are genuine programming errors (bugs),
which are caught at the `cli.run()` boundary and reported with exit code 2.

---

## Testability

The separation of concerns directly enables testing:

- **Monitor modules** — tested with temporary files or mocked `open()` calls
- **alerts.py** — purely algorithmic; no I/O; tested with hand-constructed dicts
- **reporting.py** — purely formatting; tested by checking output structure
- **cli.py** — tested by mocking `collect_all()` and checking exit codes

This design makes 100% of the business logic testable on Windows
without a Linux environment.
