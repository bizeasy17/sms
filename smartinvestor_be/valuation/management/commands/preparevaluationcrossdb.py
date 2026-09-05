from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction


class Command(BaseCommand):
    help = "Prepare valuation_service snapshot tables for BE cross-database traditional valuation storage."

    database_alias = "valuation"
    table_specs = {
        "valuation_snapshot": {
            "legacy_unique_columns": [
                "ts_code",
                "trade_date",
                "market",
                "valuation_method",
                "valuation_variant",
            ],
            "unique_columns": [
                "ts_code",
                "trade_date",
                "market",
                "valuation_method",
                "valuation_variant",
                "profit_report_type",
                "profit_report_end_date",
                "profit_data_source",
            ],
            "constraint_name": "valuation_snapshot_report_bucket_uniq",
        },
        "valuation_snapshot_latest": {
            "legacy_unique_columns": [
                "ts_code",
                "market",
                "valuation_method",
                "valuation_variant",
            ],
            "unique_columns": [
                "ts_code",
                "market",
                "valuation_method",
                "valuation_variant",
                "profit_report_type",
                "profit_data_source",
            ],
            "constraint_name": "valuation_snapshot_latest_bucket_uniq",
        },
    }

    def handle(self, *_args, **_options):
        if self.database_alias not in connections.databases:
            raise CommandError(f"Database alias is not configured: {self.database_alias}")

        connection = connections[self.database_alias]
        existing_tables = set(connection.introspection.table_names())
        missing_tables = set(self.table_specs) - existing_tables
        if missing_tables:
            raise CommandError(
                "valuation_service is missing required snapshot tables: "
                + ", ".join(sorted(missing_tables))
            )

        quote = connection.ops.quote_name
        with transaction.atomic(using=self.database_alias), connection.cursor() as cursor:
            for table_name, spec in self.table_specs.items():
                quoted_table = quote(table_name)
                cursor.execute(
                    f"ALTER TABLE {quoted_table} "
                    "ADD COLUMN IF NOT EXISTS profit_report_ann_date date"
                )

                constraints = connection.introspection.get_constraints(cursor, table_name)
                for name, details in constraints.items():
                    if details.get("primary_key") or not details.get("unique"):
                        continue
                    if details.get("columns") == spec["legacy_unique_columns"]:
                        cursor.execute(
                            f"ALTER TABLE {quoted_table} DROP CONSTRAINT {quote(name)}"
                        )

                columns = ", ".join(quote(column) for column in spec["unique_columns"])
                cursor.execute(
                    f"ALTER TABLE {quoted_table} "
                    f"DROP CONSTRAINT IF EXISTS {quote(spec['constraint_name'])}"
                )
                cursor.execute(
                    f"ALTER TABLE {quoted_table} "
                    f"ADD CONSTRAINT {quote(spec['constraint_name'])} "
                    f"UNIQUE NULLS NOT DISTINCT ({columns})"
                )

        self.stdout.write(
            self.style.SUCCESS(
                "valuation_service snapshot tables are ready for BE cross-database storage."
            )
        )