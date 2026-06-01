import yaml
import pandas as pd
import datetime
from prediction.models import (
    StockCombinedFeature,
    StockFeatures,
)
from prediction.utils.stock_util import (
    calc_atr_upper_lower_diff,
    calc_boll_band_diff,
    calc_cost_his_diff,
    calc_cost_pct_diff,
    calc_ma_diff,
    calc_open_pre_close_diff,
    calc_param_pct_diff,
    identify_tech_patterns,
)
from datastore.models import Corporation


def read_features_from_yaml(yaml_path, feature_type=None):
    """
    Reads a list of features from a YAML file.

    Args:
        yaml_path (str): Path to the YAML file.

    Returns:
        list: List of features.
    """
    with open(yaml_path, "r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
    # Assumes the YAML file contains a top-level key 'features'
    if feature_type and "+" in feature_type:
        features = []
        for ft in feature_type.split("+"):
            features.extend(data.get(ft.strip(), []))
        # Remove duplicates while preserving order
        features = list(dict.fromkeys(features))
        return features
    return data.get(feature_type, [])


def process_and_save_features(
    ts_code, freq, distance, fields, feature_type, features, project_root, trade_date=None, resume=None
):
    """
    Retrieves data from StockFeatures, calculates new features, and saves both original and calculated features
    into the relevant feature table based on feature_type.

    Args:
        ts_code (str): Stock code.
        freq (str): Frequency of data (e.g., 'daily', 'weekly').
        distance (int): Lookback period or window size.
        fields (list): List of fields to retrieve and calculate.
        feature_type (str): Type of feature ('trading', 'fundamental', 'cost', 'all').
    """
    # Prepare corporation queryset
    corps = (
        Corporation.objects.filter(ts_code=ts_code)
        if ts_code
        else Corporation.objects.all().order_by("ts_code")
    )
    if not ts_code and resume:
        corps = corps.filter(ts_code__gte=resume)
    created = None
    for corp in corps:
        print(f"Processing corporation: {corp.ts_code}")
        latest_trade_date = (
            StockCombinedFeature.objects.filter(ts_code=corp.ts_code, freq=freq)
            .order_by("-trade_date")
            .values_list("trade_date", flat=True)
            .first()
        )
        empty_feature = False
        if latest_trade_date is not None:
            next_trade_date = latest_trade_date + datetime.timedelta(days=1)
        else:
            empty_feature = True
            next_trade_date = datetime.date.today()
        
        # If latest_trade_date is weekend, move to next weekday (Monday)
        if next_trade_date is not None:
            while next_trade_date.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
                next_trade_date += datetime.timedelta(days=1)
                
        if trade_date:  # Use trade_date if provided
            next_trade_date = datetime.datetime.strptime(trade_date, "%Y-%m-%d").date()
        # mistake
        # from_date = None
        # if latest_trade_date:
        #     from_date = (latest_trade_date - datetime.timedelta(days=199)).strftime(
        #         "%Y-%m-%d"
        #     )
        # else:
        #     from_date = None
        n = 200

        # Retrieve n-1 records prior to next_trade_date
        prior_records = (
            StockFeatures.objects.filter(
            ts_code=corp.ts_code,
            freq=freq,
            trade_date__lt=next_trade_date,
            )
            .values(*fields)
            .order_by("-trade_date")[: n - 1]
        )

        # Retrieve records from next_trade_date till today
        today = datetime.date.today()
        post_records = (
            StockFeatures.objects.filter(
            ts_code=corp.ts_code,
            freq=freq,
            trade_date__gte=next_trade_date,
            trade_date__lte=today,
            )
            .values(*fields)
            .order_by("-trade_date")
        )

        # Combine and sort records by trade_date descending
        stock_feature_qs = list(prior_records) + list(post_records)
        stock_feature_qs = sorted(stock_feature_qs, key=lambda x: x["trade_date"], reverse=True)
        stock_feature_qs = list(stock_feature_qs)[::-1]  # reverse to ascending order by trade_date

        df = pd.DataFrame(stock_feature_qs)
        if df.empty:
            continue
        # Convert Decimal columns to float
        for col in df.select_dtypes(include="object").columns:
            if df[col].apply(lambda x: hasattr(x, "as_tuple")).any():
                df[col] = df[col].astype(float)

        # Calculate new features (example: simple moving average for numeric fields)
        def get_yaml_fields(key):
            return read_features_from_yaml(
                f"{project_root}/prediction/config/fields_calc.yaml", feature_type=key
            )

        if feature_type in ("tech", "all"):
            df = calc_open_pre_close_diff(
                df, open_col="open_qfq", pre_close_col="pre_close_qfq"
            )
            for key, func in {
                "trading_diff": calc_param_pct_diff,
                "atr_diff": calc_atr_upper_lower_diff,
                "ma_diff": calc_ma_diff,
                "boll_band_diff": calc_boll_band_diff,
            }.items():
                tech_fields = get_yaml_fields(key)
                if tech_fields:
                    df = func(df, tech_fields)
            identify_tech_patterns(
                df,
                open_col="open_qfq",
                close_col="close_qfq",
                high_col="high_qfq",
                low_col="low_qfq",
            )

        if feature_type in ("fundamental", "all"):
            fundamental_fields = get_yaml_fields("fundamental_diff")
            if fundamental_fields:
                df = calc_param_pct_diff(df, fundamental_fields)

        if feature_type in ("cost", "all"):
            fields_from = get_yaml_fields("cost_diff_from")
            fields_diff = get_yaml_fields("cost_diff")
            if fields_from:
                df = calc_cost_pct_diff(df, fields_from, fields_diff)
                df = calc_cost_his_diff(
                    df, fields=["close_qfq"], his_levels=["his_low", "his_high"]
                )

        if feature_type not in ("tech", "fundamental", "cost", "all"):
            raise ValueError(f"Unknown feature_type: {feature_type}")

        df = df[features]

        # Replace NaN, numpy.nan, and infinite values with None to avoid Django ValidationError
        df = df.replace(
            {
                pd.NA: None,
                pd.NaT: None,
                float("nan"): None,
                float("inf"): None,
                float("-inf"): None,
            }
        )
        # Filter out trades before latest_trade_date
        if next_trade_date and not empty_feature:
            df = df[df["trade_date"] >= next_trade_date]
        if df.empty:
            continue
        
        feature_record = df.where(pd.notnull(df), None).to_dict(orient="records")

        # Save to the relevant feature table
        feature_model_map = {
            "all": StockCombinedFeature,
        }
        model = feature_model_map.get(feature_type)
        if not model:
            raise ValueError(f"Unknown feature_type: {feature_type}")

        from django.db import IntegrityError

        try:
            # Debug: print field lengths for each record
            # for idx, record in enumerate(feature_record):
            #     for key, value in record.items():
            #         if isinstance(value, str):
            #             print(f"Record {idx}, Field '{key}': length={len(value)}, value='{value}'")

            created = model.objects.bulk_create(
                [
                    model(
                        **record,
                        corporation=corp,
                    )
                    for record in feature_record
                ]
            )
            print(
                f"Saved {len(feature_record)} records to {model.__name__} for ts_code={corp.ts_code}, freq={freq}"
            )
        except IntegrityError as e:
            print(
                f"IntegrityError saving records for ts_code={corp.ts_code}, freq={freq}: {e}"
            )
            continue

    return created
