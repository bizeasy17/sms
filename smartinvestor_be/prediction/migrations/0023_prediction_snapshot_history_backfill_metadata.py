from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("prediction", "0022_stockthsmoneyflowdaily_field_mapping_1to1"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            ALTER TABLE IF EXISTS prediction_stockvaluationsnapshothistory
                ADD COLUMN IF NOT EXISTS is_backfill boolean NOT NULL DEFAULT false,
                ADD COLUMN IF NOT EXISTS backfill_run_id varchar(64) NOT NULL DEFAULT '',
                ADD COLUMN IF NOT EXISTS refresh_policy varchar(16) NOT NULL DEFAULT '',
                ADD COLUMN IF NOT EXISTS price_anchor_mode varchar(24) NOT NULL DEFAULT '',
                ADD COLUMN IF NOT EXISTS target_report_type varchar(16) NOT NULL DEFAULT '',
                ADD COLUMN IF NOT EXISTS profit_bucket_mode varchar(16) NOT NULL DEFAULT '';

            CREATE INDEX IF NOT EXISTS prediction_svsh_backfill_archived_idx
                ON prediction_stockvaluationsnapshothistory (is_backfill, archived_at);
            CREATE INDEX IF NOT EXISTS prediction_svsh_backfill_run_idx
                ON prediction_stockvaluationsnapshothistory (backfill_run_id);
            CREATE INDEX IF NOT EXISTS prediction_svsh_refresh_policy_idx
                ON prediction_stockvaluationsnapshothistory (refresh_policy);
            """,
            reverse_sql="""
            DROP INDEX IF EXISTS prediction_svsh_backfill_archived_idx;
            DROP INDEX IF EXISTS prediction_svsh_backfill_run_idx;
            DROP INDEX IF EXISTS prediction_svsh_refresh_policy_idx;
            """,
        ),
    ]