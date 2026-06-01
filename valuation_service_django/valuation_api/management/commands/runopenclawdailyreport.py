from django.core.management.base import BaseCommand

from valuation_api.models import OpenClawWatchlist
from valuation_api.views import _build_daily_watchlist_report_text, _forward_text_to_webhook


class Command(BaseCommand):
    help = "Generate daily valuation report for OpenClaw watchlists and optionally send to Feishu webhooks"

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", type=str, default="", help="Filter by tenant_id")
        parser.add_argument("--user-id", type=str, default="", help="Filter by user_id")
        parser.add_argument("--market", type=str, default="CN")
        parser.add_argument("--freq", type=str, default="D")
        parser.add_argument("--valuation-band-pct", type=float, default=0.1)
        parser.add_argument("--forward", action="store_true", help="Send report via watchlist webhook")
        parser.add_argument("--dry-run", action="store_true", help="Print report without sending")

    def handle(self, *args, **options):
        queryset = OpenClawWatchlist.objects.prefetch_related("items").all().order_by("tenant_id", "user_id", "id")
        if options["tenant_id"]:
            queryset = queryset.filter(tenant_id=options["tenant_id"])
        if options["user_id"]:
            queryset = queryset.filter(user_id=options["user_id"])

        total = 0
        sent = 0
        failed = 0

        for watchlist in queryset:
            total += 1
            report_text, rows = _build_daily_watchlist_report_text(
                watchlist,
                market=options["market"],
                freq=(options["freq"] or "D").upper(),
                band_pct=options["valuation_band_pct"],
            )
            self.stdout.write(
                f"[{watchlist.tenant_id}/{watchlist.user_id}] watchlist={watchlist.id} {watchlist.name} items={len(rows)}"
            )

            if options["dry_run"] or not options["forward"]:
                continue

            ok, err = _forward_text_to_webhook(report_text, watchlist.feishu_webhook)
            if ok:
                sent += 1
                self.stdout.write(self.style.SUCCESS(f"sent watchlist={watchlist.id}"))
            else:
                failed += 1
                self.stdout.write(self.style.WARNING(f"failed watchlist={watchlist.id} reason={err}"))

        self.stdout.write(
            self.style.SUCCESS(
                f"done total={total} sent={sent} failed={failed} dry_run={bool(options['dry_run'])}"
            )
        )
