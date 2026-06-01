import json
import difflib
import re
import time
from collections import defaultdict
from pathlib import Path

from django.conf import settings

from datastore.models import CorporationBasic
from prediction.services.validation_loader import ValuationConfig
from prediction.utils.prediction_util import get_tushare_pro


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
    DEFAULT_KEYWORD_RULES = [
        {"keyword": "芯片", "weight": 3.2, "targets": [{"level": "L2", "name": "半导体"}]},
        {"keyword": "集成电路", "weight": 3.2, "targets": [{"level": "L2", "name": "半导体"}]},
        {"keyword": "晶圆", "weight": 3.0, "targets": [{"level": "L2", "name": "半导体"}]},
        {"keyword": "封装", "weight": 2.4, "targets": [{"level": "L2", "name": "半导体"}]},
        {"keyword": "封测", "weight": 2.8, "targets": [{"level": "L2", "name": "半导体"}]},
        {"keyword": "功率器件", "weight": 2.7, "targets": [{"level": "L2", "name": "半导体"}]},
        {"keyword": "军工", "weight": 2.0, "targets": [{"level": "L1", "name": "国防军工"}]},
        {"keyword": "导弹", "weight": 3.0, "targets": [{"level": "L1", "name": "国防军工"}]},
        {"keyword": "航空发动机", "weight": 3.0, "targets": [{"level": "L1", "name": "国防军工"}]},
        {"keyword": "光伏", "weight": 2.6, "targets": [{"level": "L2", "name": "光伏设备"}]},
        {"keyword": "锂电", "weight": 2.7, "targets": [{"level": "L2", "name": "电池"}]},
        {"keyword": "储能", "weight": 2.5, "targets": [{"level": "L2", "name": "电池"}]},
        {"keyword": "创新药", "weight": 3.0, "targets": [{"level": "L2", "name": "化学制药"}, {"level": "L2", "name": "生物制品"}]},
        {"keyword": "医疗器械", "weight": 3.0, "targets": [{"level": "L2", "name": "医疗器械"}]},
        {"keyword": "软件", "weight": 1.8, "targets": [{"level": "L2", "name": "软件开发"}]},
        {"keyword": "云计算", "weight": 2.3, "targets": [{"level": "L2", "name": "IT服务"}]},
        {"keyword": "算力", "weight": 2.4, "targets": [{"level": "L2", "name": "IT服务"}]},
        {"keyword": "服务器", "weight": 2.1, "targets": [{"level": "L2", "name": "计算机设备"}]},
        {"keyword": "白酒", "weight": 3.0, "targets": [{"level": "L2", "name": "白酒"}]},
        {"keyword": "啤酒", "weight": 2.7, "targets": [{"level": "L2", "name": "啤酒"}]},
        {"keyword": "机器人", "weight": 2.3, "targets": [{"level": "L2", "name": "自动化设备"}]},
        {"keyword": "汽车电子", "weight": 2.6, "targets": [{"level": "L2", "name": "汽车零部件"}, {"level": "L2", "name": "半导体"}]},
        {"keyword": "新能源车", "weight": 2.3, "targets": [{"level": "L1", "name": "汽车"}]},
    ]
    DEFAULT_TUSHARE_MIN_INTERVAL_SECONDS = 0.31
    DEFAULT_TUSHARE_RETRY_COUNT = 3
    DEFAULT_TUSHARE_RETRY_BACKOFF_SECONDS = 0.6

    def __init__(self, base_dir: Path, market: str = "CN", pro=None):
        self.base_dir = base_dir
        self.market = market
        self.cfg = ValuationConfig(base_dir, market=market)
        self.pro = pro or get_tushare_pro()
        self.rule_config = self._load_rule_config()
        self.field_weights = self.rule_config.get("field_weights", self.DEFAULT_FIELD_WEIGHTS)
        self.industry_name_level_weights = self.rule_config.get(
            "industry_name_level_weights", self.DEFAULT_INDUSTRY_NAME_LEVEL_WEIGHTS
        )
        self.citic_prior_weights = self.rule_config.get(
            "citic_prior_weights", {"L1": 0.8, "L2": 1.6, "L3": 2.2}
        )
        self.citic_name_match_cutoff = float(
            self.rule_config.get("citic_name_match_cutoff", 0.55)
        )
        self.citic_name_targets = self.rule_config.get("citic_name_targets", {})
        self.generic_term_score_multipliers = self.rule_config.get(
            "generic_term_score_multipliers", {}
        )
        self.citic_non_target_score_multiplier = float(
            self.rule_config.get("citic_non_target_score_multiplier", 1.0)
        )
        self.keyword_rules = self._normalize_keyword_rules(
            self.rule_config.get("keyword_rules", self.DEFAULT_KEYWORD_RULES)
        )
        self.tushare_min_interval_seconds = float(
            getattr(
                settings,
                "BUSINESS_MATCH_TUSHARE_MIN_INTERVAL_SECONDS",
                self.DEFAULT_TUSHARE_MIN_INTERVAL_SECONDS,
            )
            or self.DEFAULT_TUSHARE_MIN_INTERVAL_SECONDS
        )
        self.tushare_retry_count = int(
            getattr(
                settings,
                "BUSINESS_MATCH_TUSHARE_RETRY_COUNT",
                self.DEFAULT_TUSHARE_RETRY_COUNT,
            )
            or self.DEFAULT_TUSHARE_RETRY_COUNT
        )
        self.tushare_retry_backoff_seconds = float(
            getattr(
                settings,
                "BUSINESS_MATCH_TUSHARE_RETRY_BACKOFF_SECONDS",
                self.DEFAULT_TUSHARE_RETRY_BACKOFF_SECONDS,
            )
            or self.DEFAULT_TUSHARE_RETRY_BACKOFF_SECONDS
        )
        self.use_remote_fallback = str(
            getattr(settings, "BUSINESS_MATCH_USE_REMOTE_FALLBACK", "1")
        ).lower() in {"1", "true", "yes", "on"}
        self.cache_dir = self.base_dir / "valuation_cache"
        self._citic_cache = self._load_cache_json(
            self.cache_dir / f"citic_profile_{self.market}.json"
        )
        self._stock_company_cache = self._load_cache_json(
            self.cache_dir / f"stock_company_{self.market}.json"
        )
        self._last_tushare_call_ts = 0.0

    def _load_cache_json(self, path: Path):
        if not path.exists():
            return {}
        try:
            with path.open("r", encoding="utf-8") as file_obj:
                payload = json.load(file_obj)
            return payload.get("data", {}) if isinstance(payload, dict) else {}
        except Exception:  # pylint: disable=broad-exception-caught
            return {}

    def _sleep_for_tushare_rate_limit(self):
        min_interval = max(0.0, float(self.tushare_min_interval_seconds or 0.0))
        if min_interval <= 0:
            return
        now = time.monotonic()
        elapsed = now - self._last_tushare_call_ts
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)

    def _is_tushare_rate_limit_error(self, exc):
        message = str(exc or "").lower()
        return any(
            marker in message
            for marker in [
                "200/min",
                "too many",
                "rate limit",
                "rate_limit",
                "429",
                "频率",
                "限频",
            ]
        )

    def _call_tushare_with_retry(self, api_func, **kwargs):
        max_attempts = max(1, int(self.tushare_retry_count or 1))
        last_exc = None
        for attempt in range(1, max_attempts + 1):
            try:
                self._sleep_for_tushare_rate_limit()
                result = api_func(**kwargs)
                self._last_tushare_call_ts = time.monotonic()
                return result
            except Exception as exc:  # pylint: disable=broad-exception-caught
                self._last_tushare_call_ts = time.monotonic()
                last_exc = exc
                if (not self._is_tushare_rate_limit_error(exc)) or attempt >= max_attempts:
                    raise
                backoff = max(0.0, float(self.tushare_retry_backoff_seconds or 0.0)) * attempt
                if backoff > 0:
                    time.sleep(backoff)
        if last_exc is not None:
            raise last_exc
        return None

    def _load_rule_config(self):
        config_path = (
            self.base_dir / "valuation_config" / f"business_keyword_rules_{self.market}.json"
        )
        if not config_path.exists():
            return {}
        with config_path.open("r", encoding="utf-8") as file_obj:
            return json.load(file_obj)

    def _normalize_keyword_rules(self, rules):
        normalized_rules = []
        for rule in rules:
            keyword = rule.get("keyword")
            targets = rule.get("targets", [])
            if not keyword or not targets:
                continue
            normalized_rules.append(
                {
                    "keyword": keyword,
                    "normalized_keyword": self._normalize_text(keyword),
                    "weight": float(rule.get("weight", 1.0)),
                    "targets": targets,
                }
            )
        return normalized_rules

    def match_by_tscode(self, ts_code: str, top_n: int = 3, level: str = "L2"):
        profile = self.get_business_profile(ts_code)
        citic_profile = self.get_citic_profile(ts_code)
        search_levels = ["L1", "L2", "L3"] if level == "ALL" else [level]
        citic_mappings = self._collect_citic_mappings(citic_profile, search_levels)
        matches = self.match_from_profile(
            profile,
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

    def get_citic_context(self, ts_code: str, level: str = "L2"):
        citic_profile = self.get_citic_profile(ts_code)
        search_levels = ["L1", "L2", "L3"] if level == "ALL" else [level]
        return {
            "citic_profile": citic_profile,
            "citic_mappings": self._collect_citic_mappings(citic_profile, search_levels),
        }

    def get_citic_profile(self, ts_code: str):
        profile = {
            "ts_code": ts_code,
            "l1_code": None,
            "l1_name": None,
            "l2_code": None,
            "l2_name": None,
            "l3_code": None,
            "l3_name": None,
            "source": None,
            "available": False,
            "error": None,
        }
        cached = (self._citic_cache or {}).get(ts_code)
        if isinstance(cached, dict) and cached.get("available"):
            profile.update(
                {
                    "l1_code": cached.get("l1_code"),
                    "l1_name": cached.get("l1_name"),
                    "l2_code": cached.get("l2_code"),
                    "l2_name": cached.get("l2_name"),
                    "l3_code": cached.get("l3_code"),
                    "l3_name": cached.get("l3_name"),
                    "source": "local_cache_citic_profile",
                    "available": True,
                }
            )
            return profile

        if not self.use_remote_fallback:
            profile["source"] = "local_cache_only"
            return profile

        try:
            df = self._call_tushare_with_retry(
                self.pro.ci_index_member,
                ts_code=ts_code,
                is_new="Y",
            )
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

    def get_business_profile(self, ts_code: str):
        basic_info = CorporationBasic.objects.filter(ts_code=ts_code).first()
        profile = {
            "ts_code": ts_code,
            "main_business": None,
            "business_scope": None,
            "introduction": None,
            "source": None,
        }

        if basic_info:
            profile.update(
                {
                    "main_business": basic_info.main_business,
                    "business_scope": basic_info.business_scope,
                    "introduction": basic_info.introduction,
                    "source": "db",
                }
            )

        if any(profile.get(field) for field in self.field_weights):
            return profile

        cached_company = (self._stock_company_cache or {}).get(ts_code)
        if isinstance(cached_company, dict):
            cached_profile = {
                "main_business": cached_company.get("main_business"),
                "business_scope": cached_company.get("business_scope"),
                "introduction": cached_company.get("introduction"),
            }
            if any(cached_profile.get(field) for field in self.field_weights):
                profile.update({**cached_profile, "source": "local_cache_stock_company"})
                return profile

        if not self.use_remote_fallback:
            return profile

        exchange_map = {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}
        suffix = (ts_code.split(".")[-1] if "." in ts_code else "").upper()
        exchange = exchange_map.get(suffix)
        if not exchange:
            return profile

        try:
            df = self._call_tushare_with_retry(
                self.pro.stock_company,
                exchange=exchange,
                fields="ts_code,introduction,main_business,business_scope",
            )
        except Exception:
            return profile
        if df is None or df.empty:
            return profile
        row_df = df[df["ts_code"] == ts_code]
        if row_df.empty:
            return profile
        row = row_df.iloc[0].to_dict()
        profile.update(
            {
                "main_business": row.get("main_business"),
                "business_scope": row.get("business_scope"),
                "introduction": row.get("introduction"),
                "source": "tushare_stock_company",
            }
        )
        return profile

    def match_from_profile(
        self,
        profile: dict,
        top_n: int = 3,
        level: str = "L2",
        citic_profile: dict = None,
        citic_mappings=None,
    ):
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
                for index_code, entry in level_entries.get(level_name, {}).items():
                    industry_name = entry.get("industry_name")
                    variants = self._build_name_variants(industry_name)
                    for variant in variants:
                        if len(variant) < 2:
                            continue
                        occurrence_count = self._count_occurrences(normalized_text, variant)
                        if occurrence_count > 0:
                            variant_multiplier = self.generic_term_score_multipliers.get(
                                variant, 1.0
                            )
                            scores[(level_name, index_code)] += (
                                field_weight
                                * self.industry_name_level_weights.get(level_name, 1.0)
                                * occurrence_count
                                * (1 + len(variant) / 8)
                                * variant_multiplier
                            )
                            keyword_counts[(level_name, index_code)][variant] += occurrence_count

            for rule in self.keyword_rules:
                occurrence_count = self._count_occurrences(
                    normalized_text, rule["normalized_keyword"]
                )
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
                    scores[(level_name, index_code)] += (
                        field_weight * rule["weight"] * occurrence_count
                    )
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
            entry = level_entries.get(level_name, {}).get(index_code, {})
            hierarchy = self.cfg.get_sw_hierarchy_from_entry(level_name, entry)
            results.append(
                {
                    "level": level_name,
                    "industry_code": index_code,
                    "industry_name": entry.get("industry_name"),
                    "score": round(score, 4),
                    "matched_keywords": self._format_keyword_counts(
                        keyword_counts[(level_name, index_code)]
                    ),
                    "matched_keyword_counts": dict(
                        sorted(keyword_counts[(level_name, index_code)].items())
                    ),
                    "hierarchy": hierarchy,
                }
            )
        return results

    def _apply_citic_prior(
        self,
        scores,
        keyword_counts,
        citic_profile,
        citic_mappings,
    ):
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
            (mapping["target_level"], mapping["target_code"])
            for mapping in citic_mappings
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

            matched_targets = self._find_explicit_sw_targets_for_citic_name(
                citic_name=citic_name,
                search_levels=search_levels,
            )
            match_type = "explicit"
            if not matched_targets:
                matched_targets = self._find_rule_targets_for_citic_name(
                    citic_name=citic_name,
                    search_levels=search_levels,
                )
                match_type = "keyword_rule"
            if not matched_targets:
                matched_targets = self._find_sw_targets_for_citic_name(
                    citic_name=citic_name,
                    search_levels=search_levels,
                    level_entries=level_entries,
                )
                match_type = "fuzzy"

            for target_level, target_code, similarity in matched_targets:
                target_entry = level_entries.get(target_level, {}).get(target_code, {})
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
            resolved_targets.append(
                (level_name, index_code, float(target.get("weight", 1.0)))
            )
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
            target_entry = level_entries.get(target_level, {}).get(target_code, {})
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
            for index_code, entry in level_entries.get(level_name, {}).items():
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
        for index_code, entry in self.cfg.sw_mapping.get("levels", {}).get(level_name, {}).items():
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
    def _count_occurrences(text: str, keyword: str) -> int:
        if not text or not keyword:
            return 0
        return text.count(keyword)

    @staticmethod
    def _format_keyword_counts(keyword_count_map):
        return [
            f"{keyword}({count})"
            for keyword, count in sorted(
                keyword_count_map.items(), key=lambda item: (-item[1], item[0])
            )
        ]