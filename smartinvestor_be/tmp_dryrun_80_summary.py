import os
import datetime
import pandas as pd
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "smartinvestor_be.settings")
import django
django.setup()
from datastore.models import StockTradingHistory
from api.views import _build_latest_snapshot_method_map, _summarize_buy_candidate
from valuation.services.valuation_summary import (
    BUY_CANDIDATE_CORE_METHODS, BUY_CANDIDATE_SUPPORT_METHODS, BUY_CANDIDATE_OPTIONAL_METHODS,
    BUY_CANDIDATE_MIN_CORE_METHOD_COUNT, BUY_CANDIDATE_MIN_CORE_UNDER_COUNT,
    BUY_CANDIDATE_MIN_UNDER_METHOD_COUNT, BUY_CANDIDATE_MIN_COMPOSITE_GAP_PCT,
    BUY_CANDIDATE_MIN_CONSERVATIVE_GAP_PCT, BUY_CANDIDATE_CORE_LOWER_PRICE_MULTIPLIER,
    BUY_CANDIDATE_CORE_UPPER_PRICE_MULTIPLIER,
)

BAND=0.1
START=datetime.date.today()-datetime.timedelta(days=15)
END=datetime.date.today()

latest_day = StockTradingHistory.objects.filter(freq='D').order_by('-trade_date').values_list('trade_date', flat=True).first()
ts_codes=[]
for ts in StockTradingHistory.objects.filter(freq='D', trade_date=latest_day).order_by('-vol').values_list('ts_code', flat=True):
    if ts and ts not in ts_codes:
        ts_codes.append(ts)
    if len(ts_codes)>=80:
        break

def legacy_filter_core(valid_methods, current_price):
    filtered = {}
    lower = current_price * BUY_CANDIDATE_CORE_LOWER_PRICE_MULTIPLIER
    upper = current_price * BUY_CANDIDATE_CORE_UPPER_PRICE_MULTIPLIER
    for m in BUY_CANDIDATE_CORE_METHODS:
        p = valid_methods.get(m)
        if p is None:
            continue
        if lower <= p <= upper:
            filtered[m] = p
    if not filtered:
        return filtered
    prices = list(filtered.values())
    min_p, max_p = min(prices), max(prices)
    if min_p > 0 and (max_p / min_p) > 2.2:
        far = max(filtered.items(), key=lambda kv: abs(kv[1] - current_price))[0]
        filtered.pop(far, None)
    return filtered

def legacy_summarize(current_price, method_map, band_pct):
    out={"undervalue_score":None,"buy_candidate":False}
    if current_price in (None,0) or not method_map:
        return out
    current_price=float(current_price)
    valid={}
    for m,payload in (method_map or {}).items():
        p=(payload or {}).get('valuation_price')
        if p is None:
            continue
        p=float(p)
        if p>0:
            valid[m]=p
    if not valid:
        return out
    raw=[valid[m] for m in BUY_CANDIDATE_CORE_METHODS if m in valid]
    f=legacy_filter_core(valid,current_price)
    core=[f[m] for m in BUY_CANDIDATE_CORE_METHODS if m in f]
    support=[valid[m] for m in BUY_CANDIDATE_SUPPORT_METHODS if m in valid]
    optional=[valid[m] for m in BUY_CANDIDATE_OPTIONAL_METHODS if m in valid and 0.5*current_price<=valid[m]<=2.5*current_price]
    if len(core)>=BUY_CANDIDATE_MIN_CORE_METHOD_COUNT:
        cand=list(core)
    elif raw:
        cand=list(core or raw)
    else:
        cand=core+support+optional
    if not cand:
        return out
    composite=float(pd.Series(cand,dtype='float64').median())
    conservative=min(core or raw or cand)
    under=[m for m,p in valid.items() if current_price<=p*(1-band_pct)]
    core_under=[m for m in BUY_CANDIDATE_CORE_METHODS if m in f and current_price<=f[m]*(1-band_pct)]
    comp_gap=(composite-current_price)/current_price
    cons_gap=(conservative-current_price)/current_price
    vc,cc,cuc,uc=len(valid),len(core),len(core_under),len(under)
    score=0
    if vc>=4: score+=20
    elif vc>=3: score+=15
    elif vc>=2: score+=8
    if cc>=3: score+=25
    elif cc>=2: score+=18
    elif cc==1: score+=8
    if cuc>=3: score+=30
    elif cuc>=2: score+=24
    elif cuc==1: score+=16
    if uc>=4: score+=10
    elif uc>=3: score+=7
    elif uc>=2: score+=4
    if comp_gap>=0.3: score+=15
    elif comp_gap>=0.15: score+=10
    elif comp_gap>=band_pct: score+=5
    if cons_gap>=0.15: score+=10
    elif cons_gap>=0.08: score+=6
    elif cons_gap>=0.03: score+=3
    out['undervalue_score']=min(score,100)
    out['buy_candidate']=(
        cc>=BUY_CANDIDATE_MIN_CORE_METHOD_COUNT and cuc>=BUY_CANDIDATE_MIN_CORE_UNDER_COUNT and uc>=BUY_CANDIDATE_MIN_UNDER_METHOD_COUNT
        and comp_gap>=BUY_CANDIDATE_MIN_COMPOSITE_GAP_PCT and cons_gap>=BUY_CANDIDATE_MIN_CONSERVATIVE_GAP_PCT
    )
    return out

stats={'stocks':0,'days':0,'changed':0,'flip':0,'tf':0,'ft':0}
for ts in ts_codes:
    rows=list(StockTradingHistory.objects.filter(ts_code=ts,freq='D',trade_date__gte=START,trade_date__lte=END).order_by('trade_date').values('trade_date','close'))
    if not rows:
        continue
    stats['stocks']+=1
    for r in rows:
        stats['days']+=1
        d=r['trade_date']
        px=float(r['close']) if r.get('close') is not None else None
        mm=_build_latest_snapshot_method_map(ts_codes=[ts],market='CN',pick_strategy='latest_trade_then_updated',max_trade_date=d).get(ts,{}) or {}
        old=legacy_summarize(px,mm,BAND)
        new=_summarize_buy_candidate(px,mm,BAND)
        if old.get('undervalue_score')!=new.get('undervalue_score'):
            stats['changed']+=1
        if old.get('buy_candidate')!=new.get('buy_candidate'):
            stats['flip']+=1
            if old.get('buy_candidate') and not new.get('buy_candidate'):
                stats['tf']+=1
            elif (not old.get('buy_candidate')) and new.get('buy_candidate'):
                stats['ft']+=1

print(f"sample_stocks={stats['stocks']} latest_day={latest_day} range=[{START},{END}]")
print(f"days={stats['days']} changed_days={stats['changed']} flip_days={stats['flip']} old_true_new_false={stats['tf']} old_false_new_true={stats['ft']}")
if stats['days']:
    print(f"flip_ratio_pct={stats['flip']*100/stats['days']:.2f}")
