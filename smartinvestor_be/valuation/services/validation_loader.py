# apps/valuation/services/valuation_loader.py
import json
import difflib
from pathlib import Path
from typing import Dict, Tuple


class ValuationConfig:
    def __init__(self, base_dir: Path, market: str = "CN"):
        """
        base_dir: 项目根目录（通常传 settings.BASE_DIR）
        market: 市场类型，默认为 "CN"
        """
        self.base_dir = base_dir
        self.mapping_path = base_dir / "valuation_config" / "industry_mapping.json"
        self.defaults_path = base_dir / "valuation_config" / f"valuation_defaults_{market}.json"
        self.sw_mapping_path = base_dir / "valuation_config" / f"sw_industry_mapping_{market}.json"
        self.sw_defaults_path = base_dir / "valuation_config" / f"valuation_defaults_{market}_sw.json"

        self._mapping_cache = None
        self._defaults_cache = None
        self._sw_mapping_cache = None
        self._sw_defaults_cache = None

        # 你可以继续扩充别名库
        self._aliases = {
            "白酒": ["酒", "高端白酒", "白酒酿造", "红黄酒"],
            "半导体": ["芯片", "集成电路", "IC", "晶圆", "封测", "设计"],
            "TMT（科技/传媒/通信)": [
                "TMT",
                "科技",
                "传媒",
                "通信",
                "互联网",
                "IT设备",
                "通信设备",
                "元器件",
            ],
            "消费（可选/必需)": [
                "消费",
                "食品饮料",
                "日化",
                "家电",
                "超市连锁",
                "百货",
                "电器连锁",
                "家用电器",
            ],
            "工业与资本品": [
                "工业",
                "机械",
                "工程机械",
                "机床制造",
                "专用机械",
                "农用机械",
                "电器仪表",
                "机械基件",
            ],
            "公用事业（电力/水务/燃气/环保)": [
                "公用事业",
                "水力发电",
                "火力发电",
                "新型电力",
                "水务",
                "供气供热",
                "环保",
            ],
            "金融": ["银行", "证券", "保险", "多元金融"],
            "交通运输与物流": [
                "公路",
                "铁路",
                "机场",
                "港口",
                "空运",
                "水运",
                "公共交通",
                "仓储物流",
                "路桥",
            ],
            "材料与化工（含建材/金属)": [
                "化工",
                "化工原料",
                "化工机械",
                "染料涂料",
                "化纤",
                "建材",
                "水泥",
                "陶瓷",
                "钢铁",
                "普钢",
                "特种钢",
                "矿物制品",
                "铝",
                "铜",
                "铅锌",
                "小金属",
                "黄金",
                "塑料",
                "造纸",
            ],
            "能源（石油/煤炭/炼化/贸易/新能源)": [
                "石油开采",
                "石油加工",
                "石油贸易",
                "煤炭开采",
                "焦炭加工",
                "能源",
            ],
            "医药与生命科学": [
                "医药",
                "化学制药",
                "生物制药",
                "中成药",
                "医疗保健",
                "医药商业",
            ],
            "商业服务与零售/批发": [
                "商贸代理",
                "批发业",
                "商品城",
                "百货",
                "超市连锁",
                "电器连锁",
            ],
            "休闲服务与酒店旅游": ["旅游服务", "旅游景点", "酒店餐饮", "文教休闲"],
            "汽车与零部件": ["汽车整车", "汽车配件", "汽车服务", "摩托车"],
            "不动产与园区": ["园区开发"],
            "农林牧渔": ["种植业", "渔业", "林业", "饲料", "农业综合"],
            "综合": ["综合类"],
        }
        self._alias_reverse = self._build_alias_reverse()

    def _build_alias_reverse(self) -> Dict[str, str]:
        r = {}
        for big, arr in self._aliases.items():
            for x in arr:
                r[x] = big
        return r

    def _load_json(self, path: Path) -> Dict:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _load_json_if_exists(self, path: Path) -> Dict:
        if not path.exists():
            return {}
        return self._load_json(path)

    @property
    def mapping(self) -> Dict:
        if self._mapping_cache is None:
            self._mapping_cache = self._load_json(self.mapping_path)
        return self._mapping_cache

    @property
    def defaults(self) -> Dict:
        if self._defaults_cache is None:
            self._defaults_cache = self._load_json(self.defaults_path)
        return self._defaults_cache

    @property
    def sw_mapping(self) -> Dict:
        if self._sw_mapping_cache is None:
            self._sw_mapping_cache = self._load_json_if_exists(self.sw_mapping_path)
        return self._sw_mapping_cache

    @property
    def sw_defaults(self) -> Dict:
        if self._sw_defaults_cache is None:
            self._sw_defaults_cache = self._load_json_if_exists(self.sw_defaults_path)
        return self._sw_defaults_cache

    def _clean_test_valuation_kwargs(self, params: Dict) -> Dict:
        cleaned = {}
        for key, value in params.items():
            if value is None:
                continue
            if isinstance(value, dict):
                nested = self._clean_test_valuation_kwargs(value)
                if nested:
                    cleaned[key] = nested
                continue
            if isinstance(value, list) and not value:
                continue
            cleaned[key] = value
        return cleaned

    def _build_test_valuation_kwargs(self, params: Dict) -> Dict:
        direct_param_keys = {
            "pe_target",
            "ps_target",
            "pb_target",
            "sw_history_kwargs",
            "peg_target",
            "ev_ebitda_target",
            "dcf_kwargs",
            "ddm_kwargs",
            "scenario_model",
            "scenario_overrides",
            "sensitivity_grid",
            "current_price",
        }
        if not any(key in params for key in direct_param_keys):
            raise ValueError("valuation_defaults 配置必须直接使用 test_valuation 参数名。")

        return self._clean_test_valuation_kwargs(params)

    def normalize_test_valuation_kwargs(self, params: Dict) -> Dict:
        return self._build_test_valuation_kwargs(params)

    def resolve_bucket_by_industry_name(
        self, narrow_industry: str, fuzzy: bool = True
    ) -> Tuple[str, str]:
        ni = narrow_industry.strip()

        big = self.mapping["industry_to_big_category"].get(ni)

        if not big and ni in self._alias_reverse:
            big = self._alias_reverse[ni]

        if not big and fuzzy:
            keys = list(self.mapping["industry_to_big_category"].keys())
            hit = difflib.get_close_matches(ni, keys, n=1, cutoff=0.6)
            if hit:
                big = self.mapping["industry_to_big_category"][hit[0]]

        if not big:
            raise ValueError(f"未找到细分行业映射：{narrow_industry}")

        big_info = self.mapping["big_categories"].get(big)
        if not big_info:
            raise ValueError(f"大类未定义：{big}")
        return big, big_info["valuation_bucket"]

    def get_params_by_narrow_industry(
        self, narrow_industry: str, fuzzy: bool = True
    ) -> Tuple[str, str, Dict]:
        """
        返回: (big_category, valuation_bucket, params_dict)
        """
        big, bucket = self.resolve_bucket_by_industry_name(narrow_industry, fuzzy=fuzzy)

        # 5) 参数桶 -> 默认参数（在 valuation_defaults.json 的 industries 中查）
        params = self.defaults.get("industries", {}).get(bucket)
        if not params:
            params = self.defaults.get("global_defaults", {})
            if not params:
                raise ValueError("未在 valuation_defaults.json 中找到有效默认参数。")

        return big, bucket, self._build_test_valuation_kwargs(params)

    def get_global_params(self) -> Dict:
        params = self.defaults.get("global_defaults", {})
        if not params:
            raise ValueError("未在 valuation_defaults.json 中找到 global_defaults。")
        return self._build_test_valuation_kwargs(params)

    def _get_sw_hierarchy_from_entry(self, level_name: str, level_entry: Dict) -> Dict:
        levels = self.sw_mapping.get("levels", {})
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
            l1_entry = levels.get("L1", {}).get(l1_code, {})
            hierarchy["l1_code"] = l1_code
            hierarchy["l1_name"] = l1_entry.get("industry_name")
            return hierarchy

        hierarchy["l3_code"] = level_entry.get("index_code")
        hierarchy["l3_name"] = level_entry.get("industry_name")
        l2_code = level_entry.get("parent_index_code")
        l2_entry = levels.get("L2", {}).get(l2_code, {})
        hierarchy["l2_code"] = l2_code
        hierarchy["l2_name"] = l2_entry.get("industry_name")
        l1_code = l2_entry.get("parent_index_code")
        l1_entry = levels.get("L1", {}).get(l1_code, {})
        hierarchy["l1_code"] = l1_code
        hierarchy["l1_name"] = l1_entry.get("industry_name")
        return hierarchy

    def get_sw_hierarchy_from_entry(self, level_name: str, level_entry: Dict) -> Dict:
        return self._get_sw_hierarchy_from_entry(level_name, level_entry)

    def _get_sw_param_candidates(self, level_name: str, hierarchy: Dict):
        if level_name == "L1":
            return [("L1", hierarchy.get("l1_code"))]
        if level_name == "L2":
            return [
                ("L2", hierarchy.get("l2_code")),
                ("L1", hierarchy.get("l1_code")),
            ]
        return [
            ("L3", hierarchy.get("l3_code")),
            ("L2", hierarchy.get("l2_code")),
            ("L1", hierarchy.get("l1_code")),
        ]

    def get_sw_params_by_industry(
        self, industry: str, level: str = None, fuzzy: bool = True
    ) -> Dict:
        if not self.sw_mapping:
            raise ValueError("未找到申万行业映射文件，请先运行 syncswvaluation。")
        if not self.sw_defaults:
            raise ValueError("未找到申万行业估值参数文件，请先运行 syncswvaluation。")

        if not industry:
            raise ValueError("强制申万行业不能为空。")

        query = industry.strip()
        levels = self.sw_mapping.get("levels", {})
        search_levels = [level] if level else ["L3", "L2", "L1"]

        matched_level = None
        matched_entry = None
        for level_name in search_levels:
            level_items = levels.get(level_name, {})
            if query in level_items:
                matched_level = level_name
                matched_entry = level_items[query]
                break
            for entry in level_items.values():
                if entry.get("industry_name") == query:
                    matched_level = level_name
                    matched_entry = entry
                    break
            if matched_entry:
                break

        if matched_entry is None and fuzzy:
            candidate_pairs = []
            for level_name in search_levels:
                for entry in levels.get(level_name, {}).values():
                    industry_name = entry.get("industry_name")
                    if industry_name:
                        candidate_pairs.append((f"{level_name}:{industry_name}", level_name, entry))
            names = [item[0] for item in candidate_pairs]
            hit = difflib.get_close_matches(query, names, n=1, cutoff=0.6)
            if hit:
                matched = next(item for item in candidate_pairs if item[0] == hit[0])
                matched_level = matched[1]
                matched_entry = matched[2]

        if matched_entry is None:
            level_text = level or "L1/L2/L3"
            raise ValueError(f"未找到申万行业：{industry}，级别范围：{level_text}")

        hierarchy = self._get_sw_hierarchy_from_entry(matched_level, matched_entry)
        level_defaults = self.sw_defaults.get("levels", {})
        for candidate_level, industry_code in self._get_sw_param_candidates(matched_level, hierarchy):
            if not industry_code:
                continue
            level_info = level_defaults.get(candidate_level, {}).get(industry_code, {})
            params = level_info.get("params")
            if params:
                return {
                    "source": "sw_override",
                    "level": candidate_level,
                    "industry_code": industry_code,
                    "industry_name": level_info.get("industry_name") or hierarchy.get(f"{candidate_level.lower()}_name"),
                    "hierarchy": hierarchy,
                    "params": self._build_test_valuation_kwargs(params),
                    "metrics": level_info.get("metrics", {}),
                    "matched_level": matched_level,
                    "matched_industry_code": matched_entry.get("index_code"),
                    "matched_industry_name": matched_entry.get("industry_name"),
                }

        global_params = self.sw_defaults.get("global_defaults", {})
        if global_params:
            return {
                "source": "sw_override",
                "level": "global_defaults",
                "industry_code": None,
                "industry_name": None,
                "hierarchy": hierarchy,
                "params": self._build_test_valuation_kwargs(global_params),
                "metrics": {},
                "matched_level": matched_level,
                "matched_industry_code": matched_entry.get("index_code"),
                "matched_industry_name": matched_entry.get("industry_name"),
            }

        raise ValueError(f"未找到申万行业 {industry} 对应的估值参数。")

    def get_sw_params_by_tscode(self, ts_code: str) -> Dict:
        if not self.sw_mapping:
            raise ValueError("未找到申万行业映射文件，请先运行 syncswvaluation。")
        if not self.sw_defaults:
            raise ValueError("未找到申万行业估值参数文件，请先运行 syncswvaluation。")

        ts_entry = self.sw_mapping.get("ts_code_to_levels", {}).get(ts_code)
        if not ts_entry:
            raise ValueError(f"未找到 {ts_code} 的申万行业映射。")

        level_defaults = self.sw_defaults.get("levels", {})
        level_candidates = [
            ("L3", ts_entry.get("l3_code")),
            ("L2", ts_entry.get("l2_code")),
            ("L1", ts_entry.get("l1_code")),
        ]

        for level_name, industry_code in level_candidates:
            if not industry_code:
                continue
            level_info = level_defaults.get(level_name, {}).get(industry_code, {})
            params = level_info.get("params")
            if params:
                return {
                    "source": "sw",
                    "level": level_name,
                    "industry_code": industry_code,
                    "industry_name": ts_entry.get(f"{level_name.lower()}_name"),
                    "hierarchy": ts_entry,
                    "params": self._build_test_valuation_kwargs(params),
                    "metrics": level_info.get("metrics", {}),
                }

        global_params = self.sw_defaults.get("global_defaults", {})
        if global_params:
            return {
                "source": "sw",
                "level": "global_defaults",
                "industry_code": None,
                "industry_name": None,
                "hierarchy": ts_entry,
                "params": self._build_test_valuation_kwargs(global_params),
                "metrics": {},
            }

        raise ValueError(f"未找到 {ts_code} 对应的申万估值参数。")
