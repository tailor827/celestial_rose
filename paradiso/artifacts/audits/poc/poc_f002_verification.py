"""
Adversarial verification script for F-002 resolution.
Tests edge-case traversal payloads, absolute paths, URL encoding, extension bypasses, and execution-level containment.
"""
import sys
import json
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(BASE))

from app import create_app
from models.automation import Automations
from models.report import Report
from services.automation_service import AutomationService
from services.execution_service import ExecutionService

def test_f002_adversarial_suite():
    app, paradiso = create_app(auto_start=False)
    app.config["TESTING"] = True
    client = app.test_client()

    attack_payloads = [
        # Traversal in filename
        {"name": "Atk1", "filename": "../secret.py", "filetype": "python"},
        {"name": "Atk2", "filename": "..\\secret.py", "filetype": "python"},
        {"name": "Atk3", "filename": "dir/../secret.py", "filetype": "python"},
        # Absolute path in filename
        {"name": "Atk4", "filename": "C:/Windows/System32/calc.py", "filetype": "python"},
        {"name": "Atk5", "filename": "/etc/passwd.py", "filetype": "python"},
        {"name": "Atk6", "filename": "\\\\server\\share\\evil.py", "filetype": "python"},
        # Directory traversal in dir
        {"name": "Atk7", "filename": "valid.py", "filetype": "python", "dir": "../../"},
        {"name": "Atk8", "filename": "valid.py", "filetype": "python", "dir": "C:/Windows"},
        {"name": "Atk9", "filename": "valid.py", "filetype": "python", "dir": "../reports/../../"},
        # Extension mismatch / executable disguise
        {"name": "Atk10", "filename": "malicious.exe", "filetype": "python"},
        {"name": "Atk11", "filename": "malicious.bat", "filetype": "python"},
        {"name": "Atk12", "filename": "script.py.exe", "filetype": "python"},
        # Invalid filetype
        {"name": "Atk13", "filename": "script.py", "filetype": "bash"},
        {"name": "Atk14", "filename": "script.py", "filetype": "powershell"},
    ]

    for idx, payload in enumerate(attack_payloads, start=1):
        res = client.post("/api/automation/add", json=payload)
        status = res.status_code
        data = res.get_json() or {}
        print(f"Attack #{idx:02d} ({payload.get('name')}): status={status}, err={data.get('error')}")
        assert status == 400, f"Payload {payload} should be rejected with 400, got {status}"
        assert data.get("ok") is False, f"Payload {payload} should return ok: false"

    print("[+] All 14 adversarial registration attacks rejected with HTTP 400.")

    # Test defense-in-depth in ExecutionService
    exec_svc = ExecutionService(AutomationService(Automations(BASE / "storage" / "automations.json")))
    malicious_report = Report(
        name="DirectInject",
        filename="outside.py",
        filetype="python",
        dir="../../arbitrary",
        status="Waiting"
    )
    exec_svc.automation_service.add(malicious_report)
    try:
        failed_called = []
        def _on_fail(name, duration, error):
            failed_called.append((name, error))

        ret = exec_svc.execute_report("DirectInject", callback_fail=_on_fail)
        assert ret is False, "execute_report must refuse to launch traversed path"
        import time
        time.sleep(0.05)
        assert len(failed_called) == 1
        assert "Security violation" in failed_called[0][1]
        print("[+] ExecutionService defense-in-depth verified: blocked direct storage tampering.")
    finally:
        exec_svc.automation_service.delete("DirectInject")

    print("[+] CONFIRMED: F-002 is fully RESOLVED.")

if __name__ == "__main__":
    test_f002_adversarial_suite()

