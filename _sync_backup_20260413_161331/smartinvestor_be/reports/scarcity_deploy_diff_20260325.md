# Scarcity Deploy Diff Checklist (2026-03-25)

## Source Commit
- HEAD: 858532d

## UAT Diff
- [DIFF] docs/valuation-changelog.md
- [DIFF] prediction/management/commands/estmktv.py
- [MISSING_UAT] prediction/services/business_fallback_engine.py
- [MISSING_UAT] prediction/services/output_formatter.py
- [MISSING_UAT] prediction/services/scarcity_auto_engine.py
- [DIFF] prediction/tests.py
- [MISSING_UAT] static/valuation_config/scarcity_auto_profile_CN.json

## Standalone Valuation Project Diff Signals
- [EXISTS] valuation_api/management/commands/estmktv.py
- [MISSING] valuation_api/services/scarcity_auto_engine.py
- [MISSING] static/valuation_config/scarcity_auto_profile_CN.json
- [NO_MARKERS] standalone estmktv does not contain scarcity-auto markers
