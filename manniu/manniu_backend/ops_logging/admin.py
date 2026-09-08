from django.contrib import admin

from ops_logging.models import LogEntry, LogRun


class ReadOnlyAdminMixin:
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(LogRun)
class LogRunAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = (
        'started_at',
        'name',
        'run_type',
        'status',
        'trigger',
        'duration_ms',
        'exit_code',
    )
    list_filter = ('run_type', 'status', 'trigger')
    search_fields = ('id', 'name', 'correlation_id', 'summary')
    date_hierarchy = 'started_at'
    readonly_fields = [field.name for field in LogRun._meta.fields]


@admin.register(LogEntry)
class LogEntryAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = (
        'occurred_at',
        'level_name',
        'logger_name',
        'event_code',
        'short_message',
    )
    list_filter = ('level_name', 'logger_name', 'event_code')
    search_fields = ('event_id', 'run__id', 'correlation_id', 'event_code', 'message', 'fingerprint')
    date_hierarchy = 'occurred_at'
    readonly_fields = [field.name for field in LogEntry._meta.fields]
    list_select_related = ('run',)

    @admin.display(description='Message')
    def short_message(self, obj):
        return obj.message[:120]