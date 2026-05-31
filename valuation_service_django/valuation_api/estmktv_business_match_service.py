from pathlib import Path

from django.conf import settings

from valuation_api.business_industry_matcher import BusinessIndustryMatcher
from valuation_api.valuation_config import StandaloneValuationConfig


def handle_business_match_mode(command, ts_code, trade_date, freq, scenario_model, options):
    """Execute estmktv business-match mode using command-provided helpers.

    This keeps CLI behavior intact while moving branch-heavy orchestration
    out of the management command class.
    """
    runtime_options = command._resolve_runtime_options(options)
    market = runtime_options["market"]
    top_n = int(options.get("business_topn") or 3)
    level = str(options.get("business_match_level") or "L2").strip().upper()
    show_source = runtime_options["show_source"]
    show_citic_levels = runtime_options["show_citic_levels"]
    show_match_keywords = runtime_options["show_match_keywords"]
    show_profit_source = runtime_options["show_profit_source"]
    disable_business_fallback = bool(options.get("disable_business_fallback"))
    strict_express_match = runtime_options["strict_express_match"]
    express_max_age_days = runtime_options["express_max_age_days"]
    scarcity_profile = runtime_options["scarcity_profile"]

    matcher = BusinessIndustryMatcher(base_dir=Path(settings.BASE_DIR), market=market)
    matched_payload = matcher.match_by_tscode(ts_code=ts_code, top_n=top_n, level=level)
    matches = matched_payload.get("matches") or []
    citic_profile = matched_payload.get("citic_profile") or {}
    citic_mappings = matched_payload.get("citic_mappings") or []
    citic_mapping_summary = matcher.format_citic_mapping_summary(citic_mappings)

    fallback_settings = matcher.get_fallback_settings_for_profile(citic_profile)
    should_fallback, fallback_reason = matcher.should_fallback(matches, citic_mappings, fallback_settings)

    baseline_frames = []
    try:
        baseline_runtime_kwargs = command._resolve_params(ts_code=ts_code, market=market, fuzzy=True)
        baseline_source = baseline_runtime_kwargs.get("source_info") or {}
        baseline_result = command._run_single_valuation(
            ts_code,
            trade_date,
            freq,
            scenario_model,
            baseline_runtime_kwargs,
            persist_context={
                "compare_group": "sw_l3_baseline",
                "industry_level": baseline_source.get("level"),
                "industry_code": baseline_source.get("industry_code"),
                "industry_name": baseline_source.get("industry_name"),
                "valuation_variant": command._build_valuation_variant(
                    "sw_l3_baseline",
                    baseline_source.get("level"),
                    baseline_source.get("industry_code"),
                    baseline_source.get("industry_name"),
                ),
            },
            strict_express_match=strict_express_match,
            express_max_age_days=express_max_age_days,
            scarcity_profile=scarcity_profile,
            market=market,
        )
        baseline_frames.append(
            command._build_comparison_frame(
                result=baseline_result,
                compare_group="sw_l3_baseline",
                industry_level=baseline_source.get("level"),
                industry_code=baseline_source.get("industry_code"),
                industry_name=baseline_source.get("industry_name"),
                source=baseline_source.get("source") if show_source else None,
                citic_profile=citic_profile if show_citic_levels else None,
                citic_mapping_summary=citic_mapping_summary if show_citic_levels else None,
                include_source=show_source,
                include_citic=show_citic_levels,
            )
        )
        baseline_frames = [frame for frame in baseline_frames if frame is not None]
    except ValueError:
        baseline_frames = []

    if show_source:
        command.stdout.write(f"business_text_source: {(matched_payload.get('profile') or {}).get('source')}")
        command.stdout.write(
            f"business_match_fallback_profile: {fallback_settings.get('profile_name', 'default')}"
        )
        command.stdout.write(f"business_match_fallback: {fallback_reason}")

    if show_citic_levels:
        command.stdout.write(f"citic_l1: {citic_profile.get('l1_name')}")
        command.stdout.write(f"citic_l2: {citic_profile.get('l2_name')}")
        command.stdout.write(f"citic_l3: {citic_profile.get('l3_name')}")
        command.stdout.write(f"citic_sw_targets: {citic_mapping_summary}")

    output_frames = list(baseline_frames)
    cfg = StandaloneValuationConfig(base_dir=Path(settings.BASE_DIR), market=market)

    if (not matches or should_fallback) and not disable_business_fallback:
        fallback_match = matcher.choose_citic_fallback_match(matches, citic_mappings)
        if fallback_match is not None:
            sw_payload = cfg.get_sw_params_by_industry(
                industry=fallback_match.get("industry_code") or fallback_match.get("industry_name"),
                level=fallback_match.get("level"),
                fuzzy=False,
            )
            runtime_kwargs = command._extract_runtime_kwargs(sw_payload)
            runtime_kwargs["source_info"]["source"] = f"{runtime_kwargs['source_info'].get('source')}_business_fallback"
        else:
            runtime_kwargs = command._resolve_params(ts_code=ts_code, market=market, fuzzy=True)
            runtime_kwargs["source_info"]["source"] = f"{runtime_kwargs['source_info'].get('source')}_business_fallback"

        fallback_source = runtime_kwargs.get("source_info") or {}

        result = command._run_single_valuation(
            ts_code,
            trade_date,
            freq,
            scenario_model,
            runtime_kwargs,
            persist_context={
                "compare_group": "business_fallback",
                "industry_level": fallback_source.get("level"),
                "industry_code": fallback_source.get("industry_code"),
                "industry_name": fallback_source.get("industry_name"),
                "valuation_variant": command._build_valuation_variant(
                    "business_fallback",
                    fallback_source.get("level"),
                    fallback_source.get("industry_code"),
                    fallback_source.get("industry_name"),
                ),
            },
            strict_express_match=strict_express_match,
            express_max_age_days=express_max_age_days,
            scarcity_profile=scarcity_profile,
            market=market,
        )
        if show_profit_source:
            command._emit_profit_source(result.get("snapshot") or {})
        output_frames.append(
            command._build_comparison_frame(
                result=result,
                compare_group="business_fallback",
                industry_level=fallback_source.get("level"),
                industry_code=fallback_source.get("industry_code"),
                industry_name=fallback_source.get("industry_name"),
                source=fallback_source.get("source") if show_source else None,
                citic_profile=citic_profile if show_citic_levels else None,
                citic_mapping_summary=citic_mapping_summary if show_citic_levels else None,
                include_source=show_source,
                include_citic=show_citic_levels,
            )
        )
    else:
        for match in matches:
            sw_payload = cfg.get_sw_params_by_industry(
                industry=match.get("industry_code") or match.get("industry_name"),
                level=match.get("level"),
                fuzzy=False,
            )
            runtime_kwargs = command._extract_runtime_kwargs(sw_payload)
            result = command._run_single_valuation(
                ts_code,
                trade_date,
                freq,
                scenario_model,
                runtime_kwargs,
                persist_context={
                    "compare_group": "business_match",
                    "match_score": match.get("score"),
                    "industry_level": match.get("level"),
                    "industry_code": match.get("industry_code"),
                    "industry_name": match.get("industry_name"),
                    "valuation_variant": command._build_valuation_variant(
                        "business_match",
                        match.get("level"),
                        match.get("industry_code"),
                        match.get("industry_name"),
                    ),
                },
                strict_express_match=strict_express_match,
                express_max_age_days=express_max_age_days,
                scarcity_profile=scarcity_profile,
                market=market,
            )
            if show_profit_source:
                command._emit_profit_source(result.get("snapshot") or {})
            source_info = runtime_kwargs.get("source_info") or {}
            output_frames.append(
                command._build_comparison_frame(
                    result=result,
                    compare_group="business_match",
                    industry_level=match.get("level"),
                    industry_code=match.get("industry_code"),
                    industry_name=match.get("industry_name"),
                    match_score=match.get("score"),
                    source=source_info.get("source") if show_source else None,
                    matched_keywords=",".join(match.get("matched_keywords") or []) if show_match_keywords else None,
                    citic_profile=citic_profile if show_citic_levels else None,
                    citic_mapping_summary=citic_mapping_summary if show_citic_levels else None,
                    include_source=show_source,
                    include_keywords=show_match_keywords,
                    include_citic=show_citic_levels,
                )
            )

    output_frames = [frame for frame in output_frames if frame is not None and not frame.empty]
    command.stdout.write(command._build_multi_output(output_frames))
