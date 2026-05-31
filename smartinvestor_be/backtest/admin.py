from django.contrib import admin

from backtest.models import TraditionalBacktestRun


@admin.register(TraditionalBacktestRun)
class TraditionalBacktestRunAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "run_key",
        "status",
        "batch_key",
        "start_date",
        "end_date",
        "updated_at",
    )
    list_filter = ("status", "batch_key", "strategy_name", "market")
    search_fields = ("run_key", "result_file", "error_message")
    readonly_fields = ("created_at", "updated_at")
