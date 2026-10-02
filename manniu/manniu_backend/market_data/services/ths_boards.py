from dataclasses import dataclass
from datetime import date, timedelta
from django.db.models import Q

from market_data.models import IngestionWatermark, THSBoardCatalog, THSBoardDailyHistory


DEFAULT_PAGE_SIZE = 50
MAX_PAGE_SIZE = 200
MAX_HISTORY_DAYS = 366
MAX_HISTORY_ROWS = 2000


class THSBoardRequestError(ValueError):
    def __init__(self, code, message, *, details=None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass(frozen=True)
class THSBoardPage:
    items: list[dict]
    page: int
    page_size: int
    total: int

    @property
    def has_next(self):
        return self.page * self.page_size < self.total


def _pagination(page, page_size):
    try:
        page = int(page or 1)
        page_size = int(page_size or DEFAULT_PAGE_SIZE)
    except (TypeError, ValueError) as exc:
        raise THSBoardRequestError('INVALID_REQUEST', 'page 和 page_size 必须为整数') from exc
    if page < 1 or page_size < 1 or page_size > MAX_PAGE_SIZE:
        raise THSBoardRequestError('INVALID_REQUEST', f'page 必须大于等于 1，page_size 范围为 1-{MAX_PAGE_SIZE}')
    return page, page_size


def _datetime(value):
    return value.isoformat() if value else None


def list_ths_boards(*, query='', page=1, page_size=DEFAULT_PAGE_SIZE):
    page, page_size = _pagination(page, page_size)
    queryset = THSBoardCatalog.objects.filter(
        is_active=True,
        exchange='A',
        type='N',
        security__asset_type='INDEX',
    ).select_related('security').order_by('security__ts_code')
    text = str(query or '').strip()
    if text:
        queryset = queryset.filter(
            Q(security__name__icontains=text) | Q(security__ts_code__icontains=text)
        )
    total = queryset.count()
    rows = queryset[(page - 1) * page_size:page * page_size]
    watermark = IngestionWatermark.objects.filter(
        dataset='ths-board-catalog', scope_key='ALL', frequency='D',
    ).first()
    status = watermark.status if watermark else 'NOT_SYNCED'
    items = [{
        'ts_code': row.security.ts_code,
        'name': row.security.name,
        'count': row.count,
        'exchange': row.exchange,
        'list_date': row.list_date.isoformat() if row.list_date else None,
        'type': row.type,
        'sync_status': status,
        'source_updated_at': _datetime(row.source_updated_at),
        'synced_at': _datetime(row.synced_at),
    } for row in rows]
    return THSBoardPage(items, page, page_size, total)


def get_ths_board_bars(*, ts_code, start_date, end_date, page=1, page_size=DEFAULT_PAGE_SIZE):
    page, page_size = _pagination(page, page_size)
    if start_date > end_date:
        raise THSBoardRequestError('INVALID_DATE', 'start_date 不能晚于 end_date')
    if end_date - start_date > timedelta(days=MAX_HISTORY_DAYS):
        raise THSBoardRequestError('RANGE_TOO_LARGE', '历史查询范围不能超过 366 个自然日')
    if end_date > date.today():
        raise THSBoardRequestError('INVALID_DATE', 'end_date 不能晚于当前日期')
    board = THSBoardCatalog.objects.filter(
        security__ts_code=str(ts_code or '').strip().upper(),
        is_active=True,
        exchange='A',
        type='N',
        security__asset_type='INDEX',
    ).select_related('security').first()
    if board is None:
        raise THSBoardRequestError('INVALID_REQUEST', 'THS A 股概念板块代码无效')
    queryset = THSBoardDailyHistory.objects.filter(
        board=board,
        trade_date__range=(start_date, end_date),
    ).order_by('-trade_date')
    total = queryset.count()
    if total > MAX_HISTORY_ROWS:
        raise THSBoardRequestError('RANGE_TOO_LARGE', '单次历史查询最多返回 2000 条记录')
    rows = queryset[(page - 1) * page_size:page * page_size]
    fields = (
        'open', 'high', 'low', 'pre_close', 'avg_price', 'close', 'change',
        'pct_change', 'vol', 'turnover_rate', 'total_mv', 'float_mv',
    )
    items = [{
        'ts_code': board.security.ts_code,
        'source_ts_code': board.security.ts_code,
        'name': board.security.name,
        'trade_date': row.trade_date.isoformat(),
        'frequency': 'D',
        **{field: float(getattr(row, field)) if getattr(row, field) is not None else None for field in fields},
        'source_trade_date': row.trade_date.isoformat(),
        'status': 'VALID',
        'warnings': [],
        'source_updated_at': _datetime(row.source_updated_at),
        'synced_at': _datetime(row.synced_at),
        'units': {
            'price': 'index_points',
            'vol': 'lots',
            'turnover_rate': 'percentage_points',
            'market_cap': '10k_CNY',
        },
    } for row in rows]
    return THSBoardPage(items, page, page_size, total)