import numpy as np
from stockdata.models import Corporation
import pandas as pd
from stockdata.models import StockTradingHistory
from analysis.utils.sci_utils import (
    find_tops,
    find_bottoms,
    select_extreme_points_by_group,
)
from analysis.models import StockGainLossQuantile, StockTopBottomHistory
from datetime import datetime, timedelta
from pandas import to_datetime
import os
from django.conf import settings
from typing import List, Optional, Dict, Any
from stockdata.models import StockTradingHistory
import pandas as pd
from analysis.models import StockFeatures


def identify_stock_top_bottom(ts_code, freq="D", distance=20, resume=None):
    """
    Identify the top and bottom points of a stock's price movement.
    Args:
        stock_data (pd.DataFrame): A DataFrame containing stock price data with a 'close' column.
    Returns:
        dict: A dictionary with 'top' and 'bottom' keys indicating the respective price points.
    """
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
        # Retrieve trading history for the corporation
        trading_qs = StockTradingHistory.objects.filter(
            ts_code=corp.ts_code, freq=freq
        ).order_by("trade_date")
        if not trading_qs.exists():
            continue

        df = pd.DataFrame(
            list(trading_qs.values("trade_date", "high_qfq", "low_qfq", "close_qfq"))
        )
        if df.empty:
            continue

        # Identify tops and bottoms
        tops_idx = find_tops(df["close_qfq"], distance=distance)
        bottoms_idx = find_bottoms(df["close_qfq"], distance=distance)

        # Prepare and update StockTopBottomHistory
        records = []
        for idx in tops_idx:
            records.append(
                StockTopBottomHistory(
                    ts_code=corp.ts_code,
                    corporation=corp,
                    trade_date=df.iloc[idx]["trade_date"],
                    freq=freq,
                    close=df.iloc[idx]["close_qfq"],
                    period=distance,
                    asset=corp.asset,
                    top_or_bottom="T",
                )
            )
        for idx in bottoms_idx:
            records.append(
                StockTopBottomHistory(
                    ts_code=corp.ts_code,
                    corporation=corp,
                    trade_date=df.iloc[idx]["trade_date"],
                    freq=freq,
                    period=distance,
                    close=df.iloc[idx]["close_qfq"],
                    asset=corp.asset,
                    top_or_bottom="B",  # 犯了错误，把这里设置成了T，上面设置成了B
                )
            )
        # Bulk upsert: delete old, then bulk_create new (for this corp/freq)
        StockTopBottomHistory.objects.filter(
            corporation=corp, freq=freq, period=distance
        ).delete()
        if records:
            StockTopBottomHistory.objects.bulk_create(records)
        print(
            f"end company {corp.name}({corp.ts_code}) {datetime.now():%Y-%m-%d %H:%M:%S}"
        )


def calc_top_bottom_gain_loss(
    ts_code, freq="D", distance=20, entry_type="B", look_for_period=None, resume=None
):
    """
    Calculate the percentage gain/loss from identified tops/bottoms over specified periods.
    Args:
        ts_code (str): Stock code to filter the corporations.
        freq (str): Frequency of the stock data ('D', 'W', 'M', etc.).
        entry_type (str): 'B' for bottom-based calculations, 'T' for top-based calculations.
        period (int): The period over which to calculate gain/loss.
        resume (str): Resume from a specific stock code.
    """
    # period: int = 144 if freq == "W" else 610 if freq == "M" else 34 # 1.0版本
    # Allow period to be configured via function argument, environment variable, or default

    if look_for_period is None:
        look_for_period = 24 if freq == "W" else 12 if freq == "M" else 20

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
        gain_loss_time_points = [1, 2, 3, 5]
        top_bottom_histories = StockTopBottomHistory.objects.filter(
            corporation=corp,
            top_or_bottom=entry_type,
            freq=freq,  # pct_gain_1p=None
            period=distance,
        ).order_by("trade_date")

        try:
            df = pd.DataFrame(
                list(
                    StockTradingHistory.objects.filter(ts_code=corp.ts_code, freq=freq)
                    .order_by("trade_date")
                    .values("trade_date", "close_qfq")
                )
            )

            for top_bottom in top_bottom_histories:
                for time_point in gain_loss_time_points:
                    end_date = top_bottom.trade_date + timedelta(
                        days=look_for_period * time_point  # +1是因为不包括start date
                    )
                    mask = (df["trade_date"] > top_bottom.trade_date) & (
                        df["trade_date"] <= end_date
                    )
                    sub_df = df.loc[mask]
                    try:
                        pct_gain, gain_date, pct_loss, loss_date = calc_gain_loss(
                            sub_df, price=getattr(top_bottom, "close", 0)
                        )
                        setattr(top_bottom, f"pct_gain_{time_point}p", pct_gain)
                        setattr(top_bottom, f"pct_gain_{time_point}p_date", gain_date)
                        setattr(top_bottom, f"pct_loss_{time_point}p", pct_loss)
                        setattr(top_bottom, f"pct_loss_{time_point}p_date", loss_date)
                    except (ValueError, KeyError, TypeError) as e:
                        print(f"Error {corp.ts_code} {top_bottom.trade_date}: {e}")
                top_bottom.period = look_for_period
                top_bottom.save()
            print(
                f"end company {corp.name}({corp.ts_code}) {datetime.now():%Y-%m-%d %H:%M:%S}"
            )
        except (ValueError, KeyError, TypeError) as ex:
            print(ex)
            print("Error in calculating pct gain")


def calc_gain_loss(df, price, date_col="trade_date", price_col="close_qfq"):
    """
    Calculate the percentage gain/loss from identified peaks/troughs.
    Args:
        df (pd.DataFrame): DataFrame containing stock data with 'trade_date' and price columns.
        price (float): The reference price to calculate gain/loss against.
        date_col (str): Column name for trade dates.
        price_col (str): Column name for price data.
    Returns:
        tuple: (pct_gain, date_max, pct_loss, date_min)
    Raises:
        ValueError: If the DataFrame is empty or price is zero.
    """
    if df.empty or price == 0:
        raise ValueError("Input DataFrame is empty or price is zero.")

    price_series = df[price_col]
    trade_dates = df[date_col]

    idx_max = price_series.idxmax()
    idx_min = price_series.idxmin()
    try:
        pct_gain = round((float(price_series.loc[idx_max]) - price) / price * 100, 2)
        pct_loss = round((float(price_series.loc[idx_min]) - price) / price * 100, 2)
        return pct_gain, trade_dates.loc[idx_max], pct_loss, trade_dates.loc[idx_min]
    except Exception as e:
        print(f"Error finding peak/trough: {e}")
        raise


def analyze_top_bottom_gain_loss_statistics(
    ts_code=None,
    freq="D",
    resume: str = None,
    distance: int = None,
):
    """
    Analyze and filter automatically detected stock tops/bottoms based on gain/loss thresholds,
    and compute gain/loss statistics for peaks and troughs.
    """
    # Set default period if not specified
    if distance is None:
        distance = 24 if freq == "W" else 12 if freq == "M" else 20

    corps = (
        Corporation.objects.filter(ts_code=ts_code)
        if ts_code
        else Corporation.objects.all().order_by("ts_code")
    )
    if not ts_code and resume:
        corps = corps.filter(ts_code__gte=resume)

    # Define percentiles and fields for gain/loss statistics
    gain_loss_time_points = [1, 2, 3, 5]
    percentiles = [0.1, 0.25, 0.5, 0.75, 0.9]
    loss_fields = [f"pct_loss_{p}p" for p in gain_loss_time_points]
    gain_fields = [f"pct_gain_{p}p" for p in gain_loss_time_points]

    for corp in corps:
        print(
            f"start company loss & gain statistics {corp.name}({corp.ts_code}) {datetime.now():%Y-%m-%d %H:%M:%S}"
        )
        topbottoms = StockTopBottomHistory.objects.filter(
            corporation=corp, freq=freq, period=distance
        ).order_by("trade_date")

        bottom_df = pd.DataFrame.from_records(
            topbottoms.filter(top_or_bottom="B").values(*loss_fields, *gain_fields)
        )
        top_df = pd.DataFrame.from_records(
            topbottoms.filter(top_or_bottom="T").values(*loss_fields, *gain_fields)
        )

        if bottom_df.empty and top_df.empty:
            continue

        quant_b = (
            bottom_df.quantile(percentiles).round(2) if not bottom_df.empty else None
        )
        quant_t = top_df.quantile(percentiles).round(2) if not top_df.empty else None

        # Set default thresholds if quantiles are empty
        # Calculate thresholds for classification
        # Calculate thresholds for classification
        if quant_b is not None:
            b_gain_threshold = quant_b[gain_fields].loc[0.5].min()
            b_loss_threshold = quant_b[loss_fields].loc[0.5].max()
            high_vol_gain_threshold = quant_b[gain_fields].loc[0.75].min()
        else:
            b_gain_threshold, b_loss_threshold, high_vol_gain_threshold = 7.5, -3.75, 15

        if quant_t is not None:
            t_gain_threshold = quant_t[gain_fields].loc[0.5].min()
            t_loss_threshold = quant_t[loss_fields].loc[0.5].max()
            high_vol_loss_threshold = quant_t[loss_fields].loc[0.25].max()
        else:
            t_gain_threshold, t_loss_threshold, high_vol_loss_threshold = (
                3.75,
                -7.5,
                -15,
            )

        # Save quantiles
        # Save quantiles for bottoms and tops
        for quantile, tob in [(quant_b, "B"), (quant_t, "T")]:
            if quantile is None:
                continue
            for q, row in quantile.iterrows():
                obj = StockGainLossQuantile(
                    ts_code=corp.ts_code,
                    freq=freq,
                    corporation=corp,
                    quantile=q,
                    top_or_bottom=tob,
                    period=distance,
                    **row.to_dict(),
                )
                obj.save()

        # Classify top/bottom status
        # Collect objects to update in bulk
        to_update = []
        for topbottom in topbottoms:
            # Extract gain and loss values for the current top/bottom at different time points
            gain_vals = [
                getattr(topbottom, f"pct_gain_{p}p", None) for p in [1, 2, 3, 5]
            ]
            loss_vals = [
                getattr(topbottom, f"pct_loss_{p}p", None) for p in [1, 2, 3, 5]
            ]
            # If any value is missing, mark as 'N' (not classified) and continue
            if None in gain_vals or None in loss_vals:
                topbottom.top_or_bottom_stat = topbottom.top_bottom_volatility_stat = (
                    "N"
                )
                to_update.append(topbottom)
                continue

            # Calculate the median gain and loss for classification
            gain_median = np.median(gain_vals)
            loss_median = np.median(loss_vals)

            if topbottom.top_or_bottom == "B":
                # Classify as bottom if loss and gain medians meet thresholds
                is_bottom = (loss_median >= b_loss_threshold) and (
                    gain_median >= b_gain_threshold
                )
                topbottom.top_or_bottom_stat = "B" if is_bottom else "N"
                # Further classify as high volatility bottom if gain median is high
                is_high_vol_bottom = is_bottom and (
                    gain_median >= high_vol_gain_threshold
                )
                topbottom.top_bottom_volatility_stat = (
                    "B" if is_high_vol_bottom else "N"
                )

            elif topbottom.top_or_bottom == "T":
                # Classify as top if gain and loss medians meet thresholds
                is_top = (gain_median <= t_gain_threshold) and (
                    loss_median <= t_loss_threshold
                )
                topbottom.top_or_bottom_stat = "T" if is_top else "N"
                # Further classify as high volatility top if loss median is low
                is_high_vol_top = is_top and (loss_median <= high_vol_loss_threshold)
                topbottom.top_bottom_volatility_stat = "T" if is_high_vol_top else "N"

            # Add to list for bulk update
            to_update.append(topbottom)
        if to_update:
            StockTopBottomHistory.objects.bulk_update(
                to_update, ["top_or_bottom_stat", "top_bottom_volatility_stat"]
            )

        print(
            f"end corporation  loss & gain calc {corp.name}({corp.ts_code}) {datetime.now():%Y-%m-%d %H:%M:%S}"
        )


def refine_top_bottom_extremes_by_price(
    ts_code=None,
    freq="D",
    resume=None,
    distance=7,
):
    """
    Refine and optimize the detected top/bottom extremes by grouping and selecting the most significant points.
    This function updates the StockTopBottomHistory table with optimized classifications for tops/bottoms,
    their statistical status, and volatility status, based on grouped price extremes.
    Args:
        ts_code (str, optional): Stock code to filter corporations. If None, process all.
        freq (str): Frequency of the stock data ('D', 'W', 'M', etc.).
        resume (str, optional): Resume from a specific stock code.
        period (int): The period over which to analyze.
    """
    corps = (
        Corporation.objects.filter(ts_code=ts_code)
        if ts_code
        else Corporation.objects.all().order_by("ts_code")
    )
    if not ts_code and resume:
        corps = corps.filter(ts_code__gte=resume)

    # Set default period if not specified
    # If period is not provided, try to get it from environment variable or set a default
    if distance is None:
        distance = 24 if freq == "W" else 12 if freq == "M" else 20

    for corp in corps:
        print(
            f"start refine extremes: {corp.name}({corp.ts_code}) {datetime.now():%Y-%m-%d %H:%M:%S}"
        )

        qs = StockTopBottomHistory.objects.filter(
            corporation=corp, freq=freq, period=distance
        ).order_by("trade_date")
        if not qs.exists():
            continue

        df = pd.DataFrame.from_records(
            qs.values(
                "top_or_bottom",
                "trade_date",
                "ts_code",
                "top_or_bottom_stat",
                "close",
                "top_bottom_volatility_stat",
                "top_or_bottom_optimized",
                "top_or_bottom_stat_optimized",
                "top_bottom_volatility_optimized",
            )
        )
        if df.empty:
            continue

        for entry_col, field in [
            (None, "top_or_bottom_optimized"),
            ("top_or_bottom_stat", "top_or_bottom_stat_optimized"),
            ("top_bottom_volatility_stat", "top_bottom_volatility_optimized"),
        ]:
            opt_df = (
                select_extreme_points_by_group(
                    df, entry_col=entry_col, price_col="close"
                )
                if entry_col
                else select_extreme_points_by_group(df, price_col="close")
            )
            if not opt_df.empty:
                for _, row in opt_df.iterrows():
                    StockTopBottomHistory.objects.filter(
                        corporation=corp, trade_date=row["trade_date"], freq=freq
                    ).update(**{field: row["top_or_bottom"]})

        print(
            f"end refine extremes: {corp.name}({corp.ts_code}) {datetime.now():%Y-%m-%d %H:%M:%S}"
        )


def attach_top_bottom(ts_code=None, freq="D", resume=None, distance=20):
    """
    Attach top/bottom extremes to the stock data.
    This function updates the StockTopBottomHistory table with the top/bottom extremes for each stock.
    Args:
        ts_code (str, optional): Stock code to filter corporations. If None, process all.
        freq (str): Frequency of the stock data ('D', 'W', 'M', etc.).
        resume (str, optional): Resume from a specific stock code.
        distance (int): The distance parameter for analysis.
    """

    # Prepare corporation queryset
    corps = (
        Corporation.objects.filter(ts_code=ts_code)
        if ts_code
        else Corporation.objects.all().order_by("ts_code")
    )
    if not ts_code and resume:
        corps = corps.filter(ts_code__gte=resume)

    for corp in corps:
        print(
            f"start attach top bottom: {corp.name}({corp.ts_code}) {datetime.now():%Y-%m-%d %H:%M:%S}"
        )
        # Merge with StockTopBottomHistory
        topbottom_qs = StockTopBottomHistory.objects.filter(
            ts_code=corp.ts_code, freq=freq, period=distance
        ).order_by("trade_date")
        # Bulk fetch all StockFeatures for this corp and freq, indexed by trade_date for fast lookup
        features_qs = StockFeatures.objects.filter(
            ts_code=corp.ts_code, freq=freq
        ).only("id", "trade_date")
        features_map = {sf.trade_date: sf.id for sf in features_qs}

        # Prepare bulk update list
        updates = []
        for tb in topbottom_qs:
            feature_id = features_map.get(tb.trade_date)
            if feature_id:
                updates.append(
                    StockFeatures(
                        id=feature_id,
                        top_or_bottom=tb.top_or_bottom,
                        top_or_bottom_optimized=tb.top_or_bottom_optimized,
                        top_or_bottom_stat=tb.top_or_bottom_stat,
                        top_or_bottom_stat_optimized=tb.top_or_bottom_stat_optimized,
                        top_bottom_volatility_stat=tb.top_bottom_volatility_stat,
                        top_bottom_volatility_optimized=tb.top_bottom_volatility_optimized,
                    )
                )
        if updates:
            StockFeatures.objects.bulk_update(
                updates,
                [
                    "top_or_bottom",
                    "top_or_bottom_optimized",
                    "top_or_bottom_stat",
                    "top_or_bottom_stat_optimized",
                    "top_bottom_volatility_stat",
                    "top_bottom_volatility_optimized",
                ],
            )
            print(
                f"end attach top bottom: {corp.name}({corp.ts_code}) {datetime.now():%Y-%m-%d %H:%M:%S}"
            )


def merge_multiple_datasets_with_top_bottoms(
    ts_code: Optional[str] = None,
    freq: str = "D",
    resume: Optional[str] = None,
    period: int = 7,
    extra_tables: Optional[List[str]] = None,
    technical_indicators: Optional[List[str]] = None,
) -> pd.DataFrame:
    """
    Merge multiple datasets with top/bottom extremes and update the StockTopBottomHistory table.
    Args:
        ts_code (str, optional): Stock code to filter corporations. If None, process all.
        freq (str): Frequency of the stock data ('D', 'W', 'M', etc.).
        resume (str, optional): Resume from a specific stock code.
        period (int): The period over which to analyze.
        extra_tables (list, optional): List of extra table names to merge (as Django model names).
        technical_indicators (list, optional): List of technical indicators to calculate (e.g., ['ma5,ma10...', 'rsi']).
    Returns:
        pd.DataFrame: The merged DataFrame with technical indicators.
    """
    # Prepare corporation queryset
    corps = (
        Corporation.objects.filter(ts_code=ts_code)
        if ts_code
        else Corporation.objects.all().order_by("ts_code")
    )
    if not ts_code and resume:
        corps = corps.filter(ts_code__gte=resume)

    merged_dfs = []
    for corp in corps:
        # Get trading history
        trading_qs = StockTradingHistory.objects.filter(
            ts_code=corp.ts_code, freq=freq
        ).order_by("trade_date")
        trading_df = pd.DataFrame(list(trading_qs.values()))
        if trading_df.empty:
            continue

        # Calculate technical indicators if requested
        if technical_indicators:
            for indicator in technical_indicators:
                if indicator.startswith("ma"):
                    # Support multiple ma indicators like "ma5,ma10,ma20"
                    try:
                        ma_windows = [
                            int(w.strip())
                            for w in indicator[2:].split(",")
                            if w.strip().isdigit()
                        ]
                    except ValueError as e:
                        print(f"Error parsing MA indicator '{indicator}': {e}")
                        continue
                    for window in ma_windows:
                        trading_df[f"ma{window}"] = (
                            trading_df["close_qfq"].rolling(window=window).mean()
                        )
                elif indicator == "atr":
                    high = trading_df["high_qfq"]
                    low = trading_df["low_qfq"]
                    close = trading_df["close_qfq"]
                    prev_close = close.shift(1)
                    tr = pd.concat(
                        [
                            (high - low),
                            (high - prev_close).abs(),
                            (low - prev_close).abs(),
                        ],
                        axis=1,
                    ).max(axis=1)
                    trading_df["atr"] = tr.rolling(window=14).mean()
                # Add more indicators as needed

        # Merge with StockTopBottomHistory
        topbottom_qs = StockTopBottomHistory.objects.filter(
            ts_code=corp.ts_code, freq=freq, period=period
        ).order_by("trade_date")
        topbottom_df = pd.DataFrame(list(topbottom_qs.values()))
        if not topbottom_df.empty:
            merged_df = pd.merge(
                trading_df,
                topbottom_df,
                on=["ts_code", "trade_date"],
                how="left",
                suffixes=("", "_topbottom"),
            )
        else:
            merged_df = trading_df

        # Merge with extra tables if provided
        if extra_tables:
            for table_name in extra_tables:
                # Dynamically import model
                model = None
                try:
                    model = getattr(
                        __import__("stockdata.models", fromlist=[table_name]),
                        table_name,
                    )
                except AttributeError:
                    try:
                        model = getattr(
                            __import__("analysis.models", fromlist=[table_name]),
                            table_name,
                        )
                    except AttributeError:
                        continue
                if model:
                    extra_qs = model.objects.filter(
                        ts_code=corp.ts_code, freq=freq
                    ).order_by("trade_date")
                    extra_df = pd.DataFrame(list(extra_qs.values()))
                    if not extra_df.empty:
                        merged_df = pd.merge(
                            merged_df,
                            extra_df,
                            on=["ts_code", "trade_date"],
                            how="left",
                            suffixes=("", f"_{table_name.lower()}"),
                        )

        merged_dfs.append(merged_df)

    if merged_dfs:
        return pd.concat(merged_dfs, ignore_index=True)
    else:
        return pd.DataFrame()
