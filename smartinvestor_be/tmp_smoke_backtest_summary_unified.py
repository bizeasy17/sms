import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "smartinvestor_be.settings")
import django
django.setup()

from prediction.management.commands.backtestmarketstyleadjustment import _build_summary_by_variant

rows = [
    {"valuation_variant":"default","valuation_method":"pe","valuation_price":12.0,"match_score":None,"compare_group":None},
    {"valuation_variant":"default","valuation_method":"pb","valuation_price":11.0,"match_score":None,"compare_group":None},
    {"valuation_variant":"default","valuation_method":"ps","valuation_price":10.0,"match_score":None,"compare_group":None},
]
summary_by_variant, variant_meta = _build_summary_by_variant(rows, current_price=8.0, band_pct=0.1)
print(summary_by_variant)
print(variant_meta)
