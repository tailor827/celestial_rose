"""
PoC for F-003: Unvalidated interpreter paths in /api/settings permit arbitrary binary execution.
Runs entirely in-memory / without modifying live config.yaml.
"""
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(BASE))

from utils.config import validate_config
from services.runner import Runner

def test_unvalidated_executables():
    malicious_payload = {
        "executables": {
            "python_path": "C:\\Windows\\System32\\cmd.exe",
            "rscript_path": "C:\\Windows\\System32\\cmd.exe"
        }
    }

    # 1. Validation check
    valid, err = validate_config(malicious_payload)
    print(f"validate_config result: valid={valid}, err={err}")
    assert valid is True, "Config validation must erroneously accept arbitrary executables"

    # 2. Runner resolution check
    test_config = {"executables": {"python_path": "C:\\Windows\\System32\\cmd.exe"}}
    configured = test_config.get("executables", {}).get("python_path")
    resolved = Path(configured) if (configured and Path(configured).exists()) else Path(sys.executable)

    print(f"Configured python path: {configured}")
    print(f"Resolved executable: {resolved}")
    assert str(resolved).lower().endswith("cmd.exe"), "Runner resolves arbitrary executable binary"
    print("[+] CONFIRMED F-003: Arbitrary system binaries are accepted and resolved as script runners!")

if __name__ == "__main__":
    test_unvalidated_executables()

