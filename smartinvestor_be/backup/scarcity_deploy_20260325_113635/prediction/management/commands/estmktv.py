import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
import pandas as pd

from datastore.models import Corporation
from prediction.services.business_industry_matcher import BusinessIndustryMatcher
from prediction.services.validation_loader import ValuationConfig
from prediction.utils.prediction_util import get_stock_valuation_snapshot, test_valuation


class Command(BaseCommand):
    help = "Estimate market value using JSON valuation defaults by industry"

    def _prepare_output_encoding(self):
        for stream in [self.stdout, self.stderr]:
            raw_stream = getattr(stream, "_out", None)
            if raw_stream is not None and hasattr(raw_stream, "reconfigure"):
                raw_stream.reconfigure(encoding="utf-8")

    @staticmethod
    def _build_output_df(result):
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
        output_df["evaluated_market_value"] = (
            output_df["evaluated_market_value"] / 100000000
        )
        for column in ["evaluated_market_value", "according_price"]:
            output_df[column] = output_df[column].round(4)
        output_df = output_df.where(output_df.notna(), None)
        return output_df

    @classmethod
    def _build_output(cls, result):
        output_df = cls._build_output_df(result)
        if output_df is None or output_df.empty:
            return "No valuation results"
        return output_df.to_string(index=False)

    @staticmethod
    def _format_metric(value):
        if value is None:
            return "None"
        if isinstance(value, (int, float)):
            return f"{value:.4f}"
        return str(value)

    def _write_profit_source_details(
        self,
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
        self.stdout.write(f"profit_data_source: {snapshot.get('profit_data_source')}")
        self.stdout.write(f"strict_express_match: {snapshot.get('strict_express_match')}")
        self.stdout.write(f"express_max_age_days: {snapshot.get('express_max_age_days')}")
        self.stdout.write(f"express_apply_reason: {snapshot.get('express_apply_reason')}")
        self.stdout.write(f"express_block_reason: {snapshot.get('express_block_reason')}")
        self.stdout.write(f"profit_snapshot_trade_date: {snapshot.get('trade_date')}")
        self.stdout.write(f"profit_snapshot_end_date: {snapshot.get('end_date')}")
        self.stdout.write(f"express_end_date: {snapshot.get('express_end_date')}")
        self.stdout.write(f"express_ann_date: {snapshot.get('express_ann_date')}")

        self.stdout.write(
            "peg_growth_yoy_pct(base->effective): "
            f"{self._format_metric(snapshot.get('base_peg_growth_yoy_pct'))} -> "
            f"{self._format_metric(snapshot.get('peg_growth_yoy_pct'))}"
        )
        self.stdout.write(
            "netprofit(base->effective): "
            f"{self._format_metric(snapshot.get('base_netprofit'))} -> "
            f"{self._format_metric(snapshot.get('netprofit'))}"
        )
        self.stdout.write(
            "revenue(base->effective): "
            f"{self._format_metric(snapshot.get('base_revenue'))} -> "
            f"{self._format_metric(snapshot.get('revenue'))}"
        )
        self.stdout.write(
            f"express_blend_alpha: {self._format_metric(snapshot.get('express_blend_alpha'))}"
        )

    @staticmethod
    def _build_multi_output(output_frames):
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
    def _build_comparison_frame(
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
        output_df = cls._build_output_df(result)
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

    def add_arguments(self, parser):
        parser.add_argument("--tscode", type=str, required=True, help="TS code")
        parser.add_argument("--trade_date", type=str, help="Trade date (YYYYMMDD)")
        parser.add_argument("--ann_date", type=str, help="Announcement date (reserved)")
        parser.add_argument("--est_method", type=str, help="Override scenario_model")
        parser.add_argument("--industry", type=str, help="细分行业名称，如：白酒、半导体、公路")
        parser.add_argument(
            "--force-sw-industry",
            type=str,
            help="Force valuation using a specific SW industry name or index code",
        )
        parser.add_argument(
            "--force-sw-level",
            type=str,
            choices=["L1", "L2", "L3"],
            help="Optional SW level when force-sw-industry is provided",
        )
        parser.add_argument(
            "--match-business-industries",
            action="store_true",
            default=False,
            help="Infer multiple SW industries from stock_company business text and run valuation for each",
        )
        parser.add_argument(
            "--business-match-level",
            type=str,
            choices=["ALL", "L1", "L2", "L3"],
            default="L2",
            help="SW level used when matching business text",
        )
        parser.add_argument(
            "--business-topn",
            type=int,
            default=3,
            help="Top N matched industries for business-text valuation",
        )
        parser.add_argument(
            "--disable-business-fallback",
            action="store_true",
            default=False,
            help="Disable automatic fallback when business-text match confidence is low",
        )
        parser.add_argument("--market", type=str, default="CN", help="Market code, default CN")
        parser.add_argument(
            "--no-fuzzy",
            action="store_true",
            default=False,
            help="Disable fuzzy industry mapping",
        )
        parser.add_argument(
            "--show-source",
            action="store_true",
            default=False,
            help="Show valuation parameter source",
        )
        parser.add_argument(
            "--show-sw-levels",
            action="store_true",
            default=False,
            help="Show SW L1/L2/L3 industry hierarchy",
        )
        parser.add_argument(
            "--show-citic-levels",
            action="store_true",
            default=False,
            help="Show CITIC L1/L2/L3 hierarchy and mapped SW targets",
        )
        parser.add_argument(
            "--show-match-keywords",
            action="store_true",
            default=False,
            help="Show matched business keywords when using business industry matching",
        )
        parser.add_argument(
            "--show-profit-source",
            action="store_true",
            default=False,
            help="Show profit data source and express blend diagnostics",
        )
        parser.add_argument(
            "--no-strict-express-match",
            action="store_true",
            default=False,
            help="Disable strict express_vip matching rules (ann_date visibility, period consistency, freshness)",
        )
        parser.add_argument(
            "--express-max-age-days",
            type=int,
            default=180,
            help="Maximum allowed age in days for express ann_date relative to trade_date under strict mode",
        )
        parser.add_argument("--resume", type=str, help="Resume from a specific step", default=None)

    def _resolve_industry_by_tscode(self, tscode):
        corporation = (
            Corporation.objects.select_related("industry")
            .filter(ts_code=tscode)
            .only("ts_code", "name", "industry__name")
            .first()
        )
        if corporation is None:
            return None, None
        industry_name = corporation.industry.name if corporation.industry else None
        return corporation, industry_name

    def _load_sw_valuation_params(self, tscode, market="CN"):
        base_dir = Path(settings.BASE_DIR) / "static"
        cfg = ValuationConfig(base_dir, market=market)
        sw_info = cfg.get_sw_params_by_tscode(tscode)
        return self._format_sw_config_info(sw_info, source_prefix="sw")

    def _load_forced_sw_valuation_params(self, industry, market="CN", level=None, fuzzy=True):
        base_dir = Path(settings.BASE_DIR) / "static"
        cfg = ValuationConfig(base_dir, market=market)
        sw_info = cfg.get_sw_params_by_industry(industry=industry, level=level, fuzzy=fuzzy)
        return self._format_sw_config_info(sw_info, source_prefix="forced_sw")

    def _match_business_industries(self, tscode, market="CN", level="L2", top_n=3):
        base_dir = Path(settings.BASE_DIR) / "static"
        matcher = BusinessIndustryMatcher(base_dir, market=market)
        return matcher.match_by_tscode(tscode, top_n=top_n, level=level)

    def _load_citic_context(self, tscode, market="CN", level="L2"):
        base_dir = Path(settings.BASE_DIR) / "static"
        matcher = BusinessIndustryMatcher(base_dir, market=market)
        return matcher.get_citic_context(tscode, level=level)

    def _load_business_fallback_settings(self, market="CN", citic_profile=None):
        defaults = {
            "top_score_min": 6.0,
            "top_two_gap_min": 0.8,
            "gap_check_score_cap": 12.0,
            "citic_alignment_score_min": 12.0,
            "profile_name": "default",
        }
        config_path = (
            Path(settings.BASE_DIR)
            / "static"
            / "valuation_config"
            / f"business_keyword_rules_{market}.json"
        )
        if not config_path.exists():
            return defaults
        with config_path.open("r", encoding="utf-8") as file_obj:
            config_data = json.load(file_obj)
        settings_data = config_data.get("business_match_fallback", {})
        resolved = {
            "top_score_min": float(settings_data.get("top_score_min", defaults["top_score_min"])),
            "top_two_gap_min": float(settings_data.get("top_two_gap_min", defaults["top_two_gap_min"])),
            "gap_check_score_cap": float(settings_data.get("gap_check_score_cap", defaults["gap_check_score_cap"])),
            "citic_alignment_score_min": float(settings_data.get("citic_alignment_score_min", defaults["citic_alignment_score_min"])),
            "profile_name": "default",
        }

        citic_l1_name = (citic_profile or {}).get("l1_name")
        l1_overrides = settings_data.get("citic_l1_overrides", {})
        if citic_l1_name and citic_l1_name in l1_overrides:
            override = l1_overrides[citic_l1_name] or {}
            resolved.update(
                {
                    "top_score_min": float(override.get("top_score_min", resolved["top_score_min"])),
                    "top_two_gap_min": float(override.get("top_two_gap_min", resolved["top_two_gap_min"])),
                    "gap_check_score_cap": float(override.get("gap_check_score_cap", resolved["gap_check_score_cap"])),
                    "citic_alignment_score_min": float(
                        override.get(
                            "citic_alignment_score_min",
                            resolved["citic_alignment_score_min"],
                        )
                    ),
                    "profile_name": f"citic_l1:{citic_l1_name}",
                }
            )

        citic_l2_name = (citic_profile or {}).get("l2_name")
        l2_overrides = settings_data.get("citic_l2_overrides", {})
        if citic_l2_name and citic_l2_name in l2_overrides:
            override = l2_overrides[citic_l2_name] or {}
            resolved.update(
                {
                    "top_score_min": float(override.get("top_score_min", resolved["top_score_min"])),
                    "top_two_gap_min": float(override.get("top_two_gap_min", resolved["top_two_gap_min"])),
                    "gap_check_score_cap": float(override.get("gap_check_score_cap", resolved["gap_check_score_cap"])),
                    "citic_alignment_score_min": float(
                        override.get(
                            "citic_alignment_score_min",
                            resolved["citic_alignment_score_min"],
                        )
                    ),
                    "profile_name": f"citic_l2:{citic_l2_name}",
                }
            )

        citic_l3_name = (citic_profile or {}).get("l3_name")
        l3_overrides = settings_data.get("citic_l3_overrides", {})
        if citic_l3_name and citic_l3_name in l3_overrides:
            override = l3_overrides[citic_l3_name] or {}
            resolved.update(
                {
                    "top_score_min": float(override.get("top_score_min", resolved["top_score_min"])),
                    "top_two_gap_min": float(override.get("top_two_gap_min", resolved["top_two_gap_min"])),
                    "gap_check_score_cap": float(override.get("gap_check_score_cap", resolved["gap_check_score_cap"])),
                    "citic_alignment_score_min": float(
                        override.get(
                            "citic_alignment_score_min",
                            resolved["citic_alignment_score_min"],
                        )
                    ),
                    "profile_name": f"citic_l3:{citic_l3_name}",
                }
            )
        return resolved

    @staticmethod
    def _choose_citic_fallback_match(matches, citic_mappings):
        if not citic_mappings:
            return None
        mapped_scores = {}
        mapped_meta = {}
        for mapping in citic_mappings:
            key = (mapping.get("target_level"), mapping.get("target_code"))
            mapped_scores[key] = mapped_scores.get(key, 0.0) + float(mapping.get("boost") or 0.0)
            mapped_meta[key] = mapping

        if matches:
            for match in matches:
                key = (match.get("level"), match.get("industry_code"))
                if key in mapped_scores:
                    return {
                        "level": match.get("level"),
                        "industry_code": match.get("industry_code"),
                        "industry_name": match.get("industry_name"),
                    }

        if not mapped_scores:
            return None
        best_key = max(mapped_scores.items(), key=lambda item: item[1])[0]
        meta = mapped_meta[best_key]
        return {
            "level": meta.get("target_level"),
            "industry_code": meta.get("target_code"),
            "industry_name": meta.get("target_name"),
        }

    @staticmethod
    def _should_fallback_business_match(matches, citic_mappings, fallback_settings=None):
        if not matches:
            return True, "no_business_matches"

        fallback_settings = fallback_settings or {
            "top_score_min": 6.0,
            "top_two_gap_min": 0.8,
            "gap_check_score_cap": 12.0,
            "citic_alignment_score_min": 12.0,
        }

        top_score = float(matches[0].get("score") or 0.0)
        second_score = float(matches[1].get("score") or 0.0) if len(matches) > 1 else None
        top_key = (matches[0].get("level"), matches[0].get("industry_code"))
        citic_targets = {
            (mapping.get("target_level"), mapping.get("target_code"))
            for mapping in citic_mappings or []
        }

        if top_score < fallback_settings["top_score_min"]:
            return True, "top_score_below_threshold"
        if (
            second_score is not None
            and (top_score - second_score) < fallback_settings["top_two_gap_min"]
            and top_score < fallback_settings["gap_check_score_cap"]
        ):
            return True, "top_two_too_close"
        if (
            citic_targets
            and top_key not in citic_targets
            and top_score < fallback_settings["citic_alignment_score_min"]
        ):
            return True, "top_match_outside_citic_targets"
        return False, None

    def _build_business_fallback_config(self, tscode, matches, citic_mappings, market, fuzzy):
        fallback_match = self._choose_citic_fallback_match(matches, citic_mappings)
        if fallback_match is not None:
            config_info = self._load_forced_sw_valuation_params(
                industry=fallback_match["industry_code"],
                market=market,
                level=fallback_match["level"],
                fuzzy=False,
            )
            config_info["source"] = f"{config_info.get('source')}_business_fallback"
            config_info["fallback_match"] = fallback_match
            return config_info

        try:
            config_info = self._load_sw_valuation_params(tscode=tscode, market=market)
            config_info["source"] = f"{config_info.get('source')}_business_fallback"
            return config_info
        except (ValueError, FileNotFoundError, KeyError):
            _corporation, industry = self._resolve_industry_by_tscode(tscode)
            return self._load_valuation_params(industry=industry, market=market, fuzzy=fuzzy)

    @staticmethod
    def _format_citic_mapping_summary(citic_mappings):
        if not citic_mappings:
            return None
        targets = []
        for mapping in citic_mappings:
            target_label = f"{mapping.get('target_level')}:{mapping.get('target_name')}"
            if target_label not in targets:
                targets.append(target_label)
        return "|".join(targets)

    @staticmethod
    def _format_sw_config_info(sw_info, source_prefix="sw"):
        hierarchy = sw_info.get("hierarchy", {})
        return {
            "source": f"{source_prefix}_{sw_info.get('level', 'unknown').lower()}",
            "input_industry": hierarchy.get("l3_name"),
            "big_category": hierarchy.get("l1_name"),
            "valuation_bucket": sw_info.get("industry_code") or sw_info.get("level"),
            "sw_levels": {
                "l1_code": hierarchy.get("l1_code"),
                "l1": hierarchy.get("l1_name"),
                "l2_code": hierarchy.get("l2_code"),
                "l2": hierarchy.get("l2_name"),
                "l3_code": hierarchy.get("l3_code"),
                "l3": hierarchy.get("l3_name"),
            },
            "matched_sw": {
                "level": sw_info.get("matched_level") or sw_info.get("level"),
                "industry_code": sw_info.get("matched_industry_code") or sw_info.get("industry_code"),
                "industry_name": sw_info.get("matched_industry_name") or sw_info.get("industry_name"),
            },
            "params": sw_info.get("params", {}),
        }

    def _load_valuation_params(self, industry=None, market="CN", fuzzy=True):
        base_dir = Path(settings.BASE_DIR) / "static"
        cfg = ValuationConfig(base_dir, market=market)

        if industry:
            big, bucket, params = cfg.get_params_by_narrow_industry(industry, fuzzy=fuzzy)
            return {
                "source": "legacy_industry_mapping",
                "input_industry": industry,
                "big_category": big,
                "valuation_bucket": bucket,
                "sw_levels": None,
                "params": params,
            }

        params = cfg.get_global_params()
        if not params:
            raise CommandError("valuation defaults 中未找到可用参数。")
        return {
            "source": "global_defaults",
            "input_industry": None,
            "big_category": None,
            "valuation_bucket": "global_defaults",
            "sw_levels": None,
            "params": params,
        }

    def handle(self, *_args, **options):
        self._prepare_output_encoding()

        tscode = options["tscode"]
        trade_date = options["trade_date"]
        est_method = options["est_method"]
        industry = options["industry"]
        force_sw_industry = options["force_sw_industry"]
        force_sw_level = options["force_sw_level"]
        match_business_industries = options["match_business_industries"]
        business_match_level = options["business_match_level"]
        business_topn = options["business_topn"]
        disable_business_fallback = options["disable_business_fallback"]
        market = options["market"]
        fuzzy = not options["no_fuzzy"]
        show_source = options["show_source"]
        show_sw_levels = options["show_sw_levels"]
        show_citic_levels = options["show_citic_levels"]
        show_match_keywords = options["show_match_keywords"]
        show_profit_source = options["show_profit_source"]
        strict_express_match = not options["no_strict_express_match"]
        express_max_age_days = options["express_max_age_days"]
        express_guard_kwargs = {
            "strict_express_match": strict_express_match,
            "express_max_age_days": express_max_age_days,
        }
        config_info = None

        if match_business_industries:
            try:
                matched_payload = self._match_business_industries(
                    tscode=tscode,
                    market=market,
                    level=business_match_level,
                    top_n=business_topn,
                )
            except Exception as exc:
                raise CommandError(str(exc)) from exc

            matches = matched_payload.get("matches", [])
            citic_profile = matched_payload.get("citic_profile", {})
            citic_mappings = matched_payload.get("citic_mappings", [])
            citic_mapping_summary = self._format_citic_mapping_summary(citic_mappings)
            baseline_frames = []
            try:
                baseline_config = self._load_sw_valuation_params(tscode=tscode, market=market)
                baseline_params = dict(baseline_config["params"])
                if est_method:
                    baseline_params["scenario_model"] = est_method
                baseline_result = test_valuation(
                    ts_code=tscode,
                    trade_date=trade_date,
                    **express_guard_kwargs,
                    **baseline_params,
                )
                baseline_match = baseline_config.get("matched_sw") or {}
                baseline_frames.append(
                    self._build_comparison_frame(
                        result=baseline_result,
                        compare_group="sw_l3_baseline",
                        industry_level=baseline_match.get("level"),
                        industry_code=baseline_match.get("industry_code"),
                        industry_name=baseline_match.get("industry_name"),
                        source=baseline_config.get("source") if show_source else None,
                        citic_profile=citic_profile if show_citic_levels else None,
                        citic_mapping_summary=citic_mapping_summary if show_citic_levels else None,
                        include_source=show_source,
                        include_citic=show_citic_levels,
                    )
                )
                baseline_frames = [frame for frame in baseline_frames if frame is not None]
            except (ValueError, FileNotFoundError, KeyError):
                baseline_frames = []

            fallback_settings = self._load_business_fallback_settings(
                market=market,
                citic_profile=citic_profile,
            )
            should_fallback, fallback_reason = self._should_fallback_business_match(
                matches=matches,
                citic_mappings=citic_mappings,
                fallback_settings=fallback_settings,
            )

            if (not matches) or (should_fallback and not disable_business_fallback):
                try:
                    config_info = self._build_business_fallback_config(
                        tscode=tscode,
                        matches=matches,
                        citic_mappings=citic_mappings,
                        market=market,
                        fuzzy=fuzzy,
                    )
                except Exception as exc:
                    raise CommandError(str(exc)) from exc

                valuation_params = dict(config_info["params"])
                if est_method:
                    valuation_params["scenario_model"] = est_method
                result = test_valuation(
                    ts_code=tscode,
                    trade_date=trade_date,
                    **express_guard_kwargs,
                    **valuation_params,
                )
                profile = matched_payload.get("profile", {})
                if show_source:
                    self.stdout.write(f"business_text_source: {profile.get('source')}")
                    self.stdout.write(
                        f"business_match_fallback_profile: {fallback_settings.get('profile_name', 'default')}"
                    )
                    self.stdout.write(f"business_match_fallback: {fallback_reason or 'no_business_matches'}")
                    self.stdout.write(f"source: {config_info.get('source')}")
                if show_sw_levels:
                    sw_levels = config_info.get("sw_levels") or {}
                    self.stdout.write(f"sw_l1: {sw_levels.get('l1_code')} {sw_levels.get('l1')}")
                    self.stdout.write(f"sw_l2: {sw_levels.get('l2_code')} {sw_levels.get('l2')}")
                    self.stdout.write(f"sw_l3: {sw_levels.get('l3_code')} {sw_levels.get('l3')}")
                if show_citic_levels:
                    self.stdout.write(f"citic_l1: {citic_profile.get('l1_code')} {citic_profile.get('l1_name')}")
                    self.stdout.write(f"citic_l2: {citic_profile.get('l2_code')} {citic_profile.get('l2_name')}")
                    self.stdout.write(f"citic_l3: {citic_profile.get('l3_code')} {citic_profile.get('l3_name')}")
                    self.stdout.write(f"citic_sw_targets: {citic_mapping_summary}")
                fallback_match = config_info.get("fallback_match") or config_info.get("matched_sw") or {}
                fallback_frame = self._build_comparison_frame(
                    result=result,
                    compare_group="business_fallback",
                    industry_level=fallback_match.get("level"),
                    industry_code=fallback_match.get("industry_code"),
                    industry_name=fallback_match.get("industry_name"),
                    source=config_info.get("source") if show_source else None,
                    citic_profile=citic_profile,
                    citic_mapping_summary=citic_mapping_summary,
                    include_source=show_source,
                    include_citic=show_citic_levels,
                )
                if show_profit_source:
                    self._write_profit_source_details(
                        tscode=tscode,
                        trade_date=trade_date,
                        **express_guard_kwargs,
                    )
                self.stdout.write(self._build_multi_output(baseline_frames + ([fallback_frame] if fallback_frame is not None else [])))
                return

            output_frames = list(baseline_frames)
            for match in matches:
                config_info = self._load_forced_sw_valuation_params(
                    industry=match["industry_code"],
                    market=market,
                    level=match["level"],
                    fuzzy=False,
                )
                valuation_params = dict(config_info["params"])
                if est_method:
                    valuation_params["scenario_model"] = est_method
                result = test_valuation(
                    ts_code=tscode,
                    trade_date=trade_date,
                    **express_guard_kwargs,
                    **valuation_params,
                )
                output_df = self._build_comparison_frame(
                    result=result,
                    compare_group="business_match",
                    industry_level=match["level"],
                    industry_code=match["industry_code"],
                    industry_name=match["industry_name"],
                    match_score=match["score"],
                    source=config_info.get("source") if show_source else None,
                    matched_keywords=",".join(match.get("matched_keywords", [])) if show_match_keywords else None,
                    citic_profile=citic_profile,
                    citic_mapping_summary=citic_mapping_summary,
                    include_source=show_source,
                    include_keywords=show_match_keywords,
                    include_citic=show_citic_levels,
                )
                if output_df is None or output_df.empty:
                    continue
                output_frames.append(output_df)

            if not output_frames:
                raise CommandError("已匹配到行业，但未生成可用估值结果。")

            profile = matched_payload.get("profile", {})
            if show_source:
                self.stdout.write(f"business_text_source: {profile.get('source')}")
            if show_citic_levels:
                self.stdout.write(f"citic_l1: {citic_profile.get('l1_code')} {citic_profile.get('l1_name')}")
                self.stdout.write(f"citic_l2: {citic_profile.get('l2_code')} {citic_profile.get('l2_name')}")
                self.stdout.write(f"citic_l3: {citic_profile.get('l3_code')} {citic_profile.get('l3_name')}")
                self.stdout.write(f"citic_sw_targets: {citic_mapping_summary}")
            if show_profit_source:
                self._write_profit_source_details(
                    tscode=tscode,
                    trade_date=trade_date,
                    **express_guard_kwargs,
                )
            self.stdout.write(self._build_multi_output(output_frames))
            return

        if force_sw_industry:
            try:
                config_info = self._load_forced_sw_valuation_params(
                    industry=force_sw_industry,
                    market=market,
                    level=force_sw_level,
                    fuzzy=fuzzy,
                )
            except (ValueError, FileNotFoundError, KeyError) as exc:
                raise CommandError(str(exc)) from exc
        elif not industry:
            try:
                config_info = self._load_sw_valuation_params(tscode=tscode, market=market)
            except (ValueError, FileNotFoundError, KeyError):
                _corporation, industry = self._resolve_industry_by_tscode(tscode)

        if config_info is None:
            try:
                config_info = self._load_valuation_params(
                    industry=industry,
                    market=market,
                    fuzzy=fuzzy,
                )
            except Exception as exc:
                raise CommandError(str(exc)) from exc

        valuation_params = dict(config_info["params"])
        if est_method:
            valuation_params["scenario_model"] = est_method

        result = test_valuation(
            ts_code=tscode,
            trade_date=trade_date,
            **express_guard_kwargs,
            **valuation_params,
        )

        if show_source:
            self.stdout.write(f"source: {config_info.get('source')}")
        if show_sw_levels:
            sw_levels = config_info.get("sw_levels") or {}
            matched_sw = config_info.get("matched_sw") or {}
            if force_sw_industry:
                self.stdout.write(
                    f"forced_sw: {matched_sw.get('level')} {matched_sw.get('industry_code')} {matched_sw.get('industry_name')}"
                )
            self.stdout.write(f"sw_l1: {sw_levels.get('l1_code')} {sw_levels.get('l1')}")
            self.stdout.write(f"sw_l2: {sw_levels.get('l2_code')} {sw_levels.get('l2')}")
            self.stdout.write(f"sw_l3: {sw_levels.get('l3_code')} {sw_levels.get('l3')}")
        if show_citic_levels:
            citic_context = self._load_citic_context(tscode=tscode, market=market, level="L2")
            citic_profile = citic_context.get("citic_profile", {})
            citic_mapping_summary = self._format_citic_mapping_summary(
                citic_context.get("citic_mappings", [])
            )
            self.stdout.write(f"citic_l1: {citic_profile.get('l1_code')} {citic_profile.get('l1_name')}")
            self.stdout.write(f"citic_l2: {citic_profile.get('l2_code')} {citic_profile.get('l2_name')}")
            self.stdout.write(f"citic_l3: {citic_profile.get('l3_code')} {citic_profile.get('l3_name')}")
            self.stdout.write(f"citic_sw_targets: {citic_mapping_summary}")
        if show_profit_source:
            self._write_profit_source_details(
                tscode=tscode,
                trade_date=trade_date,
                **express_guard_kwargs,
            )
        self.stdout.write(self._build_output(result))