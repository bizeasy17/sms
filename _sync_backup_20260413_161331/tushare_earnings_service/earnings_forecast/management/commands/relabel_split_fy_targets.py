from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from earnings_forecast.services import EarningsForecastPipeline


def _resolve_config_path(override: str | None) -> Path:
    if override:
        path = Path(override)
        if not path.is_absolute():
            path = Path(settings.BASE_DIR) / path
        return path

    default_path = Path(getattr(settings, "EARNINGS_CONFIG_PATH", str(Path(settings.BASE_DIR) / "configs" / "default.yaml")))
    if not default_path.is_absolute():
        default_path = Path(settings.BASE_DIR) / default_path
    return default_path


def _parse_report_types(raw: str) -> list[str]:
    items = [x.strip().upper() for x in str(raw or "").split(",") if x.strip()]
    return items or ["Q1", "H1", "Q3"]


class Command(BaseCommand):
    help = "Relabel split datasets in-place without rebuilding full features. Q1/H1 use t, Q3/FY use t+1."

    def add_arguments(self, parser):
        parser.add_argument("--config", type=str, help="Path to pipeline yaml config")
        parser.add_argument(
            "--report-types",
            type=str,
            default="Q1,H1,Q3",
            help="Comma-separated split datasets to relabel in-place, e.g. Q1,H1,Q3 or Q1,H1,Q3,FY",
        )

    def _build_label_map(self, fy_df: pd.DataFrame, fy_value_col: str, base_abs_min: float, clip_min: float | None, clip_max: float | None) -> pd.DataFrame:
        required = {"ts_code", "fiscal_year", fy_value_col}
        if not required.issubset(set(fy_df.columns)):
            missing = sorted(required - set(fy_df.columns))
            raise CommandError(f"FY split dataset missing required columns: {missing}")

        work_cols = [c for c in ["ts_code", "fiscal_year", "trade_date", fy_value_col] if c in fy_df.columns]
        fy_rows = fy_df[work_cols].copy()
        fy_rows["ts_code"] = fy_rows["ts_code"].astype(str)
        fy_rows["fiscal_year"] = pd.to_numeric(fy_rows["fiscal_year"], errors="coerce")
        fy_rows = fy_rows.dropna(subset=["fiscal_year"])
        if fy_rows.empty:
            raise CommandError("FY split dataset has no usable fiscal_year rows")

        if "trade_date" in fy_rows.columns:
            fy_rows["trade_date"] = pd.to_datetime(fy_rows["trade_date"], errors="coerce")
            fy_rows = fy_rows.sort_values(["ts_code", "fiscal_year", "trade_date"])
        else:
            fy_rows = fy_rows.sort_values(["ts_code", "fiscal_year"])

        fy_rows = fy_rows.drop_duplicates(["ts_code", "fiscal_year"], keep="last")
        fy_rows["_fy_value"] = pd.to_numeric(fy_rows[fy_value_col], errors="coerce")
        fy_rows["target_fy_value_t"] = fy_rows["_fy_value"]
        fy_rows["target_fy_value_yoy_t"] = fy_rows.groupby("ts_code")["_fy_value"].transform(
            lambda s: EarningsForecastPipeline._build_fy_yoy(
                s,
                base_abs_min=base_abs_min,
                clip_min=clip_min,
                clip_max=clip_max,
            )
        )
        fy_rows["target_fy_up_t"] = np.where(
            fy_rows["target_fy_value_yoy_t"].notna(),
            (fy_rows["target_fy_value_yoy_t"] > 0).astype(float),
            np.nan,
        )
        fy_rows["target_fy_value_t1"] = fy_rows.groupby("ts_code")["_fy_value"].transform(lambda s: s.shift(-1))
        fy_rows["target_fy_value_yoy_t1"] = fy_rows.groupby("ts_code")["target_fy_value_yoy_t"].transform(lambda s: s.shift(-1))
        fy_rows["target_fy_up_t1"] = np.where(
            fy_rows["target_fy_value_yoy_t1"].notna(),
            (fy_rows["target_fy_value_yoy_t1"] > 0).astype(float),
            np.nan,
        )
        return fy_rows[
            [
                "ts_code",
                "fiscal_year",
                "target_fy_value_t",
                "target_fy_value_yoy_t",
                "target_fy_up_t",
                "target_fy_value_t1",
                "target_fy_value_yoy_t1",
                "target_fy_up_t1",
            ]
        ].copy()

    def handle(self, *args, **options):
        config_path = _resolve_config_path(options.get("config"))
        if not config_path.exists():
            raise CommandError(f"Config not found: {config_path}")

        pipeline = EarningsForecastPipeline(config_path=config_path)
        output_cfg = pipeline.config.get("output", {})
        label_cfg = pipeline.config.get("label", {})
        dataset_out_dir = pipeline._dataset_output_dir()

        dataset_file = str(output_cfg.get("dataset_file", "dataset.parquet"))
        stem = Path(dataset_file).stem
        suffix = Path(dataset_file).suffix or ".parquet"
        split_dir = dataset_out_dir / str(output_cfg.get("split_dataset_dir", "datasets_by_report_type"))
        if not split_dir.exists():
            raise CommandError(f"Split dataset dir not found: {split_dir}")

        fy_path = split_dir / f"{stem}_FY{suffix}"
        if not fy_path.exists():
            raise CommandError(f"FY split dataset not found: {fy_path}")

        fy_value_col = str(label_cfg.get("fy_value_col", "n_income"))
        fy_cfg = label_cfg.get("fy_yoy") or {}
        base_abs_min = float(fy_cfg.get("base_abs_min", 1e6))
        clip_min_raw = fy_cfg.get("clip_min", -20.0)
        clip_max_raw = fy_cfg.get("clip_max", 20.0)
        clip_min = None if clip_min_raw is None else float(clip_min_raw)
        clip_max = None if clip_max_raw is None else float(clip_max_raw)

        self.stdout.write(f"load FY split dataset: {fy_path}")
        fy_df = pd.read_parquet(fy_path)
        label_map = self._build_label_map(
            fy_df=fy_df,
            fy_value_col=fy_value_col,
            base_abs_min=base_abs_min,
            clip_min=clip_min,
            clip_max=clip_max,
        )
        label_idx = label_map.set_index(["ts_code", "fiscal_year"])

        report_types = _parse_report_types(options.get("report_types"))
        for report_type in report_types:
            part_path = split_dir / f"{stem}_{report_type}{suffix}"
            if not part_path.exists():
                raise CommandError(f"Split dataset not found for {report_type}: {part_path}")

            self.stdout.write(f"relabel split dataset: {report_type} -> {part_path}")
            df = pd.read_parquet(part_path)
            if not {"ts_code", "fiscal_year"}.issubset(set(df.columns)):
                raise CommandError(f"Split dataset missing ts_code/fiscal_year columns: {part_path}")

            df["ts_code"] = df["ts_code"].astype(str)
            df["fiscal_year"] = pd.to_numeric(df["fiscal_year"], errors="coerce")

            key_index = pd.MultiIndex.from_arrays(
                [df["ts_code"], df["fiscal_year"]],
                names=["ts_code", "fiscal_year"],
            )
            aligned = label_idx.reindex(key_index)

            use_t1 = report_type in {"Q3", "FY"}
            suffix_key = "t1" if use_t1 else "t"
            df["target_fy_value"] = aligned[f"target_fy_value_{suffix_key}"].to_numpy()
            df["target_fy_value_yoy"] = aligned[f"target_fy_value_yoy_{suffix_key}"].to_numpy()
            df["target_fy_up"] = aligned[f"target_fy_up_{suffix_key}"].to_numpy()

            df.to_parquet(part_path, index=False)
            self.stdout.write(
                f"  done: rows={len(df)} fy_yoy_nonnull={int(df['target_fy_value_yoy'].notna().sum())} "
                f"fy_up_nonnull={int(df['target_fy_up'].notna().sum())} mode={suffix_key}"
            )

        self.stdout.write(f"relabel_split_fy_targets done: report_types={report_types}")