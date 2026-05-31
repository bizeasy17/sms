import json
import os
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd

from valuation_api.sw_history_quantiles import SwHistoryQuantileService
from valuation_api.valuation_config import StandaloneValuationConfig


def get_tushare_pro(token=None):
    """Return a tushare pro client using explicit token or env settings."""
    try:
        import tushare as ts
    except ImportError as exc:
        raise ImportError("tushare is not installed. Please `pip install tushare`.") from exc

    use_token = token or os.getenv("TUSHARE_TOKEN") or os.getenv("TUSHARE_PRO_TOKEN")
    if use_token:
        ts.set_token(use_token)
    return ts.pro_api()


class ShenwanValuationSyncService:
    def __init__(
        self,
        static_dir: Path,
        market: str = "CN",
        src: str = "SW2021",
        pro=None,
        history_enabled: bool = True,
        history_years=(3, 5, 10),
        history_quantile: float = 0.5,
        history_min_samples: int = 120,
        params_output_suffix: str = None,
    ):
        if market != "CN":
            raise ValueError("Shenwan valuation sync currently supports CN market only.")

        self.static_dir = static_dir
        self.market = market
        self.src = src
        self.pro = pro or get_tushare_pro()
        self.mapping_path = static_dir / "valuation_config" / f"sw_industry_mapping_{market}.json"
        self.defaults_path = self._build_defaults_path(static_dir, market, params_output_suffix)
        self._fina_cache = {}
        self.request_interval = 0.45
        self._last_fina_request_at = None
        self.index_member_page_size = 4000
        self.history_enabled = bool(history_enabled)
        self.history_service = (
            SwHistoryQuantileService(
                pro=self.pro,
                window_years=history_years,
                quantile=history_quantile,
                min_samples=history_min_samples,
            )
            if self.history_enabled
            else None
        )

    def sync(
        self,
        trade_date=None,
        sample_size: int = 5,
        max_industries: int = None,
        include_mapping: bool = True,
        include_params: bool = True,
        dry_run: bool = False,
        request_interval: float = None,
        progress_every: int = 0,
        progress_callback=None,
    ):
        if not include_mapping and not include_params:
            raise ValueError("At least one of mapping/params must be enabled.")
        if request_interval is not None:
            self.request_interval = max(float(request_interval), 0.0)

        mapping_payload = None
        if include_mapping or not self.mapping_path.exists():
            mapping_payload = self.build_sw_mapping()
            if not dry_run and include_mapping:
                self._write_json(self.mapping_path, mapping_payload)
        else:
            mapping_payload = self._load_json(self.mapping_path)

        params_payload = None
        if include_params:
            params_payload = self.build_sw_valuation_defaults(
                mapping_payload=mapping_payload,
                trade_date=trade_date,
                sample_size=sample_size,
                max_industries=max_industries,
                progress_every=progress_every,
                progress_callback=progress_callback,
            )
            if not dry_run:
                self._write_json(self.defaults_path, params_payload)

        return {
            "mapping_file": str(self.mapping_path),
            "params_file": str(self.defaults_path),
            "mapping_levels": (
                {level: len(items) for level, items in mapping_payload.get("levels", {}).items()}
                if mapping_payload
                else {}
            ),
            "mapped_ts_codes": len(mapping_payload.get("ts_code_to_levels", {})) if mapping_payload else 0,
            "params_levels": (
                {level: len(items) for level, items in params_payload.get("levels", {}).items()}
                if params_payload
                else {}
            ),
            "trade_date": params_payload.get("trade_date") if params_payload else None,
            "dry_run": dry_run,
        }

    @staticmethod
    def _build_defaults_path(static_dir: Path, market: str, suffix: str = None):
        clean_suffix = "".join(
            ch if ch.isalnum() or ch in {"_", "-"} else "_"
            for ch in str(suffix or "").strip()
        ).strip("_")
        file_name = f"valuation_defaults_{market}_sw.json"
        if clean_suffix:
            file_name = f"valuation_defaults_{market}_sw_{clean_suffix}.json"
        return static_dir / "valuation_config" / file_name

    def build_sw_mapping(self):
        level_frames = {}
        industry_code_lookup = {}
        for level in ["L1", "L2", "L3"]:
            df = self.pro.index_classify(src=self.src, level=level)
            if df is None or df.empty:
                raise ValueError(f"Cannot fetch SW {level} classify data.")
            df = df.fillna("")
            level_frames[level] = df
            industry_code_lookup[level] = {
                str(row["industry_code"]): str(row["index_code"]) for _, row in df.iterrows()
            }

        levels = {"L1": {}, "L2": {}, "L3": {}}
        hierarchy = {"L1_to_L2": defaultdict(list), "L2_to_L3": defaultdict(list)}

        for level, df in level_frames.items():
            for _, row in df.iterrows():
                record = {
                    "index_code": self._clean_text(row.get("index_code")),
                    "industry_name": self._clean_text(row.get("industry_name")),
                    "level": self._clean_text(row.get("level")),
                    "industry_code": self._clean_text(row.get("industry_code")),
                    "is_pub": self._clean_text(row.get("is_pub")),
                    "parent_code": self._clean_text(row.get("parent_code")),
                    "src": self._clean_text(row.get("src")),
                }
                parent_index_code = None
                parent_name = None
                grandparent_index_code = None
                grandparent_name = None

                if level == "L2":
                    parent_index_code = industry_code_lookup["L1"].get(record["parent_code"])
                    if parent_index_code:
                        parent_name = levels["L1"].get(parent_index_code, {}).get("industry_name")
                        hierarchy["L1_to_L2"][parent_index_code].append(record["index_code"])
                elif level == "L3":
                    parent_index_code = industry_code_lookup["L2"].get(record["parent_code"])
                    if parent_index_code:
                        parent_l2 = levels["L2"].get(parent_index_code, {})
                        parent_name = parent_l2.get("industry_name")
                        grandparent_index_code = parent_l2.get("parent_index_code")
                        if grandparent_index_code:
                            grandparent_name = levels["L1"].get(grandparent_index_code, {}).get("industry_name")
                        hierarchy["L2_to_L3"][parent_index_code].append(record["index_code"])

                record["parent_index_code"] = parent_index_code
                record["parent_name"] = parent_name
                record["grandparent_index_code"] = grandparent_index_code
                record["grandparent_name"] = grandparent_name
                levels[level][record["index_code"]] = record

        ts_code_to_levels = {}
        level_members = {"L1": defaultdict(set), "L2": defaultdict(set), "L3": defaultdict(set)}
        member_df = self._fetch_index_member_all_full()
        if member_df is None or member_df.empty:
            raise ValueError("Cannot fetch SW index_member_all data.")
        member_df = member_df.fillna("")

        for _, row in member_df.iterrows():
            ts_code = self._clean_text(row.get("ts_code"))
            if not ts_code:
                continue
            out_date = self._clean_text(row.get("out_date"))
            if out_date:
                continue

            l3_code = self._clean_text(row.get("l3_code"))
            l2_code = self._clean_text(row.get("l2_code"))
            l1_code = self._clean_text(row.get("l1_code"))
            ts_code_to_levels[ts_code] = {
                "name": self._clean_text(row.get("name")),
                "l1_code": l1_code,
                "l1_name": self._clean_text(row.get("l1_name")),
                "l2_code": l2_code,
                "l2_name": self._clean_text(row.get("l2_name")),
                "l3_code": l3_code,
                "l3_name": self._clean_text(row.get("l3_name")),
                "in_date": self._clean_text(row.get("in_date")),
                "out_date": None,
                "source": self.src,
            }
            if l3_code:
                level_members["L3"][l3_code].add(ts_code)
            if l2_code:
                level_members["L2"][l2_code].add(ts_code)
            if l1_code:
                level_members["L1"][l1_code].add(ts_code)

        return {
            "version": f"{self.src}-{datetime.now().strftime('%Y%m%d%H%M%S')}",
            "market": self.market,
            "src": self.src,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "levels": levels,
            "hierarchy": {
                "L1_to_L2": {key: sorted(values) for key, values in hierarchy["L1_to_L2"].items()},
                "L2_to_L3": {key: sorted(values) for key, values in hierarchy["L2_to_L3"].items()},
            },
            "level_members": {
                level: {code: sorted(values) for code, values in members.items()}
                for level, members in level_members.items()
            },
            "ts_code_to_levels": ts_code_to_levels,
        }

    def _fetch_index_member_all_full(self):
        """
        Fetch full index_member_all payload.

        Prefer limit/offset paging to avoid default row limits. Fallback to
        single-call mode for older tushare SDK versions.
        """
        page_size = max(int(self.index_member_page_size or 2000), 500)

        frames = []
        offset = 0
        seen_page_markers = set()
        for _ in range(300):
            try:
                page_df = self.pro.index_member_all(limit=page_size, offset=offset)
            except TypeError:
                return self.pro.index_member_all()

            if page_df is None or page_df.empty:
                break

            first_marker = (
                str(page_df.iloc[0].get("ts_code") or ""),
                str(page_df.iloc[0].get("in_date") or ""),
                str(page_df.iloc[0].get("l3_code") or ""),
            )
            page_marker = (offset, len(page_df), first_marker)
            if page_marker in seen_page_markers:
                break
            seen_page_markers.add(page_marker)

            frames.append(page_df)
            current_size = len(page_df)
            offset += current_size

        if frames:
            return pd.concat(frames, ignore_index=True)

        return self.pro.index_member_all()

    def build_sw_valuation_defaults(
        self,
        mapping_payload: dict,
        trade_date=None,
        sample_size: int = 5,
        max_industries: int = None,
        progress_every: int = 0,
        progress_callback=None,
    ):
        cfg = StandaloneValuationConfig(self.static_dir.parent, market=self.market)
        trade_date_str = self._resolve_trade_date(trade_date)
        daily_basic_df = self.pro.daily_basic(
            trade_date=trade_date_str,
            fields="ts_code,trade_date,pe_ttm,ps_ttm,pb,total_mv,dv_ttm",
        )
        if daily_basic_df is None or daily_basic_df.empty:
            raise ValueError(f"Cannot fetch daily_basic data for {trade_date_str}.")
        daily_basic_df = daily_basic_df.fillna("")

        l3_nodes = {}
        l3_members = mapping_payload.get("level_members", {}).get("L3", {})
        l3_items = sorted(l3_members.items(), key=lambda item: item[0])
        if max_industries:
            l3_items = l3_items[:max_industries]
        total_l3 = len(l3_items)

        for idx, (l3_code, member_codes) in enumerate(l3_items, start=1):
            meta = mapping_payload["levels"]["L3"].get(l3_code, {})
            l3_nodes[l3_code] = self._build_l3_node(
                meta=meta,
                member_codes=member_codes,
                daily_basic_df=daily_basic_df,
                cfg=cfg,
                sample_size=sample_size,
                trade_date=trade_date_str,
            )
            if progress_callback and progress_every > 0 and (idx % progress_every == 0 or idx == total_l3):
                progress_callback(
                    {
                        "stage": "params_l3",
                        "done": idx,
                        "total": total_l3,
                        "last_code": l3_code,
                    }
                )

        l2_nodes = {}
        for l2_code, children in sorted(mapping_payload.get("hierarchy", {}).get("L2_to_L3", {}).items()):
            child_nodes = [l3_nodes[child] for child in children if child in l3_nodes]
            meta = mapping_payload["levels"]["L2"].get(l2_code, {})
            l2_nodes[l2_code] = self._build_aggregate_node(meta=meta, child_nodes=child_nodes, cfg=cfg)

        l1_nodes = {}
        for l1_code, children in sorted(mapping_payload.get("hierarchy", {}).get("L1_to_L2", {}).items()):
            child_nodes = [l2_nodes[child] for child in children if child in l2_nodes]
            meta = mapping_payload["levels"]["L1"].get(l1_code, {})
            l1_nodes[l1_code] = self._build_aggregate_node(meta=meta, child_nodes=child_nodes, cfg=cfg)

        return {
            "version": f"SW-{self.market}-1.0",
            "market": self.market,
            "src": self.src,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "trade_date": trade_date_str,
            "sample_size": sample_size,
            "history_enabled": self.history_enabled,
            "history_years": list(self.history_service.window_years) if self.history_service is not None else [],
            "history_quantile": self.history_service.quantile if self.history_service is not None else None,
            "history_min_samples": self.history_service.min_samples if self.history_service is not None else None,
            "global_defaults": cfg.sw_defaults.get("global_defaults", {}),
            "levels": {
                "L1": l1_nodes,
                "L2": l2_nodes,
                "L3": l3_nodes,
            },
        }

    def _resolve_base_params(self, meta, cfg: StandaloneValuationConfig):
        for name in [meta.get("industry_name"), meta.get("parent_name"), meta.get("grandparent_name")]:
            if not name:
                continue
            try:
                payload = cfg.get_legacy_params_by_industry(name, fuzzy=True)
                return payload.get("big_category"), payload.get("valuation_bucket"), payload.get("params") or {}
            except ValueError:
                continue

        global_payload = cfg.get_global_params()
        return None, "global_defaults", global_payload.get("params") or {}

    def _build_l3_node(
        self,
        meta,
        member_codes,
        daily_basic_df,
        cfg: StandaloneValuationConfig,
        sample_size: int,
        trade_date: str,
    ):
        base_big, base_bucket, base_params = self._resolve_base_params(meta, cfg)
        member_df = daily_basic_df[daily_basic_df["ts_code"].isin(member_codes)].copy()
        if not member_df.empty:
            member_df["pe_ttm"] = pd.to_numeric(member_df["pe_ttm"], errors="coerce")
            member_df["ps_ttm"] = pd.to_numeric(member_df["ps_ttm"], errors="coerce")
            member_df["pb"] = pd.to_numeric(member_df["pb"], errors="coerce")
            member_df["total_mv"] = pd.to_numeric(member_df["total_mv"], errors="coerce")
            member_df["dv_ttm"] = pd.to_numeric(member_df["dv_ttm"], errors="coerce")

        sample_codes = self._select_sample_codes(member_df, sample_size=sample_size)
        fina_snapshots = [self._get_fina_snapshot(ts_code) for ts_code in sample_codes]
        fina_snapshots = [snapshot for snapshot in fina_snapshots if snapshot]

        metrics = {
            "member_count": int(len(member_codes)),
            "sample_count": int(len(sample_codes)),
            "pe_median": self._series_median(member_df.get("pe_ttm"), positive_only=True),
            "ps_median": self._series_median(member_df.get("ps_ttm"), positive_only=True),
            "pb_median": self._series_median(member_df.get("pb"), positive_only=True),
            "dividend_yield_median": self._series_median(member_df.get("dv_ttm"), positive_only=True),
            "market_cap_median_yi": self._series_median(member_df.get("total_mv"), positive_only=True, scale=100000000),
            "growth_median_pct": self._dict_median(
                fina_snapshots,
                keys=["netprofit_yoy", "dt_netprofit_yoy", "tr_yoy", "or_yoy"],
            ),
            "roe_median_pct": self._dict_median(
                fina_snapshots,
                keys=["roe_dt", "roe", "q_roe"],
            ),
        }

        if self.history_service is not None and meta.get("index_code"):
            history_payload = self.history_service.build_history_payload(
                index_code=meta.get("index_code"),
                end_trade_date=trade_date,
            )
            metrics["history_quantiles"] = history_payload.get("metrics", {})
            metrics["history_anchors"] = history_payload.get("anchors", {})

        params = self._derive_params_from_metrics(metrics=metrics, base_params=base_params)

        return {
            "industry_code": meta.get("industry_code"),
            "index_code": meta.get("index_code"),
            "industry_name": meta.get("industry_name"),
            "level": meta.get("level"),
            "parent_index_code": meta.get("parent_index_code"),
            "parent_name": meta.get("parent_name"),
            "grandparent_index_code": meta.get("grandparent_index_code"),
            "grandparent_name": meta.get("grandparent_name"),
            "base_big_category": base_big,
            "base_bucket": base_bucket,
            "member_count": len(member_codes),
            "params": params,
            "metrics": metrics,
        }

    def _build_aggregate_node(self, meta, child_nodes, cfg: StandaloneValuationConfig):
        base_big, base_bucket, base_params = self._resolve_base_params(meta, cfg)
        metrics = self._aggregate_metrics(child_nodes)
        params = self._aggregate_params(child_nodes, fallback_params=base_params)

        return {
            "industry_code": meta.get("industry_code"),
            "index_code": meta.get("index_code"),
            "industry_name": meta.get("industry_name"),
            "level": meta.get("level"),
            "parent_index_code": meta.get("parent_index_code"),
            "parent_name": meta.get("parent_name"),
            "grandparent_index_code": meta.get("grandparent_index_code"),
            "grandparent_name": meta.get("grandparent_name"),
            "base_big_category": base_big,
            "base_bucket": base_bucket,
            "member_count": metrics.get("member_count", 0),
            "params": params,
            "metrics": metrics,
        }

    def _derive_params_from_metrics(self, metrics, base_params):
        pe_target = self._bounded_metric(metrics.get("pe_median"), base_params.get("pe_target"), 0.6, 1.8)
        ps_target = self._bounded_metric(metrics.get("ps_median"), base_params.get("ps_target"), 0.6, 2.0)
        pb_target = self._bounded_metric(metrics.get("pb_median"), base_params.get("pb_target"), 0.6, 2.0)

        pe_target = self._blend_with_history_anchor(
            cross_target=pe_target,
            history_target=self._get_nested(metrics, ["history_anchors", "pe"]),
            global_target=base_params.get("pe_target"),
            lower_ratio=0.6,
            upper_ratio=1.8,
        )
        pb_target = self._blend_with_history_anchor(
            cross_target=pb_target,
            history_target=self._get_nested(metrics, ["history_anchors", "pb"]),
            global_target=base_params.get("pb_target"),
            lower_ratio=0.6,
            upper_ratio=2.0,
        )

        growth_pct = metrics.get("growth_median_pct")
        roe_pct = metrics.get("roe_median_pct")

        normalized_growth = self._clamp((growth_pct / 100.0) if growth_pct is not None else 0.08, -0.02, 0.25)
        base_discount = self._get_nested(base_params, ["dcf_kwargs", "discount_rate"], 0.105)
        quality_adjust = self._clamp(((12 - roe_pct) / 250.0) if roe_pct is not None else 0.0, -0.015, 0.02)
        growth_adjust = self._clamp((0.08 - normalized_growth) / 6.0, -0.01, 0.015)
        discount_rate = self._clamp(base_discount + quality_adjust + growth_adjust, 0.075, 0.16)
        terminal_growth = self._clamp(max(normalized_growth * 0.25, 0.003), 0.003, min(0.03, discount_rate - 0.02))
        dcf_growth_rates = self._build_growth_path(normalized_growth, terminal_growth)
        ddm_growth_rate = self._clamp(min(max(normalized_growth * 0.35, 0.003), terminal_growth), 0.003, 0.025)

        peg_target = base_params.get("peg_target")
        if pe_target is not None and growth_pct is not None and growth_pct > 0:
            peg_target = self._clamp(round(pe_target / max(growth_pct, 5), 2), 0.5, 2.0)

        ev_ebitda_target = base_params.get("ev_ebitda_target")
        sensitivity_grid = {
            "discount_rate": [
                round(self._clamp(discount_rate + shift, 0.07, 0.18), 4) for shift in [0.005, 0.002, 0.0, -0.002, -0.005]
            ],
            "terminal_growth_rate": [
                round(self._clamp(terminal_growth + shift, 0.001, 0.035), 4) for shift in [-0.005, 0.0, 0.005]
            ],
        }

        member_count = metrics.get("member_count")
        sample_count = metrics.get("sample_count")
        member_count = float(member_count) if member_count is not None else None
        sample_count = float(sample_count) if sample_count is not None else None

        if member_count is None:
            scarcity_score = 0.35
        elif member_count <= 5:
            scarcity_score = 0.85
        elif member_count <= 10:
            scarcity_score = 0.72
        elif member_count <= 20:
            scarcity_score = 0.58
        elif member_count <= 40:
            scarcity_score = 0.42
        else:
            scarcity_score = 0.25

        scarcity_confidence = self._clamp((sample_count or 0.0) / 3.0, 0.35, 1.0)
        scarcity_beta = 1.0
        scarcity_cap_pct = 80.0

        result = {
            "pe_target": self._rounded_or_none(pe_target),
            "ps_target": self._rounded_or_none(ps_target),
            "pb_target": self._rounded_or_none(pb_target),
            "target_source": "blend_cross_hist_global"
            if self._get_nested(metrics, ["history_anchors", "pe"]) is not None
            or self._get_nested(metrics, ["history_anchors", "pb"]) is not None
            else "cross_section_with_global_bounds",
            "peg_target": self._rounded_or_none(peg_target),
            "ev_ebitda_target": self._rounded_or_none(ev_ebitda_target),
            "dcf_kwargs": {
                "discount_rate": round(discount_rate, 4),
                "terminal_growth_rate": round(terminal_growth, 4),
                "growth_rates": [round(value, 4) for value in dcf_growth_rates],
            },
            "ddm_kwargs": {
                "discount_rate": round(min(discount_rate + 0.01, 0.18), 4),
                "dividend_growth_rate": round(ddm_growth_rate, 4),
            },
            "scarcity_kwargs": {
                "enabled": True,
                "beta": round(scarcity_beta, 4),
                "cap_pct": round(scarcity_cap_pct, 2),
                "score": round(scarcity_score, 4),
                "confidence": round(scarcity_confidence, 4),
                "confidence_floor": 0.35,
            },
            "scenario_model": base_params.get("scenario_model", "fcff_dcf"),
            "sensitivity_grid": sensitivity_grid,
        }
        return self._clean_none(result)

    def _blend_with_history_anchor(
        self,
        cross_target,
        history_target,
        global_target,
        lower_ratio,
        upper_ratio,
    ):
        if history_target is None:
            return cross_target

        if cross_target is None and global_target is None:
            return history_target

        # Keep blending deterministic and easy to port across services.
        w_cross, w_hist, w_global = 0.5, 0.35, 0.15
        effective_cross = cross_target if cross_target is not None else global_target
        effective_global = global_target if global_target is not None else effective_cross

        blended = (
            float(effective_cross) * w_cross
            + float(history_target) * w_hist
            + float(effective_global) * w_global
        )

        if global_target is None:
            return round(blended, 4)

        lower = float(global_target) * float(lower_ratio)
        upper = float(global_target) * float(upper_ratio)
        return round(self._clamp(blended, lower, upper), 4)

    def _aggregate_metrics(self, child_nodes):
        member_count = sum(node.get("member_count", 0) or 0 for node in child_nodes)
        weights = [max(node.get("member_count", 0) or 0, 1) for node in child_nodes]
        return {
            "member_count": member_count,
            "sample_count": sum(node.get("metrics", {}).get("sample_count", 0) or 0 for node in child_nodes),
            "pe_median": self._weighted_metric(child_nodes, "pe_median", weights),
            "ps_median": self._weighted_metric(child_nodes, "ps_median", weights),
            "pb_median": self._weighted_metric(child_nodes, "pb_median", weights),
            "dividend_yield_median": self._weighted_metric(child_nodes, "dividend_yield_median", weights),
            "market_cap_median_yi": self._weighted_metric(child_nodes, "market_cap_median_yi", weights),
            "growth_median_pct": self._weighted_metric(child_nodes, "growth_median_pct", weights),
            "roe_median_pct": self._weighted_metric(child_nodes, "roe_median_pct", weights),
        }

    def _aggregate_params(self, child_nodes, fallback_params):
        weights = [max(node.get("member_count", 0) or 0, 1) for node in child_nodes]
        if not child_nodes:
            return fallback_params

        params = {
            "pe_target": self._weighted_param(child_nodes, ["params", "pe_target"], weights, fallback_params.get("pe_target")),
            "ps_target": self._weighted_param(child_nodes, ["params", "ps_target"], weights, fallback_params.get("ps_target")),
            "pb_target": self._weighted_param(child_nodes, ["params", "pb_target"], weights, fallback_params.get("pb_target")),
            "peg_target": self._weighted_param(child_nodes, ["params", "peg_target"], weights, fallback_params.get("peg_target")),
            "ev_ebitda_target": self._weighted_param(
                child_nodes,
                ["params", "ev_ebitda_target"],
                weights,
                fallback_params.get("ev_ebitda_target"),
            ),
            "dcf_kwargs": {
                "discount_rate": self._weighted_param(
                    child_nodes,
                    ["params", "dcf_kwargs", "discount_rate"],
                    weights,
                    self._get_nested(fallback_params, ["dcf_kwargs", "discount_rate"]),
                ),
                "terminal_growth_rate": self._weighted_param(
                    child_nodes,
                    ["params", "dcf_kwargs", "terminal_growth_rate"],
                    weights,
                    self._get_nested(fallback_params, ["dcf_kwargs", "terminal_growth_rate"]),
                ),
                "growth_rates": self._weighted_list_param(
                    child_nodes,
                    ["params", "dcf_kwargs", "growth_rates"],
                    weights,
                    self._get_nested(fallback_params, ["dcf_kwargs", "growth_rates"], []),
                ),
            },
            "ddm_kwargs": {
                "discount_rate": self._weighted_param(
                    child_nodes,
                    ["params", "ddm_kwargs", "discount_rate"],
                    weights,
                    self._get_nested(fallback_params, ["ddm_kwargs", "discount_rate"]),
                ),
                "dividend_growth_rate": self._weighted_param(
                    child_nodes,
                    ["params", "ddm_kwargs", "dividend_growth_rate"],
                    weights,
                    self._get_nested(fallback_params, ["ddm_kwargs", "dividend_growth_rate"]),
                ),
            },
            "scarcity_kwargs": {
                "enabled": True,
                "beta": self._weighted_param(
                    child_nodes,
                    ["params", "scarcity_kwargs", "beta"],
                    weights,
                    self._get_nested(fallback_params, ["scarcity_kwargs", "beta"], 1.0),
                ),
                "cap_pct": self._weighted_param(
                    child_nodes,
                    ["params", "scarcity_kwargs", "cap_pct"],
                    weights,
                    self._get_nested(fallback_params, ["scarcity_kwargs", "cap_pct"], 80.0),
                ),
                "score": self._weighted_param(
                    child_nodes,
                    ["params", "scarcity_kwargs", "score"],
                    weights,
                    self._get_nested(fallback_params, ["scarcity_kwargs", "score"], 0.35),
                ),
                "confidence": self._weighted_param(
                    child_nodes,
                    ["params", "scarcity_kwargs", "confidence"],
                    weights,
                    self._get_nested(fallback_params, ["scarcity_kwargs", "confidence"], 0.55),
                ),
                "confidence_floor": self._weighted_param(
                    child_nodes,
                    ["params", "scarcity_kwargs", "confidence_floor"],
                    weights,
                    self._get_nested(fallback_params, ["scarcity_kwargs", "confidence_floor"], 0.35),
                ),
            },
            "scenario_model": fallback_params.get("scenario_model", "fcff_dcf"),
            "sensitivity_grid": {
                "discount_rate": self._weighted_list_param(
                    child_nodes,
                    ["params", "sensitivity_grid", "discount_rate"],
                    weights,
                    self._get_nested(fallback_params, ["sensitivity_grid", "discount_rate"], []),
                ),
                "terminal_growth_rate": self._weighted_list_param(
                    child_nodes,
                    ["params", "sensitivity_grid", "terminal_growth_rate"],
                    weights,
                    self._get_nested(fallback_params, ["sensitivity_grid", "terminal_growth_rate"], []),
                ),
            },
        }
        return self._clean_none(params)

    @staticmethod
    def _select_sample_codes(member_df, sample_size: int):
        if member_df is None or member_df.empty:
            return []
        if "total_mv" not in member_df.columns:
            return member_df["ts_code"].head(sample_size).tolist()
        sampled = member_df.sort_values(by="total_mv", ascending=False)
        return sampled["ts_code"].head(sample_size).tolist()

    def _get_fina_snapshot(self, ts_code: str):
        if ts_code in self._fina_cache:
            return self._fina_cache[ts_code]

        self._throttle_fina_requests()
        df = self.pro.fina_indicator(ts_code=ts_code, limit=1)
        if df is None or df.empty:
            self._fina_cache[ts_code] = None
            return None
        snapshot = df.fillna("").iloc[0].to_dict()
        self._fina_cache[ts_code] = snapshot
        return snapshot

    def _throttle_fina_requests(self):
        if self.request_interval <= 0:
            self._last_fina_request_at = time.time()
            return
        if self._last_fina_request_at is not None:
            elapsed = time.time() - self._last_fina_request_at
            if elapsed < self.request_interval:
                time.sleep(self.request_interval - elapsed)
        self._last_fina_request_at = time.time()

    def _resolve_trade_date(self, trade_date=None):
        if trade_date:
            return str(trade_date).replace("-", "")
        for offset in range(15):
            candidate = (date.today() - timedelta(days=offset)).strftime("%Y%m%d")
            df = self.pro.sw_daily(trade_date=candidate, fields="ts_code")
            if df is not None and not df.empty:
                return candidate
        raise ValueError("Cannot infer latest SW trade_date. Please pass --trade-date.")

    @staticmethod
    def _clean_text(value):
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _clamp(value, lower, upper):
        return max(lower, min(value, upper))

    def _build_growth_path(self, normalized_growth, terminal_growth):
        start_growth = max(normalized_growth, terminal_growth + 0.01)
        path = [
            start_growth,
            max(start_growth * 0.9, terminal_growth + 0.008),
            max(start_growth * 0.8, terminal_growth + 0.005),
            max(start_growth * 0.7, terminal_growth + 0.002),
            max(start_growth * 0.6, terminal_growth),
        ]
        return [self._clamp(value, -0.02, 0.25) for value in path]

    @staticmethod
    def _rounded_or_none(value, digits=4):
        if value is None:
            return None
        return round(float(value), digits)

    def _bounded_metric(self, metric_value, fallback_value, lower_ratio, upper_ratio):
        if metric_value is None:
            return fallback_value
        if fallback_value is None:
            return round(metric_value, 4)
        lower = fallback_value * lower_ratio
        upper = fallback_value * upper_ratio
        return round(self._clamp(metric_value, lower, upper), 4)

    @staticmethod
    def _series_median(series, positive_only=False, scale=1):
        if series is None:
            return None
        cleaned = pd.to_numeric(series, errors="coerce").dropna()
        if positive_only:
            cleaned = cleaned[cleaned > 0]
        if cleaned.empty:
            return None
        return float(cleaned.median()) / scale

    @staticmethod
    def _dict_median(records, keys):
        values = []
        for record in records:
            for key in keys:
                value = record.get(key)
                try:
                    value = float(value)
                except (TypeError, ValueError):
                    value = None
                if value is not None:
                    values.append(value)
                    break
        if not values:
            return None
        return float(pd.Series(values).median())

    def _weighted_metric(self, nodes, metric_key, weights):
        values = []
        effective_weights = []
        for node, weight in zip(nodes, weights):
            value = node.get("metrics", {}).get(metric_key)
            if value is None:
                continue
            values.append(float(value))
            effective_weights.append(weight)
        return self._weighted_average(values, effective_weights)

    def _weighted_param(self, nodes, path, weights, fallback=None):
        values = []
        effective_weights = []
        for node, weight in zip(nodes, weights):
            value = self._get_nested(node, path)
            if value is None:
                continue
            values.append(float(value))
            effective_weights.append(weight)
        result = self._weighted_average(values, effective_weights)
        return fallback if result is None else round(result, 4)

    def _weighted_list_param(self, nodes, path, weights, fallback=None):
        fallback = fallback or []
        max_len = max((len(self._get_nested(node, path, []) or []) for node in nodes), default=0)
        if not max_len:
            return fallback
        values = []
        for idx in range(max_len):
            indexed_values = []
            indexed_weights = []
            for node, weight in zip(nodes, weights):
                data = self._get_nested(node, path, []) or []
                if idx >= len(data):
                    continue
                indexed_values.append(float(data[idx]))
                indexed_weights.append(weight)
            averaged = self._weighted_average(indexed_values, indexed_weights)
            if averaged is not None:
                values.append(round(averaged, 4))
        return values or fallback

    @staticmethod
    def _weighted_average(values, weights):
        if not values or not weights:
            return None
        total_weight = sum(weights)
        if not total_weight:
            return None
        return sum(value * weight for value, weight in zip(values, weights)) / total_weight

    @staticmethod
    def _get_nested(data, path, default=None):
        current = data
        for key in path:
            if not isinstance(current, dict) or key not in current:
                return default
            current = current[key]
        return current

    def _clean_none(self, data):
        if isinstance(data, dict):
            cleaned = {}
            for key, value in data.items():
                normalized = self._clean_none(value)
                if normalized is None:
                    continue
                if normalized == {} or normalized == []:
                    continue
                cleaned[key] = normalized
            return cleaned
        if isinstance(data, list):
            return [self._clean_none(item) for item in data if item is not None]
        return data

    @staticmethod
    def _load_json(path: Path):
        with path.open("r", encoding="utf-8") as file_obj:
            return json.load(file_obj)

    def _write_json(self, path: Path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self._clean_none(data), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
