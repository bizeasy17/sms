from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [
        migrations.CreateModel(
            name='FinancialHealthSearchHistory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('user_key', models.CharField(max_length=64)),
                ('ts_code', models.CharField(max_length=18)),
                ('symbol', models.CharField(blank=True, default='', max_length=8)),
                ('name', models.CharField(blank=True, default='', max_length=128)),
                ('industry', models.CharField(blank=True, default='', max_length=128)),
                ('searched_at', models.DateTimeField(auto_now=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'db_table': 'metrics_financial_health_search_history',
                'indexes': [models.Index(fields=['user_key', 'searched_at'], name='metrics_fhsh_user_time')],
                'constraints': [models.UniqueConstraint(fields=('user_key', 'ts_code'), name='metrics_fhsh_user_ts')],
            },
        ),
    ]
