from __future__ import annotations

from datetime import datetime
from typing import Optional

from django.core.management.base import BaseCommand
from django.db import transaction

from earnings_forecast.models import FinancialFeaturePanel, get_financial_endpoint_model


CORE_ENDPOINTS = [
    "income",
    "fina_indicator_vip",
    "balancesheet_vip",
    "cashflow_vip",
]


def _to_float(value) -> Optional[float]:
    if value in (None, "", "nan", "None"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _digits8(text: str) -> str:
    raw = "".join(ch for ch in str(text or "") if ch.isdigit())
    if len(raw) >= 8:
        return raw[:8]
    return ""


def _report_type(endpoint: str, end_date: str) -> str:
    if endpoint == "express_vip":
        return "EXPRESS"
    if endpoint == "forecast_vip":
        return "FORECAST"

    d = _digits8(end_date)
    md = d[4:8] if len(d) == 8 else ""
    if md == "0331":
        return "Q1"
    if md == "0630":
        return "H1"
    if md == "0930":
        return "Q3"
    if md == "1231":
        return "FY"
    return "OTHER"


def _pick_ann_date(row: dict, fallback: str) -> str:
    for key in ["ann_date", "f_ann_date", "publish_date"]:
        text = _digits8(row.get(key, ""))
        if text:
            return text
    return _digits8(fallback)


def _pick_end_date(row: dict, fallback: str) -> str:
    for key in ["end_date", "report_date"]:
        text = _digits8(row.get(key, ""))
        if text:
            return text
    return _digits8(fallback)


def _load_ts_codes_from_file(path: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    with open(path, "r", encoding="utf-8") as f:
        for raw in f:
            code = str(raw or "").strip().upper()
            if not code:
                continue
            if code in seen:
                continue
            seen.add(code)
            out.append(code)
    return out


class Command(BaseCommand):
    help = "Build financial feature panel (multi-row by report period) from raw financial records."

    ENDPOINT_MODELS = {
        "income": get_financial_endpoint_model("income"),
        "fina_indicator_vip": get_financial_endpoint_model("fina_indicator_vip"),
        "balancesheet_vip": get_financial_endpoint_model("balancesheet_vip"),
        "cashflow_vip": get_financial_endpoint_model("cashflow_vip"),
    }

    VALUE_FIELDS = [
        "ann_date",
        "f_ann_date",
        "end_date",
        "report_type",
        "revenue",
        "total_revenue",
        "operate_profit",
        "total_profit",
        "n_income",
        "n_income_attr_p",
        "basic_eps",
        "diluted_eps",
        "roe",
        "roe_dt",
        "roa",
        "q_dt_roe",
        "tr_yoy",
        "netprofit_yoy",
        "grossprofit_margin",
        "netprofit_margin",
        "debt_to_assets",
        "current_ratio",
        "quick_ratio",
        "cash_ratio",
        "assets_turn",
        "ocf_to_or",
        "total_assets",
        "total_liab",
        "total_hldr_eqy_exc_min_int",
        "money_cap",
        "accounts_receiv",
        "inventories",
        "st_borr",
        "lt_borr",
        "n_cashflow_act",
        "n_cashflow_inv_act",
        "n_cash_flows_fnc_act",
        "n_incr_cash_cash_equ",
    ]

    def add_arguments(self, parser):
        parser.add_argument("--batch-size", type=int, default=1000, help="Bulk upsert batch size")
        parser.add_argument("--limit", type=int, help="Limit number of symbols for smoke tests")
        parser.add_argument("--tscodes-file", type=str, help="Text file with one ts_code per line")

    def _collect_latest_by_period(self, ts_code: str, endpoint: str) -> dict[tuple[str, str], tuple[dict, Optional[datetime]]]:
        model = self.ENDPOINT_MODELS.get(endpoint)
        if model is None:
            return {}
        model_fields = {f.name for f in model._meta.fields}
        query_fields = [f for f in self.VALUE_FIELDS if f in model_fields]
        rows = model.objects.filter(ts_code=ts_code).values(*query_fields, "imported_at")

        out: dict[tuple[str, str], tuple[dict, Optional[datetime]]] = {}
        for row in rows:
            payload = dict(row)
            end_date = _pick_end_date(payload, row.get("end_date") or "")
            if not end_date:
                continue

            ann_date = _pick_ann_date(payload, row.get("ann_date") or "")
            report_type = _report_type(endpoint, end_date)
            key = (end_date, report_type)

            old = out.get(key)
            if old is None:
                out[key] = (payload, row.get("imported_at"))
                continue

            old_payload, old_imported = old
            old_ann = _pick_ann_date(old_payload, "")
            use_new = False
            if ann_date and old_ann:
                use_new = ann_date >= old_ann
            elif ann_date and not old_ann:
                use_new = True
            elif row.get("imported_at") and old_imported:
                use_new = row.get("imported_at") >= old_imported

            if use_new:
                out[key] = (payload, row.get("imported_at"))

        return out

    def handle(self, *args, **options):
        batch_size = max(100, int(options.get("batch_size") or 1000))
        limit = options.get("limit")
        ts_codes_file = str(options.get("tscodes_file") or "").strip()

        if ts_codes_file:
            ts_codes = _load_ts_codes_from_file(ts_codes_file)
        else:
            ts_code_set: set[str] = set()
            for model in self.ENDPOINT_MODELS.values():
                if model is None:
                    continue
                ts_code_set.update(model.objects.values_list("ts_code", flat=True).distinct())
            ts_codes = sorted(ts_code_set)
        if limit:
            ts_codes = ts_codes[:limit]
        total = len(ts_codes)

        self.stdout.write(self.style.SUCCESS(f"build financial feature panel: symbols={total}"))
        if total == 0:
            self.stdout.write(self.style.WARNING("no source rows found in endpoint tables"))
            return

        upserts: list[FinancialFeaturePanel] = []
        for idx, ts_code in enumerate(ts_codes, start=1):
            endpoint_map = {ep: self._collect_latest_by_period(ts_code, ep) for ep in CORE_ENDPOINTS}

            keys: set[tuple[str, str]] = set()
            for m in endpoint_map.values():
                keys.update(m.keys())

            for end_date, report_type in sorted(keys):
                income_payload, income_updated = endpoint_map["income"].get((end_date, report_type), ({}, None))
                fina_payload, fina_updated = endpoint_map["fina_indicator_vip"].get((end_date, report_type), ({}, None))
                balance_payload, balance_updated = endpoint_map["balancesheet_vip"].get((end_date, report_type), ({}, None))
                cashflow_payload, cashflow_updated = endpoint_map["cashflow_vip"].get((end_date, report_type), ({}, None))

                ann_date = _pick_ann_date(
                    fina_payload or income_payload or balance_payload or cashflow_payload,
                    "",
                )

                source_updated_at = None
                for dt in [income_updated, fina_updated, balance_updated, cashflow_updated]:
                    if dt is None:
                        continue
                    if source_updated_at is None or dt > source_updated_at:
                        source_updated_at = dt

                fiscal_year = int(end_date[:4]) if len(end_date) == 8 and end_date[:4].isdigit() else 0

                upserts.append(
                    FinancialFeaturePanel(
                        ts_code=ts_code,
                        fiscal_year=fiscal_year,
                        report_type=report_type,
                        end_date=end_date,
                        ann_date=ann_date,
                        revenue=_to_float(income_payload.get("revenue")),
                        total_revenue=_to_float(income_payload.get("total_revenue")),
                        operate_profit=_to_float(income_payload.get("operate_profit")),
                        total_profit=_to_float(income_payload.get("total_profit")),
                        n_income=_to_float(income_payload.get("n_income") or income_payload.get("n_income_attr_p")),
                        n_income_attr_p=_to_float(income_payload.get("n_income_attr_p")),
                        basic_eps=_to_float(income_payload.get("basic_eps")),
                        diluted_eps=_to_float(income_payload.get("diluted_eps")),
                        roe=_to_float(fina_payload.get("roe")),
                        roe_dt=_to_float(fina_payload.get("roe_dt")),
                        roa=_to_float(fina_payload.get("roa")),
                        q_dt_roe=_to_float(fina_payload.get("q_dt_roe")),
                        tr_yoy=_to_float(fina_payload.get("tr_yoy")),
                        netprofit_yoy=_to_float(fina_payload.get("netprofit_yoy")),
                        grossprofit_margin=_to_float(fina_payload.get("grossprofit_margin")),
                        netprofit_margin=_to_float(fina_payload.get("netprofit_margin")),
                        debt_to_assets=_to_float(fina_payload.get("debt_to_assets")),
                        current_ratio=_to_float(fina_payload.get("current_ratio")),
                        quick_ratio=_to_float(fina_payload.get("quick_ratio")),
                        cash_ratio=_to_float(fina_payload.get("cash_ratio")),
                        assets_turn=_to_float(fina_payload.get("assets_turn")),
                        ocf_to_or=_to_float(fina_payload.get("ocf_to_or")),
                        total_assets=_to_float(balance_payload.get("total_assets")),
                        total_liab=_to_float(balance_payload.get("total_liab")),
                        total_hldr_eqy_exc_min_int=_to_float(balance_payload.get("total_hldr_eqy_exc_min_int")),
                        money_cap=_to_float(balance_payload.get("money_cap")),
                        accounts_receiv=_to_float(balance_payload.get("accounts_receiv")),
                        inventories=_to_float(balance_payload.get("inventories")),
                        st_borr=_to_float(balance_payload.get("st_borr")),
                        lt_borr=_to_float(balance_payload.get("lt_borr")),
                        n_cashflow_act=_to_float(cashflow_payload.get("n_cashflow_act")),
                        n_cashflow_inv_act=_to_float(cashflow_payload.get("n_cashflow_inv_act")),
                        n_cash_flows_fnc_act=_to_float(cashflow_payload.get("n_cash_flows_fnc_act")),
                        n_incr_cash_cash_equ=_to_float(cashflow_payload.get("n_incr_cash_cash_equ")),
                        source_updated_at=source_updated_at,
                    )
                )

            if idx % 300 == 0:
                self.stdout.write(f"prepared symbols: {idx}/{total}")

        written = 0
        for i in range(0, len(upserts), batch_size):
            chunk = upserts[i : i + batch_size]
            with transaction.atomic():
                FinancialFeaturePanel.objects.bulk_create(
                    chunk,
                    update_conflicts=True,
                    unique_fields=["ts_code", "end_date", "report_type"],
                    update_fields=[
                        "fiscal_year",
                        "ann_date",
                        "revenue",
                        "total_revenue",
                        "operate_profit",
                        "total_profit",
                        "n_income",
                        "n_income_attr_p",
                        "basic_eps",
                        "diluted_eps",
                        "roe",
                        "roe_dt",
                        "roa",
                        "q_dt_roe",
                        "tr_yoy",
                        "netprofit_yoy",
                        "grossprofit_margin",
                        "netprofit_margin",
                        "debt_to_assets",
                        "current_ratio",
                        "quick_ratio",
                        "cash_ratio",
                        "assets_turn",
                        "ocf_to_or",
                        "total_assets",
                        "total_liab",
                        "total_hldr_eqy_exc_min_int",
                        "money_cap",
                        "accounts_receiv",
                        "inventories",
                        "st_borr",
                        "lt_borr",
                        "n_cashflow_act",
                        "n_cashflow_inv_act",
                        "n_cash_flows_fnc_act",
                        "n_incr_cash_cash_equ",
                        "source_updated_at",
                        "updated_at",
                    ],
                )
            written += len(chunk)

        self.stdout.write(self.style.SUCCESS(f"feature panel build done: rows_upserted={written}"))
