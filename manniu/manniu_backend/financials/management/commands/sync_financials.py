from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from financials.services.sync import (
    FinancialSyncValidationError,
    build_financial_sync_plan,
    execute_financial_sync,
)


class Command(BaseCommand):
    help = 'Synchronize corporate financial data from Tushare into PostgreSQL.'

    def add_arguments(self, parser):
        parser.add_argument('--mode', required=True, choices=['backfill', 'quarterly'], help='Sync mode')
        parser.add_argument('--endpoints', default='', help='Comma-separated endpoints to sync')
        parser.add_argument('--scope', default='', choices=['', 'all', 'ts-code', 'event-driven', 'announcement-date'])
        parser.add_argument('--ts-codes', default='', help='Comma-separated ts_codes for ts-code scope')
        parser.add_argument('--period', default='', help='Target financial period YYYYMMDD (e.g. 20250331)')
        parser.add_argument('--start-date', default='', help='Start date YYYYMMDD for backfill mode')
        parser.add_argument('--end-date', default='', help='End date YYYYMMDD')
        parser.add_argument('--history-years', type=int, default=None, help='History years for backfill mode (default 5)')
        parser.add_argument('--page-size', type=int, default=5000)
        parser.add_argument('--max-pages', type=int, default=100)
        parser.add_argument('--batch-size', type=int, default=1000)
        parser.add_argument('--dry-run', action='store_true', help='Validate options and print plan without requests/writes')

    def handle(self, *args, **options):
        try:
            plan = build_financial_sync_plan(options)
        except FinancialSyncValidationError as exc:
            raise CommandError(str(exc)) from exc

        if plan.dry_run:
            self.stdout.write(self.style.SUCCESS(
                f'Dry run valid: mode={plan.mode} endpoints={",".join(plan.endpoints)} scope={plan.scope} '
                f'period={plan.period} start_date={plan.start_date} end_date={plan.end_date}'
            ))
            return

        try:
            res = execute_financial_sync(plan)
            self.stdout.write(self.style.SUCCESS(
                f'Financial sync completed: mode={plan.mode} source_rows={res["source_count"]} '
                f'upserted_rows={res["upserted_count"]} projections={res["projection_count"]} '
                f'securities={res["impacted_securities_count"]}'
            ))
        except Exception as exc:
            raise CommandError(f'Financial sync failed: {exc}') from exc
