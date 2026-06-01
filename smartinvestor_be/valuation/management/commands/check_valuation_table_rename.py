from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connection


TABLE_RENAMES = [
    ("prediction_backtestvaluationsnapshot", "valuation_backtestvaluationsnapshot"),
    ("prediction_annualoutlooksnapshot", "valuation_annualoutlooksnapshot"),
    ("prediction_stockvaluationsnapshot", "valuation_stockvaluationsnapshot"),
    ("prediction_stockvaluationsnapshothistory", "valuation_stockvaluationsnapshothistory"),
    ("prediction_stockvaluationsnapshotlatest", "valuation_stockvaluationsnapshotlatest"),
]


class Command(BaseCommand):
    help = "Validate table-rename readiness/result for prediction_* -> valuation_* without changing data."

    def add_arguments(self, parser):
        parser.add_argument(
            "--phase",
            type=str,
            choices=["pre", "post"],
            default="pre",
            help="pre: before rename (old exists, new not exists); post: after rename (new exists, old not exists).",
        )
        parser.add_argument(
            "--strict",
            action="store_true",
            default=False,
            help="Raise CommandError when any table pair does not match expected state.",
        )
        parser.add_argument(
            "--output",
            type=str,
            default="output/valuation_table_rename_check.txt",
            help="Path to write check report.",
        )

    def _table_exists(self, cursor, table_name):
        cursor.execute("select to_regclass(%s)", [table_name])
        return cursor.fetchone()[0] is not None

    def _count_rows(self, cursor, table_name):
        cursor.execute(f"select count(*) from {table_name}")
        return int(cursor.fetchone()[0])

    def handle(self, *args, **options):
        phase = options["phase"]
        strict = bool(options["strict"])
        output_path = Path(options["output"])

        lines = [
            f"valuation table rename check phase={phase}",
            "",
        ]

        failures = []
        with connection.cursor() as cursor:
            for old_name, new_name in TABLE_RENAMES:
                old_exists = self._table_exists(cursor, old_name)
                new_exists = self._table_exists(cursor, new_name)

                old_rows = self._count_rows(cursor, old_name) if old_exists else None
                new_rows = self._count_rows(cursor, new_name) if new_exists else None

                if phase == "pre":
                    expected = (True, False)
                    passed = (old_exists, new_exists) == expected
                else:
                    expected = (False, True)
                    passed = (old_exists, new_exists) == expected

                status = "PASS" if passed else "FAIL"
                line = (
                    f"[{status}] {old_name} -> {new_name} | "
                    f"old_exists={old_exists}, old_rows={old_rows}, "
                    f"new_exists={new_exists}, new_rows={new_rows}"
                )
                lines.append(line)

                if not passed:
                    failures.append(line)

        lines.append("")
        lines.append(f"Summary: total={len(TABLE_RENAMES)}, failed={len(failures)}")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        for line in lines:
            self.stdout.write(line)

        self.stdout.write(self.style.SUCCESS(f"Check report written to: {output_path}"))

        if strict and failures:
            raise CommandError(f"{len(failures)} table pairs do not match expected phase={phase} state.")
