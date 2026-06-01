from __future__ import annotations

import argparse
import copy
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from earnings_forecast.services import EarningsForecastPipeline


def _suffix_filename(filename: str, suffix: str) -> str:
    path = Path(str(filename or "").strip() or "artifact.bin")
    stem = path.stem
    ext = path.suffix
    safe_suffix = str(suffix).strip().upper()
    return f"{stem}_{safe_suffix}{ext}"


class Command(BaseCommand):
    help = "Train models by report_type in one run, e.g. Q1,H1,Q3."

    def add_arguments(self, parser):
        parser.add_argument("--config", type=str, help="Path to pipeline yaml config")
        parser.add_argument(
            "--report-types",
            type=str,
            default="Q1,H1,Q3",
            help="Comma-separated report types, e.g. Q1,H1,Q3,FY",
        )
        parser.add_argument(
            "--rebuild-dataset",
            action=argparse.BooleanOptionalAction,
            default=False,
            help="Rebuild dataset before each report_type training",
        )
        parser.add_argument(
            "--keep-separated-artifacts",
            action=argparse.BooleanOptionalAction,
            default=True,
            help="Write per-report-type model/metrics files to avoid overwrite",
        )

    def _resolve_config_path(self, override: str | None) -> Path:
        if override:
            path = Path(override)
            if not path.is_absolute():
                path = Path(settings.BASE_DIR) / path
            return path

        default_path = Path(getattr(settings, "EARNINGS_CONFIG_PATH", str(Path(settings.BASE_DIR) / "configs" / "default.yaml")))
        if not default_path.is_absolute():
            default_path = Path(settings.BASE_DIR) / default_path
        return default_path

    def handle(self, *args, **options):
        config_path = self._resolve_config_path(options.get("config"))
        if not config_path.exists():
            raise CommandError(f"Config not found: {config_path}")

        report_types = [x.strip().upper() for x in str(options.get("report_types") or "").split(",") if x.strip()]
        if not report_types:
            raise CommandError("No report types provided")

        rebuild_dataset = bool(options.get("rebuild_dataset", False))
        keep_separated_artifacts = bool(options.get("keep_separated_artifacts", True))

        self.stdout.write(f"train report types: {report_types}")
        self.stdout.write(f"config: {config_path}")

        summary: dict[str, dict] = {}
        for i, report_type in enumerate(report_types, start=1):
            self.stdout.write(f"[{i}/{len(report_types)}] train report_type={report_type}")

            pipeline = EarningsForecastPipeline(config_path=config_path)
            cfg = copy.deepcopy(pipeline.config or {})
            cfg.setdefault("train", {})["report_type"] = report_type

            if keep_separated_artifacts:
                output_cfg = cfg.setdefault("output", {})
                output_cfg["model_file"] = _suffix_filename(output_cfg.get("model_file", "models.joblib"), report_type)
                output_cfg["metrics_file"] = _suffix_filename(output_cfg.get("metrics_file", "metrics.json"), report_type)

            pipeline.config = cfg
            metrics = pipeline.train(rebuild_dataset=rebuild_dataset)
            summary[report_type] = metrics

            self.stdout.write(
                f"  done: cls_acc={metrics.get('cls_acc')} cls_auc={metrics.get('cls_auc')} reg_mae={metrics.get('reg_mae')}"
            )

        self.stdout.write("train_report_type_models done")
        for rt in report_types:
            m = summary.get(rt) or {}
            self.stdout.write(
                f"- {rt}: train_rows={m.get('train_rows')} test_rows={m.get('test_rows')} cls_auc={m.get('cls_auc')}"
            )
