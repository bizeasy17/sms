from datetime import date, datetime, timedelta
from pathlib import Path
from django.core.management import call_command
from valuation_risk.models import ValuationRiskSnapshot, ValuationRiskFactor

start = date(2023,1,1)
end = date(2024,12,31)
market = 'CN'
log_path = Path(r"C:/Users/HANJ29/Development/web/UAT/logs/backfill_valuation_risk_2023_2024.log")
ckpt_path = Path(r"C:/Users/HANJ29/Development/web/UAT/logs/backfill_valuation_risk_2023_2024.checkpoint")

resume = None
if ckpt_path.exists():
    txt = ckpt_path.read_text(encoding='utf-8').strip()
    if txt:
        try:
            resume = datetime.strptime(txt, '%Y-%m-%d').date()
        except Exception:
            resume = None

def log(msg):
    with log_path.open('a', encoding='utf-8') as f:
        f.write(msg + "\n")

log(f"[INFO] risk backfill python-resume start {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} resume={resume}")

cur = start
failed = False
while cur <= end:
    if resume and cur <= resume:
        cur += timedelta(days=1)
        continue

    ds = cur.strftime('%Y-%m-%d')
    log(f"[STEP] {ds}")
    try:
        call_command(
            'prefillvaluationrisk',
            market=market,
            snapshot_source='history',
            trade_date=ds,
            progress_interval=500,
        )
        ckpt_path.write_text(ds, encoding='utf-8')
        log(f"[OK] {ds}")
    except Exception as e:
        log(f"[WARN] {ds} first_try_failed: {repr(e)}")
        # 清理当日后重试一次，避免唯一键冲突阻断全流程
        ValuationRiskFactor.objects.filter(snapshot__market=market, snapshot__trade_date=cur).delete()
        ValuationRiskSnapshot.objects.filter(market=market, trade_date=cur).delete()
        try:
            call_command(
                'prefillvaluationrisk',
                market=market,
                snapshot_source='history',
                trade_date=ds,
                progress_interval=500,
            )
            ckpt_path.write_text(ds, encoding='utf-8')
            log(f"[OK_AFTER_CLEAN] {ds}")
        except Exception as e2:
            log(f"[ERROR] date={ds} retry_failed: {repr(e2)}")
            failed = True
            break

    cur += timedelta(days=1)

log(f"[INFO] risk backfill python-resume end {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} failed={failed}")
if failed:
    raise SystemExit(1)