from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('financials', '0004_financialdisclosurerecord_actual_date_idx'),
    ]

    operations = [
        migrations.AddField(
            model_name='financialincomerecord',
            name='update_flag',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='financialbalancesheetrecord',
            name='update_flag',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='financialcashflowrecord',
            name='update_flag',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='financialindicatorrecord',
            name='update_flag',
            field=models.IntegerField(default=0),
        ),
        migrations.RunSQL(
            sql=[
                ("UPDATE financials_income_record SET update_flag = CASE WHEN raw_payload->>'update_flag' ~ '^[0-9]+$' THEN (raw_payload->>'update_flag')::integer ELSE 0 END", None),
                ("UPDATE financials_balance_sheet_record SET update_flag = CASE WHEN raw_payload->>'update_flag' ~ '^[0-9]+$' THEN (raw_payload->>'update_flag')::integer ELSE 0 END", None),
                ("UPDATE financials_cashflow_record SET update_flag = CASE WHEN raw_payload->>'update_flag' ~ '^[0-9]+$' THEN (raw_payload->>'update_flag')::integer ELSE 0 END", None),
                ("UPDATE financials_indicator_record SET update_flag = CASE WHEN raw_payload->>'update_flag' ~ '^[0-9]+$' THEN (raw_payload->>'update_flag')::integer ELSE 0 END", None),
            ],
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.AddIndex(
            model_name='financialincomerecord',
            index=models.Index(fields=['security', 'period', 'end_date', 'update_flag'], name='fin_inc_period_flag_idx'),
        ),
        migrations.AddIndex(
            model_name='financialbalancesheetrecord',
            index=models.Index(fields=['security', 'period', 'end_date', 'update_flag'], name='fin_bs_period_flag_idx'),
        ),
        migrations.AddIndex(
            model_name='financialcashflowrecord',
            index=models.Index(fields=['security', 'period', 'end_date', 'update_flag'], name='fin_cf_period_flag_idx'),
        ),
        migrations.AddIndex(
            model_name='financialindicatorrecord',
            index=models.Index(fields=['security', 'period', 'end_date', 'update_flag'], name='fin_ind_period_flag_idx'),
        ),
    ]