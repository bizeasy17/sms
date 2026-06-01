from django.contrib import admin

from .models import ValuationRiskFactor, ValuationRiskSnapshot


@admin.register(ValuationRiskSnapshot)
class ValuationRiskSnapshotAdmin(admin.ModelAdmin):
    list_display = (
        'ts_code',
        'market',
        'trade_date',
        'profit_report_type',
        'risk_level',
        'risk_score',
        'engine_version',
    )
    list_filter = ('market', 'profit_report_type', 'risk_level', 'engine_version')
    search_fields = ('ts_code',)


@admin.register(ValuationRiskFactor)
class ValuationRiskFactorAdmin(admin.ModelAdmin):
    list_display = (
        'snapshot',
        'dimension',
        'factor_code',
        'severity',
        'factor_score',
        'is_triggered',
    )
    list_filter = ('dimension', 'severity', 'is_triggered')
    search_fields = ('snapshot__ts_code', 'factor_code', 'factor_name')
