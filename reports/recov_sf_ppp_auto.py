from pathlib import Path
from getpass import getuser
from datetime import datetime
from typing import Optional
from toolbox.toolbox import Datefuncs
from toolbox.datalib import DataUtil
from toolbox.standards import BAUSchema
from toolbox.pretty_print import Printer
from toolbox.paradiso_dump import ParadisoConstants, ParadisoDump

import polars as pl

WITH_ENDO = False  # make sure False, kaka endorse lang

class Paths:
    dir_root = Path(f'c:/users/{getuser()}/onedrive - unionbank of the philippines')
    dir_datasets = dir_root / 'orange reports automatic/in/datasets'
    dir_amr = dir_datasets / 'sf/amr'
    dir_coll = dir_root / 'collections'
    dir_sf = dir_coll / 'amr111b - samsung finance'
    dir_sf_prewoff = dir_datasets/ 'sf' / 'pre_woff'
    dir_sf_woff = dir_datasets/ 'sf' / 'woff'

    dir_out_sf_prewoff = dir_root / 'orange reports automatic/out/sf/pre_woff'
    dir_out_sf_woff = dir_root / 'orange reports automatic/out/sf/woff'

class RecovProd:
    """
    Standardized Recov productivity processor.
    """
    REPORT_PATTERN = 'active*'

    def __init__(self, curr, prev) -> None:
        self.du = DataUtil(schema=BAUSchema.schema)

        self.path_input = Paths.dir_sf_woff
        self.path_output = Paths.dir_out_sf_woff

        self.path_prod = Paths.dir_sf_woff / 'active' 
        self.path_amr = Paths.dir_amr

        self.addr_pres = pl.read_parquet(Paths.dir_datasets / 'sf/address_present.parquet')
        self.addr_perm = pl.read_parquet(Paths.dir_datasets / 'sf/address_permanent.parquet')

        self.date_curr = curr
        self.date_prev = prev

        self.missing_datasets = True
        self.exists_amr_curr =    (self.path_amr   / f'amr_{curr}.parquet').exists()
        self.exists_amr_prev =    (self.path_amr   / f'amr_{prev}.parquet').exists()
        self.exists_active_prev = (self.path_input / 'active' / f'active_{prev}.parquet').exists()
        # checking if files exists
        if (
            self.exists_amr_curr and
            self.exists_amr_prev and
            self.exists_active_prev
        ):
            self.missing_datasets = False

    def try_loading_datasets(self) -> bool:
        if self.missing_datasets:
            Printer.err('Missing dataset/s:')
            Printer.err('- curr amr'    if not self.exists_amr_curr    else '')
            Printer.err('- prev amr'    if not self.exists_amr_prev    else '')
            Printer.err('- prev active' if not self.exists_active_prev else '')
                        
            return False
        self.amr_curr0 = self.du.read(self.path_amr      / f'amr_{self.date_curr}.parquet')
        self.amr_prev0 = self.du.read(self.path_amr      / f'amr_{self.date_prev}.parquet')
        self.active_prev0 = self.du.read(self.path_input / 'active' / f'active_{self.date_prev}.parquet')
        return True
        
    def get_prod(self, date):
        return self.du.read(self.path_input / 'active' / f'active_{date}.parquet')

    def create_prod(self):
        active_prev = (
            self.amr_prev0
            .filter(pl.col('e_loan_no').is_in(self.active_prev0['loan_no'].implode()))
            .rename({
                'os_balance': 'prev_balance',
                'e_loan_no': 'loan_no',
                'gmi_amt' : 'mi'
            })
            .with_columns(pl.col("prev_balance").str.strip_chars().cast(pl.Float64))
            .select(pl.col([
                'loan_no', 'prev_balance', 'mi', 'booking_date'
            ]))
            .unique(subset=['loan_no'])
        )
        # print(self.amr_curr0.filter('e_loan_no' == 'SP00000006268801'))
        active_curr = (
            self.amr_curr0
            .filter(pl.col('e_loan_no').is_in(active_prev['loan_no'].implode()))
            .rename({
                'os_balance': 'curr_balance',
                'e_loan_no': 'loan_no',
            })
            .with_columns(
                pl.col("curr_balance").str.strip_chars().cast(pl.Float64),
            )
            .select(pl.col([
                'loan_no', 'curr_balance'
            ]))
            .unique(subset=['loan_no'])
        )

        active_prev0_simple = (
            self.active_prev0
            .select(pl.col([
                'loan_no', 'name', 'months_past_due', 'amount_past_due', 'endo_date',
                'customer_id', 'contact_number', 'email', 'zip', 'agency'
            ]))
        )

        bal_diff = (
            active_prev
            .join(active_curr, on='loan_no', how='left')
            .with_columns(pl.col('curr_balance').fill_null(0))
            .with_columns(
                (pl.col('prev_balance') - pl.col('curr_balance')).alias('payment'),
                pl.when(
                    ~pl.col('loan_no').is_in(active_curr['loan_no'].implode()))
                    .then(pl.lit('missing'))
                    .otherwise(pl.lit('exists'))
                    .alias('remarks'),
            )
            .sort(pl.col('payment'), descending=True)
            .join(active_prev0_simple,on='loan_no',how='left')
            .rename({
                'curr_balance': 'balance'
            })
            .select(pl.col([
                'loan_no','endo_date','mi','balance', 'booking_date',
                'payment','remarks','agency','name','months_past_due','amount_past_due',
                'customer_id','contact_number','email','zip']))
        )

        self.payments = bal_diff.filter(pl.col('payment') > 0).with_columns(pl.lit(self.date_curr).alias('post_date'))
        self.closed =   bal_diff.filter(pl.col('balance') == 0)
        self.active =   bal_diff.filter(pl.col('balance') != 0).select(pl.exclude('payment'))
        return self
    
    def append_endorsement(self, with_endo: bool = False, endo_date: Optional[str] = None):
        if not with_endo:
            return self
        endo_path = Path(self.path_input) / "endorsements" / f"endorsements_{self.date_curr}.parquet"
        endo0 = self.du.read(endo_path)

        endo_agency = endo0.select([
            'loan_no', 'agency'
        ]).unique(subset='loan_no')

        amr_renamed = (
            self.amr_curr0
            .rename({
                "e_loan_no": "loan_no",
                "os_balance": "balance",
                "gmi_amt": "mi",  
            })
        )

        endo = (
            amr_renamed
            .join(endo_agency, on="loan_no", how="inner")
            .with_columns([
                # strip whitespace then cast
                pl.col("balance").str.strip_chars().cast(pl.Float64).alias("balance"),
                pl.lit(self.date_curr if endo_date is None else endo_date).alias("endo_date"),
            ])
            .select([
                "loan_no", "agency",  "endo_date", "balance", "mi"
            ])
            .with_columns(agency=pl.col('agency').str.to_uppercase())
        )

        amr_curr0_simple = (
            self.amr_curr0
            .rename({
                "e_loan_no": "loan_no",
                "months_pd": "months_past_due",
                "amt_pdue": "amount_past_due",
                "cust_id": "customer_id"
            })
            .select([
                "loan_no", "name", "months_past_due", "amount_past_due",
                "customer_id", "contact_number", "email", "zip", 'booking_date'
            ])
        )

        endo = (
            endo
            .join(amr_curr0_simple, on="loan_no", how="left")
            .with_columns(pl.lit("new endorsement").alias("remarks"))
            .select([
                "loan_no","endo_date","mi","balance", 'booking_date',
                "remarks","agency","name","months_past_due","amount_past_due",
                "customer_id","contact_number","email","zip"
            ])
        )

        print(endo.columns)
        print(self.active.columns)

        # append
        self.active = (
            self
            .active
            .join(endo, on='loan_no', how='anti')
            .vstack(endo)
            # .with_columns(pl.col('customer_id').cast(pl.Int32))
            .join(self.addr_perm, on='customer_id', how='left')
            .join(self.addr_pres, on='customer_id', how='left')
            .unique(subset='loan_no')
        )

        return self
 
    def save_files(self):
        _input = self.path_input
        _output = self.path_output

        self.payments.write_parquet(_input / 'payments' / f'payments_{self.date_curr}.parquet')
        self.closed.write_parquet(  _input / 'closed'   / f'closed_{self.date_curr}.parquet')
        self.active.write_parquet(  _input / 'active'   / f'active_{self.date_curr}.parquet')

        self.payments.to_pandas().to_excel(_output / 'payments' / f'payments_{self.date_curr}.xlsx', index=False)
        self.closed.to_pandas().to_excel(  _output / 'closed'   / f'closed_{self.date_curr}.xlsx',   index=False)
        self.active.to_pandas().to_excel(  _output / 'active'   / f'active_{self.date_curr}.xlsx',   index=False)

        return self
    
    def print_summary(self):
        Printer.ok(f'Output Summary: [{self.date_curr}]')
        Printer.ok(f'  - Payments: {self.payments.height}')
        Printer.ok(f'  - Pullout : {self.closed.height}')
        Printer.ok(f'  - Prod  : {self.active.height}')
        print()
        # print prod endo date summary
        active_endo_summary = (
            self.active
            .group_by('endo_date', 'agency')
            .agg(pl.count('loan_no').alias('count_endo'))
            .sort('endo_date')
        )

        payments_summary = (
            self.payments
            .group_by('agency')
            .agg(pl.len().alias('count_payments'))
            .sort('agency')
        )
        
        Printer.ok('payment breakdown:')
        # to_dicts() produces a list of dicts like {'endo_date': ..., 'count_loans': ...}
        for rec in payments_summary.to_dicts():
            agency = rec.get('agency')
            count = rec.get('count_payments', 0)
            Printer.ok(f'  - {agency}: {count}')

        Printer.ok('Endo date breakdown:')
        # to_dicts() produces a list of dicts like {'endo_date': ..., 'count_loans': ...}
        for rec in active_endo_summary.to_dicts():
            endo_date = rec.get('endo_date')
            endo_agcy = rec.get('agency')
            count = rec.get('count_endo', 0)
            Printer.ok(f'  - {endo_agcy} {endo_date}: {count}')

        total_loans = active_endo_summary['count_endo'].sum()
        Printer.ok(f'Total active (by endo_date): {int(total_loans)}')
        
def auto_run():
    date_now = datetime.now().strftime(format = '%Y%m%d')
    # get latest successful AMR date
    last_run = max(
        (Paths.dir_sf_woff/'active').glob("active_*.parquet"),
        key=lambda x: x.stem
    ).stem.replace("active_", "")

    paradiso_start = Datefuncs.offset(last_run, 1)
    paradiso_end   = Datefuncs.offset(date_now, -1)

    index_date = paradiso_start

    while index_date <= paradiso_end:
        index_prev = Datefuncs.offset(index_date, -1)
        print((index_date, index_prev))
        ppp = RecovProd(index_date, index_prev)
        pppok = ppp.try_loading_datasets()

        if pppok:
            (
                ppp
                .create_prod()
                .append_endorsement(WITH_ENDO, index_date)
                .save_files()
                .print_summary()
            )
        else:
            raise Exception('missing dependency')
        
        index_date = Datefuncs.offset(index_date, 1)

    return paradiso_end

import traceback
def main() -> int:
    for_rerun = False
    try:
        last_output: str = auto_run()
        status: str = ParadisoConstants.COMPLETED if not for_rerun else ParadisoConstants.ERROR
        ParadisoDump().dump(
            status=status,
            name="recov_sf_ppp_auto.py",
            last_output=last_output,
            log="Completed successfully."
        )
        return 0
    except Exception as exc:
        print(f"Error during auto_read: {exc}")
        traceback.print_exc()
        ParadisoDump().dump(
            status=ParadisoConstants.RETRIAL,
            name="recov_sf_ppp_auto.py",
            last_output='Unavailable',
            log=str(exc)
        )
        return 1
    
if __name__ == "__main__":
    raise SystemExit(main())











