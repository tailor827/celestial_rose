#!/usr/bin/env python3
"""
Paradiso Alter Test Suite Runner
Discovers and executes all unit and regression test modules.
"""
import sys
import unittest
from pathlib import Path

# Ensure paradiso directory is on sys.path
SCRIPT_DIR = Path(__file__).resolve().parent
if (SCRIPT_DIR / "paradiso").exists():
    PARADISO_DIR = SCRIPT_DIR / "paradiso"
else:
    PARADISO_DIR = SCRIPT_DIR

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
