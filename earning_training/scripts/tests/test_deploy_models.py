from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import joblib
import yaml


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "deploy_models.py"
SPEC = importlib.util.spec_from_file_location("deploy_models", SCRIPT_PATH)
assert SPEC and SPEC.loader
deploy_models = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(deploy_models)


class DeployModelsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.training_root = self.root / "earning_training"
        self.service_root = self.root / "tushare_earnings_service"
        (self.training_root / "configs").mkdir(parents=True)
        (self.service_root / "outputs").mkdir(parents=True)
        dataset_dir = self.service_root / "outputs" / "datasets" / "shared-v1"
        dataset_dir.mkdir(parents=True)
        (dataset_dir / "dataset.parquet").write_bytes(b"test dataset placeholder")
        for report_type in deploy_models.REPORT_TYPE_ORDER:
            version_dir = self.training_root / "outputs" / "model_versions" / f"source_{report_type.lower()}"
            version_dir.mkdir(parents=True)
            run_id = f"run-{report_type.lower()}"
            bundle = {
                "run_id": run_id,
                "classifier": "classifier",
                "regressor": "regressor",
                "feature_cols": ["feature_a"],
                "metrics": {"cls_auc": 0.81, "reg_mae": 1.1},
            }
            joblib.dump(bundle, version_dir / f"models_{report_type}.joblib")
            (version_dir / f"metrics_{report_type}.json").write_text(
                json.dumps({"run_id": run_id, "cls_auc": 0.81, "reg_mae": 1.1}),
                encoding="utf-8",
            )
            (version_dir / "impute_stats.json").write_text(
                json.dumps({"feature_cols": ["feature_a"]}), encoding="utf-8"
            )
        self.config_path = self.training_root / "configs" / "model_deployment.yaml"
        self.config = {
            "schema_version": 2,
            "source": {
                "model_versions_dir": "outputs/model_versions",
                "required_report_types": deploy_models.REPORT_TYPE_ORDER,
                "impute_stats_report_type": "H1",
                "releases": {
                    report_type: f"source_{report_type.lower()}"
                    for report_type in deploy_models.REPORT_TYPE_ORDER
                },
            },
            "target": {
                "project_root": "tushare_earnings_service",
                "outputs_dir": "outputs",
                "release_id": "release-quarterly",
            },
            "activation": {
                "slot": "candidate",
                "dataset": {"version": "shared-v1", "file": "dataset.parquet"},
            },
            "qualification": {
                "defaults": {"minimum": {"cls_auc": 0.8}, "maximum": {"reg_mae": 1.2}}
            },
        }
        self._write_config()

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _write_config(self) -> None:
        self.config_path.write_text(yaml.safe_dump(self.config), encoding="utf-8")

    def test_dry_run_does_not_write_target(self) -> None:
        deploy_models.deploy(self.config_path, dry_run=True, slot=None, release_id=None)
        self.assertFalse((self.service_root / "outputs" / "model_versions").exists())
        self.assertFalse((self.service_root / "outputs" / "serving.yaml").exists())

    def test_apply_and_rollback_restore_candidate(self) -> None:
        serving_path = self.service_root / "outputs" / "serving.yaml"
        serving_path.write_text(
            yaml.safe_dump({"candidate": {"model_version": "previous"}}), encoding="utf-8"
        )
        deploy_models.deploy(self.config_path, dry_run=False, slot=None, release_id=None)
        serving = yaml.safe_load(serving_path.read_text(encoding="utf-8"))
        self.assertEqual(serving["candidate"]["model_version"], "release-quarterly")
        self.assertEqual(serving["candidate"]["report_types"], deploy_models.REPORT_TYPE_ORDER)
        self.assertTrue(
            (self.service_root / "outputs" / "model_versions" / "release-quarterly" / "deployment_manifest.json").is_file()
        )
        release_files = {
            path.name
            for path in (self.service_root / "outputs" / "model_versions" / "release-quarterly").iterdir()
        }
        self.assertTrue({f"models_{item}.joblib" for item in deploy_models.REPORT_TYPE_ORDER} <= release_files)
        history = list((self.service_root / "outputs" / "deployment_history").glob("*.json"))
        self.assertEqual(len(history), 1)
        deploy_models.rollback(self.config_path, history[0].stem, dry_run=False)
        serving = yaml.safe_load(serving_path.read_text(encoding="utf-8"))
        self.assertEqual(serving["candidate"]["model_version"], "previous")

    def test_qualification_failure_blocks_deployment(self) -> None:
        self.config["qualification"]["defaults"]["minimum"]["cls_auc"] = 0.9
        self._write_config()
        with self.assertRaises(deploy_models.DeploymentError):
            deploy_models.deploy(self.config_path, dry_run=False, slot=None, release_id=None)
        self.assertFalse((self.service_root / "outputs" / "model_versions").exists())

    def test_production_requires_explicit_confirmation(self) -> None:
        self.config["activation"]["slot"] = "production"
        self._write_config()
        with self.assertRaises(deploy_models.DeploymentError):
            deploy_models.deploy(self.config_path, dry_run=False, slot=None, release_id=None)

    def test_missing_report_type_blocks_deployment(self) -> None:
        self.config["source"]["releases"].pop("FY")
        self._write_config()
        with self.assertRaises(deploy_models.DeploymentError):
            deploy_models.deploy(self.config_path, dry_run=False, slot=None, release_id=None)
        self.assertFalse((self.service_root / "outputs" / "model_versions").exists())

    def test_mismatched_feature_columns_block_deployment(self) -> None:
        model_path = self.training_root / "outputs" / "model_versions" / "source_fy" / "models_FY.joblib"
        bundle = joblib.load(model_path)
        bundle["feature_cols"] = ["different_feature"]
        joblib.dump(bundle, model_path)
        with self.assertRaises(deploy_models.DeploymentError):
            deploy_models.deploy(self.config_path, dry_run=False, slot=None, release_id=None)


if __name__ == "__main__":
    unittest.main()