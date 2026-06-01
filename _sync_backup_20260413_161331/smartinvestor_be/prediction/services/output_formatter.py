import pandas as pd

from prediction.utils.valuation_util import get_stock_valuation_snapshot


class EstMktvOutputFormatter:
    @staticmethod
    def build_output_df(result):
        valuations = result.get("valuations")
        if valuations is None or valuations.empty:
            return None

        output_df = valuations.loc[:, ["method", "equity_value", "implied_price"]].copy()
        output_df = output_df.rename(
            columns={
                "equity_value": "evaluated_market_value",
                "implied_price": "according_price",
            }
        )
        output_df["evaluated_market_value"] = output_df["evaluated_market_value"] / 100000000
        for column in ["evaluated_market_value", "according_price"]:
            output_df[column] = output_df[column].round(4)
        output_df = output_df.where(output_df.notna(), None)
        return output_df

    @classmethod
    def build_output(cls, result):
        output_df = cls.build_output_df(result)
        if output_df is None or output_df.empty:
            return "No valuation results"
        return output_df.to_string(index=False)

    @staticmethod
    def format_metric(value):
        if value is None:
            return "None"
        if isinstance(value, (int, float)):
            return f"{value:.4f}"
        return str(value)

    @classmethod
    def build_profit_source_lines(
        cls,
        tscode,
        trade_date=None,
        strict_express_match=True,
        express_max_age_days=180,
    ):
        snapshot = get_stock_valuation_snapshot(
            ts_code=tscode,
            trade_date=trade_date,
            strict_express_match=strict_express_match,
            express_max_age_days=express_max_age_days,
        )
        lines = [
            f"profit_data_source: {snapshot.get('profit_data_source')}",
            f"strict_express_match: {snapshot.get('strict_express_match')}",
            f"express_max_age_days: {snapshot.get('express_max_age_days')}",
            f"express_apply_reason: {snapshot.get('express_apply_reason')}",
            f"express_block_reason: {snapshot.get('express_block_reason')}",
            f"profit_snapshot_trade_date: {snapshot.get('trade_date')}",
            f"profit_snapshot_end_date: {snapshot.get('end_date')}",
            f"express_end_date: {snapshot.get('express_end_date')}",
            f"express_ann_date: {snapshot.get('express_ann_date')}",
            (
                "peg_growth_yoy_pct(base->effective): "
                f"{cls.format_metric(snapshot.get('base_peg_growth_yoy_pct'))} -> "
                f"{cls.format_metric(snapshot.get('peg_growth_yoy_pct'))}"
            ),
            (
                "netprofit(base->effective): "
                f"{cls.format_metric(snapshot.get('base_netprofit'))} -> "
                f"{cls.format_metric(snapshot.get('netprofit'))}"
            ),
            (
                "revenue(base->effective): "
                f"{cls.format_metric(snapshot.get('base_revenue'))} -> "
                f"{cls.format_metric(snapshot.get('revenue'))}"
            ),
            f"express_blend_alpha: {cls.format_metric(snapshot.get('express_blend_alpha'))}",
        ]
        return lines

    @staticmethod
    def build_multi_output(output_frames):
        if not output_frames:
            return "No valuation results"
        normalized_frames = []
        all_columns = []
        for frame in output_frames:
            if frame is None or frame.empty:
                continue
            normalized_frames.append(frame.astype(object))
            for column in frame.columns:
                if column not in all_columns:
                    all_columns.append(column)
        if not normalized_frames:
            return "No valuation results"
        normalized_frames = [frame.reindex(columns=all_columns) for frame in normalized_frames]
        combined = pd.concat(normalized_frames, ignore_index=True)
        combined = combined.where(combined.notna(), None)
        return combined.to_string(index=False)

    @classmethod
    def build_comparison_frame(
        cls,
        result,
        compare_group,
        industry_level=None,
        industry_code=None,
        industry_name=None,
        match_score=None,
        source=None,
        matched_keywords=None,
        citic_profile=None,
        citic_mapping_summary=None,
        include_source=False,
        include_keywords=False,
        include_citic=False,
    ):
        output_df = cls.build_output_df(result)
        if output_df is None or output_df.empty:
            return None

        output_df.insert(0, "industry_name", industry_name)
        output_df.insert(0, "industry_code", industry_code)
        output_df.insert(0, "industry_level", industry_level)
        output_df.insert(0, "match_score", round(match_score, 4) if match_score is not None else None)
        output_df.insert(0, "compare_group", compare_group)
        if include_keywords:
            output_df.insert(0, "matched_keywords", matched_keywords)
        if include_citic:
            citic_profile = citic_profile or {}
            output_df.insert(0, "citic_sw_targets", citic_mapping_summary)
            output_df.insert(0, "citic_l3", citic_profile.get("l3_name"))
            output_df.insert(0, "citic_l2", citic_profile.get("l2_name"))
            output_df.insert(0, "citic_l1", citic_profile.get("l1_name"))
        if include_source:
            output_df.insert(0, "source", source)
        return output_df

    @staticmethod
    def format_citic_mapping_summary(citic_mappings):
        if not citic_mappings:
            return None
        targets = []
        for mapping in citic_mappings:
            target_label = f"{mapping.get('target_level')}:{mapping.get('target_name')}"
            if target_label not in targets:
                targets.append(target_label)
        return "|".join(targets)
