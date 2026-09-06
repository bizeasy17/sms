from django.core.management.base import BaseCommand, CommandError

from market_data.services.sync import SyncValidationError, build_sync_plan, execute_sync


class Command(BaseCommand):
    help = 'Synchronize one market-data dataset from Tushare into PostgreSQL.'

    def add_arguments(self, parser):
        parser.add_argument('--dataset', required=True)
        parser.add_argument('--mode', required=True, choices=['backfill', 'daily'])
        parser.add_argument('--scope', default='all', choices=['all', 'ts-code', 'index-universe'])
        parser.add_argument('--ts-codes', default='')
        parser.add_argument('--start-date', default='')
        parser.add_argument('--end-date', default='')
        parser.add_argument('--history-years', type=int, default=None)
        parser.add_argument('--frequency', default='D')
        parser.add_argument('--resume-run', type=int, default=None)
        parser.add_argument('--overlap-days', type=int, default=3)
        parser.add_argument('--page-size', type=int, default=5000)
        parser.add_argument('--max-pages', type=int, default=100)
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        try:
            plan = build_sync_plan(options)
        except SyncValidationError as exc:
            raise CommandError(str(exc)) from exc
        if plan.dry_run:
            self.stdout.write(f'Dry run: dataset={plan.dataset} mode={plan.mode} start={plan.start_date} end={plan.end_date}')
            return
        try:
            count = execute_sync(plan)
        except Exception as exc:
            raise CommandError(f'Synchronization failed: {exc}') from exc
        self.stdout.write(self.style.SUCCESS(f'Synchronized dataset={plan.dataset} rows={count}'))