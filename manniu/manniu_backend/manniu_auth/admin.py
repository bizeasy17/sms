from django.contrib import admin

from .models import (
    AuthAccessToken,
    AuthProfile,
    AuthRefreshToken,
    AuthRole,
    AuthScope,
    AuthSession,
    SecurityAuditEvent,
    ServiceAccount,
)


admin.site.register(
    [
        AuthProfile,
        AuthSession,
        AuthRefreshToken,
        AuthAccessToken,
        AuthRole,
        AuthScope,
        ServiceAccount,
        SecurityAuditEvent,
    ]
)
