from __future__ import annotations
from django.core.management.base import BaseCommand, CommandError
from typing import List
import logging

from utils.prediction_util import get_feature_data

# /c:/Users/HANJ29/Development/code/sms/smartinvestor_ln/training/management/commands/genfeatures.py

logger = logging.getLogger(__name__)

SUPPORTED_FEATURE_TYPES = {
    "trading",
    "trading calc",
    "fundamental",
    "fundamental calc",
    "cost",
    "cost calc",
    "sentiment",
}

SUPPORTED_CALC_TYPES = {
    "atr",
    "bollinger_bands",
    "percentile",
    "shadow_volume",
    "moving_averages", # support, resistance, convergence/divergence
}

class Command(BaseCommand):
    help = "Generate features for a given tscode and feature type."

    def add_arguments(self, parser):
        parser.add_argument(
            "--tscode",
            required=True,
            help="Security code (e.g. 000001.SZ). For multiple, separate with commas."
        )
        parser.add_argument(
            "--freq",
            required=True,
            help="Frequency (e.g. daily, weekly)."
        )
        parser.add_argument(
            "--feature_type",
            required=True,
            choices=sorted(SUPPORTED_FEATURE_TYPES),
            help=f"Feature type. Supported: {', '.join(sorted(SUPPORTED_FEATURE_TYPES))}"
        )
        parser.add_argument(
            "--dry_run",
            action="store_true",
            help="Run without persisting results."
        )

    def handle(self, *args, **options):
        raw_tscode = options["tscode"].strip()
        freq = options["freq"].strip()
        feature_type = options["feature_type"].strip().lower()
        dry_run = options["dry_run"]

        if feature_type not in SUPPORTED_FEATURE_TYPES:
            raise CommandError(f"Unsupported feature type '{feature_type}'.")

        tscodes: List[str] = [t.strip() for t in raw_tscode.split(",") if t.strip()]
        if not tscodes:
            raise CommandError("No valid tscode provided.")

        results = []
        for code in tscodes:
            try:
                # 按照股票代码获得特征数据的步骤
                # 单个特征类型，譬如成本，基本面，技术面
                # 计算单个特征类型的计算特征，如果有的话
                # 合并基本特征和计算特征
                data = get_feature_data(ts_code=code, freq=freq, feature_type=feature_type)
                results.append(data)
                if not dry_run:
                    # TODO: Persist data (e.g., save to DB or file)
                    logger.info("Persisting features for %s", code)
            except Exception as exc:
                logger.exception("Failed generating features for %s", code)
                self.stderr.write(self.style.ERROR(f"{code}: {exc}"))

        self.stdout.write(self.style.SUCCESS(
            f"Generated {len(results)} feature object(s) for type '{feature_type}'."
        ))
        # Optional: print summary
        for r in results:
            self.stdout.write(str(r))