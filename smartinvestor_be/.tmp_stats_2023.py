from django.apps import apps
from django.db.models import Count
import os

phase = os.getenv('PHASE', 'UNKNOWN')
model = next(m for m in apps.get_models() if m.__name__ == 'StockTradingHistory')

target_date = '2023-04-27'
qs_day = model.objects.filter(freq='D', trade_date=target_date)
db_codes = set(qs_day.values_list('ts_code', flat=True).distinct())
print(f"STAT|{phase}|DAY_COUNT|{target_date}|{len(db_codes)}")

daily = list(
    model.objects.filter(freq='D', trade_date__year=2023)
    .values('trade_date')
    .annotate(c=Count('ts_code', distinct=True))
)
if daily:
    min_row = sorted(daily, key=lambda x: (x['c'], x['trade_date']))[0]
    max_row = sorted(daily, key=lambda x: (-x['c'], x['trade_date']))[0]
    print(f"STAT|{phase}|YEAR_MIN|{min_row['trade_date']}|{min_row['c']}")
    print(f"STAT|{phase}|YEAR_MAX|{max_row['trade_date']}|{max_row['c']}")
else:
    print(f"STAT|{phase}|YEAR_MIN|NONE|0")
    print(f"STAT|{phase}|YEAR_MAX|NONE|0")

log_path = os.path.join('..', 'logs', 'event_codes_traditional_2024_2025', '2023-04-27.txt')
file_codes = set()
if os.path.exists(log_path):
    with open(log_path, 'r', encoding='utf-8') as f:
        for line in f:
            code = line.strip()
            if code:
                file_codes.add(code)

print(f"STAT|{phase}|EVENT_FILE_CODES|{target_date}|{len(file_codes)}")
print(f"STAT|{phase}|INTERSECTION|{target_date}|{len(file_codes & db_codes)}")
