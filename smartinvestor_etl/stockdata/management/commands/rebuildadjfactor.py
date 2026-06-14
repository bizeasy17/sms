from django.core.management.base import BaseCommand

from utils.data_utils import rebuild_trading_history_by_adj_factor


class Command(BaseCommand):
    help = "Rebuild trading history adjusted prices (qfq/hfq) using daily + adj_factor."

    def add_arguments(self, parser):
        parser.add_argument("--tscode", type=str, help="Stock code to rebuild, e.g. 600000.SH")
        parser.add_argument("--start_date", type=str, help="Start date, format YYYYMMDD or YYYY-MM-DD")
        parser.add_argument("--end_date", type=str, help="End date, format YYYYMMDD or YYYY-MM-DD")
        parser.add_argument("--resume", type=str, help="Resume from ts_code")
        parser.add_argument(
            "--keep-pulled-status",
            action="store_true",
            help="Do not reset is_pulled_by_client to False after rebuild.",
        )

    def handle(self, *args, **options):
        result = rebuild_trading_history_by_adj_factor(
            ts_code=options.get("tscode"),
            start_date=options.get("start_date"),
            end_date=options.get("end_date"),
            resume=options.get("resume"),
            mark_unpulled=not bool(options.get("keep_pulled_status")),
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"adj_factor rebuild completed. corporations={result.get('corporations', 0)}, rows={result.get('rows', 0)}"
            )
        )
