from manniu_auth.models import SecurityAuditEvent


def record_event(event_type, *, user=None, session=None, request=None, metadata=None):
    return SecurityAuditEvent.objects.create(
        event_type=event_type,
        user=user,
        session=session,
        request_id=(request.headers.get('X-Request-ID', '')[:64] if request else ''),
        ip_hash='',
        metadata=metadata or {},
    )
