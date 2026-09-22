"""
PoC for F-007: Storage corruption triggers runaway .bak file generation flood.
Runs entirely against isolated temporary storage.
"""
import time
import tempfile
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(BASE))

from models.storage_base import StorageBase, StorageCorruptionError

def test_bak_flood():
    with tempfile.TemporaryDirectory() as temp_dir:
        dir_path = Path(temp_dir)
        corrupt_file = dir_path / "intraday.json"
        corrupt_file.write_text("{damaged_json...", encoding="utf-8")

        storage = StorageBase(corrupt_file)

        # Simulate 3 consecutive ticks spaced by 1 second
        for i in range(3):
            try:
                storage._read_json()
            except StorageCorruptionError:
                pass
            time.sleep(1.05)

        bak_files = list(dir_path.glob("intraday_corrupted_*.bak"))
        print(f"Number of generated .bak files after 3 ticks: {len(bak_files)}")
        for b in bak_files:
            print(f" - {b.name}")

        assert len(bak_files) == 3, "Each corruption read produced a separate .bak file"
        print("[+] CONFIRMED F-007: Unbounded .bak file creation flood verified!")

if __name__ == "__main__":
    test_bak_flood()

