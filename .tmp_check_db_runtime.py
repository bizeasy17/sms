import os
from pathlib import Path

TARGETS = [
    ('DEV', Path(r'c:/Users/HANJ29/Development/code/sms/smartinvestor_be')),
    ('UAT', Path(r'c:/Users/HANJ29/Development/web/UAT/smartinvestor_be')),
]

for label, root in TARGETS:
    os.chdir(root)
    os.environ['DJANGO_SETTINGS_MODULE'] = 'smartinvestor_be.settings'
    import django
    django.setup()
    from django.db import connections
    print('=== ' + label + ' ===')
    for alias in ('default', 'earnings'):
        cfg = connections.databases.get(alias, {})
        print('CFG', alias, 'host=' + str(cfg.get('HOST')), 'port=' + str(cfg.get('PORT')), 'name=' + str(cfg.get('NAME')), 'user=' + str(cfg.get('USER')))
        try:
            with connections[alias].cursor() as c:
                c.execute('select current_database(), current_user')
                row = c.fetchone()
            print('LIVE', alias, 'db=' + str(row[0]), 'user=' + str(row[1]))
        except Exception as e:
            print('LIVE', alias, 'ERROR', str(e))
