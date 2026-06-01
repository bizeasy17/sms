# Scarcity Change Deployment Execution (2026-03-25)

## Diff Checklist Files
- reports/scarcity_deploy_diff_20260325.md
- reports/scarcity_deploy_diff_20260325_post.md

## UAT Deployment
- Target: c:/Users/HANJ29/Development/web/UAT/smartinvestor_be
- Synced files from source commit 858532d:
  - docs/valuation-changelog.md
  - prediction/management/commands/estmktv.py
  - prediction/services/business_fallback_engine.py
  - prediction/services/output_formatter.py
  - prediction/services/scarcity_auto_engine.py
  - prediction/tests.py
  - static/valuation_config/scarcity_auto_profile_CN.json
- Dependency fix synced: prediction/utils/prediction_util.py
- Backup dirs:
  - backup/scarcity_deploy_*
  - backup/scarcity_deploy_fix_20260325_114058
- Validation:
  - compileall passed
  - manage.py estmktv --scarcity-profile auto --show-source passed

## Standalone Deployment
- Target: c:/Users/HANJ29/Development/code/sms/valuation_service_django
- Added files:
  - valuation_api/scarcity_auto_engine.py
  - static/valuation_config/scarcity_auto_profile_CN.json
- Updated command: valuation_api/management/commands/estmktv.py
  - added --scarcity-profile option
  - integrated ScarcityAutoEngine profile apply
  - show-source prints scarcity_profile_effective/auto_reason
- Validation:
  - compileall passed
  - manage.py estmktv --scarcity-profile auto --show-source passed

## 2026-03-25 Addendum: Composite Market-Cap Impact (Composite Only)
- Change scope:
  - smartinvestor_be/api/views.py
  - valuation_service_django/valuation_api/views.py
  - docs/valuation-changelog.md (both projects)
- Rule:
  - infer current market-cap from existing valuation rows;
  - apply size factor to `composite_valuation_price` only;
  - keep `conservative_valuation_price` and all single methods unchanged.
- Audit:
  - `buy_candidate_reason` now includes `size_factor`.

