import logging
import uuid

from django.core.management.base import BaseCommand, CommandError

from ops_logging.handlers import flush_database_logs, get_database_log_health
from ops_logging.models import LogEntry


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Write, read, and remove a database logging probe event.'

    def handle(self, *args, **options):
        event_id = uuid.uuid4()
        logger.warning(
            'Operations logging health probe',
            extra={
                'event_id': event_id,
                'event_code': 'ops.logging.health_probe',
                'context': {'probe': True},
            },
        )
        if not flush_database_logs(timeout=5.0):
            raise CommandError('Database logging flush timed out')
        try:
            entry = LogEntry.objects.get(event_id=event_id)
            entry.delete()
        except LogEntry.DoesNotExist as exc:
            raise CommandError('Database logging probe was not persisted') from exc
        self.stdout.write(self.style.SUCCESS(f'Operations logging is healthy: {get_database_log_health()}'))