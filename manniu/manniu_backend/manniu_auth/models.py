import uuid

from django.contrib.auth.models import User
from django.db import models


class AuthProfile(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        LOCKED = 'LOCKED', 'Locked'
        DISABLED = 'DISABLED', 'Disabled'

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='auth_profile')
    display_name = models.CharField(max_length=128, blank=True, default='')
    timezone = models.CharField(max_length=64, default='UTC')
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)
    failed_login_count = models.PositiveIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    last_login_at = models.DateTimeField(null=True, blank=True)
    last_password_changed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.display_name or self.user.username


class AuthSession(models.Model):
    class ClientType(models.TextChoices):
        WEB = 'WEB', 'Web'
        MOBILE = 'MOBILE', 'Mobile'
        SERVICE = 'SERVICE', 'Service'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='auth_sessions')
    client_type = models.CharField(max_length=32, choices=ClientType.choices, default=ClientType.WEB)
    device_name = models.CharField(max_length=128, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoke_reason = models.CharField(max_length=64, blank=True, default='')
    ip_hash = models.CharField(max_length=64, blank=True, default='')
    user_agent_hash = models.CharField(max_length=64, blank=True, default='')

    class Meta:
        indexes = [
            models.Index(fields=['user', 'revoked_at', 'expires_at'], name='auth_session_user_state_idx'),
            models.Index(fields=['expires_at'], name='auth_session_expiry_idx'),
        ]


class AuthRefreshToken(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(AuthSession, on_delete=models.CASCADE, related_name='refresh_tokens')
    token_hash = models.CharField(max_length=64, unique=True)
    issued_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    replaced_by = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL, related_name='replaced_tokens'
    )

    class Meta:
        indexes = [
            models.Index(fields=['session', 'expires_at'], name='auth_refresh_session_exp_idx'),
        ]


class AuthAccessToken(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(AuthSession, on_delete=models.CASCADE, related_name='access_tokens')
    token_hash = models.CharField(max_length=64, unique=True)
    scope_snapshot = models.JSONField(default=list)
    issued_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['session', 'expires_at'], name='auth_access_session_exp_idx'),
        ]


class AuthRole(models.Model):
    code = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True, default='')
    is_system = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)


class AuthScope(models.Model):
    code = models.CharField(max_length=96, unique=True)
    name = models.CharField(max_length=128)
    description = models.TextField(blank=True, default='')
    is_system = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)


class UserRole(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='auth_roles')
    role = models.ForeignKey(AuthRole, on_delete=models.CASCADE, related_name='user_roles')

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'role'], name='auth_user_role_unique')]


class RoleScope(models.Model):
    role = models.ForeignKey(AuthRole, on_delete=models.CASCADE, related_name='role_scopes')
    scope = models.ForeignKey(AuthScope, on_delete=models.CASCADE, related_name='role_scopes')

    class Meta:
        constraints = [models.UniqueConstraint(fields=['role', 'scope'], name='auth_role_scope_unique')]


class ServiceAccount(models.Model):
    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        DISABLED = 'DISABLED', 'Disabled'

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='service_account')
    service_name = models.CharField(max_length=128, unique=True)
    owner = models.ForeignKey(User, on_delete=models.PROTECT, related_name='owned_service_accounts')
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.ACTIVE)


class SecurityAuditEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    event_type = models.CharField(max_length=64)
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name='auth_audit_events')
    session = models.ForeignKey(
        AuthSession, null=True, blank=True, on_delete=models.SET_NULL, related_name='audit_events'
    )
    request_id = models.CharField(max_length=64, blank=True, default='')
    ip_hash = models.CharField(max_length=64, blank=True, default='')
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['event_type', '-created_at'], name='auth_audit_event_time_idx'),
            models.Index(fields=['user', '-created_at'], name='auth_audit_user_time_idx'),
        ]
