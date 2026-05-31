import pandas as pd


def _equity_value_to_price(equity_value, total_share):
    if equity_value in (None, 0) or total_share in (None, 0):
        return None
    return equity_value / total_share


def summarize_valuation_range(valuation_results, total_share=None):
    if isinstance(valuation_results, pd.DataFrame):
        df = valuation_results.copy()
    else:
        df = pd.DataFrame(valuation_results)

    if df.empty or "equity_value" not in df.columns:
        return {
            "equity_value_min": None,
            "equity_value_max": None,
            "price_min": None,
            "price_max": None,
        }

    equity_values = pd.to_numeric(df["equity_value"], errors="coerce").dropna()
    if equity_values.empty:
        return {
            "equity_value_min": None,
            "equity_value_max": None,
            "price_min": None,
            "price_max": None,
        }

    effective_total_share = total_share
    if effective_total_share is None and "total_share" in df.columns:
        total_share_series = pd.to_numeric(df["total_share"], errors="coerce").dropna()
        if not total_share_series.empty:
            effective_total_share = total_share_series.iloc[0]

    equity_value_min = equity_values.min()
    equity_value_max = equity_values.max()
    equity_value_mid = equity_values.median()
    return {
        "equity_value_min": equity_value_min,
        "equity_value_max": equity_value_max,
        "equity_value_mid": equity_value_mid,
        "price_min": _equity_value_to_price(equity_value_min, effective_total_share),
        "price_max": _equity_value_to_price(equity_value_max, effective_total_share),
        "price_mid": _equity_value_to_price(equity_value_mid, effective_total_share),
        "total_share": effective_total_share,
    }


def format_valuation_range_output(
    valuation_results,
    total_share=None,
    current_price=None,
    equity_unit=100000000,
    equity_unit_label="亿元",
    price_decimals=2,
):
    summary = summarize_valuation_range(valuation_results, total_share=total_share)

    def _fmt_number(value, decimals=2):
        if value is None:
            return None
        return round(value, decimals)

    def _fmt_equity(value):
        if value is None:
            return None
        return round(value / equity_unit, 2)

    equity_min = summary.get("equity_value_min")
    equity_max = summary.get("equity_value_max")
    equity_mid = summary.get("equity_value_mid")
    price_min = summary.get("price_min")
    price_max = summary.get("price_max")
    price_mid = summary.get("price_mid")

    price_upside_min = None
    price_upside_max = None
    price_upside_mid = None
    if current_price not in (None, 0):
        if price_min is not None:
            price_upside_min = (price_min / current_price) - 1
        if price_max is not None:
            price_upside_max = (price_max / current_price) - 1
        if price_mid is not None:
            price_upside_mid = (price_mid / current_price) - 1

    return {
        "equity_value_range": {
            "min": equity_min,
            "max": equity_max,
            "mid": equity_mid,
            "min_display": f"{_fmt_equity(equity_min)}{equity_unit_label}" if equity_min is not None else None,
            "max_display": f"{_fmt_equity(equity_max)}{equity_unit_label}" if equity_max is not None else None,
            "mid_display": f"{_fmt_equity(equity_mid)}{equity_unit_label}" if equity_mid is not None else None,
            "range_display": (
                f"[{_fmt_equity(equity_min)}, {_fmt_equity(equity_max)}]{equity_unit_label}"
                if equity_min is not None and equity_max is not None
                else None
            ),
        },
        "price_range": {
            "min": price_min,
            "max": price_max,
            "mid": price_mid,
            "min_display": f"{_fmt_number(price_min, price_decimals)}元" if price_min is not None else None,
            "max_display": f"{_fmt_number(price_max, price_decimals)}元" if price_max is not None else None,
            "mid_display": f"{_fmt_number(price_mid, price_decimals)}元" if price_mid is not None else None,
            "range_display": (
                f"[{_fmt_number(price_min, price_decimals)}, {_fmt_number(price_max, price_decimals)}]元"
                if price_min is not None and price_max is not None
                else None
            ),
        },
        "upside_range": {
            "min": price_upside_min,
            "max": price_upside_max,
            "mid": price_upside_mid,
            "min_display": f"{round(price_upside_min * 100, 2)}%" if price_upside_min is not None else None,
            "max_display": f"{round(price_upside_max * 100, 2)}%" if price_upside_max is not None else None,
            "mid_display": f"{round(price_upside_mid * 100, 2)}%" if price_upside_mid is not None else None,
        },
        "total_share": summary.get("total_share"),
        "current_price": current_price,
    }


def run_valuation_scenarios(model_func, scenarios, base_kwargs=None):
    base_kwargs = base_kwargs or {}
    results = []
    for scenario_name, scenario_kwargs in scenarios.items():
        merged_kwargs = {**base_kwargs, **scenario_kwargs}
        valuation = model_func(**merged_kwargs)
        valuation["scenario"] = scenario_name
        results.append(valuation)

    df = pd.DataFrame(results)
    summary = summarize_valuation_range(df)
    for key, value in summary.items():
        df[key] = value
    return df


def run_sensitivity_analysis(model_func, base_kwargs, variable_grid):
    records = []
    for variable_name, values in variable_grid.items():
        for value in values:
            kwargs = dict(base_kwargs)
            kwargs[variable_name] = value
            valuation = model_func(**kwargs)
            records.append(
                {
                    "variable": variable_name,
                    "value": value,
                    "method": valuation.get("method"),
                    "equity_value": valuation.get("equity_value"),
                    "enterprise_value": valuation.get("enterprise_value"),
                    "implied_price": valuation.get("implied_price"),
                    "total_share": valuation.get("total_share"),
                }
            )

    df = pd.DataFrame(records)
    summary = summarize_valuation_range(df)
    for key, value in summary.items():
        df[key] = value
    return df
