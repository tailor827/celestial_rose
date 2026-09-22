from pathlib import Path
from getpass import getuser
from datetime import datetime
from toolbox.toolbox import Datefuncs
from toolbox.datalib import DataUtil
from toolbox.standards import BAUSchema
from toolbox.pretty_print import Printer
from toolbox.paradiso_dump import ParadisoConstants, ParadisoDump

import pandas as pd
import polars as pl

# make sure to not overwrite last run by cy - DATE_CURR = "20251110" 

WITH_ENDO = False  # make sure False, kaka endorse lang
UPDATE_ENDO_BUCKET = False # update pag start of month

class Paths:
    dir_root = Path(f'c:/users/{getuser()}/onedrive - unionbank of the philippines')
    dir_datasets = dir_root / 'orange reports automatic/in/datasets'
    dir_amr = dir_datasets / 'sf/amr'
    dir_coll = dir_root / 'collections'
    dir_sf = dir_coll / 'amr111b - samsung finance'
    dir_sf_prewoff = dir_datasets/ 'sf' / 'pre_woff'

    dir_out_sf_prewoff = dir_root / 'orange reports automatic/out/sf/pre_woff'

class EcaProd:
    """
    Ongoing pa enhancements
    """
    REPORT_PATTERN = 'prod*'

    def __init__(self, curr, prev, with_endo, update_endo_bucket) -> None:
        self.du = DataUtil(schema=BAUSchema.schema)

        self.path_input = Paths.dir_sf_prewoff
        self.path_output = Paths.dir_out_sf_prewoff

        self.path_prod = Paths.dir_sf_prewoff / 'prod' 
        self.path_amr = Paths.dir_amr

        self.date_curr = curr
        self.date_prev = prev
        self.with_endo = with_endo
        self.update_endo_bucket = update_endo_bucket
        
        self.missing_datasets = True
        self.exists_amr_curr =    (self.path_amr   / f'amr_{curr}.parquet').exists()
        self.exists_amr_prev =    (self.path_amr   / f'amr_{prev}.parquet').exists()
        self.exists_prod_prev =   (self.path_input / 'prod' / f'prod_{prev}.parquet').exists()
        print(self.path_amr   / f'amr_{curr}.parquet')
        # checking if files exists
        if (
            self.exists_amr_curr and
            self.exists_amr_prev and
            self.exists_prod_prev
        ):
            self.missing_datasets = False

    def assign_bucket(self, alias) -> pl.Expr:
        return (pl.when((pl.col('age') <= 0) | pl.col('age').is_null()).then(pl.lit('b0'))
                .when(pl.col('age') <= 29) .then(pl.lit('b1'))
                .when(pl.col('age') <= 59) .then(pl.lit('b2'))
                .when(pl.col('age') <= 89) .then(pl.lit('b3'))
                .when(pl.col('age') <= 119).then(pl.lit('b4'))
                .when(pl.col('age') <= 149).then(pl.lit('b5'))
                .when(pl.col('age') <= 179).then(pl.lit('b6'))
                .when(pl.col('age') > 179).then(pl.lit('wo'))
                .alias(alias)) 

    def try_loading_datasets(self) -> bool:
        if self.missing_datasets:
            Printer.err('Missing dataset/s:')
            Printer.err(f'  curr amr: {self.date_curr}'    if not self.exists_amr_curr    else '')
            Printer.err(f'  prev amr: {self.date_prev}'    if not self.exists_amr_prev    else '')
            Printer.err(f'  prev prod: {self.date_prev}'   if not self.exists_prod_prev   else '')
                        
            return False
        self.amr_curr0  = self.du.read(self.path_amr   / f'amr_{self.date_curr}.parquet')
        self.amr_prev0  = self.du.read(self.path_amr   / f'amr_{self.date_prev}.parquet')
        self.prod_prev0 = self.du.read(self.path_input / 'prod' / f'prod_{self.date_prev}.parquet')

        return True
    
    def get_prod(self, date):
        return self.du.read(self.path_input / 'prod' / f'prod_{date}.parquet')

    def create_prod(self):
  
        prod_prev = (
            self.amr_prev0
            .filter(pl.col('e_loan_no').is_in(self.prod_prev0['loan_no'].implode()))
            .rename({
                'os_balance': 'prev_balance',
                'e_loan_no': 'loan_no',
                'gmi_amt' : 'mi'
            })
            .with_columns(
                pl.col("age").str.strip_chars().cast(pl.Float64).alias("age"),
                pl.col("prev_balance").str.strip_chars().cast(pl.Float64))
            .with_columns(self.assign_bucket('prev_bucket'))
            .select(pl.col([
                'loan_no', 'prev_bucket', 'prev_balance', 'mi'
            ]))
            .unique(subset=['loan_no'])
        )

        prod_curr = (
            self.amr_curr0
            .filter(pl.col('e_loan_no').is_in(prod_prev['loan_no'].implode()))
            .rename({
                'os_balance': 'curr_balance',
                'e_loan_no': 'loan_no',
            })
            .with_columns(
                pl.col("age").str.strip_chars().cast(pl.Float64).alias("age"),
                pl.col("curr_balance").str.strip_chars().cast(pl.Float64),
            )
            .with_columns(self.assign_bucket('curr_bucket'))
            .select(pl.col([
                'loan_no', 'curr_bucket', 'curr_balance'
            ]))
            .unique(subset=['loan_no'])
        )

        prod_prev0_simple = (
            self.prod_prev0
            .select(pl.col([
                'loan_no', 'name', 'months_past_due', 'amount_past_due', 
                'endo_bucket', 'endo_date', 'endo_balance','agency', 
                'customer_id', 'contact_number', 'email', 'zip'
            ]))
        )

        bal_diff = (
            prod_prev
            .join(prod_curr, on='loan_no', how='left')
            .with_columns(pl.col('curr_balance').fill_null(0))
            .with_columns(
                pl.col('curr_bucket').fill_null('b0'),
                (pl.col('prev_balance') - pl.col('curr_balance')).alias('payment'),
                pl.when(
                    ~pl.col('loan_no').is_in(prod_curr['loan_no'].implode()))
                    .then(pl.lit('missing'))
                    .otherwise(pl.lit('exists'))
                    .alias('remarks'),
            )
            .sort(pl.col('payment'), descending=True)
            .join(prod_prev0_simple,on='loan_no',how='left')
            .rename({
                'curr_bucket': 'bucket',
                'curr_balance': 'balance'
            })
            .select(pl.col([
                'loan_no','endo_bucket','endo_date','endo_bucket','endo_balance','mi','bucket','balance',
                'payment','remarks','agency','name','months_past_due','amount_past_due',
                'customer_id','contact_number','email','zip']))
        )

        self.payments = (
            bal_diff
            .filter(pl.col('payment') > 0)
            .with_columns(pl.lit(self.date_prev).alias('post_date'))
        )

        if self.update_endo_bucket:
            bal_diff = (
                bal_diff
                .with_columns(
                    pl.col('bucket').alias('endo_bucket'),
                    pl.lit(self.date_curr).alias('endo_date')
                )
            )

        self.pullout = bal_diff.filter((pl.col('bucket').is_in(['b0','wo']))) 
        self.prod = bal_diff.filter(~(pl.col('bucket').is_in(['b0', 'wo']))).select(pl.exclude('payment'))

        return self
    
    def append_endorsement(self):
        if not self.with_endo:
            return self
        endo_path = self.path_input / 'endorsements' / f'endorsements_{self.date_curr}.parquet'
        endo0 = self.du.read(endo_path)
        endo_specs = (
            endo0
            .with_columns(
                pl.lit(self.date_curr).alias('endo_date')
            )
            .select(
                pl.col(['loan_no', 'agency', 'endo_date', 'endo_bucket', 'endo_balance'])
            )
        )

        endo = (
            self.amr_curr0
            .filter(pl.col('e_loan_no').is_in(endo0['loan_no'].implode()))
            .rename({
                'os_balance'   : 'balance',
                'e_loan_no': 'loan_no',
                'gmi_amt'      : 'mi'
            })
            .join(endo_specs, on='loan_no', how='left')
            .select(pl.col([
                'loan_no', 'agency', 'endo_bucket', 'endo_date', 'endo_balance', 'balance', 'mi'
            ]))
        )

        amr_curr0_simple = (
            self.amr_curr0
            .rename({
                'e_loan_no' : 'loan_no',
                'months_pd' : 'months_past_due',
                'amt_pdue' : 'amount_past_due',
                'cust_id' : 'customer_id'
            })
            .select(pl.col([
                'loan_no', 'name', 'months_past_due', 'amount_past_due', 
                'customer_id', 'contact_number', 'email', 'zip'
            ]))
        )
        endo = (
            endo
            .join(amr_curr0_simple, on='loan_no', how='left')
            .with_columns(
                pl.lit('new endorsement').alias('remarks'),
                pl.col('endo_bucket').alias('bucket'),
                pl.col('endo_balance').cast(pl.Float64).alias('balance')
            )
            .select(pl.col([
                'loan_no','endo_bucket','endo_date','endo_balance','mi','bucket','balance',
                'remarks','agency','name','months_past_due','amount_past_due',
                'customer_id','contact_number','email','zip']))
        )

        # append endo to prod like dplyr rbind
        self.prod = (
            self.prod
            .join(endo, on='loan_no', how='anti')
            .vstack(endo).unique(subset=['loan_no'])
        )

        Printer.ok(f"Appended endorsements: {endo.height} rows")
        return self
    
    def save_parquet(self):
        self.prod.write_parquet(self.path_input / 'prod' / f'prod_{self.date_curr}.parquet')
        print(self.path_input / 'prod' / f'prod_{self.date_curr}.parquet')
        self.payments.write_parquet(self.path_input / 'payments' / f'payments_{self.date_curr}.parquet')
        self.pullout.write_parquet(self.path_input / 'pullout' / f'pullout_{self.date_curr}.parquet')

        return self
    
    def save_excel(self):
        self.payments.to_pandas().to_excel(self.path_output /'payments'/f'payments_{self.date_curr}.xlsx', index=False)
        self.pullout.to_pandas().to_excel(self.path_output/'pullout'/f'pullout_{self.date_curr}.xlsx', index=False)
        self.prod.to_pandas().to_excel(self.path_output/'prod'/f'prod_{self.date_curr}.xlsx', index=False)

        self.payments.filter(pl.col('agency').eq('BERN')).write_excel(self.path_output /'payments'/f'BERN_payments_{self.date_curr}.xlsx')
        self.pullout.filter(pl.col('agency').eq('BERN')).write_excel(self.path_output/'pullout'/f'BERN_pullout_{self.date_curr}.xlsx')
        self.prod.filter(pl.col('agency').eq('BERN')).write_excel(self.path_output/'prod'/f'BERN_prod_{self.date_curr}.xlsx')

        self.payments.filter(pl.col('agency').eq('SPMA')).write_excel(self.path_output /'payments'/f'SPMA_payments_{self.date_curr}.xlsx')
        self.pullout.filter(pl.col('agency').eq('SPMA')).write_excel(self.path_output/'pullout'/f'SPMA_pullout_{self.date_curr}.xlsx')
        self.prod.filter(pl.col('agency').eq('SPMA')).write_excel(self.path_output/'prod'/f'SPMA_prod_{self.date_curr}.xlsx')

        return self
    
    def segment_summary(self, df:pl.DataFrame, segment_col:str) -> pl.DataFrame:
        summary = (
            df
            .group_by(segment_col)
            .agg(pl.count('loan_no').alias('count_accounts'))
            .sort(segment_col)
        )
        return summary

    def print_summary(self):
        day = Datefuncs.print_weekday(self.date_curr)
        Printer.ok(f'Output Summary: [{day} - {self.date_curr}]')

        Printer.ok(f'    Payments: {self.payments.height}')
        payments_summary = self.segment_summary(self.payments, 'endo_bucket')
        for rec in payments_summary.to_dicts():
            bucket = rec.get('endo_bucket')
            count = rec.get('count_accounts', 0)
            Printer.ok(f'        endo {bucket}: {count}')

        Printer.ok(f'    Pullout: {self.pullout.height}')
        pullout_summary = self.segment_summary(self.pullout, 'bucket')
        for rec in pullout_summary.to_dicts():
            bucket = rec.get('bucket')
            count = rec.get('count_accounts', 0)
            Printer.ok(f'        curr buc {bucket}: {count}')
        Printer.ok(f'    Prod: {self.prod.height}')
        prod_summary = self.segment_summary(self.prod, 'bucket')
        for rec in prod_summary.to_dicts():
            bucket = rec.get('bucket')
            count = rec.get('count_accounts', 0)
            Printer.ok(f'        curr buc {bucket}: {count}')

        Printer.ok('Endo date breakdown:')
        # to_dicts() produces a list of dicts like {'endo_date': ..., 'count_loans': ...}
        # print prod endo date summary
        prod_endo_summary = self.segment_summary(self.prod, 'endo_date')
        for rec in prod_endo_summary.to_dicts():
            endo_date = rec.get('endo_date')
            count = rec.get('count_accounts', 0)
            Printer.ok(f'    {endo_date}: {count}')
        
        Printer.ok('Endo bucket breakdown:')
        prod_bucket_summary = (
            self.prod
            .group_by('agency','endo_bucket')
            .agg(pl.count('loan_no').alias('count_accounts'))
            .sort('endo_bucket')
        )
        for rec in prod_bucket_summary.to_dicts():
            endo_bucket = rec.get('endo_bucket')
            endo_agency = rec.get('agency')
            count = rec.get('count_accounts', 0)
            Printer.ok(f'    {endo_agency} - {endo_bucket}: {count}')

        total_accs = prod_endo_summary['count_accounts'].sum()
        Printer.ok(f'Total accounts (by endo_date): {int(total_accs)}')
        
def auto_run():
    date_now = datetime.now().strftime(format = '%Y%m%d')
    # get latest successful AMR date
    last_run = max(
        (Paths.dir_sf_prewoff/'prod').glob("prod_*.parquet"),
        key=lambda x: x.stem
    ).stem.replace("prod_", "")

    paradiso_start = Datefuncs.offset(last_run, 1)
    paradiso_end   = Datefuncs.offset(date_now, -1)

    index_date = paradiso_start

    while index_date <= paradiso_end:
        index_prev = Datefuncs.offset(index_date, -1)
        ppp = EcaProd(
            index_date, 
            index_prev,
            WITH_ENDO,
            UPDATE_ENDO_BUCKET
        )
        pppok = ppp.try_loading_datasets()
        if pppok:
            (
                ppp
                .create_prod()
                .append_endorsement()
                .save_excel()
                .save_parquet()
                .print_summary()
            )
        else:
            raise Exception('missing dependency')
        
        index_date = Datefuncs.offset(index_date, 1)
    return paradiso_end

def main() -> int:
    for_rerun = False
    try:
        last_output: str = auto_run()
        status: str = ParadisoConstants.COMPLETED if not for_rerun else ParadisoConstants.ERROR
        ParadisoDump().dump(
            status=status,
            name="eca_sf_ppp_auto.py",
            last_output=last_output,
            log="Completed successfully."
        )
        return 0
    except Exception as exc:
        print('saving as retrial')
        print(f"Error during auto_read: {exc}")
        ParadisoDump().dump(
            status=ParadisoConstants.RETRIAL,
            name="eca_sf_ppp_auto.py",
            last_output='Unavailable',
            log=str(exc)
        )
        return 1
    
if __name__ == "__main__":
    raise SystemExit(main())











