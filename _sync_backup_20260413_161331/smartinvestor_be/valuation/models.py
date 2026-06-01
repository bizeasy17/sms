from django.conf import settings

from prediction.models import (
    AnnualOutlookSnapshot,
    BacktestValuationSnapshot,
    StockValuationSnapshot,
    StockValuationSnapshotHistory,
    StockValuationSnapshotLatest,
)


def _resolve_prefix():
    prefix = str(getattr(settings, "VALUATION_TABLE_PREFIX", "prediction") or "prediction").strip().lower()
    if prefix not in {"prediction", "valuation"}:
        return "prediction"
    return prefix


def _apply_table_prefix(prefix):
    BacktestValuationSnapshot._meta.db_table = f"{prefix}_backtestvaluationsnapshot"
    AnnualOutlookSnapshot._meta.db_table = f"{prefix}_annualoutlooksnapshot"
    StockValuationSnapshot._meta.db_table = f"{prefix}_stockvaluationsnapshot"
    StockValuationSnapshotHistory._meta.db_table = f"{prefix}_stockvaluationsnapshothistory"
    StockValuationSnapshotLatest._meta.db_table = f"{prefix}_stockvaluationsnapshotlatest"


_apply_table_prefix(_resolve_prefix())

__all__ = [
    "BacktestValuationSnapshot",
    "AnnualOutlookSnapshot",
    "StockValuationSnapshot",
    "StockValuationSnapshotHistory",
    "StockValuationSnapshotLatest",
]
