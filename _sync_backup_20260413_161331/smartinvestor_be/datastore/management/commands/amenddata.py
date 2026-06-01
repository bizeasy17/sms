from django.core.management.base import BaseCommand
import tushare as ts
from datetime import datetime, date
from django.core.exceptions import ValidationError
from utils.data_utils import process_fundamental_records
from datastore.models import Corporation, StockFundamentalHistory


class Command(BaseCommand):
    help = "Amends stock data as needed"

    def add_arguments(self, parser):
        parser.add_argument("--tscode", type=str, help="Stock code")
        parser.add_argument("--trade_date", type=str, help="Trade date")
        parser.add_argument("--field", type=str, help="Field to amend")
        parser.add_argument(
            "--freq", type=str, help="Frequency of the data (e.g., daily, weekly)"
        )
        parser.add_argument(
            "--resume", type=str, help="Resume from a specific stock code"
        )

    def handle(self, *args, **options):
        ts_code = options.get("tscode")
        trade_date = options.get("trade_date")
        field = options.get("field")
        freq = options.get("freq")
        resume = options.get("resume")

        pro = ts.pro_api()
        end_date = date.today()

        def update_field_for_records(corp, records):
            updated_count = 0
            for record in records:
                trade_date_val = record.get("trade_date")
                field_val = record.get(field)
                if trade_date_val and field_val is not None:
                    obj = StockFundamentalHistory.objects.filter(
                        corporation=corp, trade_date=trade_date_val, freq=freq
                    ).first()
                    if obj:
                        setattr(obj, field, field_val)
                        obj.save(update_fields=[field])
                        updated_count += 1
            return updated_count

        try:
            corporations = []
            if ts_code:
                corp = Corporation.objects.filter(ts_code=ts_code).first()
                if not corp:
                    print(f"Corporation with ts_code {ts_code} not found.")
                    return
                corporations = [corp]
            elif trade_date:
                df = pro.daily_basic(trade_date=trade_date)
                if df is None or df.empty:
                    print(f"No data returned for {trade_date}.")
                    return
                records = process_fundamental_records(df.to_dict(orient="records"))
                ts_codes = [r["ts_code"] for r in records]
                corp_map = {
                    c.ts_code: c
                    for c in Corporation.objects.filter(ts_code__in=ts_codes)
                }
                updated_count = 0
                for r in records:
                    corp = corp_map.get(r["ts_code"])
                    if corp:
                        obj = StockFundamentalHistory.objects.filter(
                            corporation=corp, trade_date=r.get("trade_date"), freq=freq
                        ).first()
                        if obj and field in r:
                            setattr(obj, field, r[field])
                            obj.save(update_fields=[field])
                            updated_count += 1
                print(
                    f"Updated field '{field}' for trade_date {trade_date}. Total rows updated: {updated_count}"
                    if updated_count
                    else f"No matching corporations or records found to update for trade_date {trade_date}."
                )
                return
            else:
                corporations = list(Corporation.objects.all())
                if resume:
                    corporations = [c for c in corporations if c.ts_code >= resume]

            for corp in corporations:
                print(f"Fetching data for {corp.ts_code}...")
                start_date = trade_date or "20000101"
                if isinstance(start_date, (datetime, date)):
                    start_date_str = start_date.strftime("%Y%m%d")
                else:
                    start_date_str = str(start_date)
                end_date_str = end_date.strftime("%Y%m%d")
                if start_date_str > end_date_str:
                    print(
                        f"Start date {start_date_str} is after end date {end_date_str} for {corp.ts_code}. Skipping."
                    )
                    continue

                df = pro.daily_basic(
                    ts_code=corp.ts_code,
                    start_date=start_date_str,
                    end_date=end_date_str,
                )
                if df is None or df.empty:
                    print(f"No data returned for {corp.ts_code}.")
                    continue
                records = process_fundamental_records(df.to_dict(orient="records"))
                updated_count = update_field_for_records(corp, records)
                print(
                    f"{corp.ts_code} field '{field}' update complete. Total rows updated: {updated_count}"
                )

        except (
            ValueError,
            KeyError,
            TypeError,
            ValidationError,
            ConnectionError,
            AttributeError,
        ) as e:
            print(f"Error: {e}")
        self.stdout.write(self.style.SUCCESS("Stock data amendment completed."))
