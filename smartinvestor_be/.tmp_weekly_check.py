from pathlib import Path
from api import views

def normalize(res):
    a, b = res
    if isinstance(a, (str, Path)):
        used = a
        rows = b
    else:
        rows = a
        used = b
    return str(used), len(rows)

t_dates = list(views._list_weekly_undervalued_dates("traditional"))
p_dates = list(views._list_weekly_undervalued_dates("predictive"))
print("TRADITIONAL_TOP5=" + ",".join(str(x) for x in t_dates[:5]))
print("PREDICTIVE_TOP5=" + ",".join(str(x) for x in p_dates[:5]))

used_none, cnt_none = normalize(views._load_weekly_undervalued_rows("traditional", pick_date=None))
print(f"ROWS_NONE_FILE={used_none}")
print(f"ROWS_NONE_COUNT={cnt_none}")

used_pick, cnt_pick = normalize(views._load_weekly_undervalued_rows("traditional", pick_date="2026-05-18"))
print(f"ROWS_2026_05_18_FILE={used_pick}")
print(f"ROWS_2026_05_18_COUNT={cnt_pick}")

avail = set(str(x) for x in t_dates)
print("TODAY_IN_AVAILABLE=" + ("YES" if "2026-05-18" in avail else "NO"))