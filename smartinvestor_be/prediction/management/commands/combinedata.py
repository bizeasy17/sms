from datetime import datetime
from django.core.management.base import BaseCommand, CommandError

from prediction.utils.data_util import calculate_moving_quantiles, get_multi_type_data
from prediction.models import StockFeatures
from datastore.models import Corporation
from prediction.utils.stock_util import calc_tech_indicators  # Import the function


class Command(BaseCommand):
    help = "Combine data for a given ts_code"

    def add_arguments(self, parser):
        parser.add_argument("--tscode", type=str, help="The ts_code to process")
        parser.add_argument(
            "--freq", type=str, help="Frequency of the data, e.g. D, W-FRI"
        )
        parser.add_argument(
            "--date",
            type=str,
            help="Specific date to process data for (optional)",
        )
        parser.add_argument("--resume", type=str, help="Resume from a specific ts_code")

    def handle(self, *args, **options):
        ts_code = options["tscode"]
        freq = options["freq"]
        resume = options["resume"]
        dt = options["date"]
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
            corporations = list(Corporation.objects.all().order_by("ts_code"))
            if resume:
                try:
                    corporations = Corporation.objects.filter(ts_code__gte=resume)
                    print(f"Resuming from {resume}")
                except ValueError:
                    pass
                
        # if dt is None:
        #     dt = datetime.today().strftime("%Y-%m-%d")
            
        for corp in corporations:
            print(
                f"start company {corp.name}({corp.ts_code}) {datetime.now():%Y-%m-%d %H:%M:%S}"
            )

            try:
                merged_df, latest_feature_date = get_multi_type_data(
                    ts_code=corp.ts_code,
                    freq=freq,
                    data_type=["trading", "fundamental", "cost"],
                    trade_date=dt,
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
                
                if StockFeatures.objects.filter(ts_code=corp.ts_code).exists():
                    print(f"StockFeatures already has data for {corp.ts_code}")
                    # Filter merged_df to only include rows with trade_date > latest_feature_date
                    if latest_feature_date is not None:
                        # Ensure both sides are strings for comparison
                        merged_df = merged_df[merged_df["trade_date"].astype(str) >= str(latest_feature_date)]
                else:
                    print(f"StockFeatures is empty for {corp.ts_code}")

                # 批量创建 StockFeatures 实例
                records = [
                    StockFeatures(**row) for row in merged_df.to_dict(orient="records")
                ]
                # Example: append additional StockFeatures instance if needed
                # extra_record = StockFeatures(ts_code=corp.ts_code, trade_date=dt, ...)
                # records.append(extra_record)
                from django.db import IntegrityError
                try:
                    created = StockFeatures.objects.bulk_create(records, ignore_conflicts=True)
                    if created:
                        print(f"created {len(created)} records")
                        print(
                            f"created {corp.ts_code}, end company {corp.name}({corp.ts_code}) {datetime.now():%Y-%m-%d %H:%M:%S}"
                        )
                except IntegrityError as e:
                    print(f"Duplicate key error while creating StockFeatures for {corp.ts_code}: {str(e)}")
                    continue
            except (Corporation.DoesNotExist, StockFeatures.DoesNotExist) as e:
                self.stdout.write(
                    self.style.ERROR(
                        f"Database error processing ts_code {corp.ts_code}: {str(e)}"
                    )
                )
                continue
            except ValueError as e:
                self.stdout.write(
                    self.style.ERROR(
                        f"Value error processing ts_code {corp.ts_code}: {str(e)}"
                    )
                )
                continue
            except KeyError as e:
                self.stdout.write(
                    self.style.ERROR(
                        f"Key error processing ts_code {corp.ts_code}: {str(e)}"
                    )
                )
                continue
            
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f"Unexpected error processing ts_code {corp.ts_code}: {str(e)}"
                    )
                )
                raise
        self.stdout.write(
            self.style.SUCCESS(f"Successfully processed ts_code: {ts_code}")
        )
