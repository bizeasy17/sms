import re
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID


SENSITIVE_KEY = re.compile(
    r'(password|passwd|token|secret|authorization|cookie|session|csrf|private.?key|api.?key)',
    re.IGNORECASE,
)
REDACTED = '[REDACTED]'


def sanitize_value(value, *, max_string=1000, depth=0):
    if depth >= 6:
        return '[MAX_DEPTH]'
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, (date, datetime, Decimal, UUID)):
        return str(value)[:max_string]
    if isinstance(value, str):
        return value[:max_string]
    if isinstance(value, Mapping):
        return {
            str(key)[:160]: (
                REDACTED
                if SENSITIVE_KEY.search(str(key))
                else sanitize_value(item, max_string=max_string, depth=depth + 1)
            )
            for key, item in list(value.items())[:100]
        }
    if isinstance(value, (list, tuple, set)):
        return [
            sanitize_value(item, max_string=max_string, depth=depth + 1)
            for item in list(value)[:100]
        ]
    return str(value)[:max_string]


def sanitize_text(value, max_length):
    text = str(value or '')
    text = re.sub(
        r'(?i)(password|passwd|token|secret|authorization|cookie|api[_-]?key)\s*[:=]\s*([^\s,;]+)',
        lambda match: f'{match.group(1)}={REDACTED}',
        text,
    )
    return text[:max_length]