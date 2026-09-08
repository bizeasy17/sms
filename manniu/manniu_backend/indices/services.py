from datetime import date

from .constants import INDEX_BY_KEY, METRIC_FIELDS, STYLE_WEIGHTS
from .normalization import common_date_values, normalize_series, positive_number
from .quantile import summarize_series
from .result_types import DataCoverage, DomainResult
from .valuation import calculate_method, summarize_buy_candidate


class IndexService:
    def __init__(self, repository):
        self.repository = repository

    def _metric_field(self, metric):
        try:
            return METRIC_FIELDS[metric.upper()]
        except KeyError as exc:
            raise ValueError(f'unsupported metric: {metric}') from exc

    def composite_quantile(self, metric='PE', style='overall', window='ALL', start_date=None, end_date=None, min_samples=20):
        metric = metric.upper()
        style = style.lower()
        field = self._metric_field(metric)
        if style not in STYLE_WEIGHTS:
            raise ValueError(f'unsupported style: {style}')

        series_by_key = {}
        source_ts_codes = {}
        missing_indices = []
        for key, definition in INDEX_BY_KEY.items():
            security, requested_code = self.repository.resolve_security(key)
            source_ts_codes[key] = security.ts_code if security else requested_code
            if security is None:
                missing_indices.append(key)
                series_by_key[key] = {}
                continue
            rows = self.repository.index_fundamentals(security, start_date=start_date, end_date=end_date)
            series_by_key[key] = normalize_series(rows, field, start_date=start_date, end_date=end_date)
            if not series_by_key[key]:
                missing_indices.append(key)

        common = common_date_values(series_by_key, INDEX_BY_KEY)
        composite = {
            trade_date: sum(values[key] * float(STYLE_WEIGHTS[style][key]) for key in INDEX_BY_KEY)
            for trade_date, values in common.items()
        }
        summary = summarize_series(composite, window=window, asof_date=end_date, min_samples=min_samples)
        coverage = DataCoverage(
            sample_count=summary['sample_count'],
            start_date=summary['start_date'],
            end_date=summary['end_date'],
            missing_indices=missing_indices,
            source_ts_codes=source_ts_codes,
        )
        warnings = []
        if missing_indices:
            warnings.append('missing index data: ' + ', '.join(missing_indices))
        return DomainResult(
            status=summary['status'],
            data={'metric': metric, 'style': style, 'window': window, 'summary': summary, 'series': composite},
            warnings=warnings,
            coverage=coverage,
        )

    def simple_valuation(self, index_code, start_date=None, end_date=None, band_pct=0.1, min_samples=20):
        security, requested_code = self.repository.resolve_security(index_code)
        if security is None:
            return DomainResult(status='NO_DATA', warnings=[f'index not found: {requested_code}'])

        latest_bar = self.repository.latest_bar(security)
        latest_bar_date = getattr(latest_bar, 'trade_date', None) if latest_bar else None
        if latest_bar and end_date and latest_bar_date and latest_bar_date > end_date:
            latest_bar = None
        current_price = positive_number(getattr(latest_bar, 'close', None)) if latest_bar else None
        if current_price is None:
            historical_bars = self.repository.index_bars(security, end_date=end_date)
            normalized_bars = normalize_series(historical_bars, 'close', end_date=end_date)
            if normalized_bars:
                latest_bar_date, current_price = max(normalized_bars.items())
        latest_fundamental = self.repository.latest_fundamental(security)
        latest_fundamental_date = getattr(latest_fundamental, 'trade_date', None) if latest_fundamental else None
        if latest_fundamental and end_date and latest_fundamental_date and latest_fundamental_date > end_date:
            latest_fundamental = None
        rows = self.repository.index_fundamentals(security, start_date=start_date, end_date=end_date)
        methods = {}
        for metric, field in METRIC_FIELDS.items():
            series = normalize_series(rows, field, start_date=start_date, end_date=end_date)
            summary = summarize_series(series, window='ALL', asof_date=end_date, min_samples=min_samples)
            current_metric = positive_number(getattr(latest_fundamental, field, None)) if latest_fundamental else None
            if current_metric is None:
                current_metric = summary['current']
            methods[metric.lower()] = calculate_method(
                metric.lower(), current_price, current_metric, summary['p50'],
                summary['sample_count'], band_pct=band_pct, min_samples=min_samples,
            )

        summary = summarize_buy_candidate(methods)
        latest_trade_date = latest_bar_date
        return DomainResult(
            status=summary['status'],
            data={
                'index_code': requested_code,
                'source_ts_code': security.ts_code,
                'asof_trade_date': latest_trade_date,
                'current_index_price': current_price,
                'methods': methods,
                'summary': summary,
            },
            warnings=[] if current_price is not None else ['current index price unavailable'],
            coverage=DataCoverage(
                end_date=latest_trade_date,
                source_ts_codes={'index': security.ts_code},
            ),
        )