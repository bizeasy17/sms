from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
import yaml
from sklearn.inspection import permutation_importance

from .artifact_registry import ArtifactValidationError, PredictiveArtifactRegistry

logger = logging.getLogger(__name__)
REPORT_TYPES = {'Q1', 'H1', 'Q3', 'FY'}
REPORT_TYPE_ALIASES = {'ANNUAL': 'FY', 'YEAR': 'FY', 'YEARLY': 'FY'}


def _normalize_report_type(value: str | None) -> str:
    normalized = str(value or '').strip().upper()
    normalized = REPORT_TYPE_ALIASES.get(normalized, normalized)
    if normalized not in REPORT_TYPES:
        raise ArtifactValidationError(f'Unsupported financial report type: {value}')
    return normalized


def _dataset_path(model_root: Path) -> Path:
    pointer = model_root / 'serving.yaml'
    payload = yaml.safe_load(pointer.read_text(encoding='utf-8')) or {}
    production = payload.get('production') if isinstance(payload, dict) else None
    dataset_value = production.get('dataset_path') if isinstance(production, dict) else None
    if not dataset_value:
        raise ArtifactValidationError('Production serving entry requires dataset_path')
    candidate = Path(str(dataset_value))
    candidate = candidate if candidate.is_absolute() else model_root / candidate
    resolved = candidate.resolve()
    try:
        resolved.relative_to(model_root)
    except ValueError as exc:
        raise ArtifactValidationError('Dataset path must remain inside PREDICTIVE_VALUATION_MODEL_ROOT') from exc
    if not resolved.is_file():
        raise FileNotFoundError(f'Production dataset not found: {resolved}')
    return resolved


def _load_parquet_sample(path: Path, columns: list[str], max_rows: int = 3000) -> pd.DataFrame:
    try:
        import pyarrow.parquet as parquet
        import pyarrow as arrow
    except ImportError:
        return pd.read_parquet(path, columns=columns).head(max_rows)

    batches = []
    row_count = 0
    for batch in parquet.ParquetFile(path).iter_batches(batch_size=800, columns=columns):
        batches.append(batch)
        row_count += batch.num_rows
        if row_count >= max_rows:
            break
    if not batches:
        return pd.DataFrame(columns=columns)
    return arrow.Table.from_batches(batches).to_pandas()


def _calculate_features(model_path: Path, dataset_path: Path) -> list[dict[str, Any]]:
    bundle = joblib.load(model_path)
    if not isinstance(bundle, dict):
        raise ValueError('Invalid production model bundle')
    feature_columns = bundle.get('feature_cols')
    metrics = bundle.get('metrics') or {}
    classifier = bundle.get('classifier')
    regressor = bundle.get('regressor')
    classifier_target = metrics.get('cls_target_col')
    regressor_target = metrics.get('reg_target_col')
    if not isinstance(feature_columns, list) or not feature_columns:
        raise ValueError('feature_cols missing in production model bundle')
    if not classifier_target and not regressor_target:
        raise ValueError('Target columns missing in production model metrics')

    columns = list(dict.fromkeys([
        *feature_columns,
        *([str(classifier_target)] if classifier_target else []),
        *([str(regressor_target)] if regressor_target else []),
    ]))
    frame = _load_parquet_sample(dataset_path, columns)
    if frame.empty:
        raise ValueError('Production dataset sample is empty')
    frame = frame.replace([np.inf, -np.inf], np.nan)
    for column in feature_columns:
        frame[column] = pd.to_numeric(frame[column], errors='coerce')
    features = frame[feature_columns].copy()
    features = features.fillna(features.median(numeric_only=True)).fillna(0.0)

    classifier_importance = np.zeros(len(feature_columns), dtype=float)
    regressor_importance = np.zeros(len(feature_columns), dtype=float)
    has_classifier = False
    has_regressor = False
    if classifier is not None and classifier_target in frame.columns:
        target = pd.to_numeric(frame[str(classifier_target)], errors='coerce')
        mask = target.notna()
        if int(mask.sum()) >= 200:
            result = permutation_importance(
                classifier, features.loc[mask], target.loc[mask].astype(int),
                n_repeats=3, random_state=42, scoring='accuracy', n_jobs=1,
            )
            classifier_importance = np.nan_to_num(np.abs(result.importances_mean), nan=0.0, posinf=0.0, neginf=0.0)
            has_classifier = True
    if regressor is not None and regressor_target in frame.columns:
        target = pd.to_numeric(frame[str(regressor_target)], errors='coerce')
        mask = target.notna()
        if int(mask.sum()) >= 200:
            result = permutation_importance(
                regressor, features.loc[mask], target.loc[mask],
                n_repeats=3, random_state=42, scoring='neg_mean_absolute_error', n_jobs=1,
            )
            regressor_importance = np.nan_to_num(np.abs(result.importances_mean), nan=0.0, posinf=0.0, neginf=0.0)
            has_regressor = True

    if has_classifier and has_regressor:
        importance = 0.6 * classifier_importance + 0.4 * regressor_importance
    elif has_classifier:
        importance = classifier_importance
    elif has_regressor:
        importance = regressor_importance
    else:
        raise ValueError('Insufficient labeled rows for permutation importance')
    if not np.any(importance > 0):
        raise ValueError('All feature importances are zero')
    order = np.argsort(importance)[::-1]
    return [
        {
            'feature_key': str(feature_columns[index]),
            'feature_label': str(feature_columns[index]),
            'weight': float(importance[index]),
            'direction': 1,
        }
        for index in order
    ]


def _load_exported_features(model_dir: Path, model_version: str, report_type: str) -> list[dict[str, Any]]:
    export_path = model_dir / 'top_features_by_report_type.json'
    try:
        payload = json.loads(export_path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return []
    except (OSError, json.JSONDecodeError):
        logger.warning('predictive_valuation.feature_export_read_error', exc_info=True)
        return []

    if not isinstance(payload, dict) or payload.get('model_version') != model_version:
        return []
    by_report_type = payload.get('by_report_type')
    report_payload = by_report_type.get(report_type) if isinstance(by_report_type, dict) else None
    rows = report_payload.get('top_features') if isinstance(report_payload, dict) else None
    if not isinstance(rows, list):
        return []

    features = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        feature_key = str(row.get('feature_key') or '').strip()
        if not feature_key:
            continue
        try:
            weight = float(row.get('weight') or 0.0)
            rank = int(row.get('rank') or index)
            direction = 1 if int(row.get('direction') or 1) >= 0 else -1
        except (TypeError, ValueError):
            continue
        features.append({
            'rank': rank,
            'feature_key': feature_key,
            'feature_label': str(row.get('feature_label') or feature_key),
            'weight': weight,
            'direction': direction,
        })
    return sorted(features, key=lambda item: item['rank'])


def get_model_top_features(
    *,
    ts_code: str,
    stock_type: str | None = None,
    topn: int = 10,
    model_version: str | None = None,
    report_type: str | None = None,
) -> dict[str, Any]:
    normalized_type = _normalize_report_type(report_type)
    registry = PredictiveArtifactRegistry()
    artifact = registry.load_production(normalized_type)
    if model_version and model_version.strip() != artifact.model_version:
        raise ArtifactValidationError(
            f'Requested model_version is not active production for {normalized_type}: {model_version}'
        )

    cache_path = registry.model_root / 'model_versions' / artifact.model_version / f'top_features_real_{normalized_type}.json'
    model_dir = registry.model_root / 'model_versions' / artifact.model_version
    top_items = _load_exported_features(model_dir, artifact.model_version, normalized_type)
    feature_source = 'exported_snapshot' if top_items else 'permutation_importance'

    if not top_items:
        try:
            cached = json.loads(cache_path.read_text(encoding='utf-8'))
            if (
                cached.get('artifact_hash') == artifact.artifact_hash
                and cached.get('sklearn_version') == artifact.installed_sklearn_version
            ):
                rows = cached.get('top_features')
                if isinstance(rows, list):
                    top_items = [row for row in rows if isinstance(row, dict) and row.get('feature_key')]
                    feature_source = 'permutation_importance_cache'
        except FileNotFoundError:
            pass
        except (OSError, json.JSONDecodeError, AttributeError, TypeError):
            logger.warning('predictive_valuation.feature_cache_read_error', exc_info=True)

    if not top_items:
        top_items = _calculate_features(artifact.model_path, _dataset_path(registry.model_root))
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(json.dumps({
                'model_version': artifact.model_version,
                'report_type': normalized_type,
                'artifact_hash': artifact.artifact_hash,
                'sklearn_version': artifact.installed_sklearn_version,
                'feature_source': 'permutation_importance',
                'top_features': top_items,
            }, ensure_ascii=False, indent=2), encoding='utf-8')
        except (OSError, TypeError, ValueError):
            logger.warning('predictive_valuation.feature_cache_write_error', exc_info=True)

    topn = max(1, min(int(topn), 50))
    return {
        'ts_code': ts_code,
        'stock_type': stock_type or '',
        'model_scope': 'stock_type' if stock_type else 'global',
        'model_version': artifact.model_version,
        'report_type': normalized_type,
        'artifact_path': str(artifact.model_path),
        'degraded': False,
        'degrade_reason': '',
        'feature_source': feature_source,
        'top_features': [
            {
                'rank': rank,
                'feature_key': str(row['feature_key']),
                'feature_label': str(row.get('feature_label') or row['feature_key']),
                'weight': float(row.get('weight') or 0.0),
                'direction': 1 if int(row.get('direction') or 1) >= 0 else -1,
            }
            for rank, row in enumerate(top_items[:topn], start=1)
        ],
    }
