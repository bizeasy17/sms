from __future__ import annotations

from datetime import datetime
from typing import Optional

from django.core.management.base import BaseCommand
from django.db import transaction

from earnings_forecast.models import FinancialFeatureSnapshot, get_financial_endpoint_model


def _to_float(value) -> Optional[float]:
    if value in (None, "", "nan", "None"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _score_date(date_text: str) -> int:
    text = str(date_text or "").strip()
    if not text:
        return 0
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) == 8:
        try:
            return int(digits)
        except ValueError:
            return 0
    return 0


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
    help = "Build/update flattened financial feature snapshot table from raw JSON financial records."

    ENDPOINT_MODELS = {
        "income": get_financial_endpoint_model("income"),
        "fina_indicator_vip": get_financial_endpoint_model("fina_indicator_vip"),
        "balancesheet_vip": get_financial_endpoint_model("balancesheet_vip"),
        "cashflow_vip": get_financial_endpoint_model("cashflow_vip"),
    }

    VALUE_FIELDS = [
        "ann_date",
        "end_date",
        "f_ann_date",
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

    def _latest_payload_by_endpoint(self, ts_code: str, endpoint: str) -> tuple[dict, Optional[datetime]]:
        model = self.ENDPOINT_MODELS.get(endpoint)
        if model is None:
            return {}, None
        model_fields = {f.name for f in model._meta.fields}
        query_fields = [f for f in self.VALUE_FIELDS if f in model_fields]
        rows = model.objects.filter(ts_code=ts_code).values(*query_fields, "imported_at")
        best_score = -1
        best_payload: dict = {}
        best_imported_at = None
        for row in rows:
            payload = dict(row)
            end_date = str(row.get("end_date") or "")
            ann_date = str(row.get("ann_date") or row.get("f_ann_date") or "")
            score = _score_date(end_date) * 100000000 + _score_date(ann_date)
            if score > best_score:
                best_score = score
                best_payload = payload
                best_imported_at = row.get("imported_at")
        return best_payload, best_imported_at

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

        self.stdout.write(self.style.SUCCESS(f"build financial feature snapshot: symbols={total}"))
        if total == 0:
            self.stdout.write(self.style.WARNING("no source rows found in endpoint tables"))
            return

        upserts: list[FinancialFeatureSnapshot] = []
        for idx, ts_code in enumerate(ts_codes, start=1):
            income_payload, income_updated = self._latest_payload_by_endpoint(ts_code, "income")
            fina_payload, fina_updated = self._latest_payload_by_endpoint(ts_code, "fina_indicator_vip")
            balance_payload, balance_updated = self._latest_payload_by_endpoint(ts_code, "balancesheet_vip")
            cashflow_payload, cashflow_updated = self._latest_payload_by_endpoint(ts_code, "cashflow_vip")

            end_date = str(
                fina_payload.get("end_date")
                or income_payload.get("end_date")
                or ""
            ).strip()
            ann_date = str(
                fina_payload.get("ann_date")
                or fina_payload.get("f_ann_date")
                or income_payload.get("ann_date")
                or income_payload.get("f_ann_date")
                or ""
            ).strip()

            source_updated_at = fina_updated or income_updated
            if fina_updated and income_updated:
                source_updated_at = max(fina_updated, income_updated)
            if balance_updated and source_updated_at:
                source_updated_at = max(source_updated_at, balance_updated)
            elif balance_updated:
                source_updated_at = balance_updated
            if cashflow_updated and source_updated_at:
                source_updated_at = max(source_updated_at, cashflow_updated)
            elif cashflow_updated:
                source_updated_at = cashflow_updated

            upserts.append(
                FinancialFeatureSnapshot(
                    ts_code=ts_code,
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

            if idx % 500 == 0:
                self.stdout.write(f"prepared: {idx}/{total}")

        written = 0
        for i in range(0, len(upserts), batch_size):
            chunk = upserts[i : i + batch_size]
            with transaction.atomic():
                FinancialFeatureSnapshot.objects.bulk_create(
                    chunk,
                    update_conflicts=True,
                    unique_fields=["ts_code"],
                    update_fields=[
                        "end_date",
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

        self.stdout.write(self.style.SUCCESS(f"snapshot build done: rows_upserted={written}"))
