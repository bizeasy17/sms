from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal


EventType = Literal['FINANCIAL_DISCLOSED', 'SECURITY_STYLE_CHANGED']


@dataclass(frozen=True)
class SecurityEvent:
    event_type: EventType
    source_system: str
    source_event_key: str
    source_version: str | None
    ts_code: str
    security_id: int | None
    security_name: str | None
    scope_key: str
    event_date: date
    source_trade_date: date | None
    payload: dict[str, Any]
    status: str = 'COMMITTED'
    warnings: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class SecurityEventBatch:
    items: tuple[SecurityEvent, ...]
    page: int
    page_size: int
    total: int
    has_next: bool
    asof_date: date | None
    data_status: str
    warnings: tuple[str, ...] = field(default_factory=tuple)
