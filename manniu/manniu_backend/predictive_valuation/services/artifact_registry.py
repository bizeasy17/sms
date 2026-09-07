from __future__ import annotations

import hashlib
import importlib.metadata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib
import yaml
from django.conf import settings


class ArtifactValidationError(ValueError):
    """Raised when a configured serving artifact cannot safely be used."""


@dataclass(frozen=True)
class ServingArtifact:
    model_version: str
    report_type: str
    model_path: Path
    artifact_hash: str
    feature_columns: tuple[str, ...]


class PredictiveArtifactRegistry:
    def __init__(self, model_root: Path | None = None):
        configured_root = model_root or self._resolve_path(settings.PREDICTIVE_VALUATION_MODEL_ROOT)
        self.model_root = configured_root.resolve()

    def load_production(self) -> ServingArtifact:
        pointer = self.model_root / 'serving.yaml'
        if not pointer.is_file():
            raise ArtifactValidationError(f'Serving pointer not found: {pointer}')
        payload = self._read_yaml(pointer)
        production = payload.get('production')
        if not isinstance(production, dict):
            raise ArtifactValidationError('Serving pointer requires a production entry')
        return self._load_entry(production)

    def _load_entry(self, entry: dict[str, Any]) -> ServingArtifact:
        model_version = str(entry.get('model_version') or '').strip()
        model_path_value = str(entry.get('model_path') or '').strip()
        if not model_version or not model_path_value:
            raise ArtifactValidationError('Production entry requires model_version and model_path')
        model_path = self._safe_artifact_path(model_path_value)
        if not model_path.is_file():
            raise ArtifactValidationError(f'Model bundle not found: {model_path}')

        required_sklearn_version = str(entry.get('sklearn_version') or '').strip()
        installed_sklearn_version = importlib.metadata.version('scikit-learn')
        if required_sklearn_version and required_sklearn_version != installed_sklearn_version:
            raise ArtifactValidationError(
                f'Model requires scikit-learn {required_sklearn_version}, installed {installed_sklearn_version}'
            )
        bundle = joblib.load(model_path)
        if not isinstance(bundle, dict):
            raise ArtifactValidationError('Model bundle must be a dictionary')
        feature_columns = bundle.get('feature_cols')
        if not isinstance(feature_columns, list) or not feature_columns:
            raise ArtifactValidationError('Model bundle requires non-empty feature_cols')
        if 'classifier' not in bundle or 'regressor' not in bundle:
            raise ArtifactValidationError('Model bundle requires classifier and regressor')
        return ServingArtifact(
            model_version=model_version,
            report_type=str(entry.get('report_type') or 'UNKNOWN').strip().upper(),
            model_path=model_path,
            artifact_hash=self._sha256(model_path),
            feature_columns=tuple(str(column) for column in feature_columns),
        )

    def _safe_artifact_path(self, raw_path: str) -> Path:
        candidate = Path(raw_path)
        candidate = candidate if candidate.is_absolute() else self.model_root / candidate
        resolved = candidate.resolve()
        try:
            resolved.relative_to(self.model_root)
        except ValueError as exc:
            raise ArtifactValidationError('Model path must remain inside PREDICTIVE_VALUATION_MODEL_ROOT') from exc
        return resolved

    @staticmethod
    def _resolve_path(value: str) -> Path:
        path = Path(value)
        return path if path.is_absolute() else settings.BASE_DIR / path

    @staticmethod
    def _read_yaml(path: Path) -> dict[str, Any]:
        try:
            payload = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
        except yaml.YAMLError as exc:
            raise ArtifactValidationError(f'Invalid serving pointer: {exc}') from exc
        if not isinstance(payload, dict):
            raise ArtifactValidationError('Serving pointer must be a mapping')
        return payload

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open('rb') as artifact:
            for chunk in iter(lambda: artifact.read(1024 * 1024), b''):
                digest.update(chunk)
        return digest.hexdigest()