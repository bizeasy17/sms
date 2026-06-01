from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Compare historical experiment runs from outputs/experiment_runs.jsonl"

    def add_arguments(self, parser):
        parser.add_argument("--history-file", type=str, help="Path to experiment_runs.jsonl")
        parser.add_argument("--top", type=int, default=20, help="Top rows to display")
        parser.add_argument("--sort-by", type=str, default="cls_auc", help="Metric to sort by")
        parser.add_argument("--ascending", action="store_true", default=False, help="Sort ascending")
        parser.add_argument("--output-csv", type=str, help="Optional csv output path")

    def handle(self, *args, **options):
        history_file = options.get("history_file")
        if history_file:
            path = Path(history_file)
            if not path.is_absolute():
                path = Path(settings.BASE_DIR) / path
        else:
            path = Path(settings.BASE_DIR) / "outputs" / "experiment_runs.jsonl"

        if not path.exists():
            raise CommandError(f"history file not found: {path}")

        rows: list[dict] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            text = line.strip()
            if not text:
                continue
            try:
                item = json.loads(text)
            except json.JSONDecodeError:
                continue

            metrics = item.get("metrics") or {}
            rows.append(
                {
                    "run_id": item.get("run_id"),
                    "created_at_utc": item.get("created_at_utc"),
                    "classifier_algo": item.get("classifier_algo") or metrics.get("classifier_algo"),
                    "regressor_algo": item.get("regressor_algo") or metrics.get("regressor_algo"),
                    "cls_auc": metrics.get("cls_auc"),
                    "cls_acc": metrics.get("cls_acc"),
                    "reg_mae": metrics.get("reg_mae"),
                    "industry_model_count": metrics.get("industry_model_count"),
                    "train_rows": metrics.get("train_rows"),
                    "test_rows": metrics.get("test_rows"),
                }
            )

        if not rows:
            raise CommandError(f"no valid experiment records in: {path}")

        df = pd.DataFrame(rows)
        sort_by = str(options.get("sort_by") or "cls_auc")
        if sort_by not in df.columns:
            raise CommandError(f"sort-by not found: {sort_by}, available: {', '.join(df.columns)}")

        ascending = bool(options.get("ascending", False))
        df = df.sort_values(sort_by, ascending=ascending, na_position="last")

        top = max(1, int(options.get("top") or 20))
        top_df = df.head(top)

        self.stdout.write(f"experiment runs: total={len(df)}, showing_top={len(top_df)}")
        self.stdout.write(top_df.to_string(index=False))

        output_csv = options.get("output_csv")
        if output_csv:
            out = Path(output_csv)
            if not out.is_absolute():
                out = Path(settings.BASE_DIR) / out
            out.parent.mkdir(parents=True, exist_ok=True)
            top_df.to_csv(out, index=False, encoding="utf-8-sig")
            self.stdout.write(f"csv exported: {out}")
