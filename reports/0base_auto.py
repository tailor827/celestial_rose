from pathlib import Path
from getpass import getuser
from datetime import datetime
from toolbox import toolbox
from toolbox.paradiso_dump import ParadisoConstants, ParadisoDump
import pandas as pd
import polars as pl

class Paths:
    dir_root = Path(f'c:/users/{getuser()}/onedrive - unionbank of the philippines')
    dir_datasets = dir_root / 'orange reports automatic/in/datasets'
    dir_amr = dir_datasets / 'sf/amr'
    dir_coll = dir_root / 'collections'
    dir_sf = dir_coll / 'amr111b - samsung finance'

class AMRRreader:
    ok_run = 0
    missing_file = 1
    missing_directory = 2

    def __init__(self, date: str):
        if len(date) != 8 or not date.isdigit():
            raise ValueError("date must be YYYYMMDD (8 digits)")

        yy = date[2:4]
        mm = int(date[4:6])
        dd = int(date[6:8])
        raw = f"{mm}.{dd}.{yy}"

        self.date = date
        # typed Paths
        self.input_excel_file: Path = Paths.dir_sf / date / f"amr111b {raw}.xlsx"
        self.output_parquet_file: Path = Paths.dir_amr / f"amr_{date}.parquet"

        # internal placeholders
        self._raw_file = None
        self._base_file = None

    def exists(self) -> bool:
        """Explicit, manual check. No mkdir; fail loudly if missing.""" 
        print(self.input_excel_file)
        if not self.input_excel_file.exists():
            return False
        # also check the expected output parent dir (we do not create it)
        if not self.output_parquet_file.parent.exists():
            return False
        return True

    def read_base_file(self) -> None:
        """Read Excel via pandas, convert to polars, filter SAMSUNG rows."""
        try:
            self._raw_file = pd.read_excel(self.input_excel_file, engine="openpyxl", dtype=str)
        except Exception as exc:
            print(f"Failed to read excel: {exc}")
            raise Exception(f'missing / corrupted file')

        # convert to polars and filter
        self._base_file = (
            pl.from_pandas(self._raw_file)
            .with_columns([pl.col(c).cast(pl.Utf8) for c in self._raw_file.columns])
            .filter(pl.col("DEVELOPER NAME") == "SAMSUNG")
        )

    def save_file(self) -> None:
        """Write parquet to the path, assumes parent dir already exists (no mkdir)."""
        if self._base_file is None:
            raise RuntimeError("No data to save. Call read_base_file() first.")

        # explicit safety: check parent exists before writing
        parent = self.output_parquet_file.parent
        if not parent.exists():
            print(f"Output directory does not exist: {parent} (won't create).")
            raise FileNotFoundError(parent)

        rows = self._base_file.height
        print(f"Saved with {rows} rows: {self.output_parquet_file.name}")
        self._base_file.write_parquet(self.output_parquet_file)


def auto_run() -> str:
    date_now = datetime.now().strftime(format = '%Y%m%d')
    # get latest successful AMR date
    last_run = max(
        Paths.dir_amr.glob("amr_*.parquet"),
        key=lambda x: x.stem
    ).stem.replace("amr_", "")

    paradiso_start = toolbox.Datefuncs.offset(last_run, 1)
    paradiso_end   = toolbox.Datefuncs.offset(date_now, -1)

    index_date = paradiso_start

    while index_date <= paradiso_end:
        print(f'SF reading amr: {index_date}')
        amr = AMRRreader(index_date)
        if amr.exists():
            amr.read_base_file()
            amr.save_file()
        else:
            raise Exception('missing dependency')
        index_date = toolbox.Datefuncs.offset(index_date, 1)
    return paradiso_end

def main() -> int:
    for_rerun = False
    try:
        last_output: str = auto_run()
        status: str = ParadisoConstants.COMPLETED if not for_rerun else ParadisoConstants.ERROR
        ParadisoDump().dump(
            status=status,
            name="0base_auto.py",
            last_output=last_output,

            log="Completed successfully."
        )
        return 0
    except Exception as exc:
        print(f"Error during auto_read: {exc}")
        ParadisoDump().dump(
            status=ParadisoConstants.RETRIAL,
            name="0base_auto.py",
            last_output='Unavailable',

            log=str(exc)
        )
        return 1
    
if __name__ == "__main__":
    raise SystemExit(main())







