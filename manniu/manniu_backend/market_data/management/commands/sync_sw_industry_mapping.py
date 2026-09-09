from __future__ import annotations

from datetime import date

from django.core.management.base import BaseCommand, CommandError

from django.conf import settings

from market_data.services.industry import IndustryMappingError, _read_json, _validate_mapping, _validate_rules, build_sw_mapping_from_tushare, publish_industry_mapping, publish_industry_mapping_files


class Command(BaseCommand):
    help = 'Publish a validated versioned SW mapping and industry regime rules into PostgreSQL.'

    def add_arguments(self, parser):
        parser.add_argument('--mapping-file', default='')
        parser.add_argument('--rules-file', required=True)
        parser.add_argument('--source-trade-date', default='')
        parser.add_argument('--from-tushare', action='store_true')
        parser.add_argument('--page-size', type=int, default=2000)
        parser.add_argument('--max-pages', type=int, default=300)
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        source_date = None
        if options['source_trade_date']:
            try:
                source_date = date.fromisoformat(options['source_trade_date'])
            except ValueError as exc:
                raise CommandError('--source-trade-date must use YYYY-MM-DD') from exc
        if bool(options['mapping_file']) == bool(options['from_tushare']):
            raise CommandError('Specify exactly one of --mapping-file or --from-tushare')
        if options['dry_run']:
            try:
                mapping = build_sw_mapping_from_tushare(token=settings.TUSHARE_TOKEN, page_size=options['page_size'], max_pages=options['max_pages']) if options['from_tushare'] else _read_json(options['mapping_file'])
                _validate_mapping(mapping)
                _validate_rules(_read_json(options['rules_file']))
            except IndustryMappingError as exc:
                raise CommandError(str(exc)) from exc
            self.stdout.write('Dry run validated mapping and rules artifacts; no mapping version was published.')
            return
        try:
            if options['from_tushare']:
                mapping, rules = publish_industry_mapping(mapping=build_sw_mapping_from_tushare(token=settings.TUSHARE_TOKEN, page_size=options['page_size'], max_pages=options['max_pages']), rules=_read_json(options['rules_file']), source_trade_date=source_date)
            else:
                mapping, rules = publish_industry_mapping_files(mapping_file=options['mapping_file'], rules_file=options['rules_file'], source_trade_date=source_date)
        except IndustryMappingError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(
            f'Published SW mapping={mapping.mapping_version} rules={rules.rules_version}'
        ))