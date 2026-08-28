from rest_framework.decorators import api_view
from rest_framework.response import Response

from market_sentiment.models import MarketSentimentSnapshot


def _serialize(snapshot, include_factors=False):
    payload = {
        'market': snapshot.market,
        'scope_type': snapshot.scope_type,
        'scope_code': snapshot.scope_code,
        'trade_date': snapshot.trade_date.isoformat(),
        'score': float(snapshot.sentiment_score) if snapshot.sentiment_score is not None else None,
        'level': snapshot.sentiment_level,
        'raw_score': float(snapshot.raw_score) if snapshot.raw_score is not None else None,
        'standardized_score': float(snapshot.standardized_score) if snapshot.standardized_score is not None else None,
        'momentum_score': float(snapshot.momentum_score) if snapshot.momentum_score is not None else None,
        'activity_score': float(snapshot.activity_score) if snapshot.activity_score is not None else None,
        'fear_score': float(snapshot.fear_score) if snapshot.fear_score is not None else None,
        'universe_size': snapshot.universe_size,
        'valid_sample_size': snapshot.valid_sample_size,
        'coverage': float(snapshot.coverage) if snapshot.coverage is not None else None,
        'engine_version': snapshot.engine_version,
        'status': snapshot.status,
        'metadata': snapshot.metadata,
    }
    if include_factors:
        payload['factors'] = [
            {
                'dimension': factor.dimension,
                'code': factor.factor_code,
                'name': factor.factor_name,
                'normalized_value': float(factor.normalized_value) if factor.normalized_value is not None else None,
                'contribution': float(factor.contribution) if factor.contribution is not None else None,
                'available': factor.available,
                'payload': factor.payload,
            }
            for factor in snapshot.factors.all()
        ]
    return payload


def _query(request):
    return MarketSentimentSnapshot.objects.filter(
        market=request.query_params.get('market', 'CN'),
        scope_type=request.query_params.get('scope', 'MARKET').upper(),
        scope_code=request.query_params.get('scope_code', 'ALL_A').upper(),
        engine_version=request.query_params.get('engine_version', 'daily_v1_20260828'),
    )


@api_view(['GET'])
def get_market_sentiment_latest(request):
    snapshot = _query(request).prefetch_related('factors').order_by('-trade_date').first()
    if snapshot is None:
        return Response({'detail': 'No persisted market sentiment snapshot found.'}, status=404)
    return Response({'data': _serialize(snapshot, include_factors=True)})


@api_view(['GET'])
def get_market_sentiment_history(request):
    snapshots = _query(request)
    start_date = request.query_params.get('start_date')
    end_date = request.query_params.get('end_date')
    if start_date:
        snapshots = snapshots.filter(trade_date__gte=start_date)
    if end_date:
        snapshots = snapshots.filter(trade_date__lte=end_date)
    limit = min(max(int(request.query_params.get('limit', 120)), 1), 1000)
    rows = list(snapshots.order_by('-trade_date')[:limit])
    return Response({'data': [_serialize(snapshot) for snapshot in reversed(rows)]})
