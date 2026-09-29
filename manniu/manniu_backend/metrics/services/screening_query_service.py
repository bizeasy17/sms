from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import re
from typing import Any, Sequence

from django.db import DatabaseError
from django.db.models import F, Window
from django.db.models.functions import DenseRank

from market_data.models import Security
from metrics.models import MetricsScoreSnapshot

REPORT_TYPE_PATTERN = re.compile(r'^(?P<year>\d{2})(?P<period>Q1|H1|Q3|FY)$')


class MetricsScoreQueryError(Exception):
    """Raised when persisted score snapshots cannot be queried."""


@dataclass(frozen=True)
class ScreeningScoreSnapshot:
    ts_code: str
    score_type: str
    score: Decimal | None
    score_status: str
    filterable: bool
    asof_date: date
    financial_end_date: date | None
    report_type: str
    provenance: dict[str, Any]
    reason_code: str | None = None


def _version_provenance(snapshot: MetricsScoreSnapshot) -> dict[str, Any]:
    return {
        'calculation_version': snapshot.calculation_version or None,
        'scoring_version': snapshot.scoring_version or None,
        'profile_version': snapshot.profile_version or None,
        'peer_mapping_version': snapshot.peer_mapping_version or None,
        'model_version': snapshot.model_version or None,
        'feature_set_version': snapshot.feature_set_version or None,
        'mapping_version': snapshot.mapping_version or None,
        'normalization_version': snapshot.normalization_version or None,
        'dimension_weight_version': snapshot.dimension_weight_version or None,
        'score_topn': snapshot.score_topn,
        'store_topn': snapshot.store_topn,
        'model_scope': snapshot.model_scope or None,
        'model_degraded': snapshot.model_degraded,
        'model_degrade_reason': snapshot.model_degrade_reason or None,
        'source_periods': snapshot.source_periods,
        'warnings': snapshot.warnings,
    }


def query_screening_scores(
    *,
    securities: Sequence[Security],
    score_types: Sequence[str],
    asof_date: date,
    report_type: str,
) -> list[ScreeningScoreSnapshot]:
    """Return the latest persisted snapshot per security and score type."""
    supported_types = {choice for choice, _ in MetricsScoreSnapshot.ScoreType.choices}
    requested_types = set(score_types)
    unsupported_types = requested_types - supported_types
    if unsupported_types:
        raise ValueError(f'unsupported score types: {sorted(unsupported_types)}')
    report_match = REPORT_TYPE_PATTERN.fullmatch(str(report_type or '').strip().upper())
    if report_match is None:
        raise ValueError('report_type must use YYQ1, YYH1, YYQ3, or YYFY')
    report_year = 2000 + int(report_match.group('year'))
    report_period = report_match.group('period')
    security_ids = {security.pk for security in securities}
    if not security_ids or not requested_types:
        return []

    try:
        snapshot_manager = getattr(MetricsScoreSnapshot, 'objects')
        snapshots = list(
            snapshot_manager.filter(
                security_id__in=security_ids,
                score_type__in=requested_types,
                report_type=report_period,
                financial_end_date__year=report_year,
                asof_date__lte=asof_date,
            )
            .annotate(
                _latest_rank=Window(
                    expression=DenseRank(),
                    partition_by=[F('security_id'), F('score_type')],
                    order_by=F('asof_date').desc(),
                ),
            )
            .filter(_latest_rank=1)
            .select_related('security')
            .order_by('security_id', 'score_type', 'pk')
        )
    except DatabaseError as exc:
        raise MetricsScoreQueryError('metrics 评分快照查询失败') from exc

    grouped: dict[tuple[int, str], list[MetricsScoreSnapshot]] = {}
    for snapshot in snapshots:
        grouped.setdefault((snapshot.security_id, snapshot.score_type), []).append(snapshot)

    results = []
    for rows in grouped.values():
        snapshot = rows[0]
        common = {
            'ts_code': snapshot.security.ts_code,
            'score_type': snapshot.score_type,
            'asof_date': snapshot.asof_date,
            'financial_end_date': snapshot.financial_end_date,
            'report_type': snapshot.report_type,
        }
        if len(rows) > 1:
            results.append(ScreeningScoreSnapshot(
                **common,
                score=None,
                score_status='AMBIGUOUS',
                filterable=False,
                provenance={
                    'candidate_versions': [_version_provenance(row) for row in rows],
                    'candidate_count': len(rows),
                },
                reason_code='AMBIGUOUS_SCORE_VERSION',
            ))
            continue

        filterable = (
            snapshot.score is not None
            and snapshot.score_status != MetricsScoreSnapshot.Status.NOT_APPLICABLE
        )
        results.append(ScreeningScoreSnapshot(
            **common,
            score=snapshot.score,
            score_status=snapshot.score_status,
            filterable=filterable,
            provenance=_version_provenance(snapshot),
            reason_code=(
                None if filterable else 'SCORE_NOT_APPLICABLE'
                if snapshot.score_status == MetricsScoreSnapshot.Status.NOT_APPLICABLE
                else 'SCORE_MISSING'
            ),
        ))
    return results