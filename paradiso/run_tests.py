#!/usr/bin/env python3
"""
Paradiso Alter Test Suite Runner (Local Entry Point)
"""
import sys
import unittest
from pathlib import Path

PARADISO_DIR = Path(__file__).resolve().parent
if str(PARADISO_DIR) not in sys.path:
    sys.path.insert(0, str(PARADISO_DIR))

def main():
    test_dir = PARADISO_DIR / "tests"
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=str(test_dir), pattern="test_*.py", top_level_dir=str(PARADISO_DIR))
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)

if __name__ == "__main__":
    main()
