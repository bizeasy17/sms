import unittest
from datetime import date
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import TestCase
from financials.models import FinancialIncomeRecord
from market_data.models import Industry, Security
from metrics.models import MetricsScoreDimension, MetricsScoreSnapshot
from metrics.services.growth_potential_service import _factor_periods, _ratio_percent
from metrics.services.health_scoring_service import (
    _growth_dimension_score,
    _peer_revenue_share_position,
    _source_dimensions,
)
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


class HealthScoringTests(unittest.TestCase):
    def test_market_value_does_not_change_competitive_position_score(self):
        features = {
            'or_yoy': 25.0,
            'competitive_position': {'score': 70.0, 'status': 'AVAILABLE'},
            'total_mv': 1_000_000_000,
        }
        original = next(
            dimension for dimension in _source_dimensions('growth_tech', features)
            if dimension[0] == 'growth_quality'
        )

        features['total_mv'] = 900_000_000_000_000
        scaled = next(
            dimension for dimension in _source_dimensions('growth_tech', features)
            if dimension[0] == 'growth_quality'
        )

        self.assertEqual(original[3], scaled[3])
        self.assertNotIn('total_mv', original[4])

    def test_missing_growth_and_peer_factors_have_no_available_weight(self):
        score, available_weight, evidence = _growth_dimension_score(
            None,
            {'score': None, 'status': 'NOT_AVAILABLE'},
            0.20,
            0.14,
        )

        self.assertIsNone(score)
        self.assertEqual(available_weight, 0)
        self.assertEqual(evidence['available_weight'], 0)

    def test_cash_runway_uses_cashflow_margins_not_absolute_amounts(self):
        features = {
            'operating_cashflow_margin': 10.0,
            'free_cashflow_margin': 5.0,
            'n_cashflow_act': 1_000_000_000,
            'free_cashflow': 500_000_000,
        }

        cash_dimension = next(
            dimension for dimension in _source_dimensions('platform_service', features)
            if dimension[0] == 'cash_runway'
        )
        original_score = cash_dimension[3]

        features['n_cashflow_act'] *= 1000
        features['free_cashflow'] *= 1000
        scaled_cash_dimension = next(
            dimension for dimension in _source_dimensions('platform_service', features)
            if dimension[0] == 'cash_runway'
        )

        self.assertAlmostEqual(original_score, 39.2857, places=3)
        self.assertEqual(original_score, scaled_cash_dimension[3])
        self.assertEqual(
            set(cash_dimension[4]),
            {'operating_cashflow_margin', 'free_cashflow_margin'},
        )


class CompetitivePositionTests(TestCase):
    def setUp(self):
        self.industry = Industry.objects.create(
            name='Test Industry',
            source_system='test',
            source_version='v1',
        )
        self.cutoff = date(2026, 9, 28)
        self.current_period = date(2026, 6, 30)
        self.prior_period = date(2023, 6, 30)

    def _create_peers(self, count):
        securities = []
        for index in range(count):
            security = Security.objects.create(
                ts_code=f'{600000 + index}.SH',
                asset_type=Security.AssetType.STOCK,
                name=f'Test Security {index}',
                industry=self.industry,
                list_date=date(2010, 1, 1),
            )
            securities.append(security)
            for period, revenue in (
                (self.prior_period, 100),
                (self.current_period, 1000 if index == 0 else 100),
            ):
                FinancialIncomeRecord.objects.create(
                    security=security,
                    ts_code=security.ts_code,
                    ann_date=date(period.year, 8, 1),
                    end_date=period,
                    period=period.strftime('%Y%m%d'),
                    row_signature=f'{security.pk}-{period.isoformat()}',
                    report_type='1',
                    comp_type='1',
                    total_revenue=revenue,
                )
        return securities

    def test_scores_income_share_change_for_comparable_peer_cohort(self):
        securities = self._create_peers(20)

        result = _peer_revenue_share_position(
            security=securities[0],
            target_income=FinancialIncomeRecord.objects.get(
                security=securities[0], end_date=self.current_period,
            ),
            cutoff=self.cutoff,
        )

        self.assertEqual(result['status'], 'AVAILABLE')
        self.assertEqual(result['peer_count'], 20)
        self.assertEqual(result['score'], 100)
        self.assertEqual(result['metric_basis'], 'revenue_share_change_3y')
        self.assertEqual(result['industry_source_system'], 'test')
        self.assertEqual(result['industry_source_version'], 'v1')

    def test_marks_position_unavailable_below_minimum_peer_count(self):
        securities = self._create_peers(19)

        result = _peer_revenue_share_position(
            security=securities[0],
            target_income=FinancialIncomeRecord.objects.get(
                security=securities[0], end_date=self.current_period,
            ),
            cutoff=self.cutoff,
        )

        self.assertIsNone(result['score'])
        self.assertEqual(result['status'], 'NOT_AVAILABLE')
        self.assertEqual(result['reason'], 'peer_sample_below_minimum')


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