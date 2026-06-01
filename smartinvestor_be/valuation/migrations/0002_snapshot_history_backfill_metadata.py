from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("valuation", "0001_fund_tables"),
        ("prediction", "0017_history_backfill_metadata"),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            ALTER TABLE IF EXISTS valuation_stockvaluationsnapshothistory
                ADD COLUMN IF NOT EXISTS is_backfill boolean NOT NULL DEFAULT false,
                ADD COLUMN IF NOT EXISTS backfill_run_id varchar(64) NOT NULL DEFAULT '',
                ADD COLUMN IF NOT EXISTS refresh_policy varchar(16) NOT NULL DEFAULT '',
                ADD COLUMN IF NOT EXISTS price_anchor_mode varchar(24) NOT NULL DEFAULT '',
                ADD COLUMN IF NOT EXISTS target_report_type varchar(16) NOT NULL DEFAULT '',
                ADD COLUMN IF NOT EXISTS profit_bucket_mode varchar(16) NOT NULL DEFAULT '';

            CREATE INDEX IF NOT EXISTS idx_svsh_mkt_dt_method
                ON valuation_stockvaluationsnapshothistory (market, trade_date, valuation_method);
            CREATE INDEX IF NOT EXISTS idx_svsh_bf_archived
                ON valuation_stockvaluationsnapshothistory (is_backfill, archived_at);
            CREATE INDEX IF NOT EXISTS valuation_stockvaluationsnapshothistory_backfill_run_id_idx
                ON valuation_stockvaluationsnapshothistory (backfill_run_id);
            CREATE INDEX IF NOT EXISTS valuation_stockvaluationsnapshothistory_refresh_policy_idx
                ON valuation_stockvaluationsnapshothistory (refresh_policy);
            CREATE INDEX IF NOT EXISTS valuation_stockvaluationsnapshothistory_price_anchor_mode_idx
                ON valuation_stockvaluationsnapshothistory (price_anchor_mode);
            CREATE INDEX IF NOT EXISTS valuation_stockvaluationsnapshothistory_target_report_type_idx
                ON valuation_stockvaluationsnapshothistory (target_report_type);
            CREATE INDEX IF NOT EXISTS valuation_stockvaluationsnapshothistory_profit_bucket_mode_idx
                ON valuation_stockvaluationsnapshothistory (profit_bucket_mode);
            """,
            reverse_sql="""
            DROP INDEX IF EXISTS idx_svsh_mkt_dt_method;
            DROP INDEX IF EXISTS idx_svsh_bf_archived;
            DROP INDEX IF EXISTS valuation_stockvaluationsnapshothistory_backfill_run_id_idx;
            DROP INDEX IF EXISTS valuation_stockvaluationsnapshothistory_refresh_policy_idx;
            DROP INDEX IF EXISTS valuation_stockvaluationsnapshothistory_price_anchor_mode_idx;
            DROP INDEX IF EXISTS valuation_stockvaluationsnapshothistory_target_report_type_idx;
            DROP INDEX IF EXISTS valuation_stockvaluationsnapshothistory_profit_bucket_mode_idx;

            ALTER TABLE IF EXISTS valuation_stockvaluationsnapshothistory
                DROP COLUMN IF EXISTS is_backfill,
                DROP COLUMN IF EXISTS backfill_run_id,
                DROP COLUMN IF EXISTS refresh_policy,
                DROP COLUMN IF EXISTS price_anchor_mode,
                DROP COLUMN IF EXISTS target_report_type,
                DROP COLUMN IF EXISTS profit_bucket_mode;
            """,
        ),
    ]
