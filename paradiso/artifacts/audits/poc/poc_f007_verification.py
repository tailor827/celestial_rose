"""
Adversarial verification script for F-007 (Storage Corruption Rescue Backup Deduplication).
Tests rapid repeated reads, reboot simulation, mtime touch without content change,
content mutations, and the 5-backup rotation ceiling.
"""
import os
import sys
import time
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(BASE))

from models.storage_base import StorageBase, StorageCorruptionError

class TestF007AdversarialVerification(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.dir_path = Path(self.temp_dir.name)
        self.file_path = self.dir_path / "automations.json"

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_rapid_ticks_do_not_flood(self):
        """Attacks F-007: 20 rapid consecutive ticks on a corrupted file produce exactly 1 backup."""
        self.file_path.write_text("{bad_json_payload...", encoding="utf-8")
        storage = StorageBase(self.file_path)

        for _ in range(20):
            with self.assertRaises(StorageCorruptionError):
                storage._read_json()

        baks = list(self.dir_path.glob("automations_corrupted_*.bak"))
        self.assertEqual(len(baks), 1, f"Expected exactly 1 backup, found {len(baks)}")

    def test_reboot_simulation_does_not_create_duplicate(self):
        """Attacks F-007: Simulates application reboot with memory wiped while file remains corrupted."""
        self.file_path.write_text("{corrupt_state_1...", encoding="utf-8")
        storage = StorageBase(self.file_path)

        # First read creates initial backup
        with self.assertRaises(StorageCorruptionError):
            storage._read_json()

        # Simulate cold reboot: wipe in-memory state dictionary
        StorageBase._global_corrupted_states.clear()

        # Read again on fresh instance
        fresh_storage = StorageBase(self.file_path)
        with self.assertRaises(StorageCorruptionError):
            fresh_storage._read_json()

        baks = list(self.dir_path.glob("automations_corrupted_*.bak"))
        self.assertEqual(len(baks), 1, "Cold boot must recognize existing identical backup and avoid duplicating.")

    def test_mtime_touch_without_content_change_deduped(self):
        """Attacks F-007: Timestamp changed via os.utime, but content unchanged."""
        self.file_path.write_text("{corrupt_state_touch...", encoding="utf-8")
        storage = StorageBase(self.file_path)

        with self.assertRaises(StorageCorruptionError):
            storage._read_json()

        # Touch file to change mtime
        time.sleep(0.05)
        new_time = time.time() + 100
        os.utime(str(self.file_path), (new_time, new_time))

        with self.assertRaises(StorageCorruptionError):
            storage._read_json()

        baks = list(self.dir_path.glob("automations_corrupted_*.bak"))
        self.assertEqual(len(baks), 1, "Touching mtime without content change must not trigger duplicate backup.")

    def test_backup_rotation_ceiling_capped_at_five(self):
        """Attacks F-007: 10 distinct corruption events must cap total .bak files at 5."""
        storage = StorageBase(self.file_path)

        for i in range(10):
            time.sleep(0.02)
            self.file_path.write_text(f"{{bad_json_version_{i}...", encoding="utf-8")
            with self.assertRaises(StorageCorruptionError):
                storage._read_json()

        baks = list(self.dir_path.glob("automations_corrupted_*.bak"))
        self.assertLessEqual(len(baks), 5, f"Backup count exceeded 5! Found {len(baks)} backups.")
        self.assertEqual(len(baks), 5, "Expected exactly 5 latest backups retained.")

if __name__ == "__main__":
    unittest.main()
