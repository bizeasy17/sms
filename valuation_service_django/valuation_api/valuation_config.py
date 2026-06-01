import difflib
import json
from pathlib import Path


def _safe_load_json(path: Path):
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


class StandaloneValuationConfig:
    """Standalone loader compatible with legacy valuation template files."""

    def __init__(self, base_dir: Path, market: str = "CN"):
        config_dir = base_dir / "static" / "valuation_config"
        self.market = market
        self.mapping = _safe_load_json(config_dir / "industry_mapping.json")
        self.defaults = _safe_load_json(config_dir / f"valuation_defaults_{market}.json")
        self.sw_mapping = _safe_load_json(config_dir / f"sw_industry_mapping_{market}.json")
        self.sw_defaults = _safe_load_json(config_dir / f"valuation_defaults_{market}_sw.json")
        self.method_weights = _safe_load_json(config_dir / f"valuation_method_weights_{market}.json")

    def _clean(self, payload):
        cleaned = {}
        for key, value in (payload or {}).items():
            if value is None:
                continue
            if isinstance(value, dict):
                nested = self._clean(value)
                if nested:
                    cleaned[key] = nested
                continue
            if isinstance(value, list) and not value:
                continue
            cleaned[key] = value
        return cleaned

    def _normalize_method_weights(self, value):
        if not isinstance(value, dict):
            return None
        normalized = {}
        for method, weight in value.items():
            key = str(method or "").strip().lower()
            try:
                val = float(weight)
            except (TypeError, ValueError):
                continue
            if not key or val <= 0:
                continue
            normalized[key] = val
        return normalized or None

    def _method_weights_for_sw(self, level_name, industry_code, hierarchy):
        cfg = self.method_weights or {}
        levels_cfg = cfg.get("sw_level_defaults") or {}
        names_cfg = cfg.get("sw_name_defaults") or {}

        candidates = []
        if level_name and industry_code:
            candidates.append((level_name, industry_code, (levels_cfg.get(level_name) or {}).get(industry_code)))

        if isinstance(hierarchy, dict):
            h_candidates = [
                ("L3", hierarchy.get("l3_code"), hierarchy.get("l3_name")),
                ("L2", hierarchy.get("l2_code"), hierarchy.get("l2_name")),
                ("L1", hierarchy.get("l1_code"), hierarchy.get("l1_name")),
            ]
            for lvl, code, name in h_candidates:
                candidates.append((lvl, code, (levels_cfg.get(lvl) or {}).get(code) if code else None))
                if name:
                    candidates.append((lvl, name, (names_cfg.get(lvl) or {}).get(name)))

        for _lvl, _key, payload in candidates:
            weights = self._normalize_method_weights(payload)
            if weights:
                return weights

        return self._normalize_method_weights((cfg.get("global_defaults") or {}))

    def _method_weights_for_legacy(self, valuation_bucket, industry_name=None):
        cfg = self.method_weights or {}
        bucket_cfg = (cfg.get("legacy_bucket_defaults") or {})
        if valuation_bucket:
            weights = self._normalize_method_weights(bucket_cfg.get(valuation_bucket))
            if weights:
                return weights

        name_cfg = (cfg.get("legacy_industry_name_defaults") or {})
        if industry_name:
            weights = self._normalize_method_weights(name_cfg.get(industry_name))
            if weights:
                return weights

        return self._normalize_method_weights((cfg.get("global_defaults") or {}))

    def _attach_method_weights(self, params, method_weights):
        payload = dict(params or {})
        if "method_weights" in payload:
            normalized_existing = self._normalize_method_weights(payload.get("method_weights"))
            if normalized_existing:
                payload["method_weights"] = normalized_existing
                return payload
        normalized = self._normalize_method_weights(method_weights)
        if normalized:
            payload["method_weights"] = normalized
        return payload

    def _require_test_valuation_shape(self, params):
        keys = {
            "pe_target",
            "ps_target",
            "pb_target",
            "scarcity_kwargs",
            "peg_target",
            "ev_ebitda_target",
            "dcf_kwargs",
            "ddm_kwargs",
            "scenario_model",
            "scenario_overrides",
            "sensitivity_grid",
            "current_price",
        }
        if not any(k in (params or {}) for k in keys):
            raise ValueError("valuation template is not in test_valuation kwargs format")
        return self._clean(params)

    def _sw_hierarchy_from_entry(self, level_name: str, level_entry: dict):
        levels = self.sw_mapping.get("levels") or {}
        hierarchy = {
            "l1_code": None,
            "l1_name": None,
            "l2_code": None,
            "l2_name": None,
            "l3_code": None,
            "l3_name": None,
        }

        if level_name == "L1":
            hierarchy["l1_code"] = level_entry.get("index_code")
            hierarchy["l1_name"] = level_entry.get("industry_name")
            return hierarchy

        if level_name == "L2":
            hierarchy["l2_code"] = level_entry.get("index_code")
            hierarchy["l2_name"] = level_entry.get("industry_name")
            l1_code = level_entry.get("parent_index_code")
            l1_entry = (levels.get("L1") or {}).get(l1_code, {})
            hierarchy["l1_code"] = l1_code
            hierarchy["l1_name"] = l1_entry.get("industry_name")
            return hierarchy

        hierarchy["l3_code"] = level_entry.get("index_code")
        hierarchy["l3_name"] = level_entry.get("industry_name")
        l2_code = level_entry.get("parent_index_code")
        l2_entry = (levels.get("L2") or {}).get(l2_code, {})
        hierarchy["l2_code"] = l2_code
        hierarchy["l2_name"] = l2_entry.get("industry_name")
        l1_code = l2_entry.get("parent_index_code")
        l1_entry = (levels.get("L1") or {}).get(l1_code, {})
        hierarchy["l1_code"] = l1_code
        hierarchy["l1_name"] = l1_entry.get("industry_name")
        return hierarchy

    def get_sw_hierarchy_from_entry(self, level_name: str, level_entry: dict):
        return self._sw_hierarchy_from_entry(level_name, level_entry)

    def _get_sw_candidates(self, matched_level: str, hierarchy: dict):
        if matched_level == "L1":
            return [("L1", hierarchy.get("l1_code"))]
        if matched_level == "L2":
            return [
                ("L2", hierarchy.get("l2_code")),
                ("L1", hierarchy.get("l1_code")),
            ]
        return [
            ("L3", hierarchy.get("l3_code")),
            ("L2", hierarchy.get("l2_code")),
            ("L1", hierarchy.get("l1_code")),
        ]

    def get_sw_params_by_tscode(self, ts_code: str):
        ts_entry = (self.sw_mapping.get("ts_code_to_levels") or {}).get(ts_code)
        if not ts_entry:
            raise ValueError(f"sw mapping missing for {ts_code}")

        level_defaults = self.sw_defaults.get("levels", {})
        candidates = [
            ("L3", ts_entry.get("l3_code")),
            ("L2", ts_entry.get("l2_code")),
            ("L1", ts_entry.get("l1_code")),
        ]
        for level_name, industry_code in candidates:
            if not industry_code:
                continue
            level_info = (level_defaults.get(level_name) or {}).get(industry_code) or {}
            params = level_info.get("params")
            if params:
                method_weights = self._method_weights_for_sw(level_name, industry_code, ts_entry)
                return {
                    "source": "sw",
                    "level": level_name,
                    "industry_code": industry_code,
                    "industry_name": ts_entry.get(f"{level_name.lower()}_name"),
                    "hierarchy": ts_entry,
                    "metrics": level_info.get("metrics") if isinstance(level_info.get("metrics"), dict) else None,
                    "params": self._require_test_valuation_shape(
                        self._attach_method_weights(params, method_weights)
                    ),
                }

        global_params = self.sw_defaults.get("global_defaults") or {}
        if global_params:
            method_weights = self._normalize_method_weights((self.method_weights or {}).get("global_defaults"))
            return {
                "source": "sw_global_defaults",
                "level": "global_defaults",
                "industry_code": None,
                "industry_name": None,
                "hierarchy": ts_entry,
                "params": self._require_test_valuation_shape(
                    self._attach_method_weights(global_params, method_weights)
                ),
            }
        raise ValueError(f"sw params missing for {ts_code}")

    def get_sw_params_by_industry(self, industry: str, level: str = None, fuzzy: bool = True):
        if not industry:
            raise ValueError("sw industry is required")

        levels = self.sw_mapping.get("levels") or {}
        search_levels = [level] if level else ["L3", "L2", "L1"]
        query = str(industry).strip()

        matched_level = None
        matched_entry = None
        for level_name in search_levels:
            level_items = levels.get(level_name) or {}
            if query in level_items:
                matched_level = level_name
                matched_entry = level_items[query]
                break
            for entry in level_items.values():
                if entry.get("industry_name") == query:
                    matched_level = level_name
                    matched_entry = entry
                    break
            if matched_entry is not None:
                break

        if matched_entry is None and fuzzy:
            candidates = []
            for level_name in search_levels:
                for entry in (levels.get(level_name) or {}).values():
                    name = entry.get("industry_name")
                    if name:
                        candidates.append((f"{level_name}:{name}", level_name, entry))
            names = [item[0] for item in candidates]
            hit = difflib.get_close_matches(query, names, n=1, cutoff=0.6)
            if hit:
                matched = next(item for item in candidates if item[0] == hit[0])
                matched_level = matched[1]
                matched_entry = matched[2]

        if matched_entry is None:
            raise ValueError(f"sw industry missing for {industry}")

        hierarchy = self._sw_hierarchy_from_entry(matched_level, matched_entry)
        defaults = self.sw_defaults.get("levels") or {}
        for candidate_level, industry_code in self._get_sw_candidates(matched_level, hierarchy):
            if not industry_code:
                continue
            level_info = (defaults.get(candidate_level) or {}).get(industry_code, {})
            params = level_info.get("params")
            if params:
                method_weights = self._method_weights_for_sw(candidate_level, industry_code, hierarchy)
                return {
                    "source": "forced_sw",
                    "level": candidate_level,
                    "industry_code": industry_code,
                    "industry_name": level_info.get("industry_name") or hierarchy.get(f"{candidate_level.lower()}_name"),
                    "hierarchy": hierarchy,
                    "metrics": level_info.get("metrics") if isinstance(level_info.get("metrics"), dict) else None,
                    "matched_level": matched_level,
                    "matched_industry_code": matched_entry.get("index_code"),
                    "matched_industry_name": matched_entry.get("industry_name"),
                    "params": self._require_test_valuation_shape(
                        self._attach_method_weights(params, method_weights)
                    ),
                }

        global_params = self.sw_defaults.get("global_defaults") or {}
        if global_params:
            method_weights = self._normalize_method_weights((self.method_weights or {}).get("global_defaults"))
            return {
                "source": "forced_sw_global_defaults",
                "level": "global_defaults",
                "industry_code": None,
                "industry_name": None,
                "hierarchy": hierarchy,
                "matched_level": matched_level,
                "matched_industry_code": matched_entry.get("index_code"),
                "matched_industry_name": matched_entry.get("industry_name"),
                "params": self._require_test_valuation_shape(
                    self._attach_method_weights(global_params, method_weights)
                ),
            }

        raise ValueError(f"sw params missing for industry {industry}")

    def get_legacy_params_by_industry(self, industry: str, fuzzy: bool = True):
        if not industry:
            raise ValueError("industry is required")

        mapping = self.mapping.get("industry_to_big_category") or {}
        big = mapping.get(industry)
        if not big and fuzzy:
            all_keys = list(mapping.keys())
            hit = difflib.get_close_matches(industry, all_keys, n=1, cutoff=0.6)
            if hit:
                big = mapping.get(hit[0])
        if not big:
            raise ValueError(f"legacy industry mapping missing for {industry}")

        big_info = (self.mapping.get("big_categories") or {}).get(big) or {}
        bucket = big_info.get("valuation_bucket")
        params = ((self.defaults.get("industries") or {}).get(bucket) or {})
        if not params:
            params = self.defaults.get("global_defaults") or {}
        if not params:
            raise ValueError("legacy defaults missing")

        method_weights = self._method_weights_for_legacy(bucket, industry)

        return {
            "source": "legacy_industry_mapping",
            "big_category": big,
            "valuation_bucket": bucket,
            "params": self._require_test_valuation_shape(
                self._attach_method_weights(params, method_weights)
            ),
        }

    def get_global_params(self):
        params = self.defaults.get("global_defaults") or self.sw_defaults.get("global_defaults") or {}
        if not params:
            raise ValueError("global defaults missing")
        method_weights = self._normalize_method_weights((self.method_weights or {}).get("global_defaults"))
        return {
            "source": "global_defaults",
            "params": self._require_test_valuation_shape(
                self._attach_method_weights(params, method_weights)
            ),
        }


def resolve_template_params(base_dir: Path, ts_code: str, industry: str = "", market: str = "CN"):
    cfg = StandaloneValuationConfig(base_dir=base_dir, market=market)

    try:
        return cfg.get_sw_params_by_tscode(ts_code)
    except (ValueError, KeyError, TypeError):
        pass

    if industry:
        try:
            return cfg.get_legacy_params_by_industry(industry)
        except (ValueError, KeyError, TypeError):
            pass

    try:
        return cfg.get_global_params()
    except (ValueError, KeyError, TypeError):
        return None
