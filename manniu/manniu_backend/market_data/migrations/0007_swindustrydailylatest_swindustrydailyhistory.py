import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('market_data', '0006_citic_business_match'),
    ]

    operations = [
        migrations.CreateModel(
            name='SWIndustryDailyLatest',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('trade_date', models.DateField()),
                ('source_updated_at', models.DateTimeField(blank=True, null=True)),
                ('synced_at', models.DateTimeField(auto_now=True)),
                ('name', models.CharField(blank=True, max_length=128)),
                ('open', models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True)),
                ('high', models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True)),
                ('low', models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True)),
                ('close', models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True)),
                ('pre_close', models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True)),
                ('change', models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True)),
                ('pct_change', models.DecimalField(blank=True, decimal_places=6, max_digits=12, null=True)),
                ('vol', models.DecimalField(blank=True, decimal_places=4, max_digits=24, null=True)),
                ('amount', models.DecimalField(blank=True, decimal_places=4, max_digits=24, null=True)),
                ('pe', models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True)),
                ('pb', models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True)),
                ('float_share', models.DecimalField(blank=True, decimal_places=4, max_digits=28, null=True)),
                ('free_share', models.DecimalField(blank=True, decimal_places=4, max_digits=28, null=True)),
                ('total_share', models.DecimalField(blank=True, decimal_places=4, max_digits=28, null=True)),
                ('total_mv', models.DecimalField(blank=True, decimal_places=4, max_digits=28, null=True)),
                ('float_mv', models.DecimalField(blank=True, decimal_places=4, max_digits=28, null=True)),
                ('raw_payload', models.JSONField(default=dict)),
                ('security', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='sw_industry_daily_latest', to='market_data.security')),
            ],
            options={
                'abstract': False,
            },
        ),
        migrations.CreateModel(
            name='SWIndustryDailyHistory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('trade_date', models.DateField()),
                ('source_updated_at', models.DateTimeField(blank=True, null=True)),
                ('synced_at', models.DateTimeField(auto_now=True)),
                ('name', models.CharField(blank=True, max_length=128)),
                ('open', models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True)),
                ('high', models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True)),
                ('low', models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True)),
                ('close', models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True)),
                ('pre_close', models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True)),
                ('change', models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True)),
                ('pct_change', models.DecimalField(blank=True, decimal_places=6, max_digits=12, null=True)),
                ('vol', models.DecimalField(blank=True, decimal_places=4, max_digits=24, null=True)),
                ('amount', models.DecimalField(blank=True, decimal_places=4, max_digits=24, null=True)),
                ('pe', models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True)),
                ('pb', models.DecimalField(blank=True, decimal_places=6, max_digits=20, null=True)),
                ('float_share', models.DecimalField(blank=True, decimal_places=4, max_digits=28, null=True)),
                ('free_share', models.DecimalField(blank=True, decimal_places=4, max_digits=28, null=True)),
                ('total_share', models.DecimalField(blank=True, decimal_places=4, max_digits=28, null=True)),
                ('total_mv', models.DecimalField(blank=True, decimal_places=4, max_digits=28, null=True)),
                ('float_mv', models.DecimalField(blank=True, decimal_places=4, max_digits=28, null=True)),
                ('raw_payload', models.JSONField(default=dict)),
                ('security', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='sw_industry_daily_history', to='market_data.security')),
            ],
            options={
                'indexes': [models.Index(fields=['security', '-trade_date'], name='market_data_securit_426854_idx'), models.Index(fields=['trade_date', 'security'], name='market_data_trade_d_d9d584_idx')],
                'constraints': [models.UniqueConstraint(fields=('security', 'trade_date'), name='market_data_sw_daily_uniq')],
            },
        ),
    ]
