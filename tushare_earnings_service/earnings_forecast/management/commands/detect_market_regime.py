from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from earnings_forecast.services.pipeline import EarningsForecastPipeline


class Command(BaseCommand):
    help = "Detect current market regime (BULL/BEAR/BALANCE) from earnings forecast pipeline rules."

    def add_arguments(self, parser):
        parser.add_argument("--config", type=str, default="configs/default.yaml", help="Pipeline config path")
        parser.add_argument("--asof-date", type=str, default="", help="Optional asof trade date, e.g. 2026-05-09")
        parser.add_argument("--value-only", action="store_true", default=False, help="Print only regime value")

    def handle(self, *_args, **options):
        config_text = str(options.get("config") or "configs/default.yaml").strip() or "configs/default.yaml"
        config_path = Path(config_text)
        if not config_path.is_absolute():
            config_path = Path(settings.BASE_DIR) / config_path
        asof_date_text = str(options.get("asof_date") or "").strip()
        value_only = bool(options.get("value_only"))

        pipeline = EarningsForecastPipeline(config_path=str(config_path))
        meta = pipeline.detect_market_regime(asof_trade_date=asof_date_text or None)
        regime = str((meta or {}).get("regime") or "BALANCE").strip().upper() or "BALANCE"

        if value_only:
            self.stdout.write(regime)
            return

        payload = dict(meta or {})
        payload["regime"] = regime
        self.stdout.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))