# docs/TESTING.md — Test Procedures and Expected Results

---

## Test Categories

| Category | Can run on Windows | Requires Alpine VM |
|---|---|---|
| Unit tests | ✅ Yes | Optional |
| Static analysis (syntax/import) | ✅ Yes | Optional |
| CLI behavior (mocked) | ✅ Yes | Optional |
| Integration tests | ❌ No | ✅ Required |

---

## 1. Running Unit Tests (Any OS)

### Prerequisites
- Python 3.8+
- Project cloned or copied to local filesystem

### Command
```sh
# From project root
python -m unittest discover -s tests -p "test_*.py" -v
```

### Expected output
```
test_collect_missing_file_returns_error (tests.test_memory.TestCollect) ... ok
test_collect_no_memavailable_falls_back_to_memfree (tests.test_memory.TestCollect) ... ok
test_collect_swap_not_configured (tests.test_memory.TestCollect) ... ok
test_collect_swap_usage (tests.test_memory.TestCollect) ... ok
test_collect_typical (tests.test_memory.TestCollect) ... ok
...
----------------------------------------------------------------------
Ran 128 tests in 0.3s

OK
```

All tests should pass with `OK`. Zero failures, zero errors.

### What each test file covers

| File | What is tested |
|---|---|
| `test_system_info.py` | os-release parsing, kernel version, uptime, CPU info |
| `test_cpu.py` | Two-sample delta calculation, snapshot arithmetic, error handling |
| `test_memory.py` | `/proc/meminfo` parsing, utilization calculation, edge cases |
| `test_disk.py` | `os.statvfs()` via mock, utilization calculation, mountpoint parsing |
| `test_process.py` | `/proc/<pid>/` status, cmdline, stat ticks, and process CPU calculation |
| `test_network.py` | `/proc/net/dev`, `/proc/net/tcp`, IPv6 parsing, and port extraction |
| `test_security.py` | Failed SSH login parsing, listening port risks, and world-writable files |
| `test_alerts.py` | All threshold levels, Alert.to_dict(), summarize() |
| `test_cli.py` | Arg parsing, JSON output validity, exit codes, file output |

---

## 2. Static Analysis

### Syntax check
```sh
python -m py_compile alpineguard/*.py && echo "Syntax OK"
```

### Import check
```sh
python -c "import alpineguard; import alpineguard.cli; import alpineguard.alerts; print('Imports OK')"
```

### Pyflakes (optional, install with `pip install pyflakes`)
```sh
pyflakes alpineguard/
```

---

## 3. CLI Behavior Tests

These can be run on any OS but produce more meaningful output on Linux.

```sh
# Help text
python -m alpineguard --help

# Version
python -m alpineguard --version
# Expected: alpineguard 1.0.0

# JSON output validation
python -m alpineguard --json | python -m json.tool
# Expected: valid JSON printed to stdout

# JSON to file
python -m alpineguard --json --output /tmp/test_report.json
cat /tmp/test_report.json | python -m json.tool

# Threshold warning demo (triggers warnings at 1%)
python -m alpineguard --mem-warn 1 --disk-warn 1 --cpu-warn 1
# Expected: WARNING alerts for memory, disk, and CPU
```

---

## 4. Integration Tests (Alpine Linux VM Only)

> ⚠️ **These tests have not yet been executed on the Alpine VM.**
> They must be run on the target Alpine Linux 3.24 system.
> Mark this section complete only after actual VM execution.

### 4.1 Setup
```sh
# On Alpine VM
apk update && apk add python3 py3-pip git
git clone https://github.com/parthguntewar/alpine-kernel-project.git
cd alpine-kernel-project
pip3 install --user .
export PATH="$HOME/.local/bin:$PATH"
```

### 4.2 Version check
```sh
alpineguard --version
```
Expected: `alpineguard 1.0.0`

### 4.3 Full health report
```sh
alpineguard
```
Expected:
- Distribution shows `Alpine Linux 3.24`
- Kernel shows `6.1.58-0-lts` (or current installed kernel)
- Memory shows real values from `/proc/meminfo`
- Disk shows real values for `/`
- CPU shows a percentage (requires the 1-second measurement)
- Security section shows auth log status

### 4.4 JSON export
```sh
alpineguard --json --output /tmp/report.json
python3 -m json.tool /tmp/report.json | head -30
```
Expected: valid, pretty-printed JSON

### 4.5 Unit tests on Alpine
```sh
python3 -m unittest discover -s tests -p "test_*.py" -v
```
Expected: all tests pass

### 4.6 Threshold warning demonstration
```sh
# Use artificially low thresholds to demonstrate WARNING status
alpineguard --mem-warn 1 --disk-warn 1 --cpu-warn 1
```
Expected: WARNING alerts without exhausting real system resources

### 4.7 Auth log check (may need root)
```sh
sudo alpineguard
```
Expected: security section shows actual auth log results from `/var/log/messages`

### 4.8 Exit code verification
```sh
# Should exit 0 on healthy system
alpineguard; echo "Exit code: $?"

# Should exit 1 with forced error threshold
alpineguard --mem-crit 1; echo "Exit code: $?"
```

---

## 5. Test Result Recording Template

When running integration tests on the Alpine VM, fill in this table:

| Test | Command | Expected | Actual | Pass/Fail |
|---|---|---|---|---|
| Version | `alpineguard --version` | `alpineguard 1.0.0` | | |
| Distro name | `alpineguard` | Alpine Linux shown | | |
| Kernel version | `alpineguard` | 6.x.x-lts shown | | |
| Memory reading | `alpineguard` | Real MiB values | | |
| CPU reading | `alpineguard` | Non-null % | | |
| Disk reading | `alpineguard` | Real GiB values | | |
| JSON valid | `alpineguard --json \| python3 -m json.tool` | No error | | |
| Unit tests | `python3 -m unittest discover` | All pass | | |
| Warning demo | `--mem-warn 1` | WARNING status | | |
| Exit code OK | healthy system | exit 0 | | |

---

## 6. Known Acceptable Gaps

| Scenario | Expected behavior |
|---|---|
| First run CPU % | Shows `n/a` — requires two samples |
| Auth log without root | Shows "unavailable, root may be required" |
| No network interfaces up | Network section shows "no data available" |
| Container environment | `/proc/net/tcp` reflects namespace; expected |
