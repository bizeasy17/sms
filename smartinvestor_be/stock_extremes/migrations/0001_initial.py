from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="StockExtremeSnapshot",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("ts_code", models.CharField(db_index=True, max_length=10, unique=True)),
                ("name", models.CharField(blank=True, default="", max_length=50)),
                ("daily_max_return", models.DecimalField(blank=True, decimal_places=12, max_digits=24, null=True)),
                ("daily_min_return", models.DecimalField(blank=True, decimal_places=12, max_digits=24, null=True)),
                ("weekly_max_return", models.DecimalField(blank=True, decimal_places=12, max_digits=24, null=True)),
                ("weekly_min_return", models.DecimalField(blank=True, decimal_places=12, max_digits=24, null=True)),
                ("monthly_max_return", models.DecimalField(blank=True, decimal_places=12, max_digits=24, null=True)),
                ("monthly_min_return", models.DecimalField(blank=True, decimal_places=12, max_digits=24, null=True)),
                ("max_runup", models.DecimalField(blank=True, decimal_places=12, max_digits=24, null=True)),
                ("max_drawdown", models.DecimalField(blank=True, decimal_places=12, max_digits=24, null=True)),
                ("source_start_date", models.DateField(blank=True, null=True)),
                ("source_end_date", models.DateField(blank=True, null=True)),
                ("price_type", models.CharField(default="qfq", max_length=16)),
                ("calculated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"ordering": ["ts_code"]},
        ),
    ]
