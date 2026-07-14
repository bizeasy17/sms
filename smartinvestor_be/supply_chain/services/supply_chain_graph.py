import datetime
import re
from collections import defaultdict

import pandas as pd
from django.db.models import Q

from datastore.models import Corporation, CorporationBasic
from datastore.utils.tushare_util import fetch_tushare_data
from prediction.utils.prediction_util import get_tushare_pro


DEFAULT_CHAIN_DEFINITIONS = {
    "锂电产业链": {
        "layers": [
            {"id": 0, "name": "资源端", "keywords": ["锂矿", "锂辉石", "盐湖", "钴矿", "镍矿", "锰矿"]},
            {"id": 1, "name": "锂盐加工", "keywords": ["碳酸锂", "氢氧化锂", "锂盐", "锂化合物"]},
            {"id": 2, "name": "电池材料", "keywords": ["正极材料", "负极材料", "电解液", "隔膜", "铜箔", "铝箔", "导电剂"]},
            {"id": 3, "name": "电芯制造", "keywords": ["动力电池", "储能电池", "电芯", "圆柱电池", "方形电池", "软包电池"]},
            {"id": 4, "name": "PACK集成", "keywords": ["电池包", "pack", "模组", "bms"]},
            {"id": 5, "name": "终端应用", "keywords": ["新能源汽车", "电动车", "储能系统", "3c电池"]},
        ]
    },
    "半导体产业链": {
        "layers": [
            {"id": 0, "name": "上游材料", "keywords": ["硅片", "光刻胶", "电子特气", "靶材", "抛光液"]},
            {"id": 1, "name": "设备与代工", "keywords": ["晶圆代工", "刻蚀设备", "薄膜设备", "测试设备", "封装设备"]},
            {"id": 2, "name": "芯片设计制造", "keywords": ["芯片", "集成电路", "功率器件", "存储芯片", "模拟芯片"]},
            {"id": 3, "name": "封测与模组", "keywords": ["封测", "先进封装", "模组", "传感器模组"]},
            {"id": 4, "name": "终端应用", "keywords": ["服务器", "汽车电子", "消费电子", "工业控制", "通信设备"]},
        ]
    },
}

STOPWORDS = {
    "公司",
    "产品",
    "业务",
    "相关",
    "以及",
    "主要",
    "生产",
    "销售",
    "研发",
    "服务",
    "系统",
    "领域",
    "技术",
    "设备",
}

CONCEPT_KEYWORD_HINTS = {
    "锂": ["锂电池", "盐湖提锂", "固态电池", "动力电池", "储能"],
    "电池": ["锂电池", "动力电池", "储能", "固态电池"],
    "储能": ["储能", "新型电力系统"],
    "电解液": ["锂电池", "电解液"],
    "隔膜": ["锂电池", "隔膜"],
    "正极": ["锂电池", "正极材料"],
    "负极": ["锂电池", "负极材料"],
    "芯片": ["芯片", "半导体", "集成电路", "算力"],
    "半导体": ["半导体", "芯片", "集成电路", "先进封装"],
    "封测": ["先进封装", "芯片"],
    "算力": ["算力", "数据中心", "人工智能"],
    "光伏": ["光伏", "新能源", "储能"],
    "逆变器": ["光伏", "储能"],
    "风电": ["风电", "新能源"],
    "军工": ["军工", "低空经济"],
    "机器人": ["机器人", "人工智能", "工业母机"],
    "汽车电子": ["汽车电子", "智能驾驶", "新能源车"],
    "新能源车": ["新能源车", "动力电池", "智能驾驶"],
}


class SupplyChainGraphBuilder:
    _concept_catalog_cache = None

    def __init__(self):
        self.chain_definitions = DEFAULT_CHAIN_DEFINITIONS

    @staticmethod
    def _normalize_ts_code(ts_code):
        raw = str(ts_code or "").strip().upper()
        if not raw:
            return ""
        if "." in raw:
            return raw
        if not re.fullmatch(r"\d{6}", raw):
            return raw
        if raw.startswith(("60", "68", "90")):
            return f"{raw}.SH"
        if raw.startswith(("00", "30", "20")):
            return f"{raw}.SZ"
        if raw.startswith(("43", "83", "87")):
            return f"{raw}.BJ"
        return raw

    @staticmethod
    def _safe_float(value):
        try:
            if value is None or value == "":
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _split_tags(text):
        normalized = str(text or "").strip()
        if not normalized:
            return []
        candidates = re.split(r"[，,。；;、/\\|\s（）()]+", normalized)
        out = []
        seen = set()
        for token in candidates:
            tk = str(token or "").strip()
            if len(tk) < 2 or len(tk) > 24:
                continue
            low = tk.lower()
            if low in STOPWORDS or tk in STOPWORDS:
                continue
            if re.fullmatch(r"\d+", tk):
                continue
            key = tk.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(tk)
        return out

    def _load_company_profile(self, ts_code):
        basic = CorporationBasic.objects.filter(ts_code=ts_code).first()
        corp = Corporation.objects.filter(ts_code=ts_code).first()
        profile = {
            "ts_code": ts_code,
            "name": (corp.name if corp else "") or ts_code,
            "business_scope": "",
            "main_business": "",
            "introduction": "",
            "source": "db",
        }

        if basic:
            profile["business_scope"] = str(basic.business_scope or "")
            profile["main_business"] = str(basic.main_business or "")
            profile["introduction"] = str(basic.introduction or "")

        if profile["business_scope"] or profile["main_business"]:
            return profile

        pro = get_tushare_pro()
        suffix = ts_code.split(".")[-1] if "." in ts_code else ""
        exchange = {"SH": "SSE", "SZ": "SZSE", "BJ": "BSE"}.get(suffix)
        if not exchange:
            return profile

        try:
            df = pro.stock_company(
                exchange=exchange,
                fields="ts_code,introduction,main_business,business_scope",
            )
            if df is None or df.empty:
                return profile
            row_df = df[df["ts_code"] == ts_code]
            if row_df.empty:
                return profile
            row = row_df.iloc[0].to_dict()
            profile["business_scope"] = str(row.get("business_scope") or "")
            profile["main_business"] = str(row.get("main_business") or "")
            profile["introduction"] = str(row.get("introduction") or "")
            profile["source"] = "tushare_stock_company"
        except Exception:
            return profile
        return profile

    def _load_mainbiz_df(self, ts_code):
        try:
            start_date = datetime.date(2010, 1, 1)
            end_date = datetime.date.today()
            df = fetch_tushare_data(
                ts_code,
                "MAINBIZ",
                start_date=start_date,
                end_date=end_date,
            )
        except Exception:
            return pd.DataFrame()
        if df is None or df.empty:
            return pd.DataFrame()
        out = df.copy()
        for col in ["bz_sales", "bz_profit", "bz_cost"]:
            if col in out.columns:
                out[col] = pd.to_numeric(out[col], errors="coerce")
        return out

    @staticmethod
    def _extract_tags_from_mainbiz(df):
        tags = []
        if df is None or df.empty:
            return tags
        rows = df.sort_values("end_date") if "end_date" in df.columns else df
        latest_rows = rows.tail(20)
        for _, row in latest_rows.iterrows():
            bz_item = str(row.get("bz_item") or "").strip()
            if not bz_item:
                continue
            weight = 0.75
            sales = SupplyChainGraphBuilder._safe_float(row.get("bz_sales"))
            profit = SupplyChainGraphBuilder._safe_float(row.get("bz_profit"))
            if sales is not None and sales > 0:
                weight += 0.1
            if profit is not None and profit > 0:
                weight += 0.1
            tags.append(
                {
                    "text": bz_item,
                    "source": "fina_mainbz.bz_item",
                    "score": min(0.95, weight),
                }
            )
            for token in SupplyChainGraphBuilder._split_tags(bz_item):
                tags.append(
                    {
                        "text": token,
                        "source": "fina_mainbz.bz_item",
                        "score": min(0.92, weight - 0.05),
                    }
                )
        return tags

    @staticmethod
    def _extract_tags_from_scope(profile):
        text = "\n".join(
            [
                str(profile.get("business_scope") or ""),
                str(profile.get("main_business") or ""),
            ]
        ).strip()
        if not text:
            return []
        tags = []
        for token in SupplyChainGraphBuilder._split_tags(text):
            tags.append(
                {
                    "text": token,
                    "source": "stock_company.business_scope",
                    "score": 0.62,
                }
            )
        return tags

    def _extract_chain_keyword_tags(self, profile):
        source_text = "\n".join(
            [
                str(profile.get("business_scope") or ""),
                str(profile.get("main_business") or ""),
                str(profile.get("introduction") or ""),
            ]
        ).lower()
        tags = []
        for chain_name, chain in self.chain_definitions.items():
            for layer in chain.get("layers", []):
                for kw in layer.get("keywords", []):
                    if str(kw or "").lower() in source_text:
                        tags.append(
                            {
                                "text": kw,
                                "source": "chain_keywords",
                                "score": 0.72,
                                "chain_name": chain_name,
                                "layer_id": layer.get("id"),
                                "layer_name": layer.get("name"),
                            }
                        )
        return tags

    @staticmethod
    def _dedupe_tags(tag_rows):
        best = {}
        for row in tag_rows:
            text = str(row.get("text") or "").strip()
            if not text:
                continue
            key = text.lower()
            prev = best.get(key)
            if prev is None or float(row.get("score") or 0) > float(prev.get("score") or 0):
                best[key] = row
        return list(best.values())

    def _match_layers(self, tags):
        matches = []
        for tag in tags:
            text_low = str(tag.get("text") or "").lower()
            if not text_low:
                continue
            for chain_name, chain in self.chain_definitions.items():
                for layer in chain.get("layers", []):
                    for kw in layer.get("keywords", []):
                        kw_low = str(kw or "").lower()
                        if not kw_low:
                            continue
                        if kw_low == text_low or kw_low in text_low or text_low in kw_low:
                            matches.append(
                                {
                                    "tag": tag.get("text"),
                                    "chain_name": chain_name,
                                    "layer_id": layer.get("id"),
                                    "layer_name": layer.get("name"),
                                    "keyword": kw,
                                    "confidence": max(0.55, min(0.95, float(tag.get("score") or 0) + 0.15)),
                                }
                            )
                            break
        uniq = {}
        for row in matches:
            key = (
                str(row.get("tag") or "").lower(),
                str(row.get("chain_name") or ""),
                int(row.get("layer_id") or 0),
            )
            prev = uniq.get(key)
            if prev is None or row["confidence"] > prev["confidence"]:
                uniq[key] = row
        return list(uniq.values())

    @classmethod
    def _load_concept_catalog(cls):
        if isinstance(cls._concept_catalog_cache, list) and cls._concept_catalog_cache:
            return cls._concept_catalog_cache
        pro = get_tushare_pro()
        catalog = []
        try:
            df = pro.concept()
            if df is not None and not df.empty:
                for _, row in df.iterrows():
                    cid = str(row.get("code") or row.get("id") or "").strip()
                    name = str(row.get("name") or row.get("concept_name") or "").strip()
                    if not name:
                        continue
                    catalog.append({"id": cid or name, "name": name})
        except Exception:
            catalog = []
        cls._concept_catalog_cache = catalog
        return catalog

    @staticmethod
    def _collect_concept_seed_keywords(tags, layer_matches):
        seeds = set()
        for row in tags or []:
            text = str((row or {}).get("text") or "").strip()
            if len(text) >= 2:
                seeds.add(text)
        for row in layer_matches or []:
            layer_name = str((row or {}).get("layer_name") or "").strip()
            chain_name = str((row or {}).get("chain_name") or "").strip()
            keyword = str((row or {}).get("keyword") or "").strip()
            for item in (layer_name, chain_name, keyword):
                if len(item) >= 2:
                    seeds.add(item)
        return sorted(seeds)

    def _load_company_concepts(self, ts_code, tags=None, layer_matches=None):
        pro = get_tushare_pro()
        try:
            df = pro.concept_detail(ts_code=ts_code)
        except Exception:
            df = None

        direct_concepts = []
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                name = str(row.get("concept_name") or row.get("name") or "").strip()
                cid = str(row.get("id") or "").strip()
                if not name:
                    continue
                direct_concepts.append({"id": cid or name, "name": name, "source": "concept_detail"})
        if direct_concepts:
            dedup = {}
            for c in direct_concepts:
                dedup[c["name"].lower()] = c
            return list(dedup.values()), "concept_detail"

        seed_keywords = self._collect_concept_seed_keywords(tags, layer_matches)
        catalog = self._load_concept_catalog()
        scored = []
        for concept in catalog:
            cname = str(concept.get("name") or "").strip()
            c_low = cname.lower()
            if not c_low:
                continue
            score = 0.0
            for kw in seed_keywords:
                k = str(kw or "").strip().lower()
                if len(k) < 2:
                    continue
                if k in c_low or c_low in k:
                    score += 1.0 + min(0.8, len(k) / 12.0)
            if score > 0:
                scored.append((score, concept))
        scored.sort(key=lambda x: x[0], reverse=True)
        if scored:
            out = []
            for score, concept in scored[:20]:
                out.append(
                    {
                        "id": concept.get("id") or concept.get("name"),
                        "name": concept.get("name"),
                        "source": "concept_catalog_fallback",
                        "score": round(float(score), 4),
                    }
                )
            dedup = {}
            for c in out:
                dedup[str(c.get("name") or "").lower()] = c
            return list(dedup.values()), "concept_catalog_fallback"

        matched_hint_names = set()
        for kw in seed_keywords:
            for hint_kw, hint_names in CONCEPT_KEYWORD_HINTS.items():
                if hint_kw in kw or kw in hint_kw:
                    for h in hint_names:
                        matched_hint_names.add(h)
        if matched_hint_names:
            out = [
                {"id": name, "name": name, "source": "concept_rule_fallback"}
                for name in sorted(matched_hint_names)
            ]
            return out, "concept_rule_fallback"

        return [], "concept_empty"

    @staticmethod
    def _tag_to_concept_edges(tags, concepts):
        edges = []
        for tag in tags:
            t = str(tag.get("text") or "").strip()
            if not t:
                continue
            t_low = t.lower()
            for concept in concepts:
                concept_name = str(concept.get("name") or "")
                c_low = concept_name.lower()
                if t_low in c_low or c_low in t_low:
                    edges.append(
                        {
                            "tag": t,
                            "concept_name": concept_name,
                            "confidence": max(0.45, min(0.88, float(tag.get("score") or 0) - 0.05)),
                            "evidence_source": str(concept.get("source") or "concept_match"),
                            "evidence_text": f"tag={t}, concept={concept_name}",
                        }
                    )
        uniq = {}
        for row in edges:
            key = (row["tag"].lower(), row["concept_name"].lower())
            prev = uniq.get(key)
            if prev is None or row["confidence"] > prev["confidence"]:
                uniq[key] = row
        return list(uniq.values())

    @staticmethod
    def _to_level(confidence):
        value = float(confidence or 0)
        if value >= 0.75:
            return "high"
        if value >= 0.55:
            return "medium"
        return "low"

    @staticmethod
    def _direction_from_layer_name(layer_name):
        text = str(layer_name or "")
        if any(k in text for k in ["资源", "材料", "加工", "上游", "设备", "代工"]):
            return "up"
        if any(k in text for k in ["终端", "应用", "客户", "下游", "消费"]):
            return "down"
        return "peer"

    def _build_related_company_candidates(self, center_ts_code, concepts, layer_matches, tags=None, max_candidates=8):
        pro = get_tushare_pro()

        # Use concept members as potential counterparties, then infer up/down via chain-layer keywords.
        concept_refs = []
        for c in concepts or []:
            cid = str(c.get("id") or "").strip()
            cname = str(c.get("name") or "").strip()
            if not cid and not cname:
                continue
            concept_refs.append({"id": cid, "name": cname})
        concept_refs = concept_refs[:6]

        if not concept_refs:
            return []

        candidate_scores = {}
        candidate_concepts = defaultdict(set)
        for idx, concept in enumerate(concept_refs):
            concept_id = concept.get("id")
            concept_name = concept.get("name")
            weight = max(0.25, 1.0 - idx * 0.1)
            df = None
            try:
                if concept_id:
                    df = pro.concept_detail(id=concept_id)
            except Exception:
                df = None
            if (df is None or df.empty) and concept_name:
                try:
                    fallback_df = pro.concept()
                    if fallback_df is not None and not fallback_df.empty:
                        matched = fallback_df[
                            fallback_df["name"].astype(str).str.strip().str.lower()
                            == concept_name.strip().lower()
                        ]
                        if not matched.empty:
                            fallback_id = str(matched.iloc[0].get("code") or matched.iloc[0].get("id") or "").strip()
                            if fallback_id:
                                df = pro.concept_detail(id=fallback_id)
                except Exception:
                    df = df

            if df is None or df.empty:
                continue

            head_df = df.head(80)
            for _, row in head_df.iterrows():
                ts_code = str(row.get("ts_code") or "").strip().upper()
                if not ts_code or ts_code == center_ts_code:
                    continue
                candidate_scores[ts_code] = float(candidate_scores.get(ts_code) or 0.0) + weight
                if concept_name:
                    candidate_concepts[ts_code].add(concept_name)

        # Local fallback: derive counterparties from business text keyword overlaps.
        keyword_direction = {}
        for row in layer_matches or []:
            kw = str(row.get("keyword") or "").strip()
            if not kw:
                continue
            keyword_direction[kw] = {
                "direction": self._direction_from_layer_name(row.get("layer_name")),
                "confidence": float(row.get("confidence") or 0.5),
            }

        seed_keywords = []
        seen_kw = set()
        for kw in keyword_direction.keys():
            if kw not in seen_kw:
                seed_keywords.append(kw)
                seen_kw.add(kw)
        for t in tags or []:
            text = str((t or {}).get("text") or "").strip()
            if len(text) < 2 or len(text) > 16:
                continue
            if text in seen_kw:
                continue
            seed_keywords.append(text)
            seen_kw.add(text)
        seed_keywords = seed_keywords[:12]

        local_hit_keywords = defaultdict(set)
        local_direction_scores = defaultdict(lambda: {"up": 0.0, "down": 0.0, "peer": 0.0})
        if seed_keywords:
            for kw in seed_keywords:
                rows = (
                    CorporationBasic.objects.exclude(ts_code=center_ts_code)
                    .filter(
                        Q(business_scope__icontains=kw)
                        | Q(main_business__icontains=kw)
                        | Q(introduction__icontains=kw)
                    )
                    .values("ts_code")[:120]
                )
                for row in rows:
                    ts_code = str(row.get("ts_code") or "").strip().upper()
                    if not ts_code:
                        continue
                    candidate_scores[ts_code] = float(candidate_scores.get(ts_code) or 0.0) + 0.28
                    local_hit_keywords[ts_code].add(kw)
                    info = keyword_direction.get(kw)
                    if info:
                        d = str(info.get("direction") or "peer")
                        local_direction_scores[ts_code][d] += max(0.2, min(0.9, float(info.get("confidence") or 0.5)))

        if not candidate_scores:
            center_corp = Corporation.objects.filter(ts_code=center_ts_code).select_related("industry").first()
            if center_corp is not None:
                same_qs = Corporation.objects.exclude(ts_code=center_ts_code)
                if str(center_corp.sw_l3_code or "").strip():
                    same_qs = same_qs.filter(sw_l3_code=center_corp.sw_l3_code)
                elif center_corp.industry_id:
                    same_qs = same_qs.filter(industry_id=center_corp.industry_id)
                for c in same_qs.values("ts_code")[:80]:
                    code = str(c.get("ts_code") or "").strip().upper()
                    if not code:
                        continue
                    candidate_scores[code] = float(candidate_scores.get(code) or 0.0) + 0.36
                    local_direction_scores[code]["peer"] += 0.35

        if not candidate_scores:
            return []

        ranked_codes = [k for k, _ in sorted(candidate_scores.items(), key=lambda x: x[1], reverse=True)][: max_candidates * 4]
        corp_qs = Corporation.objects.filter(ts_code__in=ranked_codes).select_related("industry")
        corp_map = {c.ts_code: c for c in corp_qs}
        basic_qs = CorporationBasic.objects.filter(ts_code__in=ranked_codes)
        basic_map = {b.ts_code: b for b in basic_qs}

        layer_rows = list(layer_matches or [])
        candidates = []
        for code in ranked_codes:
            corp = corp_map.get(code)
            basic = basic_map.get(code)
            if corp is None and basic is None:
                continue

            company_name = (
                (corp.name if corp else "")
                or (str(getattr(basic, "name", "") or "").strip())
                or code
            )
            industry_name = ""
            if corp is not None:
                industry_name = str(corp.sw_l3_name or "").strip() or str((corp.industry.name if corp.industry else "") or "").strip()

            profile_text = " ".join(
                [
                    str(getattr(basic, "business_scope", "") or ""),
                    str(getattr(basic, "main_business", "") or ""),
                    str(getattr(basic, "introduction", "") or ""),
                    industry_name,
                ]
            ).lower()

            direction_score = {"up": 0.0, "down": 0.0, "peer": 0.0}
            preset_dir = local_direction_scores.get(code)
            if preset_dir:
                direction_score["up"] += float(preset_dir.get("up") or 0.0)
                direction_score["down"] += float(preset_dir.get("down") or 0.0)
                direction_score["peer"] += float(preset_dir.get("peer") or 0.0)
            hit_keywords = list(local_hit_keywords.get(code) or [])
            for row in layer_rows:
                kw = str(row.get("keyword") or "").strip().lower()
                if not kw or kw not in profile_text:
                    continue
                direction = self._direction_from_layer_name(row.get("layer_name"))
                base_conf = float(row.get("confidence") or 0.45)
                direction_score[direction] += max(0.2, min(1.0, base_conf))
                hit_keywords.append(str(row.get("keyword") or ""))

            if sum(direction_score.values()) <= 0:
                direction_score["peer"] = 0.35

            direction = max(direction_score.items(), key=lambda x: x[1])[0]
            confidence = min(
                0.95,
                0.3
                + float(candidate_scores.get(code) or 0.0) * 0.18
                + float(direction_score.get(direction) or 0.0) * 0.15,
            )

            candidates.append(
                {
                    "ts_code": code,
                    "name": company_name,
                    "industry": industry_name,
                    "direction": direction,
                    "confidence": round(float(confidence), 4),
                    "hit_keywords": sorted(set(hit_keywords))[:5],
                    "concept_hits": sorted(candidate_concepts.get(code) or [])[:4],
                }
            )

        candidates.sort(key=lambda x: float(x.get("confidence") or 0), reverse=True)
        return candidates[:max_candidates]

    def build(self, ts_code, max_nodes=120, min_confidence=0.35, include_concepts=True, include_layers=True):
        normalized = self._normalize_ts_code(ts_code)
        if not normalized:
            raise ValueError("ts_code is required")

        profile = self._load_company_profile(normalized)
        mainbiz_df = self._load_mainbiz_df(normalized)

        raw_tags = []
        raw_tags.extend(self._extract_tags_from_scope(profile))
        raw_tags.extend(self._extract_tags_from_mainbiz(mainbiz_df))
        raw_tags.extend(self._extract_chain_keyword_tags(profile))
        tags = self._dedupe_tags(raw_tags)

        layer_matches = self._match_layers(tags) if include_layers else []
        concept_mode = "concept_disabled"
        concepts = []
        if include_concepts:
            concepts, concept_mode = self._load_company_concepts(
                normalized,
                tags=tags,
                layer_matches=layer_matches,
            )
        tag_concept_edges = self._tag_to_concept_edges(tags, concepts) if include_concepts else []
        related_companies = self._build_related_company_candidates(
            center_ts_code=normalized,
            concepts=concepts,
            layer_matches=layer_matches,
            tags=tags,
            max_candidates=max(6, min(14, int(max_nodes // 6) if max_nodes else 10)),
        )

        nodes = []
        edges = []

        center_corp = Corporation.objects.filter(ts_code=normalized).select_related("industry").first()
        center_industry = ""
        if center_corp is not None:
            center_industry = str(center_corp.sw_l3_name or "").strip() or str((center_corp.industry.name if center_corp.industry else "") or "").strip()

        center_node_id = f"company:{normalized}"
        nodes.append(
            {
                "id": center_node_id,
                "type": "company",
                "label": profile.get("name") or normalized,
                "score": 1.0,
                "confidence": 1.0,
                "meta": {
                    "ts_code": normalized,
                    "profile_source": profile.get("source"),
                    "industry": center_industry,
                },
            }
        )

        for rc in related_companies:
            rc_code = str(rc.get("ts_code") or "").strip().upper()
            if not rc_code:
                continue
            rc_node_id = f"company_related:{rc_code}"
            rc_conf = float(rc.get("confidence") or 0)
            if rc_conf < min_confidence:
                continue
            rc_direction = str(rc.get("direction") or "peer")
            nodes.append(
                {
                    "id": rc_node_id,
                    "type": "company_related",
                    "label": str(rc.get("name") or rc_code),
                    "score": rc_conf,
                    "confidence": rc_conf,
                    "meta": {
                        "ts_code": rc_code,
                        "industry": str(rc.get("industry") or ""),
                        "direction": rc_direction,
                        "direction_label": "上游" if rc_direction == "up" else ("下游" if rc_direction == "down" else "同链"),
                        "concept_hits": rc.get("concept_hits") or [],
                        "hit_keywords": rc.get("hit_keywords") or [],
                        "confidence_level": self._to_level(rc_conf),
                    },
                }
            )
            edges.append(
                {
                    "source": center_node_id,
                    "target": rc_node_id,
                    "relation": "company_supply_link_inferred",
                    "confidence": rc_conf,
                    "evidence_source": "concept_detail+layer_keywords",
                    "evidence_text": f"direction={rc_direction}; concepts={','.join((rc.get('concept_hits') or [])[:3])}",
                }
            )

        for tag in tags:
            conf = float(tag.get("score") or 0)
            if conf < min_confidence:
                continue
            tag_text = str(tag.get("text") or "").strip()
            if not tag_text:
                continue
            tag_node_id = f"tag:{tag_text}"
            nodes.append(
                {
                    "id": tag_node_id,
                    "type": "tag",
                    "label": tag_text,
                    "score": conf,
                    "confidence": conf,
                    "meta": {
                        "source": tag.get("source"),
                        "confidence_level": self._to_level(conf),
                    },
                }
            )
            edges.append(
                {
                    "source": center_node_id,
                    "target": tag_node_id,
                    "relation": "company_has_tag",
                    "confidence": conf,
                    "evidence_source": str(tag.get("source") or "unknown"),
                    "evidence_text": f"tag={tag_text}",
                }
            )

        if include_layers:
            for row in layer_matches:
                conf = float(row.get("confidence") or 0)
                if conf < min_confidence:
                    continue
                tag_text = str(row.get("tag") or "").strip()
                layer_node_id = (
                    f"layer:{row.get('chain_name')}:{row.get('layer_id')}:{row.get('layer_name')}"
                )
                nodes.append(
                    {
                        "id": layer_node_id,
                        "type": "layer",
                        "label": f"{row.get('chain_name')} · {row.get('layer_name')}",
                        "score": conf,
                        "confidence": conf,
                        "meta": {
                            "chain_name": row.get("chain_name"),
                            "layer_id": row.get("layer_id"),
                            "layer_name": row.get("layer_name"),
                        },
                    }
                )
                edges.append(
                    {
                        "source": f"tag:{tag_text}",
                        "target": layer_node_id,
                        "relation": "tag_in_layer",
                        "confidence": conf,
                        "evidence_source": "chain_definitions",
                        "evidence_text": f"keyword={row.get('keyword')}",
                    }
                )

        if include_concepts:
            for c in concepts:
                concept_node_id = f"concept:{c.get('name')}"
                nodes.append(
                    {
                        "id": concept_node_id,
                        "type": "concept",
                        "label": c.get("name"),
                        "score": 0.5,
                        "confidence": 0.5,
                        "meta": {"concept_id": c.get("id")},
                    }
                )
                edges.append(
                    {
                        "source": center_node_id,
                        "target": concept_node_id,
                        "relation": "company_in_concept",
                        "confidence": 0.5,
                        "evidence_source": str(c.get("source") or concept_mode),
                        "evidence_text": f"concept={c.get('name')}",
                    }
                )

            for row in tag_concept_edges:
                conf = float(row.get("confidence") or 0)
                if conf < min_confidence:
                    continue
                edges.append(
                    {
                        "source": f"tag:{row.get('tag')}",
                        "target": f"concept:{row.get('concept_name')}",
                        "relation": "tag_in_concept",
                        "confidence": conf,
                        "evidence_source": row.get("evidence_source"),
                        "evidence_text": row.get("evidence_text"),
                    }
                )

        dedup_nodes = {}
        for node in nodes:
            key = str(node.get("id") or "")
            if not key:
                continue
            prev = dedup_nodes.get(key)
            if prev is None or float(node.get("confidence") or 0) > float(prev.get("confidence") or 0):
                dedup_nodes[key] = node

        dedup_edges = {}
        for edge in edges:
            key = (
                str(edge.get("source") or ""),
                str(edge.get("target") or ""),
                str(edge.get("relation") or ""),
            )
            prev = dedup_edges.get(key)
            if prev is None or float(edge.get("confidence") or 0) > float(prev.get("confidence") or 0):
                dedup_edges[key] = edge

        node_list = list(dedup_nodes.values())[: max(10, int(max_nodes))]
        node_ids = {n["id"] for n in node_list}
        edge_list = [
            e
            for e in dedup_edges.values()
            if e.get("source") in node_ids and e.get("target") in node_ids
        ]

        confidence_counter = defaultdict(int)
        for edge in edge_list:
            confidence_counter[self._to_level(edge.get("confidence"))] += 1

        source_modes = sorted(
            {
                str(profile.get("source") or ""),
                "fina_mainbz" if (mainbiz_df is not None and not mainbiz_df.empty) else "fina_mainbz_empty",
                concept_mode,
            }
        )

        warnings = []
        if concept_mode in {"concept_catalog_fallback", "concept_rule_fallback"}:
            warnings.append("concept_detail_empty_fallback_used")
        if concept_mode == "concept_empty":
            warnings.append("concept_unavailable")

        return {
            "code": 0,
            "data": {
                "center": {
                    "ts_code": normalized,
                    "name": profile.get("name") or normalized,
                    "industry": center_industry,
                },
                "nodes": node_list,
                "edges": edge_list,
                "stats": {
                    "related_company_count": len([n for n in node_list if n.get("type") == "company_related"]),
                    "tag_count": len([n for n in node_list if n.get("type") == "tag"]),
                    "concept_count": len([n for n in node_list if n.get("type") == "concept"]),
                    "layer_count": len([n for n in node_list if n.get("type") == "layer"]),
                    "edge_count": len(edge_list),
                    "confidence_summary": dict(confidence_counter),
                },
                "trace": {
                    "source_modes": source_modes,
                    "asof": datetime.date.today().isoformat(),
                    "warnings": warnings,
                },
            },
        }


def build_supply_chain_graph_payload(
    ts_code,
    max_nodes=120,
    min_confidence=0.35,
    include_concepts=True,
    include_layers=True,
):
    builder = SupplyChainGraphBuilder()
    return builder.build(
        ts_code=ts_code,
        max_nodes=max_nodes,
        min_confidence=min_confidence,
        include_concepts=include_concepts,
        include_layers=include_layers,
    )
