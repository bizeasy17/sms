from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

from django.conf import settings
from market_data.services.industry import IndustryMappingError, resolve_industry_regime, resolve_sw_industry_mapping


DEFAULTS = {
    'pe_target': 14.0,
    'ps_target': 1.8,
    'pb_target': 1.8,
    'peg_target': 1.0,
    'ev_ebitda_target': 9.0,
    'dcf_kwargs': {'discount_rate': 0.105, 'terminal_growth_rate': 0.015},
    'ddm_kwargs': {'discount_rate': 0.115, 'dividend_growth_rate': 0.015},
}


class ValuationTemplateError(ValueError):
    """Raised when the active valuation template is unavailable or invalid."""


class ValuationTemplateLoader:
    def __init__(self, market='CN'):
        self.market = market.upper()
        self.root = Path(__file__).resolve().parents[1] / 'static' / 'valuation_config'
        self.defaults_path = self.root / 'valuation_defaults_CN.json'
        self.sw_defaults_path = self.root / f'valuation_defaults_{self.market}_sw.json'
        self.scarcity_path = self.root / f'scarcity_auto_profile_{self.market}.json'

    def _read(self, path):
        if not path.is_file():
            return {}
        return json.loads(path.read_text(encoding='utf-8'))

    @staticmethod
    def _clean(value):
        if isinstance(value, dict):
            return {key: cleaned for key, item in value.items() if (cleaned := ValuationTemplateLoader._clean(item)) is not None}
        if isinstance(value, list):
            return [item for item in (ValuationTemplateLoader._clean(x) for x in value) if item is not None]
        return value if value is not None else None

    def load(self):
        defaults = self._read(self.defaults_path)
        sw_defaults = self._read(self.sw_defaults_path)
        scarcity = self._read(self.scarcity_path)
        global_params = dict(DEFAULTS)
        global_params.update(defaults.get('global_defaults') or {})
        if sw_defaults.get('global_defaults'):
            global_params.update(sw_defaults['global_defaults'])
        return {
            'defaults': defaults,
            'sw_defaults': sw_defaults,
            'scarcity': scarcity,
            'global_params': self._clean(global_params),
            'template_version': str(sw_defaults.get('version') or defaults.get('version') or 'builtin-1'),
            'source_hash': self._source_hash(sw_defaults, defaults),
            'trade_date': self._parse_date(sw_defaults.get('trade_date')),
            'mapping_version': str(sw_defaults.get('mapping_version') or ''),
        }

    @staticmethod
    def _parse_date(value):
        text = str(value or '').replace('-', '')
        if len(text) != 8 or not text.isdigit():
            return None
        try:
            return date(int(text[:4]), int(text[4:6]), int(text[6:8]))
        except ValueError:
            return None

    @staticmethod
    def _source_hash(*payloads):
        raw = json.dumps(payloads, ensure_ascii=True, sort_keys=True, separators=(',', ':')).encode('utf-8')
        return hashlib.sha256(raw).hexdigest()

    def resolve(self, ts_code):
        data = self.load()
        if not data['mapping_version']:
            raise ValuationTemplateError('Traditional SW template is missing mapping_version')
        try:
            mapping_entry = resolve_sw_industry_mapping(
                security=ts_code,
                mapping_version=data['mapping_version'],
            )
            industry_regime = resolve_industry_regime(
                security=ts_code,
                mapping_version=data['mapping_version'],
            )
        except (IndustryMappingError, ValueError) as exc:
            raise ValuationTemplateError(f'Unable to resolve canonical SW mapping: {exc}') from exc
        levels = data['sw_defaults'].get('levels') or {}
        candidates = [
            ('L3', mapping_entry.get('l3_code'), mapping_entry.get('l3_name')),
            ('L2', mapping_entry.get('l2_code'), mapping_entry.get('l2_name')),
            ('L1', mapping_entry.get('l1_code'), mapping_entry.get('l1_name')),
        ]
        for level, code, name in candidates:
            entry = (levels.get(level) or {}).get(code or '', {})
            if entry.get('params'):
                return self._result(data, level, code, entry.get('industry_name') or name, entry, mapping_entry, industry_regime)
        return self._result(data, 'GLOBAL', '', '', {'params': data['global_params'], 'metrics': {}}, mapping_entry, industry_regime)

    def resolve_industry(self, industry_code, level='L2', industry_name=''):
        data = self.load()
        level = str(level or 'L2').upper()
        code = str(industry_code or '').strip()
        entry = (data['sw_defaults'].get('levels') or {}).get(level, {}).get(code)
        if not entry or not entry.get('params'):
            raise ValuationTemplateError(f'No valuation template for {level}:{code}')
        mapping_entry = resolve_sw_industry_mapping(
            industry_code=code,
            mapping_version=data['mapping_version'],
        )
        industry_regime = resolve_industry_regime(
            industry_code=code,
            industry_name=industry_name,
            mapping_version=data['mapping_version'],
        )
        return self._result(
            data, level, code, entry.get('industry_name') or industry_name, entry,
            mapping_entry, industry_regime,
        )

    def _result(self, data, level, code, name, entry, mapping_entry, industry_regime):
        return {
            'level': level,
            'code': code or '',
            'name': name or '',
            'params': self._clean(entry.get('params') or data['global_params']),
            'metrics': entry.get('metrics') or {},
            'parameter_version': data['template_version'],
            'source_hash': data['source_hash'],
            'source_trade_date': data['trade_date'],
            'scarcity': data.get('scarcity') or {},
            'fallback': level == 'GLOBAL',
            'mapping_version': mapping_entry['mapping_version'],
            'mapping_source_hash': mapping_entry['source_hash'],
            'industry_regime': industry_regime,
        }