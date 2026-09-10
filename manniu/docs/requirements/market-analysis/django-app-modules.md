# Market Analysis Django Modules

## 1 Scope

Create and register empty Django applications under `manniu_backend`:

- `traditional_valuation`: traditional valuation domain.
- `predictive_valuation`: predictive valuation domain.
- `stock_selection`: stock-selection domain.
- `backtest_engine`: backtesting domain.
- `financials`: financial data domain.
- `market_data`: market-data domain.
- `indices`: index-data domain.
- `market_sentiment`: market and stock end-of-day sentiment indicators (planned; not yet registered).

## 2 Confirmed Boundaries

- Each application is registered in Django settings.
- This change introduces no API endpoints, request fields, response fields, database models, migrations, or PostgreSQL schema changes.
- The modules must not implement automated trading execution.
- `market_sentiment` consumes persisted `market_data` records and does not own Tushare downloads.

## 3 Test Case Definition

### 3.1 Core Flow

- Django loads each application configuration.
- Each application name is present in `INSTALLED_APPS`.

### 3.2 Boundary Scenarios

- Empty application modules do not require a database connection to load.

### 3.3 Failure Scenarios

- An omitted registration or mismatched application configuration causes the focused test to fail.

### 3.4 TODO List

- [ ] 按本文档完成 Django 应用注册核验及对应单元测试，并在测试通过后更新本条状态。
