from __future__ import annotations

import argparse
import copy
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[2]
REPLAY_SCRIPT = PROJECT_ROOT / "scripts" / "q1h1_variant_replay_eval.py"
ANALYZE_SCRIPT = PROJECT_ROOT / "scripts" / "opt" / "analyze_opt_results.py"


def parse_scalar(value: str) -> Any:
    return yaml.safe_load(value)


def set_nested(config: dict[str, Any], dotted_path: str, value: Any) -> None:
    keys = dotted_path.split(".")
    current = config
    for key in keys[:-1]:
        child = current.get(key)
        if not isinstance(child, dict):
            child = {}
            current[key] = child
        current = child
    current[keys[-1]] = value


def anchor_output_dir(config: dict[str, Any]) -> None:
    output = config.setdefault("output", {})
    out_dir = Path(output.get("dir", "outputs"))
    if not out_dir.is_absolute():
        output["dir"] = str((PROJECT_ROOT / out_dir).resolve())


def safe_value(value: Any) -> str:
    return str(value).replace(".", "p").replace("-", "m").replace(" ", "_")


def parse_override(value: str) -> tuple[str, Any]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("fixed override must be dotted.path=value")
    path, raw_value = value.split("=", 1)
    return path, parse_scalar(raw_value)


def run(command: list[str], dry_run: bool) -> None:
    print("RUN:", subprocess.list2cmdline(command))
    if dry_run:
        return
    subprocess.run(command, cwd=PROJECT_ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Train and replay a one-parameter earnings-model sweep.")
    parser.add_argument("--report-type", required=True, choices=["Q1", "H1", "Q3", "FY"])
    parser.add_argument("--base-config", required=True)
    parser.add_argument("--baseline-model", required=True)
    parser.add_argument("--baseline-config")
    parser.add_argument("--parameter", required=True, help="Dotted YAML path, for example label.cls_gray_zone.abs_min")
    parser.add_argument("--values", nargs="+", required=True)
    parser.add_argument("--top-pct", type=float, required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument(
        "--set",
        action="append",
        type=parse_override,
        default=[],
        dest="fixed_overrides",
        help="Fixed YAML override applied to baseline replay and every candidate, dotted.path=value",
    )
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--run-tag", default=datetime.now().strftime("%Y%m%d_%H%M%S"))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    base_config_path = (PROJECT_ROOT / args.base_config).resolve()
    baseline_config_path = (PROJECT_ROOT / (args.baseline_config or args.base_config)).resolve()
    base_config = yaml.safe_load(base_config_path.read_text(encoding="utf-8")) or {}
    baseline_config = yaml.safe_load(baseline_config_path.read_text(encoding="utf-8")) or {}
    for override_path, override_value in args.fixed_overrides:
        set_nested(base_config, override_path, override_value)
        set_nested(baseline_config, override_path, override_value)
    anchor_output_dir(base_config)
    anchor_output_dir(baseline_config)

    run_name = f"{args.run_tag}_{args.name}_{args.report_type.lower()}"
    run_dir = PROJECT_ROOT / "outputs" / "experiments" / "opt" / run_name
    config_dir = run_dir / "configs"
    result_dir = run_dir / "results"
    config_dir.mkdir(parents=True, exist_ok=True)
    result_dir.mkdir(parents=True, exist_ok=True)

    baseline_replay_config_path = config_dir / "_baseline_replay.yaml"
    baseline_replay_config_path.write_text(
        yaml.safe_dump(baseline_config, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )

    variants = [
        (
            "baseline",
            args.baseline_model,
            baseline_replay_config_path,
        )
    ]

    for raw_value in args.values:
        value = parse_scalar(raw_value)
        candidate = copy.deepcopy(base_config)
        set_nested(candidate, args.parameter, value)

        variant_name = f"{args.parameter.split('.')[-1]}_{safe_value(value)}"
        model_version = f"opt_{run_name}_{variant_name}"
        candidate.setdefault("train", {})["model_version"] = model_version
        candidate["train"]["promote_to_production"] = False

        config_path = config_dir / f"{variant_name}.yaml"
        config_path.write_text(
            yaml.safe_dump(candidate, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        variants.append((variant_name, model_version, config_path))

        train_command = [
            args.python,
            str(PROJECT_ROOT / "manage.py"),
            "train_report_type_models",
            "--config",
            str(config_path),
            "--report-types",
            args.report_type,
            "--no-rebuild-dataset",
            "--keep-separated-artifacts",
        ]
        run(train_command, args.dry_run)

    replay_path = result_dir / "replay.json"
    replay_command = [
        args.python,
        str(REPLAY_SCRIPT),
        "--report-type",
        args.report_type,
        "--top-pct",
        str(args.top_pct),
        "--out",
        str(replay_path.relative_to(PROJECT_ROOT)),
    ]
    for variant_name, model_version, config_path in variants:
        relative_config = config_path.relative_to(PROJECT_ROOT)
        replay_command.extend(
            ["--variant", f"{variant_name}={model_version}={relative_config.as_posix()}"]
        )
    run(replay_command, args.dry_run)

    analyze_command = [
        args.python,
        str(ANALYZE_SCRIPT),
        "--input",
        str(replay_path),
        "--parameter",
        args.parameter,
        "--output-dir",
        str(result_dir),
    ]
    run(analyze_command, args.dry_run)

    manifest = {
        "run_name": run_name,
        "report_type": args.report_type,
        "parameter": args.parameter,
        "values": [parse_scalar(value) for value in args.values],
        "top_pct": args.top_pct,
        "base_config": str(base_config_path),
        "baseline_model": args.baseline_model,
        "baseline_config": str(baseline_config_path),
        "fixed_overrides": dict(args.fixed_overrides),
        "dry_run": args.dry_run,
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"output: {run_dir}")


if __name__ == "__main__":
    main()
