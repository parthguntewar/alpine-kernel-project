# AlpineGuard — Makefile
# Tested targets work on Alpine Linux (BusyBox make) and GNU make.

PYTHON   ?= python3
PIP      ?= pip3
VENV     := .venv
SRC      := alpineguard
TESTS    := tests

.PHONY: help install install-dev test lint clean run run-json demo

help:
	@echo "AlpineGuard — available targets:"
	@echo "  make install      Install alpineguard command (local, no venv)"
	@echo "  make install-dev  Install in editable mode for development"
	@echo "  make test         Run the automated test suite"
	@echo "  make lint         Run pyflakes static analysis"
	@echo "  make run          Run a full health report"
	@echo "  make run-json     Run and output JSON report"
	@echo "  make demo         Run demo sequence (report + JSON export)"
	@echo "  make clean        Remove compiled Python caches"

install:
	$(PIP) install --user .

install-dev:
	$(PIP) install --user -e .

test:
	$(PYTHON) -m unittest discover -s $(TESTS) -p "test_*.py" -v

lint:
	@which pyflakes >/dev/null 2>&1 && pyflakes $(SRC)/ || \
		echo "pyflakes not installed — skipping lint (pip install pyflakes)"

run:
	$(PYTHON) -m alpineguard

run-json:
	$(PYTHON) -m alpineguard --json

demo:
	@echo "=== AlpineGuard Demo ==="
	@echo ""
	@echo "--- 1. Version ---"
	$(PYTHON) -m alpineguard --version
	@echo ""
	@echo "--- 2. Full Health Report ---"
	$(PYTHON) -m alpineguard
	@echo ""
	@echo "--- 3. Warning Threshold Demo (mem-warn=1) ---"
	$(PYTHON) -m alpineguard --mem-warn 1 --disk-warn 1
	@echo ""
	@echo "--- 4. JSON Report Export ---"
	$(PYTHON) -m alpineguard --json --output /tmp/alpineguard_report.json
	@echo "JSON report saved to /tmp/alpineguard_report.json"
	@echo ""
	@echo "--- 5. Automated Tests ---"
	$(PYTHON) -m unittest discover -s $(TESTS) -p "test_*.py" -v
	@echo ""
	@echo "=== Demo Complete ==="

clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	rm -rf *.egg-info .pytest_cache dist build
