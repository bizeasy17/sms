from datetime import date


PUBLIC_API_GROUPS = [
    {
        'key': 'market_data',
        'name': 'Market Data',
        'endpoints': [
            {
                'id': 'market_data.securities.list',
                'method': 'GET',
                'path': '/api/v1/market-analysis/securities',
                'name': '证券主数据列表',
                'description': '按条件查询已持久化的证券主数据。',
                'visibility': 'public',
                'access_mode': 'authenticated',
                'parameters': [
                    {'name': 'asset_type', 'in': 'query', 'type': 'string', 'required': False, 'example': 'stock'},
                    {'name': 'market', 'in': 'query', 'type': 'string', 'required': False, 'example': '主板'},
                    {'name': 'industry', 'in': 'query', 'type': 'string', 'required': False},
                    {'name': 'list_status', 'in': 'query', 'type': 'string', 'required': False, 'example': 'L'},
                    {'name': 'q', 'in': 'query', 'type': 'string', 'required': False, 'example': '平安'},
                    {'name': 'page', 'in': 'query', 'type': 'integer', 'required': False, 'default': 1},
                    {'name': 'page_size', 'in': 'query', 'type': 'integer', 'required': False, 'default': 50},
                ],
                'limits': {'page_size_default': 50, 'page_size_max': 200},
                'response_example': {'ts_code': '000001.SZ', 'name': '平安银行'},
            },
            {
                'id': 'market_data.securities.detail',
                'method': 'GET',
                'path': '/api/v1/market-analysis/securities/:ts_code',
                'name': '证券详情和分类身份',
                'description': '查询单个证券的规范代码、分类和基础身份信息。',
                'visibility': 'public',
                'access_mode': 'authenticated',
                'parameters': [
                    {'name': 'ts_code', 'in': 'path', 'type': 'string', 'required': True, 'example': '000001.SZ'},
                ],
                'response_example': {'ts_code': '000001.SZ', 'symbol': '000001'},
            },
            {
                'id': 'market_data.securities.bars',
                'method': 'GET',
                'path': '/api/v1/market-analysis/securities/:ts_code/bars',
                'name': 'EOD 行情历史',
                'description': '查询有界的证券日行情历史。',
                'visibility': 'public',
                'access_mode': 'authenticated',
                'parameters': [
                    {'name': 'ts_code', 'in': 'path', 'type': 'string', 'required': True, 'example': '000001.SZ'},
                    {'name': 'start_date', 'in': 'query', 'type': 'date', 'required': True, 'example': '2026-09-01'},
                    {'name': 'end_date', 'in': 'query', 'type': 'date', 'required': True, 'example': '2026-09-10'},
                    {'name': 'adjust', 'in': 'query', 'type': 'string', 'required': False, 'default': 'qfq', 'enum': ['raw', 'qfq', 'hfq']},
                    {'name': 'page', 'in': 'query', 'type': 'integer', 'required': False, 'default': 1},
                    {'name': 'page_size', 'in': 'query', 'type': 'integer', 'required': False, 'default': 50},
                ],
                'limits': {'page_size_default': 50, 'page_size_max': 200, 'max_date_range_days': 366},
                'response_example': {'trade_date': '2026-09-10', 'close': 10.2},
            },
            {
                'id': 'market_data.securities.fundamentals',
                'method': 'GET',
                'path': '/api/v1/market-analysis/securities/:ts_code/fundamentals',
                'name': '日基本面历史',
                'description': '查询有界的证券日基本面历史。',
                'visibility': 'public',
                'access_mode': 'authenticated',
                'parameters': [
                    {'name': 'ts_code', 'in': 'path', 'type': 'string', 'required': True, 'example': '000001.SZ'},
                    {'name': 'start_date', 'in': 'query', 'type': 'date', 'required': True, 'example': '2026-09-01'},
                    {'name': 'end_date', 'in': 'query', 'type': 'date', 'required': True, 'example': '2026-09-10'},
                    {'name': 'page', 'in': 'query', 'type': 'integer', 'required': False, 'default': 1},
                    {'name': 'page_size', 'in': 'query', 'type': 'integer', 'required': False, 'default': 50},
                ],
                'limits': {'page_size_default': 50, 'page_size_max': 200, 'max_date_range_days': 366},
                'response_example': {'trade_date': '2026-09-10', 'pe': 12.5},
            },
            {
                'id': 'market_data.regime.market',
                'method': 'GET',
                'path': '/api/v1/market-analysis/market/regime',
                'name': '市场风格状态',
                'description': '查询指定日期和基准下的市场风格状态。',
                'visibility': 'public',
                'access_mode': 'authenticated',
                'parameters': [
                    {'name': 'asof_date', 'in': 'query', 'type': 'date', 'required': False, 'example': '2026-09-10'},
                    {'name': 'benchmark_ts_code', 'in': 'query', 'type': 'string', 'required': False, 'default': '000001.SH'},
                ],
                'response_example': {'regime': 'neutral', 'source': 'persisted'},
            },
            {
                'id': 'market_data.regime.security',
                'method': 'GET',
                'path': '/api/v1/market-analysis/securities/:ts_code/regime',
                'name': '个股风格状态',
                'description': '查询指定证券在某个 as-of 日期的风格状态。',
                'visibility': 'public',
                'access_mode': 'authenticated',
                'parameters': [
                    {'name': 'ts_code', 'in': 'path', 'type': 'string', 'required': True, 'example': '000001.SZ'},
                    {'name': 'asof_date', 'in': 'query', 'type': 'date', 'required': False, 'example': '2026-09-10'},
                ],
                'response_example': {'regime': 'neutral', 'source': 'persisted'},
            },
        ],
    },
]


def public_api_catalog():
    return {
        'catalog_version': date.today().isoformat(),
        'groups': PUBLIC_API_GROUPS,
    }
