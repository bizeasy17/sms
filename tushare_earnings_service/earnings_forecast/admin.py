from django.contrib import admin
from .models import EarningsBacktestRun


@admin.register(EarningsBacktestRun)
class EarningsBacktestRunAdmin(admin.ModelAdmin):
    list_display = ("id", "run_key", "batch_key", "status", "started_at", "finished_at")
    search_fields = ("run_key", "batch_key")
    list_filter = ("status",)
