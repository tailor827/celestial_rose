import os
import sys
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(BASE))

from utils.clock import CLOCK
from app import create_app

class TestF033WaitingToCloseAndCrossLaneLeak(unittest.TestCase):
    """
    Adversarial PoC for F-033:
    Proves that force_open stickiness across lane lifecycles:
    1. Eliminates the WAITING_TO_CLOSE window (21:00-21:59), forcing OPEN state.
    2. Leaks out-of-window permission to other lanes that did not specify force_open.
    """
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.storage_dir = Path(self.tmpdir.name)
        os.environ["PARADISO_STORAGE_DIR"] = str(self.storage_dir)

    def tearDown(self):
        self.tmpdir.cleanup()
        os.environ.pop("PARADISO_STORAGE_DIR", None)

    def test_force_open_eliminates_waiting_to_close_and_leaks_cross_lane(self):
        app, paradiso = create_app(storage_dir=self.storage_dir)
        intra = paradiso.intraday_service

        # Operator started Lane A with force_open=True earlier
        intra.start_lane("type_a", force_open=True)

        try:
            # 1. Simulate evening wrap-up window at 21:15 (normally WAITING_TO_CLOSE)
            with patch.object(CLOCK, "time_24_str", return_value="21:15"):
                status = intra.resolve_status()

                # DEFECT DEMONSTRATION 1:
                # WAITING_TO_CLOSE is completely eliminated; status resolves as OPEN
                self.assertEqual(status, "OPEN",
                                 "F-033 Defect: force_open overrides WAITING_TO_CLOSE window.")

                # 2. Operator attempts to start Lane B WITHOUT force_open
                with app.test_client() as client:
                    res = client.post("/api/paradiso/lane/start", json={"lane": "type_b"})

                    # DEFECT DEMONSTRATION 2:
                    # HTTP 200 OK is returned because global force_open was True from Lane A!
                    self.assertEqual(res.status_code, 200,
                                     "F-033 Defect: Lane B started out-of-window without force_open flag.")
        finally:
            paradiso.stop()

if __name__ == "__main__":
    unittest.main()
