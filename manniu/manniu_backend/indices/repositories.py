from market_data.models import (
    IndexDailyFundamentalHistory,
    IndexDailyFundamentalLatest,
    MarketBarDailyHistory,
    MarketBarLatest,
    Security,
)

from .constants import INDEX_BY_KEY


DEFAULT_SOURCE_ALIASES = {}


class MarketDataIndexRepository:
    """Read-only adapter for the market_data index facts."""

    def __init__(self, source_aliases=None):
        self.source_aliases = source_aliases or DEFAULT_SOURCE_ALIASES

    def resolve_security(self, index_key_or_code):
        definition = INDEX_BY_KEY.get(index_key_or_code)
        requested_code = definition.ts_code if definition else index_key_or_code
        candidate_codes = (requested_code,) + tuple(self.source_aliases.get(requested_code, ()))
        security = Security.objects.filter(
            asset_type=Security.AssetType.INDEX,
            ts_code__in=candidate_codes,
        ).order_by('ts_code').first()
        return security, requested_code

    def resolve_universe(self):
        return {
            key: self.resolve_security(key)[0]
            for key in INDEX_BY_KEY
        }

    def index_fundamentals(self, security, start_date=None, end_date=None):
        query = IndexDailyFundamentalHistory.objects.filter(security=security)
        if start_date:
            query = query.filter(trade_date__gte=start_date)
        if end_date:
            query = query.filter(trade_date__lte=end_date)
        return query.order_by('trade_date').values('trade_date', 'pe', 'pe_ttm', 'pb')

    def latest_fundamental(self, security):
        return IndexDailyFundamentalLatest.objects.filter(security=security).first()

    def index_bars(self, security, start_date=None, end_date=None):
        query = MarketBarDailyHistory.objects.filter(security=security)
        if start_date:
            query = query.filter(trade_date__gte=start_date)
        if end_date:
            query = query.filter(trade_date__lte=end_date)
        return query.order_by('trade_date').values('trade_date', 'close')

    def latest_bar(self, security):
        return MarketBarLatest.objects.filter(
            security=security,
            frequency=MarketBarLatest.Frequency.DAILY,
        ).order_by('-trade_date').first()