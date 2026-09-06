# Market Analysis Django Modules

## Scope

Create and register empty Django applications under `manniu_backend`:

- `traditional_valuation`: traditional valuation domain.
- `predictive_valuation`: predictive valuation domain.
- `stock_selection`: stock-selection domain.
- `backtest_engine`: backtesting domain.
- `financials`: financial data domain.
- `market_data`: market-data domain.
- `indices`: index-data domain.
- `market_sentiment`: market and stock end-of-day sentiment indicators (planned; not yet registered).

## Confirmed Boundaries

- Each application is registered in Django settings.
- This change introduces no API endpoints, request fields, response fields, database models, migrations, or PostgreSQL schema changes.
- The modules must not implement automated trading execution.
- `market_sentiment` consumes persisted `market_data` records and does not own Tushare downloads.

## Test Case Definition

### Core Flow

- Django loads each application configuration.
- Each application name is present in `INSTALLED_APPS`.

### Boundary Scenarios

- Empty application modules do not require a database connection to load.

### Failure Scenarios

- An omitted registration or mismatched application configuration causes the focused test to fail.
