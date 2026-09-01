from django.db import models


class StockExtremeSnapshot(models.Model):
    ts_code = models.CharField(max_length=10, unique=True, db_index=True)
    name = models.CharField(max_length=50, blank=True, default="")
    daily_max_return = models.DecimalField(max_digits=24, decimal_places=12, null=True, blank=True)
    daily_min_return = models.DecimalField(max_digits=24, decimal_places=12, null=True, blank=True)
    weekly_max_return = models.DecimalField(max_digits=24, decimal_places=12, null=True, blank=True)
    weekly_min_return = models.DecimalField(max_digits=24, decimal_places=12, null=True, blank=True)
    monthly_max_return = models.DecimalField(max_digits=24, decimal_places=12, null=True, blank=True)
    monthly_min_return = models.DecimalField(max_digits=24, decimal_places=12, null=True, blank=True)
    max_runup = models.DecimalField(max_digits=24, decimal_places=12, null=True, blank=True)
    max_drawdown = models.DecimalField(max_digits=24, decimal_places=12, null=True, blank=True)
    source_start_date = models.DateField(null=True, blank=True)
    source_end_date = models.DateField(null=True, blank=True)
    price_type = models.CharField(max_length=16, default="qfq")
    calculated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["ts_code"]

    def __str__(self):
        return self.ts_code
