from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone

from manniu_auth.models import AuthProfile, AuthSession
from .audit import record_event
from .authorization import user_scopes
from .token_service import issue_tokens, revoke_session


def get_profile(user):
    profile, _ = AuthProfile.objects.get_or_create(user=user)
    return profile


@transaction.atomic
def login_user(*, username, password, client_type, device_name, request=None):
    user = authenticate(username=username, password=password)
    if user is None:
        failed_user = User.objects.filter(username__iexact=username).first()
        if failed_user:
            profile = get_profile(failed_user)
            profile.failed_login_count += 1
            if profile.failed_login_count >= settings.AUTH_LOGIN_MAX_FAILURES:
                profile.status = AuthProfile.Status.LOCKED
                profile.locked_until = timezone.now() + timedelta(seconds=settings.AUTH_LOGIN_LOCK_SECONDS)
            profile.save(update_fields=['failed_login_count', 'status', 'locked_until', 'updated_at'])
            record_event('LOGIN_FAILED', user=failed_user, request=request, metadata={'reason': 'invalid_credentials'})
        return None
    profile = get_profile(user)
    now = timezone.now()
    if profile.status == AuthProfile.Status.LOCKED and profile.locked_until and profile.locked_until <= now:
        profile.status = AuthProfile.Status.ACTIVE
        profile.failed_login_count = 0
        profile.locked_until = None
        profile.save(update_fields=['status', 'failed_login_count', 'locked_until', 'updated_at'])
    if profile.status != AuthProfile.Status.ACTIVE or (profile.locked_until and profile.locked_until > now):
        record_event('LOGIN_FAILED', user=user, request=request, metadata={'reason': 'account_locked_or_disabled'})
        return None
    profile.failed_login_count = 0
    profile.last_login_at = now
    profile.save(update_fields=['failed_login_count', 'last_login_at', 'updated_at'])
    session = AuthSession.objects.create(
        user=user,
        client_type=client_type,
        device_name=device_name,
        expires_at=now + timedelta(seconds=settings.AUTH_REFRESH_TOKEN_TTL_SECONDS),
    )
    scopes = user_scopes(user)
    access_raw, refresh_raw, access, refresh = issue_tokens(session, scopes)
    record_event('LOGIN_SUCCEEDED', user=user, session=session, request=request)
    return session, scopes, access_raw, refresh_raw, access, refresh


def logout_session(session, request=None):
    revoke_session(session, 'logout')
    record_event('LOGOUT', user=session.user, session=session, request=request)
