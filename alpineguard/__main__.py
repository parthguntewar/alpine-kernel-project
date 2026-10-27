"""
__main__.py — Standard entry point for 'python -m alpineguard'.
"""

import sys
from .cli import run

if __name__ == "__main__":
    sys.exit(run())
