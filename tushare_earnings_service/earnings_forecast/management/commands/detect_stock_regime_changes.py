from __future__ import annotations

from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from earnings_forecast.models import LocalCorporation, LocalTradingHistory, StockRegimeState
from earnings_forecast.services.stock_regime import classify_stock_regime, next_regime_state


def _scope_prefixes(scope: str) -> list[str]:
    value = str(scope or "ALL").strip().upper()
    if value == "ALL":
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


class Command(BaseCommand):
    help = "Detect confirmed per-stock regime changes and optionally persist state/output triggered codes."

    def add_arguments(self, parser):
        parser.add_argument("--scope", default="60,00,30,68", help="ALL or ts_code prefixes")
        parser.add_argument("--confirm-days", type=int, default=2, help="Consecutive days required before a switch triggers")
        parser.add_argument("--output-file", type=str, default="", help="Triggered ts_code output file")
        parser.add_argument("--metadata-file", type=str, default="", help="Triggered ts_code to stock-regime JSON output file")
        parser.add_argument("--write", action="store_true", default=False, help="Persist state changes; without it the command is read-only")
        parser.add_argument("--limit", type=int, default=0, help="Limit symbols for a smoke check")

    def handle(self, *_args, **options):
        prefixes = _scope_prefixes(options["scope"])
        confirm_days = max(1, int(options["confirm_days"] or 2))
        codes = list(LocalCorporation.objects.order_by("ts_code").values_list("ts_code", flat=True))
        codes = [str(code).strip().upper() for code in codes if str(code).strip()]
        if prefixes:
            codes = [code for code in codes if any(code.startswith(prefix) for prefix in prefixes)]
        if int(options["limit"] or 0) > 0:
            codes = codes[: int(options["limit"])]

        existing = {state.ts_code: state for state in StockRegimeState.objects.filter(ts_code__in=codes)}
        triggered, triggered_regimes, observed, insufficient = [], {}, 0, 0
        pending_updates = []
        for code in codes:
            history = list(
                LocalTradingHistory.objects.filter(ts_code=code, freq="D")
                .order_by("-trade_date").values("trade_date", "close")[:65]
            )
            history.reverse()
            metrics = classify_stock_regime([row.get("close") for row in history])
            if metrics is None:
                insufficient += 1
                continue
            observed += 1
            state = existing.get(code)
            current = state.regime if state else ""
            pending = state.pending_regime if state else ""
            pending_days = state.pending_days if state else 0
            regime, next_pending, next_pending_days, is_triggered = next_regime_state(
                current, pending, pending_days, metrics.regime, confirm_days
            )
            if is_triggered:
                triggered.append(code)
                triggered_regimes[code] = regime
            if options["write"]:
                pending_updates.append(
                    StockRegimeState(
                        id=state.id if state else None,
                        ts_code=code,
                        regime=regime,
                        previous_regime=current if is_triggered else (state.previous_regime if state else ""),
                        pending_regime=next_pending,
                        pending_days=next_pending_days,
                        asof_trade_date=history[-1].get("trade_date"),
                        ma20=metrics.ma20,
                        ma60=metrics.ma60,
                        volatility_20d=metrics.volatility_20d,
                        drawdown_60d=metrics.drawdown_60d,
                        last_triggered_at=timezone.now() if is_triggered else (state.last_triggered_at if state else None),
                    )
                )

        if options["write"]:
            with transaction.atomic():
                for state in pending_updates:
                    StockRegimeState.objects.update_or_create(
                        ts_code=state.ts_code,
                        defaults={field: getattr(state, field) for field in (
                            "regime", "previous_regime", "pending_regime", "pending_days", "asof_trade_date",
                            "ma20", "ma60", "volatility_20d", "drawdown_60d", "last_triggered_at",
                        )},
                    )
        output_file = str(options["output_file"] or "").strip()
        if output_file:
            path = Path(output_file)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("\n".join(triggered) + ("\n" if triggered else ""), encoding="utf-8")
        metadata_file = str(options["metadata_file"] or "").strip()
        if metadata_file:
            path = Path(metadata_file)
            path.parent.mkdir(parents=True, exist_ok=True)
            import json
            path.write_text(json.dumps(triggered_regimes, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        self.stdout.write(
            f"stock regime scan: scanned={len(codes)} observed={observed} insufficient={insufficient} "
            f"triggered={len(triggered)} write={bool(options['write'])}"
        )
        for code in triggered:
            self.stdout.write(f"triggered: {code}")