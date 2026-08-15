import os, csv, re, requests
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'market_data_service.settings')
import django
django.setup()
from market_data_service.market_data_core.models import CompanyProfileLatest

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36'}

def clean_url(raw):
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    text = text.replace(' ', '')
    if re.match(r'^https?://', text, re.I):
        return text
    return 'https://' + text

def probe(url):
    text = clean_url(url)
    if not text:
        return {'raw': url, 'ok': False, 'final_url': None, 'status': None, 'scheme': None, 'reason': 'empty'}
    if text.startswith('http://'):
        candidates = [text]
    elif text.startswith('https://'):
        candidates = [text]
    else:
        candidates = ['https://' + text, 'http://' + text]
    seen = []
    ordered = []
    for c in candidates:
        if c not in seen:
            seen.append(c)
            ordered.append(c)
    last = None
    for c in ordered:
        try:
            r = requests.get(c, headers=HEADERS, timeout=8, allow_redirects=True, verify=True)
            last = {'raw': url, 'candidate': c, 'ok': True, 'final_url': r.url, 'status': r.status_code, 'scheme': c.split('://', 1)[0].lower(), 'reason': None}
            if r.ok:
                return last
        except Exception as exc:
            last = {'raw': url, 'candidate': c, 'ok': False, 'final_url': None, 'status': None, 'scheme': c.split('://', 1)[0].lower(), 'reason': str(exc)}
    return last or {'raw': url, 'ok': False, 'final_url': None, 'status': None, 'scheme': None, 'reason': 'unknown'}

rows = list(CompanyProfileLatest.objects.exclude(website__isnull=True).exclude(website='').order_by('ts_code'))
results = []
for row in rows:
    r = probe(row.website)
    results.append({'ts_code': row.ts_code, 'name': row.name, 'raw': row.website, **r})

ok = [x for x in results if x['ok']]
bad = [x for x in results if not x['ok']]
print(f'ACCESSIBLE_COUNT:{len(ok)}')
for x in ok[:20]:
    print(f"{x['ts_code']}|{x['name']}|{x['final_url']}|{x['status']}")
print(f'UNACCESSIBLE_COUNT:{len(bad)}')
for x in bad[:20]:
    print(f"{x['ts_code']}|{x['name']}|{x['raw']}|{x['reason']}")

with open('company_website_probe.csv', 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=['ts_code','name','raw','candidate','ok','final_url','status','scheme','reason'])
    writer.writeheader()
    for x in results:
        writer.writerow(x)
print('CSV_PATH:company_website_probe.csv')
