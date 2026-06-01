from datetime import datetime
from django.core.management.base import BaseCommand, CommandError

from analysis.utils.data_util import calculate_moving_quantiles, get_multi_type_data
from analysis.models import StockFeatures
from stockdata.models import Corporation
from analysis.utils.stock_util import calc_tech_indicators  # Import the function


class Command(BaseCommand):
    help = "Combine data for a given ts_code"

    def add_arguments(self, parser):
        parser.add_argument("--tscode", type=str, help="The ts_code to process")
        parser.add_argument(
            "--freq", type=str, help="Frequency of the data, e.g. D, W-FRI"
        )
        parser.add_argument("--resume", type=str, help="Resume from a specific ts_code")

    def handle(self, *args, **options):
        ts_code = options["tscode"]
        freq = options["freq"]
        resume = options["resume"]
        # Your data combining logic here
        quantile_cols = [
            "close_qfq",
            "vol",
            "amount",
            "turnover_rate_f",
            "volume_ratio",
            "pe",
            "pb",
            "ps",
        ]

        if ts_code:
            corporations = [Corporation.objects.get(ts_code=ts_code)]
        else:
            corporations = list(Corporation.objects.all())
            if resume:
                try:
                    idx = [c.ts_code for c in corporations].index(resume)
                    corporations = corporations[idx:]
                except ValueError:
                    pass
        for corp in corporations:
            print(
                f"start company {corp.name}({corp.ts_code}) {datetime.now():%Y-%m-%d %H:%M:%S}"
            )
            merged_df = get_multi_type_data(
                ts_code=corp.ts_code,
                freq=freq,
                data_type=["trading", "fundamental", "cost"],
            )
            # Save the merged_df DataFrame to the StockFeatures model
            # Convert DataFrame to a dictionary or JSON string before saving
            if merged_df is None:
                print(f"No data to process for {corp.ts_code}")
                continue
            # 添加技术指标计算特征
            merged_df = calc_tech_indicators(merged_df)
            # 计算关键特征列的移动统计值
            merged_df = calculate_moving_quantiles(merged_df, columns=quantile_cols)

            # 假设 model 为你的 Django Model
            # Replace NaN and infinite values with None for Django model compatibility
            import numpy as np
            merged_df = merged_df.replace([np.inf, -np.inf], None)
            merged_df = merged_df.astype(object).where(merged_df.notnull(), None)

            # 批量创建 StockFeatures 实例
            records = [
                StockFeatures(**row) for row in merged_df.to_dict(orient="records")
            ]
            created = StockFeatures.objects.bulk_create(records)
            if created:
                print(f"created {len(created)} records")
                print(
                    f"created {corp.ts_code}, end company {corp.name}({corp.ts_code}) {datetime.now():%Y-%m-%d %H:%M:%S}"
                )
        self.stdout.write(
            self.style.SUCCESS(f"Successfully processed ts_code: {ts_code}")
        )
