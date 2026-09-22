import unittest
import tempfile
from pathlib import Path
from models.storage_base import StorageBase
from models.automation import Automations
from models.report import Report
from models.intraday import Intraday, IntradayDay, ReportRun
from models.report_log import ReportLog

class TestStorageModels(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.test_dir.name)

    def tearDown(self):
        self.test_dir.cleanup()

    def test_storage_base_atomic_read_write(self):
        file_path = self.dir_path / "test_storage.json"
        storage = StorageBase(file_path)
        
        # Test initial read empty
        data = storage._read_json()
        self.assertEqual(data, {})

        # Test write and read back
        sample = {"key": "value", "count": 42}
        storage._write_json(sample)
        read_back = storage._read_json()
        self.assertEqual(read_back, sample)
        self.assertTrue(file_path.exists())

    def test_automation_storage(self):
        file_path = self.dir_path / "automations.json"
        auto_repo = Automations(file_path)
        
        # Write sample automation dataset
        sample_data = {
            "CC_Collection_Summary": {
                "name": "CC_Collection_Summary",
                "team": "Finance",
                "scheduled_time": "08:00",
                "status": "Waiting",
                "duration": "--",
                "started_at": "--",
                "filename": "cc_summary.py",
                "dir": "reports",
                "filetype": "python"
            }
        }
        auto_repo._write_json(sample_data)

        retrieved = auto_repo.get_by_name("CC_Collection_Summary")
        self.assertIsNotNone(retrieved)
        self.assertEqual(retrieved.team, "Finance")

        # Test add/update report object
        retrieved.status = "Completed"
        retrieved.duration = "12s"
        auto_repo.add(retrieved)

        updated = auto_repo.get_by_name("CC_Collection_Summary")
        self.assertEqual(updated.status, "Completed")
        self.assertEqual(updated.duration, "12s")

    def test_intraday_storage(self):
        file_path = self.dir_path / "intraday.json"
        intraday_repo = Intraday(file_path)

        today_date = "20260906"
        day = IntradayDay(
            date=today_date,
            status=Intraday.OPEN,
            expected_reports=["CC_Collection_Summary"],
            reports_ran={},
            timeline=[]
        )
        intraday_repo.add_day(day)

        retrieved_day = intraday_repo.get_day(today_date)
        self.assertIsNotNone(retrieved_day)
        self.assertEqual(retrieved_day.status, Intraday.OPEN)

        # Test add timeline event
        intraday_repo.add_timeline_event(today_date, "Test Event", "Description", "system")
        updated_day = intraday_repo.get_day(today_date)
        self.assertEqual(len(updated_day.timeline), 1)
        self.assertEqual(updated_day.timeline[0].title, "Test Event")

        # Test add report run
        run = ReportRun(started_at="08:00", finished_at="08:01", result="completed", duration="60s", reason="Clean exit")
        intraday_repo.add_report_run(today_date, "CC_Collection_Summary", run)
        final_day = intraday_repo.get_day(today_date)
        self.assertIn("CC_Collection_Summary", final_day.reports_ran)
        self.assertEqual(final_day.reports_ran["CC_Collection_Summary"].result, "completed")

    def test_report_log_parsing(self):
        log = ReportLog("test_report")
        status_skipped = log.parse_output("Execution SKIPPED: missing dependency table_a")
        self.assertEqual(status_skipped, "Skipped")

        status_failed = log.parse_output("Traceback error: division by zero")
        self.assertEqual(status_failed, "Failed")

        status_ok = log.parse_output("Successfully processed 100 rows.")
        self.assertEqual(status_ok, "Completed")

    def test_storage_base_concurrent_mutations_no_lost_updates(self):
        """Verifies concurrent mutate() calls execute atomically without lost updates."""
        import threading
        file_path = self.dir_path / "concurrent_test.json"
        storage = StorageBase(file_path)
        storage.mutate(lambda d: d.update({"count": 0}))

        def worker():
            for _ in range(10):
                def inc(d):
                    d["count"] = d.get("count", 0) + 1
                storage.mutate(inc)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        data = storage._read_json()
        self.assertEqual(data.get("count"), 100)

if __name__ == "__main__":
    unittest.main()

