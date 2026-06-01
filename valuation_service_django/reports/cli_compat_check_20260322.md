# CLI Compatibility Check 20260322

- New command: manage.py estmktv --trade-date
- Legacy command: manage.py estmktv --trade_date
- Both commands executed successfully for 688002.SH with --show-source and produced valuation rows.

## Evidence
- reports/exec_logs/step04_new_template_688002.txt
- reports/exec_logs/step05_old_template_688002.txt
- reports/exec_logs/g14_new_688002_profit_source.txt
- reports/exec_logs/g14_old_688002_profit_source.txt
