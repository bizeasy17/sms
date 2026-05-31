import difflib
from functools import lru_cache
import json
import os
import re
from collections import defaultdict
from pathlib import Path

from django.conf import settings

from .models import CompanyProfile
from .valuation_config import StandaloneValuationConfig


@lru_cache(maxsize=1)
def _get_tushare_pro_client():
    try:
        import tushare as ts
    except ImportError:
        return None

    token = (
        os.getenv("TUSHARE_TOKEN")
        or os.getenv("TUSHARE_PRO_TOKEN")
        or str(getattr(settings, "TUSHARE_TOKEN", "") or "").strip()
    )
    if token:
        ts.set_token(token)

    try:
        return ts.pro_api()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return None


class BusinessIndustryMatcher:
    DEFAULT_FIELD_WEIGHTS = {
        "main_business": 3.0,
        "business_scope": 2.0,
        "introduction": 1.0,
    }
    DEFAULT_INDUSTRY_NAME_LEVEL_WEIGHTS = {
        "L1": 0.9,
        "L2": 1.15,
        "L3": 1.3,
    }

    def __init__(self, base_dir: Path, market: str = "CN"):
        self.base_dir = base_dir
        self.market = market
        self.cfg = StandaloneValuationConfig(base_dir=base_dir, market=market)
        self.rule_config = self._load_rule_config()
        self.field_weights = self.rule_config.get("field_weights", self.DEFAULT_FIELD_WEIGHTS)
        self.industry_name_level_weights = self.rule_config.get(
            "industry_name_level_weights", self.DEFAULT_INDUSTRY_NAME_LEVEL_WEIGHTS
        )
        self.citic_prior_weights = self.rule_config.get(
            "citic_prior_weights", {"L1": 1.5, "L2": 3.2, "L3": 4.2}
        )
        self.citic_name_match_cutoff = float(self.rule_config.get("citic_name_match_cutoff", 0.55))
        self.citic_name_targets = self.rule_config.get("citic_name_targets", {})
        self.generic_term_score_multipliers = self.rule_config.get(
            "generic_term_score_multipliers", {}
        )
        self.citic_non_target_score_multiplier = float(
            self.rule_config.get("citic_non_target_score_multiplier", 0.8)
        )
        self.keyword_rules = self._normalize_keyword_rules(self.rule_config.get("keyword_rules", []))

    def _load_rule_config(self):
        config_path = self.base_dir / "static" / "valuation_config" / f"business_keyword_rules_{self.market}.json"
        if not config_path.exists():
            return {}
        with config_path.open("r", encoding="utf-8") as file_obj:
            return json.load(file_obj)

    def get_fallback_settings(self):
        return self.get_fallback_settings_for_profile(citic_profile=None)

    def get_fallback_settings_for_profile(self, citic_profile=None):
        fallback = self.rule_config.get("business_match_fallback", {})
        resolved = {
            "top_score_min": float(fallback.get("top_score_min", 6.0)),
            "top_two_gap_min": float(fallback.get("top_two_gap_min", 0.8)),
            "gap_check_score_cap": float(fallback.get("gap_check_score_cap", 12.0)),
            "citic_alignment_score_min": float(fallback.get("citic_alignment_score_min", 12.0)),
            "profile_name": "default",
        }

        def _apply_override(level_key, citic_name):
            if not citic_name:
                return
            overrides = fallback.get(level_key, {})
            if citic_name not in overrides:
                return
            override = overrides.get(citic_name) or {}
            resolved.update(
                {
                    "top_score_min": float(override.get("top_score_min", resolved["top_score_min"])),
                    "top_two_gap_min": float(override.get("top_two_gap_min", resolved["top_two_gap_min"])),
                    "gap_check_score_cap": float(override.get("gap_check_score_cap", resolved["gap_check_score_cap"])),
                    "citic_alignment_score_min": float(
                        override.get("citic_alignment_score_min", resolved["citic_alignment_score_min"])
                    ),
                }
            )

        citic_profile = citic_profile or {}
        l1_name = citic_profile.get("l1_name")
        l2_name = citic_profile.get("l2_name")
        l3_name = citic_profile.get("l3_name")

        _apply_override("citic_l1_overrides", l1_name)
        if l1_name and l1_name in (fallback.get("citic_l1_overrides", {}) or {}):
            resolved["profile_name"] = f"citic_l1:{l1_name}"

        _apply_override("citic_l2_overrides", l2_name)
        if l2_name and l2_name in (fallback.get("citic_l2_overrides", {}) or {}):
            resolved["profile_name"] = f"citic_l2:{l2_name}"

        _apply_override("citic_l3_overrides", l3_name)
        if l3_name and l3_name in (fallback.get("citic_l3_overrides", {}) or {}):
            resolved["profile_name"] = f"citic_l3:{l3_name}"

        return resolved

    def should_fallback(self, matches, citic_mappings, fallback_settings=None):
        if not matches:
            return True, "no_business_matches"

        settings = fallback_settings or self.get_fallback_settings()
        top_score = float(matches[0].get("score") or 0.0)
        second_score = float(matches[1].get("score") or 0.0) if len(matches) > 1 else None
        top_key = (matches[0].get("level"), matches[0].get("industry_code"))
        citic_targets = {
            (mapping.get("target_level"), mapping.get("target_code"))
            for mapping in citic_mappings or []
        }

        if top_score < settings["top_score_min"]:
            return True, "top_score_below_threshold"
        if (
            second_score is not None
            and (top_score - second_score) < settings["top_two_gap_min"]
            and top_score < settings["gap_check_score_cap"]
        ):
            return True, "top_two_too_close"
        if (
            citic_targets
            and top_key not in citic_targets
            and top_score < settings["citic_alignment_score_min"]
        ):
            return True, "top_match_outside_citic_targets"
        return False, None

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
    def format_citic_mapping_summary(citic_mappings):
        if not citic_mappings:
            return None
        targets = []
        for mapping in citic_mappings:
            label = f"{mapping.get('target_level')}:{mapping.get('target_name')}"
            if label not in targets:
                targets.append(label)
        return "|".join(targets)

    def _normalize_keyword_rules(self, rules):
        normalized = []
        for rule in rules:
            keyword = rule.get("keyword")
            targets = rule.get("targets") or []
            if not keyword or not targets:
                continue
            normalized.append(
                {
                    "keyword": keyword,
                    "normalized_keyword": self._normalize_text(keyword),
                    "weight": float(rule.get("weight", 1.0)),
                    "targets": targets,
                }
            )
        return normalized

    def get_business_profile(self, ts_code: str):
        profile_row = CompanyProfile.objects.filter(ts_code=ts_code).first()
        if profile_row is None:
            return {
                "ts_code": ts_code,
                "main_business": None,
                "business_scope": None,
                "introduction": None,
                "source": "none",
            }

        return {
            "ts_code": ts_code,
            "main_business": profile_row.main_business,
            "business_scope": profile_row.business_scope,
            "introduction": profile_row.introduction,
            "source": "db_company_profile",
        }

    def get_citic_profile(self, ts_code: str):
        profile_row = CompanyProfile.objects.filter(ts_code=ts_code).first()
        l1 = profile_row.citic_l1_name or None if profile_row else None
        l2 = profile_row.citic_l2_name or None if profile_row else None
        l3 = profile_row.citic_l3_name or None if profile_row else None
        if l1 or l2 or l3:
            return {
                "ts_code": ts_code,
                "l1_code": None,
                "l1_name": l1,
                "l2_code": None,
                "l2_name": l2,
                "l3_code": None,
                "l3_name": l3,
                "source": "db_company_profile",
                "available": True,
                "error": None,
            }

        profile = {
            "ts_code": ts_code,
            "l1_code": None,
            "l1_name": None,
            "l2_code": None,
            "l2_name": None,
            "l3_code": None,
            "l3_name": None,
            "source": "none",
            "available": False,
            "error": None,
        }

        pro = _get_tushare_pro_client()
        if pro is None:
            return profile

        try:
            df = pro.ci_index_member(ts_code=ts_code, is_new="Y")
        except Exception as exc:  # pylint: disable=broad-exception-caught
            profile["source"] = "tushare_ci_index_member"
            profile["error"] = str(exc)
            return profile

        if df is None or df.empty:
            profile["source"] = "tushare_ci_index_member"
            return profile

        row = df.iloc[0].to_dict()
        profile.update(
            {
                "l1_code": row.get("l1_code"),
                "l1_name": row.get("l1_name"),
                "l2_code": row.get("l2_code"),
                "l2_name": row.get("l2_name"),
                "l3_code": row.get("l3_code"),
                "l3_name": row.get("l3_name"),
                "source": "tushare_ci_index_member",
                "available": True,
            }
        )
        return profile

    def match_by_tscode(self, ts_code: str, top_n: int = 3, level: str = "L2"):
        profile = self.get_business_profile(ts_code)
        citic_profile = self.get_citic_profile(ts_code)
        search_levels = ["L1", "L2", "L3"] if level == "ALL" else [level]
        citic_mappings = self._collect_citic_mappings(citic_profile, search_levels)
        matches = self.match_from_profile(
            profile=profile,
            top_n=top_n,
            level=level,
            citic_profile=citic_profile,
            citic_mappings=citic_mappings,
        )
        return {
            "profile": profile,
            "citic_profile": citic_profile,
            "citic_mappings": citic_mappings,
            "matches": matches,
        }

    def match_from_profile(self, profile, top_n=3, level="L2", citic_profile=None, citic_mappings=None):
        search_levels = ["L1", "L2", "L3"] if level == "ALL" else [level]
        scores = defaultdict(float)
        keyword_counts = defaultdict(lambda: defaultdict(int))
        level_entries = self.cfg.sw_mapping.get("levels", {})

        for field_name, field_weight in self.field_weights.items():
            field_text = profile.get(field_name) or ""
            normalized_text = self._normalize_text(field_text)
            if not normalized_text:
                continue

            for level_name in search_levels:
                for index_code, entry in (level_entries.get(level_name) or {}).items():
                    industry_name = entry.get("industry_name")
                    variants = self._build_name_variants(industry_name)
                    for variant in variants:
                        if len(variant) < 2:
                            continue
                        occurrence_count = self._count_occurrences(normalized_text, variant)
                        if occurrence_count <= 0:
                            continue
                        variant_multiplier = self.generic_term_score_multipliers.get(variant, 1.0)
                        scores[(level_name, index_code)] += (
                            field_weight
                            * self.industry_name_level_weights.get(level_name, 1.0)
                            * occurrence_count
                            * (1 + len(variant) / 8)
                            * variant_multiplier
                        )
                        keyword_counts[(level_name, index_code)][variant] += occurrence_count

            for rule in self.keyword_rules:
                occurrence_count = self._count_occurrences(normalized_text, rule["normalized_keyword"])
                if occurrence_count <= 0:
                    continue
                for target in rule["targets"]:
                    target_level = target.get("level")
                    target_name = target.get("name")
                    if target_level not in search_levels:
                        continue
                    match = self._find_level_entry_by_name(target_level, target_name)
                    if match is None:
                        continue
                    level_name, index_code, _entry = match
                    scores[(level_name, index_code)] += field_weight * rule["weight"] * occurrence_count
                    keyword_counts[(level_name, index_code)][rule["keyword"]] += occurrence_count

        self._apply_citic_prior(
            scores=scores,
            keyword_counts=keyword_counts,
            citic_profile=citic_profile,
            citic_mappings=citic_mappings or self._collect_citic_mappings(citic_profile, search_levels),
        )
        self._apply_citic_target_penalty(
            scores=scores,
            citic_mappings=citic_mappings or self._collect_citic_mappings(citic_profile, search_levels),
        )

        ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0][0], item[0][1]))
        results = []
        for (level_name, index_code), score in ranked[:top_n]:
            entry = (level_entries.get(level_name) or {}).get(index_code, {})
            hierarchy = self.cfg.get_sw_hierarchy_from_entry(level_name, entry)
            results.append(
                {
                    "level": level_name,
                    "industry_code": index_code,
                    "industry_name": entry.get("industry_name"),
                    "score": round(score, 4),
                    "matched_keywords": self._format_keyword_counts(keyword_counts[(level_name, index_code)]),
                    "matched_keyword_counts": dict(sorted(keyword_counts[(level_name, index_code)].items())),
                    "hierarchy": hierarchy,
                }
            )
        return results

    def _apply_citic_prior(self, scores, keyword_counts, citic_profile, citic_mappings):
        if not citic_profile or not citic_profile.get("available"):
            return
        for mapping in citic_mappings:
            scores[(mapping["target_level"], mapping["target_code"])] += mapping["boost"]
            keyword_counts[(mapping["target_level"], mapping["target_code"])][
                f"citic:{mapping['citic_name']}"
            ] += 1

    def _apply_citic_target_penalty(self, scores, citic_mappings):
        if self.citic_non_target_score_multiplier >= 1.0 or not citic_mappings:
            return
        mapped_targets = {
            (mapping["target_level"], mapping["target_code"]) for mapping in citic_mappings
        }
        if not mapped_targets:
            return
        for target_key in list(scores.keys()):
            if target_key in mapped_targets:
                continue
            scores[target_key] *= self.citic_non_target_score_multiplier

    def _collect_citic_mappings(self, citic_profile, search_levels):
        if not citic_profile or not citic_profile.get("available"):
            return []

        level_entries = self.cfg.sw_mapping.get("levels", {})
        mappings = []
        for level_name in ["L1", "L2", "L3"]:
            citic_name = citic_profile.get(f"{level_name.lower()}_name")
            if not citic_name:
                continue

            matched_targets = self._find_explicit_sw_targets_for_citic_name(citic_name, search_levels)
            match_type = "explicit"
            if not matched_targets:
                matched_targets = self._find_rule_targets_for_citic_name(citic_name, search_levels)
                match_type = "keyword_rule"
            if not matched_targets:
                matched_targets = self._find_sw_targets_for_citic_name(citic_name, search_levels, level_entries)
                match_type = "fuzzy"

            for target_level, target_code, similarity in matched_targets:
                target_entry = (level_entries.get(target_level) or {}).get(target_code, {})
                mappings.append(
                    {
                        "citic_level": level_name,
                        "citic_name": citic_name,
                        "target_level": target_level,
                        "target_code": target_code,
                        "target_name": target_entry.get("industry_name"),
                        "match_type": match_type,
                        "similarity": round(float(similarity), 4),
                        "boost": self.citic_prior_weights.get(level_name, 0.0) * float(similarity),
                    }
                )
        return mappings

    def _find_explicit_sw_targets_for_citic_name(self, citic_name, search_levels):
        resolved_targets = []
        for target in self.citic_name_targets.get(citic_name, []):
            target_level = target.get("level")
            target_name = target.get("name")
            if target_level not in search_levels or not target_name:
                continue
            match = self._find_level_entry_by_name(target_level, target_name)
            if match is None:
                continue
            level_name, index_code, _entry = match
            resolved_targets.append((level_name, index_code, float(target.get("weight", 1.0))))
        return resolved_targets

    def _find_rule_targets_for_citic_name(self, citic_name, search_levels):
        resolved_targets = []
        normalized_citic = self._normalize_text(citic_name)
        for rule in self.keyword_rules:
            if rule.get("normalized_keyword") != normalized_citic:
                continue
            for target in rule.get("targets", []):
                target_level = target.get("level")
                target_name = target.get("name")
                if target_level not in search_levels or not target_name:
                    continue
                match = self._find_level_entry_by_name(target_level, target_name)
                if match is None:
                    continue
                level_name, index_code, _entry = match
                resolved_targets.append((level_name, index_code, 1.0))
        return resolved_targets

    def suggest_citic_targets(self, citic_name: str, level: str = "L2"):
        search_levels = ["L1", "L2", "L3"] if level == "ALL" else [level]
        level_entries = self.cfg.sw_mapping.get("levels", {})

        explicit_targets = self._find_explicit_sw_targets_for_citic_name(
            citic_name=citic_name,
            search_levels=search_levels,
        )
        if explicit_targets:
            return self._format_citic_target_suggestions(
                citic_name=citic_name,
                matched_targets=explicit_targets,
                match_type="explicit",
                level_entries=level_entries,
            )

        rule_targets = self._find_rule_targets_for_citic_name(
            citic_name=citic_name,
            search_levels=search_levels,
        )
        if rule_targets:
            return self._format_citic_target_suggestions(
                citic_name=citic_name,
                matched_targets=rule_targets,
                match_type="keyword_rule",
                level_entries=level_entries,
            )

        fuzzy_targets = self._find_sw_targets_for_citic_name(
            citic_name=citic_name,
            search_levels=search_levels,
            level_entries=level_entries,
        )
        return self._format_citic_target_suggestions(
            citic_name=citic_name,
            matched_targets=fuzzy_targets,
            match_type="fuzzy",
            level_entries=level_entries,
        )

    @staticmethod
    def _format_citic_target_suggestions(citic_name, matched_targets, match_type, level_entries):
        suggestions = []
        for target_level, target_code, similarity in matched_targets:
            target_entry = (level_entries.get(target_level) or {}).get(target_code, {})
            suggestions.append(
                {
                    "citic_name": citic_name,
                    "target_level": target_level,
                    "target_code": target_code,
                    "target_name": target_entry.get("industry_name"),
                    "match_type": match_type,
                    "similarity": round(float(similarity), 4),
                }
            )
        return suggestions

    def _find_sw_targets_for_citic_name(self, citic_name, search_levels, level_entries):
        normalized_citic = self._normalize_text(citic_name)
        best_matches = []
        for level_name in search_levels:
            level_best = None
            best_similarity = 0.0
            for index_code, entry in (level_entries.get(level_name) or {}).items():
                industry_name = entry.get("industry_name")
                if not industry_name:
                    continue
                variants = self._build_name_variants(industry_name)
                similarity = max(
                    (
                        difflib.SequenceMatcher(None, normalized_citic, variant).ratio()
                        for variant in variants
                    ),
                    default=0.0,
                )
                if normalized_citic in variants:
                    similarity = 1.0
                if similarity < self.citic_name_match_cutoff:
                    continue
                if level_best is None or similarity > best_similarity:
                    level_best = (level_name, index_code, similarity)
                    best_similarity = similarity
            if level_best is not None:
                best_matches.append(level_best)
        return best_matches

    def _find_level_entry_by_name(self, level_name: str, target_name: str):
        for index_code, entry in (self.cfg.sw_mapping.get("levels", {}).get(level_name) or {}).items():
            if entry.get("industry_name") == target_name:
                return level_name, index_code, entry
        return None

    @staticmethod
    def _normalize_text(text):
        if not text:
            return ""
        normalized = str(text).lower()
        normalized = re.sub(r"\s+", "", normalized)
        normalized = normalized.replace("（", "(").replace("）", ")")
        normalized = normalized.replace("，", ",").replace("；", ";")
        return normalized

    def _build_name_variants(self, name: str):
        if not name:
            return set()
        variants = {self._normalize_text(name)}
        simplified = re.sub(r"[ⅠⅡⅢIV]+$", "", name).strip()
        if simplified:
            variants.add(self._normalize_text(simplified))
        simplified = simplified.replace("股份", "")
        if simplified:
            variants.add(self._normalize_text(simplified))
        return {item for item in variants if item}

    @staticmethod
    def _count_occurrences(text: str, keyword: str):
        if not text or not keyword:
            return 0
        return text.count(keyword)

    @staticmethod
    def _format_keyword_counts(keyword_count_map):
        return [
            f"{keyword}({count})"
            for keyword, count in sorted(keyword_count_map.items(), key=lambda item: (-item[1], item[0]))
        ]
