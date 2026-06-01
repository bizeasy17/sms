from django.contrib import admin

from .models import (
    OpenClawUser,
    OpenClawUserIdentity,
    OpenClawTokenCredential,
    OpenClawWatchlist,
    OpenClawWatchlistItem,
    OpenClawAlertRule,
    OpenClawAlertState,
)


@admin.register(OpenClawUser)
class OpenClawUserAdmin(admin.ModelAdmin):
    list_display = ("tenant_id", "user_id", "display_name", "is_active", "updated_at")
    search_fields = ("tenant_id", "user_id", "display_name")
    list_filter = ("tenant_id", "is_active")
    readonly_fields = ("created_at", "updated_at")


@admin.register(OpenClawUserIdentity)
class OpenClawUserIdentityAdmin(admin.ModelAdmin):
    list_display = ("channel", "channel_user_id", "user", "updated_at")
    search_fields = ("channel", "channel_user_id", "user__tenant_id", "user__user_id")
    list_filter = ("channel", "user__tenant_id")
    raw_id_fields = ("user",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(OpenClawTokenCredential)
class OpenClawTokenCredentialAdmin(admin.ModelAdmin):
    list_display = ("user", "token_hint", "channel", "is_active", "expires_at", "updated_at")
    search_fields = ("user__tenant_id", "user__user_id", "token_hint", "channel")
    list_filter = ("channel", "is_active", "user__tenant_id")
    raw_id_fields = ("user",)
    readonly_fields = ("token_hash", "token_hint", "created_at", "updated_at")


@admin.register(OpenClawWatchlist)
class OpenClawWatchlistAdmin(admin.ModelAdmin):
    list_display = ("tenant_id", "user_id", "name", "is_default", "updated_at")
    search_fields = ("tenant_id", "user_id", "name")
    list_filter = ("tenant_id", "is_default")
    readonly_fields = ("created_at", "updated_at")


@admin.register(OpenClawWatchlistItem)
class OpenClawWatchlistItemAdmin(admin.ModelAdmin):
    list_display = ("watchlist", "ts_code", "note", "updated_at")
    search_fields = ("watchlist__tenant_id", "watchlist__user_id", "watchlist__name", "ts_code", "note")
    list_filter = ("watchlist__tenant_id",)
    raw_id_fields = ("watchlist",)
    readonly_fields = ("created_at", "updated_at")


@admin.register(OpenClawAlertRule)
class OpenClawAlertRuleAdmin(admin.ModelAdmin):
    list_display = (
        "tenant_id",
        "user_id",
        "ts_code",
        "discount_threshold_pct",
        "method_dispersion_threshold_pct",
        "change_threshold_pct",
        "enabled",
        "updated_at",
    )
    search_fields = ("tenant_id", "user_id", "ts_code")
    list_filter = ("tenant_id", "enabled")
    readonly_fields = ("created_at", "updated_at")


@admin.register(OpenClawAlertState)
class OpenClawAlertStateAdmin(admin.ModelAdmin):
    list_display = ("tenant_id", "user_id", "ts_code", "last_composite_gap_pct", "updated_at")
    search_fields = ("tenant_id", "user_id", "ts_code")
    list_filter = ("tenant_id",)
    readonly_fields = ("updated_at",)
