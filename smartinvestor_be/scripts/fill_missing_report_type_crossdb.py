import os
from django.db import connections, transaction
from prediction.models import StockValuationSnapshotHistory as H

TABLE = H._meta.db_table
START = os.getenv("START_DATE", "2023-01-01")
END = os.getenv("END_DATE", "2024-12-31")


def to_yyyymmdd(v):
    if v is None:
        return ""
    s = str(v).strip()
    if not s:
        return ""
    d = "".join(ch for ch in s if ch.isdigit())
    return d[:8] if len(d) >= 8 else ""


def report_type_from_end(end_date_text):
    if not end_date_text or len(end_date_text) != 8:
        return None
    md = end_date_text[4:]
    if md == "0331":
        return "Q1"
    if md == "0630":
        return "H1"
    if md == "0930":
        return "Q3"
    if md == "1231":
        return "ANNUAL"
    return None


def load_source_rows(ts_code):
    sql = """
        SELECT end_date, ann_date
        FROM (
          SELECT end_date, ann_date FROM earnings_fin_fina_indicator_vip WHERE ts_code=%s AND end_date IS NOT NULL
          UNION ALL
          SELECT end_date, ann_date FROM earnings_fin_income WHERE ts_code=%s AND end_date IS NOT NULL
        ) s
    """
    with connections["earnings"].cursor() as cur:
        cur.execute(sql, [ts_code, ts_code])
        rows = cur.fetchall()

    parsed = []
    for end_date, ann_date in rows:
        end_t = to_yyyymmdd(end_date)
        ann_t = to_yyyymmdd(ann_date)
        if not end_t:
            continue
        ann_key = ann_t if ann_t else "00000000"
        parsed.append((ann_key, end_t, ann_t))

    parsed.sort(key=lambda x: (x[0], x[1], x[2]))
    return parsed


def build_trade_date_mapping(trade_dates, source_rows):
    mapping = {}
    i = 0
    n = len(source_rows)
    best = None
    for td in sorted(trade_dates):
        td_text = to_yyyymmdd(td)
        while i < n and source_rows[i][0] <= td_text:
            _ann_key, end_t, ann_t = source_rows[i]
            cand = (end_t, ann_t)
            if best is None or cand > best:
                best = cand
            i += 1
        mapping[td] = report_type_from_end(best[0]) if best is not None else None
    return mapping


stats = {
    "updated_rows": 0,
    "resolved_pairs": 0,
    "unresolved_pairs": 0,
    "processed_ts": 0,
}

with connections["default"].cursor() as cur:
    cur.execute(
        f"""
        SELECT COUNT(*)
        FROM {TABLE}
        WHERE market='CN'
          AND trade_date BETWEEN %s AND %s
          AND profit_data_source='fina_indicator_income'
          AND profit_report_type IS NULL
    """,
        [START, END],
    )
    before_null = cur.fetchone()[0]

print(f"XDBFILL|start={START}|end={END}")
print(f"XDBFILL|before_null={before_null}")

pair_sql = f"""
    SELECT ts_code, trade_date
    FROM {TABLE}
    WHERE market='CN'
      AND trade_date BETWEEN %s AND %s
      AND profit_data_source='fina_indicator_income'
      AND profit_report_type IS NULL
    GROUP BY ts_code, trade_date
    ORDER BY ts_code, trade_date
"""


def flush_one(ts_code, date_list):
    if not ts_code or not date_list:
        return

    stats["processed_ts"] += 1
    src_rows = load_source_rows(ts_code)
    mapping = build_trade_date_mapping(date_list, src_rows)

    update_params = []
    for td in date_list:
        rt = mapping.get(td)
        if rt:
            update_params.append((rt, ts_code, td, START, END))
            stats["resolved_pairs"] += 1
        else:
            stats["unresolved_pairs"] += 1

    if update_params:
        with transaction.atomic(using="default"):
            with connections["default"].cursor() as cur_u:
                cur_u.executemany(
                    f"""
                    UPDATE {TABLE}
                    SET profit_report_type = %s
                    WHERE ts_code = %s
                      AND trade_date = %s
                      AND market='CN'
                      AND trade_date BETWEEN %s AND %s
                      AND profit_data_source='fina_indicator_income'
                      AND profit_report_type IS NULL
                    """,
                    update_params,
                )
                stats["updated_rows"] += cur_u.rowcount

    if stats["processed_ts"] % 100 == 0:
        print(
            f"XDBFILL|progress_ts={stats['processed_ts']}|resolved_pairs={stats['resolved_pairs']}|"
            f"unresolved_pairs={stats['unresolved_pairs']}|updated_rows={stats['updated_rows']}"
        )


with connections["default"].cursor() as cur_pairs:
    cur_pairs.execute(pair_sql, [START, END])
    current_ts = None
    trade_dates = []

    while True:
        rows = cur_pairs.fetchmany(5000)
        if not rows:
            break
        for ts_code, trade_date in rows:
            if current_ts is None:
                current_ts = ts_code
            if ts_code != current_ts:
                flush_one(current_ts, trade_dates)
                current_ts = ts_code
                trade_dates = []
            trade_dates.append(trade_date)

    flush_one(current_ts, trade_dates)

with connections["default"].cursor() as cur:
    cur.execute(
        f"""
        SELECT COUNT(*)
        FROM {TABLE}
        WHERE market='CN'
          AND trade_date BETWEEN %s AND %s
          AND profit_data_source='fina_indicator_income'
          AND profit_report_type IS NULL
    """,
        [START, END],
    )
    after_null = cur.fetchone()[0]

print(f"XDBFILL|processed_ts={stats['processed_ts']}")
print(f"XDBFILL|resolved_pairs={stats['resolved_pairs']}|unresolved_pairs={stats['unresolved_pairs']}")
print(f"XDBFILL|updated_rows={stats['updated_rows']}")
print(f"XDBFILL|after_null={after_null}")
print(f"XDBFILL|delta_null={before_null - after_null}")
