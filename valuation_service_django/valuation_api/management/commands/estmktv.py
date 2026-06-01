import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
import pandas as pd

from valuation_api.business_industry_matcher import BusinessIndustryMatcher
from valuation_api.estmktv_business_match_service import handle_business_match_mode
from valuation_api.live_valuation import test_valuation_local
from valuation_api.models import CompanyProfile
from valuation_api.scarcity_auto_engine import ScarcityAutoEngine
from valuation_api.valuation_config import StandaloneValuationConfig


class Command(BaseCommand):
    help = "Run standalone valuation for a stock and print summary/output."

    @staticmethod
    def _resolve_runtime_options(options):
        return {
            "market": str(options.get("market") or "CN").strip().upper() or "CN",
            "show_source": bool(options.get("show_source")),
            "show_sw_levels": bool(options.get("show_sw_levels")),
            "show_citic_levels": bool(options.get("show_citic_levels")),
            "show_match_keywords": bool(options.get("show_match_keywords")),
            "show_profit_source": bool(options.get("show_profit_source")),
            "strict_express_match": not bool(options.get("no_strict_express_match")),
            "express_max_age_days": int(options.get("express_max_age_days") or 180),
            "scarcity_profile": options.get("scarcity_profile"),
        }

    @staticmethod
    def _resolve_requested_scenario_model(options, default_scenario_model):
        if options.get("est_method"):
            return str(options.get("est_method")).strip().lower()
        if options.get("scenario_model"):
            return str(options.get("scenario_model")).strip().lower()
        return default_scenario_model

    @staticmethod
    def _apply_scarcity_profile(runtime_kwargs, scarcity_profile, market, ts_code, trade_date):
        return ScarcityAutoEngine._apply_scarcity_profile(
            valuation_params=runtime_kwargs,
            scarcity_profile=scarcity_profile,
            market=market,
            tscode=ts_code,
            trade_date=trade_date,
        )

    def add_arguments(self, parser):
        parser.add_argument("--tscode", required=True, help="Stock code, e.g. 600036.SH")
        parser.add_argument("--trade-date", default=None, help="Trade date YYYY-MM-DD")
        parser.add_argument("--trade_date", default=None, help="Trade date (legacy format key)")
        parser.add_argument("--ann_date", default=None, help="Announcement date (reserved)")
        parser.add_argument("--freq", default="D", help="Frequency: D/W/M")
        parser.add_argument("--scenario-model", default="fcff_dcf", help="Scenario model: fcff_dcf/ddm/pe/ps/pb")
        parser.add_argument("--est_method", default=None, help="Override scenario_model")
        parser.add_argument("--industry", default=None, help="Legacy narrow industry name")
        parser.add_argument("--force-sw-industry", default=None, help="Force valuation with SW industry name or index code")
        parser.add_argument("--force-sw-level", choices=["L1", "L2", "L3"], default=None, help="Optional SW level when force-sw-industry is provided")
        parser.add_argument("--market", default="CN", help="Market code")
        parser.add_argument("--no-fuzzy", action="store_true", default=False, help="Disable fuzzy industry mapping")
        parser.add_argument("--show-source", action="store_true", default=False, help="Print parameter source information")
        parser.add_argument("--show-sw-levels", action="store_true", default=False, help="Print SW hierarchy if available")
        parser.add_argument("--show-profit-source", action="store_true", default=False, help="Print snapshot-level source diagnostics")
        parser.add_argument(
            "--scarcity-profile",
            choices=["conservative", "balanced", "aggressive", "off", "auto"],
            default=None,
            help="Override scarcity kwargs profile for this run",
        )

        parser.add_argument("--match-business-industries", action="store_true", default=False)
        parser.add_argument("--business-match-level", choices=["ALL", "L1", "L2", "L3"], default="L2")
        parser.add_argument("--business-topn", type=int, default=3)
        parser.add_argument("--disable-business-fallback", action="store_true", default=False)
        parser.add_argument("--show-citic-levels", action="store_true", default=False)
        parser.add_argument("--show-match-keywords", action="store_true", default=False)
        parser.add_argument("--no-strict-express-match", action="store_true", default=False)
        parser.add_argument("--express-max-age-days", type=int, default=180)
        parser.add_argument("--resume", default=None)

        parser.add_argument("--json", action="store_true", help="Print full result as JSON")

    @staticmethod
    def _normalize_trade_date(trade_date):
        if not trade_date:
            return None
        text = str(trade_date).strip()
        if len(text) == 8 and text.isdigit():
            return f"{text[0:4]}-{text[4:6]}-{text[6:8]}"
        return text

    @staticmethod
    def _extract_runtime_kwargs(params_payload):
        params = (params_payload or {}).get("params") or {}
        scarcity_kwargs = params.get("scarcity_kwargs") if isinstance(params.get("scarcity_kwargs"), dict) else {}
        if params.get("scarcity_enabled") is not None:
            scarcity_kwargs["enabled"] = bool(params.get("scarcity_enabled"))
        if params.get("scarcity_beta") is not None:
            scarcity_kwargs["beta"] = params.get("scarcity_beta")
        if params.get("scarcity_cap_pct") is not None:
            scarcity_kwargs["cap_pct"] = params.get("scarcity_cap_pct")
        if params.get("scarcity_score") is not None:
            scarcity_kwargs["score"] = params.get("scarcity_score")
        if params.get("scarcity_confidence") is not None:
            scarcity_kwargs["confidence"] = params.get("scarcity_confidence")

        return {
            "pe_target": params.get("pe_target"),
            "ps_target": params.get("ps_target"),
            "pb_target": params.get("pb_target"),
            "peg_target": params.get("peg_target"),
            "ev_ebitda_target": params.get("ev_ebitda_target"),
            "dcf_kwargs": params.get("dcf_kwargs") or {},
            "ddm_kwargs": params.get("ddm_kwargs") or {},
            "scarcity_kwargs": scarcity_kwargs or None,
            "scenario_model": params.get("scenario_model") or "fcff_dcf",
            "sensitivity_grid": params.get("sensitivity_grid"),
            "source_info": params_payload or {},
        }

    @staticmethod
    def _resolve_profile_industry(ts_code):
        profile = (
            CompanyProfile.objects.filter(ts_code=ts_code)
            .only("ts_code", "industry")
            .first()
        )
        industry = (profile.industry or "").strip() if profile else ""
        return industry or None

    def _resolve_params(self, ts_code, market="CN", industry=None, force_sw_industry=None, force_sw_level=None, fuzzy=True):
        cfg = StandaloneValuationConfig(base_dir=Path(settings.BASE_DIR), market=market)

        if force_sw_industry:
            payload = cfg.get_sw_params_by_industry(
                industry=force_sw_industry,
                level=force_sw_level,
                fuzzy=fuzzy,
            )
            return self._extract_runtime_kwargs(payload)

        if industry:
            payload = cfg.get_legacy_params_by_industry(industry=industry, fuzzy=fuzzy)
            return self._extract_runtime_kwargs(payload)

        try:
            payload = cfg.get_sw_params_by_tscode(ts_code)
            return self._extract_runtime_kwargs(payload)
        except (ValueError, KeyError, TypeError):
            pass

        profile_industry = self._resolve_profile_industry(ts_code)
        if profile_industry:
            try:
                payload = cfg.get_legacy_params_by_industry(industry=profile_industry, fuzzy=fuzzy)
                runtime = self._extract_runtime_kwargs(payload)
                runtime["source_info"]["input_industry"] = profile_industry
                return runtime
            except (ValueError, KeyError, TypeError):
                pass

        payload = cfg.get_global_params()
        return self._extract_runtime_kwargs(payload)

    @staticmethod
    def _format_valuation_rows(result):
        valuations_df = result.get("valuations")
        if valuations_df is None or valuations_df.empty:
            return ["valuations: []"]
        lines = []
        for _, row in valuations_df.iterrows():
            lines.append(
                "- {method}: implied_price={price:.4f}, equity_value={equity}".format(
                    method=row.get("method"),
                    price=float(row.get("implied_price") or 0.0),
                    equity=round(float(row.get("equity_value")), 2)
                    if row.get("equity_value") is not None
                    else None,
                )
            )
        return lines

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
        output_df["evaluated_market_value"] = output_df["evaluated_market_value"] / 100000000
        for column in ["evaluated_market_value", "according_price"]:
            output_df[column] = output_df[column].round(4)
        output_df = output_df.where(output_df.notna(), None)
        return output_df

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
    def _build_valuation_variant(cls, compare_group, industry_level=None, industry_code=None, industry_name=None):
        group = str(compare_group or "").strip()
        if not group:
            return "default"
        level = str(industry_level or "").strip()
        code = str(industry_code or "").strip()
        name = str(industry_name or "").strip()
        if any([level, code, name]):
            return "|".join([group, level, code, name])
        return group

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

    def _run_single_valuation(
        self,
        ts_code,
        trade_date,
        freq,
        scenario_model,
        runtime_kwargs,
        persist_context=None,
        strict_express_match=True,
        express_max_age_days=180,
        scarcity_profile=None,
        market="CN",
    ):
        runtime_kwargs = dict(runtime_kwargs or {})
        runtime_kwargs, scarcity_meta = self._apply_scarcity_profile(
            runtime_kwargs=runtime_kwargs,
            scarcity_profile=scarcity_profile,
            market=market,
            ts_code=ts_code,
            trade_date=trade_date,
        )
        result = test_valuation_local(
            ts_code=ts_code,
            trade_date=trade_date,
            freq=freq,
            scenario_model=scenario_model,
            pe_target=runtime_kwargs.get("pe_target"),
            ps_target=runtime_kwargs.get("ps_target"),
            pb_target=runtime_kwargs.get("pb_target"),
            peg_target=runtime_kwargs.get("peg_target"),
            ev_ebitda_target=runtime_kwargs.get("ev_ebitda_target"),
            dcf_kwargs=runtime_kwargs.get("dcf_kwargs") or {},
            ddm_kwargs=runtime_kwargs.get("ddm_kwargs") or {},
            scarcity_kwargs=runtime_kwargs.get("scarcity_kwargs") or {},
            sensitivity_grid=runtime_kwargs.get("sensitivity_grid"),
            persist_context=persist_context,
            strict_express_match=strict_express_match,
            express_max_age_days=express_max_age_days,
        )
        result["_scarcity_meta"] = scarcity_meta
        result["_resolved_runtime_kwargs"] = runtime_kwargs
        return result

    def _emit_profit_source(self, snapshot):
        self.stdout.write(f"profit_data_source: {snapshot.get('profit_data_source')}")
        self.stdout.write(f"financial_data_source: {snapshot.get('financial_data_source')}")
        self.stdout.write(f"financial_data_reason: {snapshot.get('financial_data_reason')}")
        self.stdout.write(f"strict_express_match: {snapshot.get('strict_express_match')}")
        self.stdout.write(f"express_max_age_days: {snapshot.get('express_max_age_days')}")
        self.stdout.write(f"express_apply_reason: {snapshot.get('express_apply_reason')}")
        self.stdout.write(f"express_block_reason: {snapshot.get('express_block_reason')}")
        self.stdout.write(f"ev_ebitda_applicable: {snapshot.get('ev_ebitda_applicable')}")
        self.stdout.write(f"ev_ebitda_block_reason: {snapshot.get('ev_ebitda_block_reason')}")
        self.stdout.write(f"requested_scenario_model: {snapshot.get('requested_scenario_model')}")
        self.stdout.write(f"effective_scenario_model: {snapshot.get('effective_scenario_model')}")
        self.stdout.write(f"scenario_model_switch_reason: {snapshot.get('scenario_model_switch_reason')}")
        self.stdout.write(f"report_date: {snapshot.get('report_date')}")
        self.stdout.write(f"trade_date: {snapshot.get('trade_date')}")
        self.stdout.write(
            "peg_growth_yoy_pct(base->effective): "
            f"{snapshot.get('base_peg_growth_yoy_pct')} -> {snapshot.get('peg_growth_yoy_pct')}"
        )
        self.stdout.write(
            "netprofit(base->effective): "
            f"{snapshot.get('base_netprofit')} -> {snapshot.get('netprofit')}"
        )
        self.stdout.write(
            "revenue(base->effective): "
            f"{snapshot.get('base_revenue')} -> {snapshot.get('revenue')}"
        )

    def _handle_business_match_mode(self, ts_code, trade_date, freq, scenario_model, options):
        return handle_business_match_mode(
            command=self,
            ts_code=ts_code,
            trade_date=trade_date,
            freq=freq,
            scenario_model=scenario_model,
            options=options,
        )

    def handle(self, *args, **options):
        ts_code = str(options["tscode"]).strip().upper()
        trade_date = self._normalize_trade_date(options.get("trade_date") or options.get("trade_date"))
        freq = str(options.get("freq") or "D").strip().upper() or "D"
        scenario_model = str(options.get("scenario_model") or "fcff_dcf").strip().lower()
        print_json = bool(options.get("json"))

        if options.get("match_business_industries"):
            self._handle_business_match_mode(
                ts_code=ts_code,
                trade_date=trade_date,
                freq=freq,
                scenario_model=scenario_model,
                options=options,
            )
            return

        runtime_options = self._resolve_runtime_options(options)
        market = runtime_options["market"]
        industry = options.get("industry")
        force_sw_industry = options.get("force_sw_industry")
        force_sw_level = options.get("force_sw_level")
        fuzzy = not bool(options.get("no_fuzzy"))
        show_source = runtime_options["show_source"]
        show_sw_levels = runtime_options["show_sw_levels"]
        show_citic_levels = runtime_options["show_citic_levels"]
        show_profit_source = runtime_options["show_profit_source"]
        strict_express_match = runtime_options["strict_express_match"]
        express_max_age_days = runtime_options["express_max_age_days"]
        scarcity_profile = runtime_options["scarcity_profile"]

        try:
            runtime_kwargs = self._resolve_params(
                ts_code=ts_code,
                market=market,
                industry=industry,
                force_sw_industry=force_sw_industry,
                force_sw_level=force_sw_level,
                fuzzy=fuzzy,
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        runtime_kwargs["scenario_model"] = self._resolve_requested_scenario_model(
            options=options,
            default_scenario_model=runtime_kwargs.get("scenario_model") or scenario_model,
        )
        scenario_model = runtime_kwargs.get("scenario_model") or scenario_model

        try:
            result = self._run_single_valuation(
                ts_code,
                trade_date,
                freq,
                scenario_model,
                runtime_kwargs,
                strict_express_match=strict_express_match,
                express_max_age_days=express_max_age_days,
                scarcity_profile=scarcity_profile,
                market=market,
            )
        except ValueError as exc:
            raise CommandError(str(exc)) from exc

        snapshot = result.get("snapshot") or {}
        formatted_range = result.get("formatted_range") or {}
        valuations_df = result.get("valuations")

        if print_json:
            payload = {
                "ts_code": ts_code,
                "snapshot": snapshot,
                "formatted_range": formatted_range,
                "valuations": [] if valuations_df is None else valuations_df.to_dict(orient="records"),
                "weighted_valuation": result.get("weighted_valuation") or {},
                "scenario_analysis": []
                if result.get("scenario_analysis") is None
                else result.get("scenario_analysis").to_dict(orient="records"),
                "sensitivity_analysis": []
                if result.get("sensitivity_analysis") is None
                else result.get("sensitivity_analysis").to_dict(orient="records"),
            }
            self.stdout.write(json.dumps(payload, ensure_ascii=False, default=str, indent=2))
            return

        self.stdout.write(f"ts_code: {ts_code}")
        self.stdout.write(f"trade_date: {snapshot.get('trade_date')}")
        self.stdout.write(f"close_price: {snapshot.get('close_price')}")
        self.stdout.write(f"assumption_source: {snapshot.get('assumption_source')}")
        self.stdout.write(
            f"price_range: {(formatted_range.get('price_range') or {}).get('range_display')}"
        )

        if show_source:
            source_info = runtime_kwargs.get("source_info") or {}
            self.stdout.write(f"source: {source_info.get('source')}")
            if source_info.get("level"):
                self.stdout.write(f"source_level: {source_info.get('level')}")
            if source_info.get("industry_code"):
                self.stdout.write(f"source_industry_code: {source_info.get('industry_code')}")
            if source_info.get("industry_name"):
                self.stdout.write(f"source_industry_name: {source_info.get('industry_name')}")
            scarcity_meta = result.get("_scarcity_meta") or {}
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
                resolved_runtime_kwargs = result.get("_resolved_runtime_kwargs") or runtime_kwargs
                self.stdout.write(
                    f"scarcity_kwargs: {(resolved_runtime_kwargs or {}).get('scarcity_kwargs')}"
                )

        if show_sw_levels:
            hierarchy = (runtime_kwargs.get("source_info") or {}).get("hierarchy") or {}
            if force_sw_industry:
                source_info = runtime_kwargs.get("source_info") or {}
                self.stdout.write(
                    "forced_sw: "
                    f"{source_info.get('matched_level') or source_info.get('level')} "
                    f"{source_info.get('matched_industry_code') or source_info.get('industry_code')} "
                    f"{source_info.get('matched_industry_name') or source_info.get('industry_name')}"
                )
            self.stdout.write(f"sw_l1: {hierarchy.get('l1_code')} {hierarchy.get('l1_name')}")
            self.stdout.write(f"sw_l2: {hierarchy.get('l2_code')} {hierarchy.get('l2_name')}")
            self.stdout.write(f"sw_l3: {hierarchy.get('l3_code')} {hierarchy.get('l3_name')}")

        if show_citic_levels:
            matcher = BusinessIndustryMatcher(base_dir=Path(settings.BASE_DIR), market=market)
            payload = matcher.match_by_tscode(ts_code=ts_code, top_n=1, level="L2")
            citic_profile = payload.get("citic_profile") or {}
            citic_mappings = payload.get("citic_mappings") or []
            self.stdout.write(f"citic_l1: {citic_profile.get('l1_name')}")
            self.stdout.write(f"citic_l2: {citic_profile.get('l2_name')}")
            self.stdout.write(f"citic_l3: {citic_profile.get('l3_name')}")
            self.stdout.write(
                f"citic_sw_targets: {matcher.format_citic_mapping_summary(citic_mappings)}"
            )

        if show_profit_source:
            self._emit_profit_source(snapshot)

        for line in self._format_valuation_rows(result):
            self.stdout.write(line)
