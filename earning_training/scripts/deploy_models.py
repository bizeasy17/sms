from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import os
import re
import shutil
import sys
import tempfile
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import joblib
import yaml


REPORT_TYPES = {"Q1", "H1", "Q3", "FY"}
REPORT_TYPE_ORDER = ["Q1", "H1", "Q3", "FY"]
SLOTS = {"candidate", "production"}
RELEASE_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class DeploymentError(RuntimeError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _load_yaml(path: Path) -> dict[str, Any]:
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise DeploymentError(f"Cannot read YAML {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise DeploymentError(f"YAML root must be a mapping: {path}")
    return payload


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    os.replace(temporary, path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve_inside(root: Path, value: str | Path, label: str) -> Path:
    root = root.resolve()
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise DeploymentError(f"{label} escapes allowed root {root}: {resolved}") from exc
    return resolved


def _safe_release_id(value: str) -> str:
    release_id = str(value or "").strip()
    if not RELEASE_ID_PATTERN.fullmatch(release_id):
        raise DeploymentError("release_id must use only letters, digits, dot, underscore, or hyphen")
    return release_id


def _metric_value(metrics: dict[str, Any], name: str) -> float:
    value = metrics.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DeploymentError(f"Metric {name!r} is missing or non-numeric")
    return float(value)


def _check_qualification(
    report_type: str,
    metrics: dict[str, Any],
    rules: dict[str, Any],
    source_root: Path,
) -> list[str]:
    checks: list[str] = []
    for metric, minimum in (rules.get("minimum") or {}).items():
        actual = _metric_value(metrics, str(metric))
        if actual < float(minimum):
            raise DeploymentError(f"{report_type} {metric}={actual} is below minimum {minimum}")
        checks.append(f"{metric}>={minimum}")
    for metric, maximum in (rules.get("maximum") or {}).items():
        actual = _metric_value(metrics, str(metric))
        if actual > float(maximum):
            raise DeploymentError(f"{report_type} {metric}={actual} exceeds maximum {maximum}")
        checks.append(f"{metric}<={maximum}")

    baseline_value = str(rules.get("baseline_metrics") or "").strip()
    deltas = rules.get("minimum_delta") or {}
    max_regression = rules.get("maximum_regression") or {}
    if deltas or max_regression:
        if not baseline_value:
            raise DeploymentError(f"{report_type} baseline_metrics is required for relative checks")
        baseline_path = _resolve_inside(source_root, baseline_value, "baseline_metrics")
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        for metric, minimum_delta in deltas.items():
            delta = _metric_value(metrics, str(metric)) - _metric_value(baseline, str(metric))
            if delta < float(minimum_delta):
                raise DeploymentError(
                    f"{report_type} {metric} delta={delta:.6g} is below {minimum_delta}"
                )
            checks.append(f"delta({metric})>={minimum_delta}")
        for metric, maximum_increase in max_regression.items():
            increase = _metric_value(metrics, str(metric)) - _metric_value(baseline, str(metric))
            if increase > float(maximum_increase):
                raise DeploymentError(
                    f"{report_type} {metric} regression={increase:.6g} exceeds {maximum_increase}"
                )
            checks.append(f"regression({metric})<={maximum_increase}")
    return checks


def _merge_qualification_rules(defaults: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = dict(defaults)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = {**merged[key], **value}
        else:
            merged[key] = value
    return merged


def _verify_bundle(path: Path, required_keys: list[str]) -> dict[str, Any]:
    try:
        bundle = joblib.load(path)
    except Exception as exc:
        raise DeploymentError(f"Cannot load model bundle {path}: {exc}") from exc
    if not isinstance(bundle, dict):
        raise DeploymentError(f"Model bundle must be a mapping: {path}")
    missing = [key for key in required_keys if key not in bundle]
    if missing:
        raise DeploymentError(f"Model bundle {path.name} misses keys: {', '.join(missing)}")
    feature_cols = bundle.get("feature_cols")
    if not isinstance(feature_cols, list) or not feature_cols:
        raise DeploymentError(f"Model bundle {path.name} has no feature_cols")
    return bundle


@contextmanager
def _deployment_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise DeploymentError(f"Another deployment may be running; lock exists: {path}") from exc
    try:
        os.write(descriptor, f"pid={os.getpid()} created={_utc_now()}\n".encode("ascii"))
        os.close(descriptor)
        yield
    finally:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _runtime_versions() -> dict[str, str]:
    versions = {"python": ".".join(map(str, sys.version_info[:3]))}
    for package in ("joblib", "numpy", "scikit-learn"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "missing"
    return versions


def _check_runtime_constraints(safety_cfg: dict[str, Any]) -> dict[str, str]:
    versions = _runtime_versions()
    for package, expected_prefix in (safety_cfg.get("runtime_version_prefixes") or {}).items():
        actual = versions.get(str(package))
        if actual is None:
            raise DeploymentError(f"Unsupported runtime package constraint: {package}")
        if not actual.startswith(str(expected_prefix)):
            raise DeploymentError(
                f"Runtime {package}={actual} does not match required prefix {expected_prefix}"
            )
    return versions


def _build_plan(config_path: Path, slot_override: str | None, release_override: str | None) -> dict[str, Any]:
    config = _load_yaml(config_path)
    if config.get("schema_version") != 2:
        raise DeploymentError("Only deployment config schema_version 2 is supported")

    training_root = config_path.resolve().parents[1]
    source_cfg = config.get("source") or {}
    target_cfg = config.get("target") or {}
    activation_cfg = config.get("activation") or {}
    safety_cfg = config.get("safety") or {}
    runtime = _check_runtime_constraints(safety_cfg)
    source_root = _resolve_inside(training_root, source_cfg.get("model_versions_dir", "outputs/model_versions"), "source root")
    target_project = _resolve_inside(training_root.parent, target_cfg.get("project_root", "tushare_earnings_service"), "target project")
    target_outputs = _resolve_inside(target_project, target_cfg.get("outputs_dir", "outputs"), "target outputs")
    release_id = _safe_release_id(release_override or target_cfg.get("release_id"))
    slot = str(slot_override or activation_cfg.get("slot", "candidate")).lower()
    if slot not in SLOTS:
        raise DeploymentError(f"Unsupported slot: {slot}")

    releases = source_cfg.get("releases") or {}
    required_report_types = [str(item).upper() for item in source_cfg.get("required_report_types", REPORT_TYPE_ORDER)]
    if required_report_types != REPORT_TYPE_ORDER or set(releases) != REPORT_TYPES:
        raise DeploymentError("A release must contain exactly Q1, H1, Q3, and FY in that order")
    missing_configs = [item for item in required_report_types if not releases.get(item)]
    if missing_configs:
        raise DeploymentError(f"Missing source release configuration for: {', '.join(missing_configs)}")

    artifacts: list[dict[str, Any]] = []
    qualification_cfg = config.get("qualification") or {}
    per_report = qualification_cfg.get("per_report_type") or {}
    default_rules = qualification_cfg.get("defaults") or {}
    required_keys = list(safety_cfg.get("required_bundle_keys") or ["run_id", "classifier", "regressor", "feature_cols", "metrics"])
    feature_cols_by_report: dict[str, list[str]] = {}
    impute_stats_by_report: dict[str, Path] = {}
    for report_type in required_report_types:
        source_dir = _resolve_inside(source_root, str(releases[report_type]), f"{report_type} source release")
        model_path = source_dir / f"models_{report_type}.joblib"
        metrics_path = source_dir / f"metrics_{report_type}.json"
        if not model_path.is_file() or not metrics_path.is_file():
            raise DeploymentError(f"{report_type} source release lacks model or metrics: {source_dir}")
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        if not isinstance(metrics, dict):
            raise DeploymentError(f"Metrics root must be a mapping: {metrics_path}")
        bundle = _verify_bundle(model_path, required_keys)
        if str(bundle.get("run_id") or "") != str(metrics.get("run_id") or ""):
            raise DeploymentError(f"{report_type} model and metrics run_id do not match")
        feature_cols_by_report[report_type] = list(bundle["feature_cols"])
        rules = _merge_qualification_rules(default_rules, per_report.get(report_type) or {})
        checks = _check_qualification(report_type, metrics, rules, training_root)
        model_artifact = {
            "source": model_path,
            "source_release": str(releases[report_type]),
            "name": model_path.name,
            "sha256": _sha256(model_path),
            "report_type": report_type,
            "run_id": metrics.get("run_id"),
            "checks": checks,
        }
        artifacts.extend(
            [
                model_artifact,
                {"source": metrics_path, "name": metrics_path.name, "sha256": _sha256(metrics_path)},
            ]
        )
        impute_path = source_dir / "impute_stats.json"
        if impute_path.is_file():
            impute_stats_by_report[report_type] = impute_path

    reference_report = required_report_types[0]
    mismatched = [
        report_type
        for report_type in required_report_types[1:]
        if feature_cols_by_report[report_type] != feature_cols_by_report[reference_report]
    ]
    if mismatched:
        raise DeploymentError(
            "Prediction service shares one impute cache per release; feature_cols differ for: "
            + ", ".join([reference_report, *mismatched])
        )
    impute_report_type = str(source_cfg.get("impute_stats_report_type") or "").upper()
    if impute_report_type not in required_report_types:
        raise DeploymentError("impute_stats_report_type must explicitly select Q1, H1, Q3, or FY")
    selected_impute = impute_stats_by_report.get(impute_report_type)
    if selected_impute is None:
        raise DeploymentError(f"{impute_report_type} source release lacks impute_stats.json")
    artifacts.append({"source": selected_impute, "name": "impute_stats.json", "sha256": _sha256(selected_impute)})
    final_dir = target_outputs / "model_versions" / release_id
    if final_dir.exists():
        raise DeploymentError(f"Immutable target release already exists: {final_dir}")
    return {
        "config": config,
        "training_root": training_root,
        "target_project": target_project,
        "target_outputs": target_outputs,
        "release_id": release_id,
        "slot": slot,
        "report_types": required_report_types,
        "artifacts": artifacts,
        "runtime": runtime,
        "final_dir": final_dir,
    }


def _serving_entry(plan: dict[str, Any], deployed_at: str) -> dict[str, Any]:
    model_artifact = next(item for item in plan["artifacts"] if item["name"].startswith("models_"))
    report_type = model_artifact["report_type"]
    final_dir: Path = plan["final_dir"]
    entry = {
        "run_id": f"deploy_{plan['release_id']}",
        "model_version": plan["release_id"],
        "model_name": "earnings_forecast",
        "report_type": report_type if len(plan["report_types"]) == 1 else "MULTI",
        "model_path": str((final_dir / model_artifact["name"]).resolve()),
        "metrics_path": str((final_dir / f"metrics_{report_type}.json").resolve()),
        "deployed_at_utc": deployed_at,
    }
    serving_path = plan["target_outputs"] / "serving.yaml"
    current = _load_yaml(serving_path) if serving_path.exists() else {}
    old_entry = current.get(plan["slot"])
    dataset_cfg = (plan["config"].get("activation") or {}).get("dataset") or {}
    dataset_version = str(dataset_cfg.get("version") or "").strip()
    if not dataset_version:
        raise DeploymentError("activation.dataset.version is required for a complete quarterly release")
    dataset_file = str(dataset_cfg.get("file", "dataset.parquet"))
    dataset_path = _resolve_inside(plan["target_outputs"] / "datasets", Path(dataset_version) / dataset_file, "target dataset")
    if not dataset_path.is_file():
        raise DeploymentError(f"Configured target dataset does not exist: {dataset_path}")
    entry.update({"dataset_version": dataset_version, "dataset_path": str(dataset_path)})
    entry["report_types"] = REPORT_TYPE_ORDER
    return entry


def deploy(
    config_path: Path,
    dry_run: bool,
    slot: str | None,
    release_id: str | None,
    production_confirmed: bool = False,
) -> None:
    plan = _build_plan(config_path, slot, release_id)
    if plan["slot"] == "production" and not dry_run and not production_confirmed:
        raise DeploymentError("Production deployment requires explicit --slot production --apply")
    deployed_at = _utc_now()
    entry = _serving_entry(plan, deployed_at)
    print(f"release={plan['release_id']} slot={plan['slot']} reports={','.join(plan['report_types'])}")
    for artifact in plan["artifacts"]:
        print(f"  {artifact['name']} sha256={artifact['sha256'][:12]} source={artifact['source']}")
    if dry_run:
        print("DRY RUN: qualification and bundle validation passed; no files changed")
        return

    outputs: Path = plan["target_outputs"]
    with _deployment_lock(outputs / ".model-deploy.lock"):
        staging = outputs / ".deploy-staging" / f"{plan['release_id']}.{uuid.uuid4().hex}"
        staging.mkdir(parents=True)
        try:
            for artifact in plan["artifacts"]:
                destination = staging / artifact["name"]
                shutil.copy2(artifact["source"], destination)
                if _sha256(destination) != artifact["sha256"]:
                    raise DeploymentError(f"Checksum mismatch after copy: {destination}")
            for model_path in staging.glob("models_*.joblib"):
                _verify_bundle(model_path, list((plan["config"].get("safety") or {}).get("required_bundle_keys") or ["run_id", "classifier", "regressor", "feature_cols", "metrics"]))
            expected_names = {
                *(f"models_{report_type}.joblib" for report_type in REPORT_TYPE_ORDER),
                *(f"metrics_{report_type}.json" for report_type in REPORT_TYPE_ORDER),
                "impute_stats.json",
            }
            staged_names = {path.name for path in staging.iterdir()}
            if staged_names != expected_names:
                raise DeploymentError(f"Staging release is incomplete: expected {sorted(expected_names)}")

            serving_path = outputs / "serving.yaml"
            before = _load_yaml(serving_path) if serving_path.exists() else {}
            deployment_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
            manifest = {
                "schema_version": 1,
                "deployment_id": deployment_id,
                "deployed_at_utc": deployed_at,
                "release_id": plan["release_id"],
                "slot": plan["slot"],
                "report_types": plan["report_types"],
                "runtime": plan["runtime"],
                "previous_slot": before.get(plan["slot"]),
                "artifacts": [
                    {key: value for key, value in item.items() if key != "source"} | {"source": str(item["source"])}
                    for item in plan["artifacts"]
                ],
            }
            _atomic_write(staging / "deployment_manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            plan["final_dir"].parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging, plan["final_dir"])

            history_dir = outputs / "deployment_history"
            history_dir.mkdir(parents=True, exist_ok=True)
            _atomic_write(history_dir / f"{deployment_id}.json", json.dumps(manifest, ensure_ascii=False, indent=2))
            after = dict(before)
            after["updated_at_utc"] = deployed_at
            after[plan["slot"]] = entry
            _atomic_write(serving_path, yaml.safe_dump(after, allow_unicode=True, sort_keys=False))
            print(f"DEPLOYED deployment_id={deployment_id} target={plan['final_dir']}")
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise


def rollback(config_path: Path, deployment_id: str, dry_run: bool) -> None:
    config = _load_yaml(config_path)
    training_root = config_path.resolve().parents[1]
    target_project = _resolve_inside(training_root.parent, (config.get("target") or {}).get("project_root", "tushare_earnings_service"), "target project")
    outputs = _resolve_inside(target_project, (config.get("target") or {}).get("outputs_dir", "outputs"), "target outputs")
    history_path = _resolve_inside(outputs / "deployment_history", f"{_safe_release_id(deployment_id)}.json", "deployment history")
    manifest = json.loads(history_path.read_text(encoding="utf-8"))
    slot = str(manifest.get("slot") or "")
    if slot not in SLOTS:
        raise DeploymentError(f"Invalid slot in deployment history: {slot}")
    previous = manifest.get("previous_slot")
    if not isinstance(previous, dict):
        raise DeploymentError(f"Deployment {deployment_id} has no previous slot to restore")
    print(f"rollback deployment={deployment_id} slot={slot} previous={previous.get('model_version')}")
    if dry_run:
        print("DRY RUN: rollback validated; no files changed")
        return
    with _deployment_lock(outputs / ".model-deploy.lock"):
        serving_path = outputs / "serving.yaml"
        serving = _load_yaml(serving_path)
        serving["updated_at_utc"] = _utc_now()
        serving[slot] = previous
        _atomic_write(serving_path, yaml.safe_dump(serving, allow_unicode=True, sort_keys=False))
        print(f"ROLLED BACK slot={slot} model_version={previous.get('model_version')}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Safely deploy trained earnings models to the prediction service")
    parser.add_argument("--config", default="configs/model_deployment.yaml", type=Path)
    parser.add_argument("--apply", action="store_true", help="Write files; default is dry-run")
    parser.add_argument("--slot", choices=sorted(SLOTS), help="Override activation slot")
    parser.add_argument("--release-id", help="Override target release ID")
    parser.add_argument("--rollback", metavar="DEPLOYMENT_ID", help="Restore the slot saved by a deployment")
    args = parser.parse_args()
    config_path = args.config.resolve()
    try:
        if args.slot == "production" and not args.apply:
            print("Production selection is being validated in dry-run mode")
        if args.rollback:
            rollback(config_path, args.rollback, dry_run=not args.apply)
        else:
            deploy(
                config_path,
                dry_run=not args.apply,
                slot=args.slot,
                release_id=args.release_id,
                production_confirmed=args.slot == "production" and args.apply,
            )
    except (DeploymentError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())