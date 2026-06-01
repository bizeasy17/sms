import os
from datetime import date, timedelta
from django.conf import settings
import pandas as pd
from stockdata.models import (
    StockTradingHistory,
    StockFundamentalHistory,
    StockCostHistory,
)

from utils.ta_util import calculate_all_features
from smartinvestor_ln.analysis.utils.feature_util import (
    features,
    fields_trading,
    fields_fundamental,
    fields_technical_calc,
    fields_calc_M,
    features_DW,
    fields_ohlc,
    fields_cost,
)

# step 1 - 获取单只股票的交易，基本面和成本历史数据
# step 2 - 

def get_multi_type_data(ts_code, data_type, freq="D"):
    """
    Retrieve multiple types of stock data and return merged DataFrame.

    Args:
        ts_code (str): Stock code.
        data_type (list): List of types, e.g. ['trading', 'fundamental', 'cost'].
        freq (str): Frequency, default 'D'.

    Returns:
        pd.DataFrame: Merged DataFrame containing requested data types.
    """
    dfs = {}
    if "trading" in data_type:
        trading_df = StockTradingHistory.objects.filter(ts_code=ts_code, freq=freq).order_by("trade_date").values()
        trading_df = pd.DataFrame.from_records(trading_df)
        dfs["trading"] = trading_df.set_index("trade_date") if not trading_df.empty else None
    if "fundamental" in data_type:
        fundamental_df = StockFundamentalHistory.objects.filter(ts_code=ts_code, freq=freq).order_by("trade_date").values()
        fundamental_df = pd.DataFrame.from_records(fundamental_df)
        dfs["fundamental"] = fundamental_df.set_index("trade_date") if not fundamental_df.empty else None
    if "cost" in data_type:
        cost_df = StockCostHistory.objects.filter(ts_code=ts_code, freq=freq).order_by("trade_date").values()
        cost_df = pd.DataFrame.from_records(cost_df)
        dfs["cost"] = cost_df.set_index("trade_date") if not cost_df.empty else None

    merged = None
    # If both trading and fundamental, left join on trading
    if "trading" in dfs and dfs["trading"] is not None and "fundamental" in dfs and dfs["fundamental"] is not None:
        merged = dfs["trading"].merge(dfs["fundamental"], left_index=True, right_index=True, how="left")
    elif "trading" in dfs and dfs["trading"] is not None:
        merged = dfs["trading"]
    elif "fundamental" in dfs and dfs["fundamental"] is not None:
        merged = dfs["fundamental"]

    # If cost is requested, left join on cost
    if "cost" in dfs and dfs["cost"] is not None:
        if merged is not None:
            merged = merged.merge(dfs["cost"], left_index=True, right_index=True, how="left")
        else:
            merged = dfs["cost"]

    if merged is None or merged.empty:
        raise ValueError(f"No data available for {ts_code} with types {data_type}")

    merged = merged.reset_index()
    return merged

def get_feature_data(
    ts_code, feature_type=None, feature_list=None, freq="D", version="v1"
):
    """
    Retrieves data from StockTradingHistory and StockFundamentalHistory for the given stock and feature list.

    Args:
        ts_code (str): Stock code to query.
        start_date (str): Start date (YYYY-MM-DD).
        end_date (str): End date (YYYY-MM-DD).
        feature_list (list, optional): List of feature names to retrieve. If None, uses default based on freq.
        freq (str): Frequency, 'D' for daily, 'W' for weekly, 'M' for monthly.

    Returns:
        pd.DataFrame: DataFrame with columns matching feature_list.
    """
    if feature_type == "fundamental":
        features = fields_fundamental
    elif feature_type == "technical":
        features = fields_trading + fields_ohlc
        features = features + fields_trading + fields_technical_calc
        features = features + fields_technical_calc
    elif feature_type == "cost":
        features = fields_cost + fields_ohlc

    # Select feature list based on freq
    calc_fields = []
    if freq in ["D", "W"]:
        calc_fields = fields_technical_calc
    elif freq == "M":
        calc_fields = fields_calc_M

    if feature_list is not None:
        selected_features = feature_list
    else:
        selected_features = features if freq == "M" else features + features_DW

    # Validate input
    if not any([freq]):
        raise ValueError("At least one of freq must be provided.")

    # Build query params
    def get_qs(model, freq, fields, date_from=None, count=200):
        # Build base filters
        filters = {"ts_code": ts_code, "freq": freq}

        # Handle optional date_from (backtrack count days to ensure enough rows for feature calc)
        if date_from:
            if isinstance(date_from, date):
                target_date = date_from
            else:
                try:
                    target_date = date.fromisoformat(str(date_from))
                except ValueError:
                    raise ValueError(f"Invalid date_from: {date_from}")
            start_date = target_date - timedelta(days=max(0, count))
            filters["trade_date__gte"] = start_date
        qs = (
            model.objects.filter(**filters)
            .order_by("trade_date")
            .values("trade_date", *fields)
        )
        if not qs.exists():
            raise ValueError(f"No data available for {ts_code}")
        df = pd.DataFrame.from_records(qs)
        if df.empty:
            raise ValueError(f"No data available for {ts_code}")
        df = df.sort_values("trade_date")  # ensure chronological order
        return df

    trading_df = get_qs(
        StockTradingHistory, freq, fields=fields_trading + fields_ohlc
    )
    fundamental_df = get_qs(StockFundamentalHistory, freq, fields=fields_fundamental)

    if (
        trading_df is None
        or trading_df.empty
        or fundamental_df is None
        or fundamental_df.empty
    ):
        raise ValueError(f"No data available for {ts_code}")

    trading_df.rename(
        columns={
            "open_qfq": "open",
            "high_qfq": "high",
            "low_qfq": "low",
            "close_qfq": "close",
            "pct_change": "pct_chg",
            "macd_dif": "dif",
            "macd_dea": "dea",
            "macd": "bar",
            "kdj_k": "k",
            "kdj_d": "d",
            "kdj_j": "j",
        },
        inplace=True,
    )

    # Merge on date, prioritizing trading data, then fill with fundamental data
    # Merge trading and fundamental data on 'trade_date'
    result_df = trading_df.set_index("trade_date")
    if not fundamental_df.empty:
        fundamental_df = fundamental_df.set_index("trade_date")
        result_df = result_df.combine_first(fundamental_df)

    # Calculate additional features if needed
    if calc_fields:
        result_df = calculate_all_features(result_df)

    # Select and order columns
    result_df = result_df.reindex(columns=selected_features)

    # Reset index to make 'trade_date' a column
    result_df = result_df.reset_index()

    if version == "v2":  # 增加了cost history
        cost_date_from = "2018-01-02"  # 成本数据的开始时间
        # Filter result_df and fundamental_df by cost_date_from
        result_df = result_df[result_df["trade_date"] >= cost_date_from]
        cost_df = get_qs(StockCostHistory, freq, fields=fields_cost)
        if cost_df is not None and not cost_df.empty:
            result_df = result_df.merge(cost_df, on="trade_date", how="left")
        else:
            raise ValueError(
                f"No cost data available for {ts_code} on {cost_date_from}"
            )

    # Filter rows based on provided dates
    result_df["trade_date"] = result_df["trade_date"].astype(str)
    # if given_date:
    #     result_df = result_df[result_df["trade_date"] >= str(given_date)]
    # else: keep all

    # Drop 'index' column if present, but keep 'trade_date'
    result_df = result_df.drop(columns=["index"], errors="ignore")
    return result_df


class FeatureManager:
    def __init__(self, trading_df, fundamental_df, cost_df):
        self.tables = {
            "trading": trading_df,
            "fundamental": fundamental_df,
            "cost": cost_df,
        }

    def get_feature(self, feature_type, feature_name=None, calc_func=None):
        """
        根据 feature_type 获取特征或计算特征
        :param feature_type: str, 如 'trading', 'trading calculation', 'fundamental', 'fundamental calculation'
        :param feature_name: str 或 list, 指定特征名（可选）
        :param calc_func: function, 计算函数（仅当 feature_type 包含 'calculation' 时需要）
        :return: DataFrame 或 Series
        """
        if "calculation" in feature_type:
            if calc_func is None:
                raise ValueError("calculation 类型必须传入 calc_func")
            # 支持多个表一起计算
            if isinstance(feature_type, list):
                results = []
                for t in feature_type:
                    if isinstance(calc_func, list):
                        # 多个表和多个函数，分别计算
                        for func in calc_func:
                            results.append(self._calculate_feature(t, calc_func=func))
                    else:
                        results.append(self._calculate_feature(t, calc_func=calc_func))
                # 合并多个计算结果（按列）
                return pd.concat(results, axis=1)
            else:
                if isinstance(calc_func, list):
                    results = []
                    for func in calc_func:
                        results.append(self._calculate_feature(feature_type, calc_func=func))
                    return pd.concat(results, axis=1)
                else:
                    return self._calculate_feature(feature_type, calc_func=calc_func)
        else:
            # 支持多个表一起获取特征
            if isinstance(feature_type, list):
                dfs = []
                for t in feature_type:
                    table_key = t.split()[0]
                    if table_key in self.tables:
                        df = self.tables[table_key]
                        if feature_name:
                            if isinstance(feature_name, list):
                                dfs.append(df[feature_name])
                            else:
                                dfs.append(df[[feature_name]])
                        else:
                            dfs.append(df)
                    else:
                        raise ValueError(f"未知的特征类型: {t}")
                # 合并多个表（按行或列，视需求而定，这里按列合并）
                return pd.concat(dfs, axis=1)
            else:
                table_key = feature_type.split()[0]
                if table_key in self.tables:
                    df = self.tables[table_key]
                    if feature_name:
                        if isinstance(feature_name, list):
                            return df[feature_name]
                        else:
                            return df[[feature_name]]
                    return df
                else:
                    raise ValueError(f"未知的特征类型: {feature_type}")

    def _calculate_feature(self, feature_type, calc_func=None):
        """
        根据类型执行计算逻辑，支持传入自定义计算函数或函数列表
        :param feature_type: str, 如 'trading calculation', 'fundamental calculation'
        :param calc_func: function 或 list of function, 计算函数，接受对应的 DataFrame 并返回计算后的 DataFrame 或 Series
        """
        table_key = feature_type.split()[0]
        if table_key not in self.tables:
            raise ValueError(f"未知的特征类型: {feature_type}")
        df = self.tables[table_key]
        if calc_func is None:
            raise ValueError("calculation 类型必须传入 calc_func")
        if isinstance(calc_func, list):
            results = []
            for func in calc_func:
                results.append(func(df))
            # 合并多个计算结果（按列）
            return pd.concat(results, axis=1)
        else:
            return calc_func(df)
