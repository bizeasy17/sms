from django.db import migrations, models


SNAPSHOT_OLD_UNIQUE_FIELDS = [
    "ts_code",
    "trade_date",
    "market",
    "valuation_method",
    "valuation_variant",
    "profit_report_type",
    "profit_report_end_date",
]

SNAPSHOT_NEW_UNIQUE_FIELDS = [
    "ts_code",
    "trade_date",
    "market",
    "valuation_method",
    "valuation_variant",
    "profit_report_type",
    "profit_report_end_date",
    "profit_data_source",
]

LATEST_OLD_UNIQUE_FIELDS = [
    "ts_code",
    "market",
    "valuation_method",
    "valuation_variant",
]

LATEST_NEW_UNIQUE_FIELDS = [
    "ts_code",
    "market",
    "valuation_method",
    "valuation_variant",
    "profit_report_type",
    "profit_data_source",
]

SNAPSHOT_NEW_UNIQUE_NAME = "prediction_sv_snapshot_bucket_uniq"
LATEST_NEW_UNIQUE_NAME = "prediction_sv_latest_bucket_uniq"
LATEST_BUCKET_INDEX_NAME = "prediction_s_latest_bucket_idx"


def _resolve_table_name(schema_editor, suffix):
    existing_tables = set(schema_editor.connection.introspection.table_names())
    for candidate in [
        f"valuation_{suffix}",
        f"prediction_{suffix}",
    ]:
        if candidate in existing_tables:
            return candidate
    return None


def _fetch_postgres_unique_constraint_names(schema_editor, table_name, columns):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT con.conname
            FROM pg_constraint con
            JOIN pg_class rel ON rel.oid = con.conrelid
            JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
            WHERE nsp.nspname = current_schema()
              AND rel.relname = %s
              AND con.contype = 'u'
            """,
            [table_name],
        )
        names = [row[0] for row in cursor.fetchall()]

        matched_names = []
        for name in names:
            cursor.execute(
                """
                SELECT att.attname
                FROM pg_constraint con
                JOIN pg_class rel ON rel.oid = con.conrelid
                JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
                JOIN unnest(con.conkey) WITH ORDINALITY AS keys(attnum, ord) ON TRUE
                JOIN pg_attribute att ON att.attrelid = rel.oid AND att.attnum = keys.attnum
                WHERE nsp.nspname = current_schema()
                  AND rel.relname = %s
                  AND con.conname = %s
                ORDER BY keys.ord
                """,
                [table_name, name],
            )
            constraint_columns = [row[0] for row in cursor.fetchall()]
            if constraint_columns == columns:
                matched_names.append(name)

    return matched_names


def _drop_postgres_constraint_if_exists(schema_editor, table_name, constraint_name):
    qn = schema_editor.quote_name
    schema_editor.execute(
        f"ALTER TABLE {qn(table_name)} DROP CONSTRAINT IF EXISTS {qn(constraint_name)}"
    )


def _create_postgres_unique_if_missing(schema_editor, table_name, constraint_name, columns):
    qn = schema_editor.quote_name
    existing = _fetch_postgres_unique_constraint_names(schema_editor, table_name, columns)
    if existing:
        return

    column_sql = ", ".join(qn(column) for column in columns)
    schema_editor.execute(
        f"ALTER TABLE {qn(table_name)} ADD CONSTRAINT {qn(constraint_name)} UNIQUE ({column_sql})"
    )


def _create_index_if_missing(schema_editor, table_name, index_name, columns):
    qn = schema_editor.quote_name
    column_sql = ", ".join(qn(column) for column in columns)
    schema_editor.execute(
        f"CREATE INDEX IF NOT EXISTS {qn(index_name)} ON {qn(table_name)} ({column_sql})"
    )


def _drop_index_if_exists(schema_editor, table_name, index_name):
    qn = schema_editor.quote_name
    vendor = schema_editor.connection.vendor
    if vendor in {"sqlite", "postgresql"}:
        schema_editor.execute(f"DROP INDEX IF EXISTS {qn(index_name)}")
    elif vendor == "mysql":
        schema_editor.execute(f"ALTER TABLE {qn(table_name)} DROP INDEX {qn(index_name)}")


def _reconcile_snapshot_bucket_uniques(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    snapshot_table = _resolve_table_name(schema_editor, "stockvaluationsnapshot")
    if snapshot_table:
        old_constraints = _fetch_postgres_unique_constraint_names(
            schema_editor,
            snapshot_table,
            SNAPSHOT_OLD_UNIQUE_FIELDS,
        )
        for name in old_constraints:
            _drop_postgres_constraint_if_exists(schema_editor, snapshot_table, name)
        _create_postgres_unique_if_missing(
            schema_editor,
            snapshot_table,
            SNAPSHOT_NEW_UNIQUE_NAME,
            SNAPSHOT_NEW_UNIQUE_FIELDS,
        )

    latest_table = _resolve_table_name(schema_editor, "stockvaluationsnapshotlatest")
    if latest_table:
        old_constraints = _fetch_postgres_unique_constraint_names(
            schema_editor,
            latest_table,
            LATEST_OLD_UNIQUE_FIELDS,
        )
        for name in old_constraints:
            _drop_postgres_constraint_if_exists(schema_editor, latest_table, name)
        _create_postgres_unique_if_missing(
            schema_editor,
            latest_table,
            LATEST_NEW_UNIQUE_NAME,
            LATEST_NEW_UNIQUE_FIELDS,
        )
        _create_index_if_missing(
            schema_editor,
            latest_table,
            LATEST_BUCKET_INDEX_NAME,
            ["market", "ts_code", "profit_report_type", "profit_data_source"],
        )


def _reconcile_snapshot_bucket_uniques_reverse(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return

    snapshot_table = _resolve_table_name(schema_editor, "stockvaluationsnapshot")
    if snapshot_table:
        _drop_postgres_constraint_if_exists(schema_editor, snapshot_table, SNAPSHOT_NEW_UNIQUE_NAME)

    latest_table = _resolve_table_name(schema_editor, "stockvaluationsnapshotlatest")
    if latest_table:
        _drop_postgres_constraint_if_exists(schema_editor, latest_table, LATEST_NEW_UNIQUE_NAME)
        _drop_index_if_exists(schema_editor, latest_table, LATEST_BUCKET_INDEX_NAME)


class Migration(migrations.Migration):

    dependencies = [
        ("prediction", "0015_alter_stockvaluationsnapshot_period_unique"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(
                    _reconcile_snapshot_bucket_uniques,
                    _reconcile_snapshot_bucket_uniques_reverse,
                )
            ],
            state_operations=[
                migrations.AlterUniqueTogether(
                    name="stockvaluationsnapshot",
                    unique_together={
                        (
                            "ts_code",
                            "trade_date",
                            "market",
                            "valuation_method",
                            "valuation_variant",
                            "profit_report_type",
                            "profit_report_end_date",
                            "profit_data_source",
                        )
                    },
                ),
                migrations.AlterUniqueTogether(
                    name="stockvaluationsnapshotlatest",
                    unique_together={
                        (
                            "ts_code",
                            "market",
                            "valuation_method",
                            "valuation_variant",
                            "profit_report_type",
                            "profit_data_source",
                        )
                    },
                ),
                migrations.AddIndex(
                    model_name="stockvaluationsnapshotlatest",
                    index=models.Index(
                        fields=["market", "ts_code", "profit_report_type", "profit_data_source"],
                        name=LATEST_BUCKET_INDEX_NAME,
                    ),
                ),
            ],
        ),
    ]