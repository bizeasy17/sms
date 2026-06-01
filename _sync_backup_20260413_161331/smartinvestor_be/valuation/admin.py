from django.contrib import admin

from valuation.models import (
    AnnualOutlookSnapshot,
    BacktestValuationSnapshot,
    StockValuationSnapshot,
    StockValuationSnapshotHistory,
    StockValuationSnapshotLatest,
)


admin.site.register(BacktestValuationSnapshot)
admin.site.register(AnnualOutlookSnapshot)
admin.site.register(StockValuationSnapshot)
admin.site.register(StockValuationSnapshotHistory)
admin.site.register(StockValuationSnapshotLatest)
