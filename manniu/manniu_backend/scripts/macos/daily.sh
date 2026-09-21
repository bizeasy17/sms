#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PYTHON="$PROJECT_ROOT/.venv/bin/python"
LOG_DIR="$PROJECT_ROOT/log/daily"
LOCK_DIR="$PROJECT_ROOT/log/daily/.lock"
CORE_INDICES='000001.SH,399001.SZ,000300.SH,000016.SH,000905.SH,399005.SZ,399006.SZ'

mkdir -p "$LOG_DIR"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    printf '[%s] daily job is already running; exiting.\n' "$(date '+%Y-%m-%d %H:%M:%S')" >> "$LOG_DIR/cron.log"
    exit 0
fi
trap 'rmdir "$LOCK_DIR" 2>/dev/null || true' EXIT

RUN_TIMESTAMP="$(date '+%Y%m%d_%H%M%S')"
LOG_FILE="$LOG_DIR/daily_${RUN_TIMESTAMP}.log"
exec > >(tee -a "$LOG_FILE") 2>&1

run() {
    printf '[%s] START %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
    "$PYTHON" manage.py "$@"
    printf '[%s] DONE %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"
}

cd "$PROJECT_ROOT"
printf '[%s] Daily market-data synchronization started.\n' "$(date '+%Y-%m-%d %H:%M:%S')"

run sync_market_data --dataset security-master --mode daily --scope all --strategy by-code
run sync_market_data --dataset index-master --mode daily --scope all --strategy by-code
run sync_market_data --dataset company-profile --mode daily --scope all --strategy by-code
run sync_market_data --dataset stock-bars --mode daily --scope all --strategy by-date
run sync_market_data --dataset stock-fundamentals --mode daily --scope all --strategy by-date
run sync_market_data --dataset stock-cost --mode daily --scope all --strategy by-date
run sync_market_data --dataset index-bars --mode daily --scope ts-code --ts-codes "$CORE_INDICES"
run sync_market_data --dataset index-fundamentals --mode daily --scope ts-code --ts-codes "$CORE_INDICES"
run sync_market_data --dataset sw-industry-daily --mode daily --scope all --strategy by-date
run detect_regime_events --scope all
run sync_financials --mode daily --scope actual-date
run traditional_valuation refresh --scope all --limit 100 --retry-failed
run predictive_valuation refresh --scope all --limit 500 --retry-failed

printf '[%s] Daily market-data synchronization completed.\n' "$(date '+%Y-%m-%d %H:%M:%S')"