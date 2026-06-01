from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from datastore.models import Corporation
from prediction.services.business_fallback_engine import BusinessFallbackEngine
from prediction.services.business_industry_matcher import BusinessIndustryMatcher
from prediction.services.output_formatter import EstMktvOutputFormatter
from prediction.services.scarcity_auto_engine import ScarcityAutoEngine
from prediction.services.validation_loader import ValuationConfig
from prediction.utils.valuation_util import test_valuation


class Command(BaseCommand):
    help = "Estimate market value using JSON valuation defaults by industry"
    SCARCITY_AUTO_PROFILE_DEFAULTS = ScarcityAutoEngine.SCARCITY_AUTO_PROFILE_DEFAULTS
    SCARCITY_PROFILE_PRESETS = ScarcityAutoEngine.SCARCITY_PROFILE_PRESETS
    SCARCITY_AUTOFILL_DEFAULTS = ScarcityAutoEngine.SCARCITY_AUTOFILL_DEFAULTS
    _scarcity_auto_profile_cache = ScarcityAutoEngine._scarcity_auto_profile_cache

    def _prepare_output_encoding(self):
        for stream in [self.stdout, self.stderr]:
            raw_stream = getattr(stream, "_out", None)
            if raw_stream is not None and hasattr(raw_stream, "reconfigure"):
                raw_stream.reconfigure(encoding="utf-8")

    @staticmethod
    def _build_output_df(result):
        return EstMktvOutputFormatter.build_output_df(result)

    @classmethod
    def _build_output(cls, result):
        return EstMktvOutputFormatter.build_output(result)

    @staticmethod
    def _format_metric(value):
        return EstMktvOutputFormatter.format_metric(value)

    def _write_profit_source_details(
        self,
        tscode,
        trade_date=None,
        strict_express_match=True,
        express_max_age_days=180,
    ):
        lines = EstMktvOutputFormatter.build_profit_source_lines(
            tscode=tscode,
            trade_date=trade_date,
            strict_express_match=strict_express_match,
            express_max_age_days=express_max_age_days,
        )
        for line in lines:
            self.stdout.write(line)

    @staticmethod
    def _build_multi_output(output_frames):
        return EstMktvOutputFormatter.build_multi_output(output_frames)

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
        return EstMktvOutputFormatter.build_comparison_frame(
            result=result,
            compare_group=compare_group,
            industry_level=industry_level,
            industry_code=industry_code,
            industry_name=industry_name,
            match_score=match_score,
            source=source,
            matched_keywords=matched_keywords,
            citic_profile=citic_profile,
            citic_mapping_summary=citic_mapping_summary,
            include_source=include_source,
            include_keywords=include_keywords,
            include_citic=include_citic,
        )

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
        parser.add_argument(
            "--scarcity-profile",
            type=str,
            choices=["conservative", "balanced", "aggressive", "off", "auto"],
            default=None,
            help="Override scarcity kwargs profile for this run",
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
        return BusinessFallbackEngine.load_business_fallback_settings(
            market=market,
            citic_profile=citic_profile,
        )

    @staticmethod
    def _choose_citic_fallback_match(matches, citic_mappings):
        return BusinessFallbackEngine.choose_citic_fallback_match(matches, citic_mappings)

    @staticmethod
    def _should_fallback_business_match(matches, citic_mappings, fallback_settings=None):
        return BusinessFallbackEngine.should_fallback_business_match(
            matches=matches,
            citic_mappings=citic_mappings,
            fallback_settings=fallback_settings,
        )

    def _build_business_fallback_config(self, tscode, matches, citic_mappings, market, fuzzy):
        return BusinessFallbackEngine.build_business_fallback_config(
            tscode=tscode,
            matches=matches,
            citic_mappings=citic_mappings,
            market=market,
            fuzzy=fuzzy,
            load_forced_sw_valuation_params=self._load_forced_sw_valuation_params,
            load_sw_valuation_params=self._load_sw_valuation_params,
            resolve_industry_by_tscode=self._resolve_industry_by_tscode,
            load_valuation_params=self._load_valuation_params,
        )

    @staticmethod
    def _format_citic_mapping_summary(citic_mappings):
        return EstMktvOutputFormatter.format_citic_mapping_summary(citic_mappings)

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

    @classmethod
    def _autofill_scarcity_kwargs(cls, scarcity_kwargs):
        return ScarcityAutoEngine._autofill_scarcity_kwargs(scarcity_kwargs)

    @staticmethod
    def _safe_float(value, default=None):
        return ScarcityAutoEngine._safe_float(value, default=default)

    @staticmethod
    def _clamp_unit(value):
        return ScarcityAutoEngine._clamp_unit(value)

    @staticmethod
    def _parse_run_date(value):
        return ScarcityAutoEngine._parse_run_date(value)

    @staticmethod
    def _format_run_date(value):
        return ScarcityAutoEngine._format_run_date(value)

    @classmethod
    def _load_scarcity_auto_state(cls, market="CN"):
        return ScarcityAutoEngine._load_scarcity_auto_state(market=market)

    @classmethod
    def _save_scarcity_auto_state(cls, state_path, state_payload):
        return ScarcityAutoEngine._save_scarcity_auto_state(state_path, state_payload)

    @classmethod
    def _derive_auto_risk_indicators_from_df(cls, trading_df, run_day=None):
        return ScarcityAutoEngine._derive_auto_risk_indicators_from_df(
            trading_df=trading_df,
            run_day=run_day,
        )

    @classmethod
    def _compute_auto_risk_indicators(cls, tscode, trade_date=None):
        return ScarcityAutoEngine._compute_auto_risk_indicators(
            tscode=tscode,
            trade_date=trade_date,
        )

    @classmethod
    def _load_scarcity_auto_profile(cls, market="CN"):
        return ScarcityAutoEngine._load_scarcity_auto_profile(market=market)

    @classmethod
    def _resolve_auto_target_profile(cls, risk_score, last_profile, auto_profile_cfg):
        return ScarcityAutoEngine._resolve_auto_target_profile(
            risk_score=risk_score,
            last_profile=last_profile,
            auto_profile_cfg=auto_profile_cfg,
        )

    @classmethod
    def _resolve_auto_scarcity_profile(
        cls,
        scarcity_kwargs,
        auto_profile_cfg=None,
        tscode=None,
        market="CN",
        run_date=None,
    ):
        return ScarcityAutoEngine._resolve_auto_scarcity_profile(
            scarcity_kwargs=scarcity_kwargs,
            auto_profile_cfg=auto_profile_cfg,
            tscode=tscode,
            market=market,
            run_date=run_date,
        )

    @classmethod
    def _apply_scarcity_profile(
        cls,
        valuation_params,
        scarcity_profile,
        market="CN",
        tscode=None,
        trade_date=None,
    ):
        return ScarcityAutoEngine._apply_scarcity_profile(
            valuation_params=valuation_params,
            scarcity_profile=scarcity_profile,
            market=market,
            tscode=tscode,
            trade_date=trade_date,
        )

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
        scarcity_profile = options["scarcity_profile"]
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
                baseline_params, _baseline_scarcity_meta = self._apply_scarcity_profile(
                    baseline_params,
                    scarcity_profile,
                    market=market,
                    tscode=tscode,
                    trade_date=trade_date,
                )
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
                valuation_params, scarcity_meta = self._apply_scarcity_profile(
                    valuation_params,
                    scarcity_profile,
                    market=market,
                    tscode=tscode,
                    trade_date=trade_date,
                )
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
                    if scarcity_meta.get("requested_profile"):
                        self.stdout.write(f"scarcity_profile: {scarcity_meta.get('requested_profile')}")
                        self.stdout.write(f"scarcity_profile_effective: {scarcity_meta.get('effective_profile')}")
                        if scarcity_meta.get("auto_reason"):
                            self.stdout.write(f"scarcity_profile_auto_reason: {scarcity_meta.get('auto_reason')}")
                    if scarcity_meta.get("autofilled_keys"):
                        self.stdout.write(
                            f"scarcity_autofilled: {','.join(scarcity_meta.get('autofilled_keys') or [])}"
                        )
                    if scarcity_meta.get("auto_injected_indicator_keys"):
                        self.stdout.write(
                            "scarcity_auto_injected: "
                            f"{','.join(scarcity_meta.get('auto_injected_indicator_keys') or [])}"
                        )
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
                valuation_params, _scarcity_meta = self._apply_scarcity_profile(
                    valuation_params,
                    scarcity_profile,
                    market=market,
                    tscode=tscode,
                    trade_date=trade_date,
                )
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
        valuation_params, scarcity_meta = self._apply_scarcity_profile(
            valuation_params,
            scarcity_profile,
            market=market,
            tscode=tscode,
            trade_date=trade_date,
        )
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
            if scarcity_meta.get("requested_profile"):
                self.stdout.write(f"scarcity_profile: {scarcity_meta.get('requested_profile')}")
                self.stdout.write(f"scarcity_profile_effective: {scarcity_meta.get('effective_profile')}")
                if scarcity_meta.get("auto_reason"):
                    self.stdout.write(f"scarcity_profile_auto_reason: {scarcity_meta.get('auto_reason')}")
            if scarcity_meta.get("autofilled_keys"):
                self.stdout.write(
                    f"scarcity_autofilled: {','.join(scarcity_meta.get('autofilled_keys') or [])}"
                )
            if scarcity_meta.get("auto_injected_indicator_keys"):
                self.stdout.write(
                    "scarcity_auto_injected: "
                    f"{','.join(scarcity_meta.get('auto_injected_indicator_keys') or [])}"
                )
            if scarcity_profile or scarcity_meta.get("autofilled_keys"):
                self.stdout.write(f"scarcity_kwargs: {valuation_params.get('scarcity_kwargs')}")
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