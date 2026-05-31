import json
from pathlib import Path

from django.conf import settings


class BusinessFallbackEngine:
    @staticmethod
    def load_business_fallback_settings(market="CN", citic_profile=None):
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
            "citic_alignment_score_min": float(
                settings_data.get("citic_alignment_score_min", defaults["citic_alignment_score_min"])
            ),
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
    def choose_citic_fallback_match(matches, citic_mappings):
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
    def should_fallback_business_match(matches, citic_mappings, fallback_settings=None):
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
            (mapping.get("target_level"), mapping.get("target_code")) for mapping in citic_mappings or []
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

    @classmethod
    def build_business_fallback_config(
        cls,
        tscode,
        matches,
        citic_mappings,
        market,
        fuzzy,
        load_forced_sw_valuation_params,
        load_sw_valuation_params,
        resolve_industry_by_tscode,
        load_valuation_params,
    ):
        fallback_match = cls.choose_citic_fallback_match(matches, citic_mappings)
        if fallback_match is not None:
            config_info = load_forced_sw_valuation_params(
                industry=fallback_match["industry_code"],
                market=market,
                level=fallback_match["level"],
                fuzzy=False,
            )
            config_info["source"] = f"{config_info.get('source')}_business_fallback"
            config_info["fallback_match"] = fallback_match
            return config_info

        try:
            config_info = load_sw_valuation_params(tscode=tscode, market=market)
            config_info["source"] = f"{config_info.get('source')}_business_fallback"
            return config_info
        except (ValueError, FileNotFoundError, KeyError):
            _corporation, industry = resolve_industry_by_tscode(tscode)
            return load_valuation_params(industry=industry, market=market, fuzzy=fuzzy)
