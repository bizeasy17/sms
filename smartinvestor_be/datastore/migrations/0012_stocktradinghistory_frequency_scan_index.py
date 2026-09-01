from django.db import migrations, models


class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ("datastore", "0011_corporation_sw_l3_fields"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql=(
                        "CREATE INDEX CONCURRENTLY IF NOT EXISTS "
                        "dst_trd_freq_code_date_idx ON "
                        "datastore_stocktradinghistory (freq, ts_code, trade_date)"
                    ),
                    reverse_sql=(
                        "DROP INDEX CONCURRENTLY IF EXISTS "
                        "dst_trd_freq_code_date_idx"
                    ),
                ),
            ],
            state_operations=[
                migrations.AddIndex(
                    model_name="stocktradinghistory",
                    index=models.Index(
                        fields=["freq", "ts_code", "trade_date"],
                        name="dst_trd_freq_code_date_idx",
                    ),
                ),
            ],
        ),
    ]
