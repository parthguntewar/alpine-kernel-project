#!/bin/sh
# examples/demo.sh — AlpineGuard demonstration script
# Run this on the Alpine Linux VM after installation.
# Usage: sh examples/demo.sh

set -e

echo "================================================================"
echo "  AlpineGuard — College Project Demonstration"
echo "================================================================"
echo ""

# ── Step 1: Version
echo "STEP 1: Version check"
echo "─────────────────────"
alpineguard --version || python3 -m alpineguard --version
echo ""

# ── Step 2: Full health report
echo "STEP 2: Full system health report"
echo "──────────────────────────────────"
alpineguard 2>/dev/null || python3 -m alpineguard
echo ""

# ── Step 3: Warning threshold demo
echo "STEP 3: Warning threshold demonstration"
echo "  (Using --mem-warn 1 to trigger warnings without exhausting resources)"
echo "────────────────────────────────────────"
alpineguard --mem-warn 1 --disk-warn 1 --cpu-warn 1 2>/dev/null || \
  python3 -m alpineguard --mem-warn 1 --disk-warn 1 --cpu-warn 1
echo ""

# ── Step 4: JSON export
echo "STEP 4: JSON report export"
echo "──────────────────────────"
REPORT="/tmp/alpineguard_demo_report.json"
alpineguard --json --output "$REPORT" 2>/dev/null || \
  python3 -m alpineguard --json --output "$REPORT"
echo "Report saved to: $REPORT"
echo "First 30 lines:"
head -30 "$REPORT"
echo ""

# ── Step 5: Automated tests
echo "STEP 5: Automated unit tests"
echo "─────────────────────────────"
python3 -m unittest discover -s tests -p "test_*.py" -v
echo ""

echo "================================================================"
echo "  Demonstration complete."
echo "  AlpineGuard made NO changes to the system."
echo "================================================================"
