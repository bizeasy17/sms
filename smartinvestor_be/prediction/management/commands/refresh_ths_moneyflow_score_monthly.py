from django.core.management.base import BaseCommand, CommandError

from api.views import _compute_and_write_ths_moneyflow_score_snapshot


class Command(BaseCommand):
    help = "按 THS 行业类型生成资金流评分月度快照。"

    def add_arguments(self, parser):
        parser.add_argument(
            "--top-n",
            type=int,
            default=20,
            help="每个 THS 类型输出 TopN，默认20。",
        )
        parser.add_argument(
            "--lookback-days",
            type=int,
            default=30,
            help="资金流累计窗口天数，默认30。",
        )
        parser.add_argument(
            "--ths-index-type",
            type=str,
            default="N",
            help="THS 行业类型，当前默认仅 N。",
        )
        parser.add_argument(
            "--strict",
            action="store_true",
            default=False,
            help="strict 模式下若无可评分候选则返回非零退出码。",
        )

    def handle(self, *args, **options):
        top_n = int(options.get("top_n") or 20)
        lookback_days = int(options.get("lookback_days") or 30)
        ths_index_type = str(options.get("ths_index_type") or "N").strip().upper() or "N"
        strict = bool(options.get("strict", False))

        try:
            payload, output_path = _compute_and_write_ths_moneyflow_score_snapshot(
                top_n=top_n,
                lookback_days=lookback_days,
                ths_index_type=ths_index_type,
            )
        except Exception as exc:
            raise CommandError(f"refresh ths moneyflow score failed: {exc}") from exc

        snapshots = payload.get("snapshots") if isinstance(payload.get("snapshots"), dict) else {}
        if strict and not snapshots:
            raise CommandError("ths moneyflow score snapshot is empty in strict mode")

        self.stdout.write(
            self.style.SUCCESS(
                "[ths-moneyflow-score] refresh done: "
                f"asof_date={payload.get('asof_date')} "
                f"types={len(snapshots)} "
                f"top_n={payload.get('top_n_default')} "
                f"output={output_path}"
            )
        )
