from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class IndexDefinition:
    key: str
    ts_code: str
    name: str


INDEX_DEFINITIONS = (
    IndexDefinition('sh', '000001.SH', '上证综指'),
    IndexDefinition('sz', '399001.SZ', '深证成指'),
    IndexDefinition('hs300', '399300.SZ', '沪深300'),
    IndexDefinition('sse50', '000016.SH', '上证50'),
    IndexDefinition('csi500', '000905.SH', '中证500'),
    IndexDefinition('sme', '399005.SZ', '中小板指'),
    IndexDefinition('cyb', '399006.SZ', '创业板指'),
)

INDEX_BY_KEY = {item.key: item for item in INDEX_DEFINITIONS}

STYLE_WEIGHTS = {
    'overall': {'sh': Decimal('0.18'), 'sz': Decimal('0.16'), 'hs300': Decimal('0.20'), 'sse50': Decimal('0.14'), 'csi500': Decimal('0.14'), 'sme': Decimal('0.08'), 'cyb': Decimal('0.10')},
    'defensive': {'sh': Decimal('0.24'), 'sz': Decimal('0.12'), 'hs300': Decimal('0.26'), 'sse50': Decimal('0.20'), 'csi500': Decimal('0.10'), 'sme': Decimal('0.03'), 'cyb': Decimal('0.05')},
    'balanced': {'sh': Decimal('0.18'), 'sz': Decimal('0.16'), 'hs300': Decimal('0.20'), 'sse50': Decimal('0.16'), 'csi500': Decimal('0.15'), 'sme': Decimal('0.06'), 'cyb': Decimal('0.09')},
    'aggressive': {'sh': Decimal('0.10'), 'sz': Decimal('0.18'), 'hs300': Decimal('0.14'), 'sse50': Decimal('0.08'), 'csi500': Decimal('0.18'), 'sme': Decimal('0.12'), 'cyb': Decimal('0.20')},
}

WINDOWS = {'30D': 30, '60D': 60, '90D': 90, '1Y': 365, '3Y': 1095, '5Y': 1825, '10Y': 3650, 'ALL': None}
METRIC_FIELDS = {'PE': 'pe', 'PETTM': 'pe_ttm', 'PB': 'pb'}


def validate_configuration():
    expected_keys = set(INDEX_BY_KEY)
    if len(INDEX_DEFINITIONS) != len(expected_keys):
        raise ValueError('index definitions contain duplicate keys')
    for style, weights in STYLE_WEIGHTS.items():
        if set(weights) != expected_keys:
            raise ValueError(f'{style} weights do not cover the index universe')
        if sum(weights.values(), Decimal('0')) != Decimal('1'):
            raise ValueError(f'{style} weights must sum to 1')


validate_configuration()