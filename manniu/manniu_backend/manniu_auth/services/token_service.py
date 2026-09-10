import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from manniu_auth.models import AuthAccessToken, AuthRefreshToken, AuthSession


def _secret():
    secret = getattr(settings, 'AUTH_TOKEN_HASH_SECRET', '')
    if not secret:
        raise RuntimeError('AUTH_TOKEN_HASH_SECRET is required')
    return secret.encode()


def generate_raw_token():
    return secrets.token_urlsafe(48)


def token_hash(raw_token):
    return hmac.new(_secret(), raw_token.encode(), hashlib.sha256).hexdigest()


def issue_tokens(session, scopes):
    now = timezone.now()
    access_raw = generate_raw_token()
    refresh_raw = generate_raw_token()
    access = AuthAccessToken.objects.create(
        session=session,
        token_hash=token_hash(access_raw),
        scope_snapshot=sorted(set(scopes)),
        expires_at=now + timedelta(seconds=settings.AUTH_ACCESS_TOKEN_TTL_SECONDS),
    )
    refresh = AuthRefreshToken.objects.create(
        session=session,
        token_hash=token_hash(refresh_raw),
        expires_at=now + timedelta(seconds=settings.AUTH_REFRESH_TOKEN_TTL_SECONDS),
    )
    return access_raw, refresh_raw, access, refresh


def authenticate_access_token(raw_token):
    now = timezone.now()
    access = AuthAccessToken.objects.select_related('session', 'session__user').filter(
        token_hash=token_hash(raw_token),
        revoked_at__isnull=True,
        expires_at__gt=now,
        session__revoked_at__isnull=True,
        session__expires_at__gt=now,
        session__user__is_active=True,
    ).first()
    if access is None:
        return None
    profile = getattr(access.session.user, 'auth_profile', None)
    if profile is None or profile.status != 'ACTIVE' or (
        profile.locked_until and profile.locked_until <= now
    ):
        return None
    AuthAccessToken.objects.filter(pk=access.pk).update(last_used_at=now)
    return access


def revoke_session(session, reason):
    now = timezone.now()
    AuthSession.objects.filter(pk=session.pk, revoked_at__isnull=True).update(
        revoked_at=now,
        revoke_reason=reason,
    )
    AuthAccessToken.objects.filter(session=session, revoked_at__isnull=True).update(revoked_at=now)
    AuthRefreshToken.objects.filter(session=session, revoked_at__isnull=True).update(revoked_at=now)


@transaction.atomic
def rotate_refresh_token(raw_token):
    now = timezone.now()
    refresh = AuthRefreshToken.objects.select_for_update().select_related(
        'session', 'session__user'
    ).filter(token_hash=token_hash(raw_token)).first()
    if refresh is None:
        return None, 'invalid'
    if refresh.used_at or refresh.revoked_at or refresh.expires_at <= now:
        revoke_session(refresh.session, 'refresh_replay')
        return None, 'reused'
    if refresh.session.revoked_at or refresh.session.expires_at <= now or not refresh.session.user.is_active:
        return None, 'invalid'
    profile = getattr(refresh.session.user, 'auth_profile', None)
    if profile is None or profile.status != 'ACTIVE':
        return None, 'invalid'
    refresh.used_at = now
    refresh.save(update_fields=['used_at'])
    access_raw, new_refresh_raw, access, new_refresh = issue_tokens(
        refresh.session,
        refresh.session.user.auth_roles.values_list('role__role_scopes__scope__code', flat=True),
    )
    refresh.replaced_by = new_refresh
    refresh.save(update_fields=['replaced_by'])
    return (access_raw, new_refresh_raw, access, new_refresh), None
