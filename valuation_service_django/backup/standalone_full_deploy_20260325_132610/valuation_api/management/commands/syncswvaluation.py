import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from valuation_api.sw_valuation import ShenwanValuationSyncService


class Command(BaseCommand):
    help = "Sync Shenwan mapping and valuation defaults using Tushare Pro."

    def add_arguments(self, parser):
        parser.add_argument(
            "--trade-date",
            dest="trade_date",
            default=None,
            help="Trade date in YYYYMMDD or YYYY-MM-DD. If not provided, auto-detect latest available.",
        )
        parser.add_argument(
            "--sample-size",
            type=int,
            default=5,
            help="How many top market-cap constituents to sample per L3 for fina_indicator metrics.",
        )
        parser.add_argument(
            "--request-interval",
            type=float,
            default=0.45,
            help="Seconds between fina_indicator requests to avoid API throttling.",
        )
        parser.add_argument(
            "--max-industries",
            type=int,
            default=None,
            help="Limit number of L3 industries for quick tests.",
        )
        parser.add_argument(
            "--mapping-only",
            action="store_true",
            help="Only refresh sw_industry_mapping_CN.json.",
        )
        parser.add_argument(
            "--params-only",
            action="store_true",
            help="Only refresh valuation_defaults_CN_sw.json. Uses existing mapping file.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Compute payloads without writing files.",
        )
        parser.add_argument(
            "--progress-every",
            type=int,
            default=0,
            help="Print progress every N L3 industries when building params.",
        )
        parser.add_argument(
            "--disable-history-anchors",
            action="store_true",
            default=False,
            help="Disable sw_daily-based historical quantile anchors (3Y/5Y/10Y).",
        )
        parser.add_argument(
            "--history-years",
            type=str,
            default="3,5,10",
            help="History windows in years, comma separated. Example: 3,5,10",
        )
        parser.add_argument(
            "--history-quantile",
            type=float,
            default=0.5,
            help="History quantile point, default 0.5 (median).",
        )
        parser.add_argument(
            "--history-min-samples",
            type=int,
            default=120,
            help="Minimum sample points required for each history window.",
        )
        parser.add_argument(
            "--params-output-suffix",
            type=str,
            default=None,
            help="Optional suffix for params output file, e.g. ref_5_10_20 -> valuation_defaults_CN_sw_ref_5_10_20.json.",
        )

    def handle(self, *args, **options):
        include_mapping = not options["params_only"]
        include_params = not options["mapping_only"]

        if not include_mapping and not include_params:
            raise CommandError("Cannot use --mapping-only and --params-only together.")

        history_years = []
        for item in str(options.get("history_years") or "").split(","):
            item = item.strip()
            if not item:
                continue
            try:
                value = int(item)
            except ValueError as exc:
                raise CommandError(f"invalid --history-years value: {item}") from exc
            if value > 0:
                history_years.append(value)
        if not history_years:
            history_years = [3, 5, 10]

        static_dir = Path(settings.BASE_DIR) / "static"
        service = ShenwanValuationSyncService(
            static_dir=static_dir,
            history_enabled=not bool(options.get("disable_history_anchors", False)),
            history_years=history_years,
            history_quantile=float(options.get("history_quantile") or 0.5),
            history_min_samples=int(options.get("history_min_samples") or 120),
            params_output_suffix=options.get("params_output_suffix"),
        )

        progress_every = int(options.get("progress_every") or 0)

        def _progress_callback(payload):
            if payload.get("stage") != "params_l3":
                return
            self.stdout.write(
                "[progress] {done}/{total} L3 industries done (last={last_code})".format(
                    done=payload.get("done"),
                    total=payload.get("total"),
                    last_code=payload.get("last_code"),
                )
            )

        try:
            result = service.sync(
                trade_date=options.get("trade_date"),
                sample_size=int(options.get("sample_size") or 5),
                max_industries=options.get("max_industries"),
                include_mapping=include_mapping,
                include_params=include_params,
                dry_run=bool(options.get("dry_run")),
                request_interval=options.get("request_interval"),
                progress_every=progress_every,
                progress_callback=_progress_callback if progress_every > 0 else None,
            )
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write("syncswvaluation completed.")
        self.stdout.write(
            "history_enabled={enabled}, history_years={years}, history_quantile={quantile}, history_min_samples={samples}".format(
                enabled=not bool(options.get("disable_history_anchors", False)),
                years=",".join(str(y) for y in history_years),
                quantile=float(options.get("history_quantile") or 0.5),
                samples=int(options.get("history_min_samples") or 120),
            )
        )
        self.stdout.write(f"params_output_suffix={options.get('params_output_suffix') or 'default'}")
        self.stdout.write(json.dumps(result, ensure_ascii=False, indent=2))
