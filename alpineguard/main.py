"""
main.py — Package entry point.

Allows the package to be invoked as:
  python -m alpineguard

Delegates to cli.run() and exits with the returned status code.
"""

import sys
from .cli import run

if __name__ == "__main__":
    sys.exit(run())
