from django.conf import settings
from django.core import checks


@checks.register(checks.Tags.security)
def auth_security_check(app_configs, **kwargs):
    errors = []
    if not settings.DEBUG and not settings.AUTH_TOKEN_HASH_SECRET:
        errors.append(
            checks.Error(
                'AUTH_TOKEN_HASH_SECRET must be configured when DEBUG is False.',
                id='manniu_auth.E001',
            )
        )
    if not settings.DEBUG and settings.SECRET_KEY.startswith('django-insecure-'):
        errors.append(
            checks.Error(
                'SECRET_KEY must be supplied through the environment in production.',
                id='manniu_auth.E002',
            )
        )
    if not settings.DEBUG and settings.AUTH_COOKIE_SECURE is False:
        errors.append(
            checks.Error(
                'AUTH_COOKIE_SECURE must be enabled when DEBUG is False.',
                id='manniu_auth.E003',
            )
        )
    if not settings.DEBUG and not settings.SECURE_SSL_REDIRECT:
        errors.append(
            checks.Warning(
                'SECURE_SSL_REDIRECT is disabled while DEBUG is False.',
                id='manniu_auth.W001',
            )
        )
    if '*' in settings.AUTH_ALLOWED_CORS_ORIGINS:
        errors.append(
            checks.Error(
                'AUTH_ALLOWED_CORS_ORIGINS must not contain a wildcard.',
                id='manniu_auth.E004',
            )
        )
    return errors