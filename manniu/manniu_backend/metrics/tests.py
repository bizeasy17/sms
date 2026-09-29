import unittest
from datetime import date
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from market_data.models import Security
from metrics.models import MetricsScoreDimension, MetricsScoreSnapshot
from metrics.services.growth_potential_service import _factor_periods, _ratio_percent
from metrics.services.score_persistence_service import persist_score_result


class RatioPercentTests(unittest.TestCase):
    def test_converts_valid_ratio_to_percentage(self):
        self.assertEqual(_ratio_percent(25, 100), 25.0)

    def test_preserves_missing_or_invalid_ratio_as_none(self):
        self.assertIsNone(_ratio_percent(None, 100))
        self.assertIsNone(_ratio_percent(25, None))
        self.assertIsNone(_ratio_percent(25, 0))

    def test_factor_periods_include_prior_cumulative_quarter(self):
        periods = _factor_periods(date(2026, 6, 30))
        self.assertIn(date(2024, 6, 30), periods)
        self.assertIn(date(2026, 6, 30), periods)


class MetricsScorePersistenceTests(TestCase):
    def setUp(self):
        self.security = getattr(Security, 'objects').create(
            ts_code='600000.SH',
            asset_type=Security.AssetType.STOCK,
            name='Test Security',
        )

    def test_persists_snapshot_dimensions_and_evidence(self):
        result = {
            'ts_code': self.security.ts_code,
            'total_score': 72.5,
            'score_grade': 'B',
            'snapshot_asof_date': '20260630',
            'dimension_scores': [{
                'key': 'growth_quality',
                'name': 'Growth',
                'weight': 0.2,
                'score': 70,
                'evidence': {'revenue_yoy': 12.5},
            }],
        }

        stored = persist_score_result(
            result,
            MetricsScoreSnapshot.ScoreType.FINANCIAL_HEALTH_6D,
            '2026-09-28',
            security=self.security,
        )

        self.assertTrue(stored['created'])
        snapshot = getattr(MetricsScoreSnapshot, 'objects').get(pk=stored['snapshot'].pk)
        dimension = getattr(MetricsScoreDimension, 'objects').get(snapshot=snapshot)
        self.assertEqual(snapshot.score, Decimal('72.50'))
        self.assertEqual(snapshot.score_status, MetricsScoreSnapshot.Status.VALID)
        self.assertEqual(dimension.dimension_key, 'growth_quality')
        self.assertEqual(dimension.evidence['evidence']['revenue_yoy'], 12.5)

    def test_repeated_same_fingerprint_is_idempotent(self):
        result = {
            'ts_code': self.security.ts_code,
            'score': 60,
            'label': 'NEUTRAL',
            'status': 'VALID',
            'coverage': 1.0,
            'dimensions': [],
        }
        score_type = MetricsScoreSnapshot.ScoreType.COMPANY_GROWTH_POTENTIAL

        first = persist_score_result(result, score_type, '2026-09-28', security=self.security)
        second = persist_score_result(result, score_type, '2026-09-28', security=self.security)

        self.assertTrue(first['created'])
        self.assertTrue(second['already_exists'])
        self.assertEqual(getattr(MetricsScoreSnapshot, 'objects').count(), 1)

    def test_composite_unique_key_scopes_fingerprint_by_security_and_type(self):
        common = {
            'security': self.security,
            'asof_date': date(2026, 9, 28),
            'score_status': MetricsScoreSnapshot.Status.VALID,
            'input_fingerprint': 'a' * 64,
        }
        snapshot_manager = getattr(MetricsScoreSnapshot, 'objects')
        snapshot_manager.create(
            **common,
            score_type=MetricsScoreSnapshot.ScoreType.FINANCIAL_HEALTH_6D,
        )
        snapshot_manager.create(
            **common,
            score_type=MetricsScoreSnapshot.ScoreType.MODEL_TOPN_6D,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            snapshot_manager.create(
                **common,
                score_type=MetricsScoreSnapshot.ScoreType.FINANCIAL_HEALTH_6D,
            )

    def test_command_reports_progress_for_each_batch(self):
        second_security = getattr(Security, 'objects').create(
            ts_code='600001.SH',
            asset_type=Security.AssetType.STOCK,
            name='Second Test Security',
        )
        output = StringIO()
        with (
            patch('metrics.management.commands.persist_metrics_scores.compute_score') as compute_score,
            patch('metrics.management.commands.persist_metrics_scores.persist_score_result') as persist,
        ):
            compute_score.side_effect = lambda ts_code, *_args, **_kwargs: {'ts_code': ts_code, 'total_score': 60}
            persist.return_value = {'created': True, 'already_exists': False}
            call_command(
                'persist_metrics_scores',
                '--asof-date', '2026-09-28',
                '--score-types', 'FINANCIAL_HEALTH_6D',
                '--scope', 'ts-codes',
                '--ts-code', self.security.ts_code,
                '--ts-code', second_security.ts_code,
                '--batch-size', '1',
                stdout=output,
            )

        self.assertIn('Batch 1/2 started: securities=1-1/2', output.getvalue())
        self.assertIn('Batch 1/2 completed: securities=1/2 progress=50.0%', output.getvalue())
        self.assertIn('Batch 2/2 completed: securities=2/2 progress=100.0%', output.getvalue())