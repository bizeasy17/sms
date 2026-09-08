from datetime import datetime, time, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from ops_logging.context import log_run
from ops_logging.models import LogEntry, LogRun


class Command(BaseCommand):
    help = 'Delete expired operations logs in bounded batches.'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--before', default='')
        parser.add_argument('--batch-size', type=int, default=5000)

    def handle(self, *args, **options):
        batch_size = options['batch_size']
        if batch_size <= 0 or batch_size > 50000:
            raise CommandError('--batch-size must be between 1 and 50000')

        now = timezone.now()
        explicit_cutoff = self._parse_cutoff(options['before'])
        normal_cutoff = explicit_cutoff or now - timedelta(days=settings.OPS_DB_LOG_RETENTION_DAYS)
        error_cutoff = explicit_cutoff or now - timedelta(days=settings.OPS_DB_ERROR_RETENTION_DAYS)
        expired_entries = LogEntry.objects.filter(
            Q(level_no__lt=40, occurred_at__lt=normal_cutoff)
            | Q(level_no__gte=40, occurred_at__lt=error_cutoff)
        )
        expired_runs = LogRun.objects.filter(
            finished_at__lt=error_cutoff,
            entries__isnull=True,
        )

        entry_count = expired_entries.count()
        run_count = expired_runs.count()
        if options['dry_run']:
            self.stdout.write(f'Would delete entries={entry_count} runs={run_count}')
            return

        with log_run(
            run_type=LogRun.RunType.COMMAND,
            name='prune_ops_logs',
            parameters={'before': options['before'], 'batch_size': batch_size},
        ) as run:
            deleted_entries = self._delete_batches(expired_entries, batch_size)
            deleted_runs = self._delete_batches(expired_runs, batch_size)
            run.set_counters(entries=deleted_entries, runs=deleted_runs)
            run.set_summary(f'Deleted entries={deleted_entries} runs={deleted_runs}')
            self.stdout.write(
                self.style.SUCCESS(f'Deleted entries={deleted_entries} runs={deleted_runs}')
            )

    @staticmethod
    def _delete_batches(queryset, batch_size):
        deleted = 0
        while True:
            ids = list(queryset.order_by('pk').values_list('pk', flat=True)[:batch_size])
            if not ids:
                return deleted
            count, _ = queryset.model.objects.filter(pk__in=ids).delete()
            deleted += count

    @staticmethod
    def _parse_cutoff(value):
        if not value:
            return None
        try:
            parsed = datetime.strptime(value, '%Y-%m-%d').date()
        except ValueError as exc:
            raise CommandError('--before must use YYYY-MM-DD') from exc
        return timezone.make_aware(datetime.combine(parsed, time.min))