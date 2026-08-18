# Opt Stock Research Dashboard

## Goal

Create a new stock-research dashboard from
`stock-research-workspace_lean.html` without modifying existing frontend
components or backend business logic.

## URL Contract

- Page route: `/opt/stock-research-dashboard`
- This first version sends no API requests.
- Any later request added for this optimization module must use an `/opt/...`
  endpoint and must not change existing non-`/opt` endpoints.

## Module Layout

- `smartinvestor_fe/src/views/OptStockResearchDashboardView.vue`: route view,
  search, mobile drawer, company selection, and research-event panel.
- `smartinvestor_fe/src/modules/opt-stock-research/OptResearchRail.vue`:
  coverage-list module.
- `smartinvestor_fe/src/modules/opt-stock-research/OptResearchDossier.vue`:
  research dossier, valuation summary, trend, fundamentals, and tab interaction.
- `smartinvestor_fe/src/modules/opt-stock-research/researchData.ts`: isolated
  static prototype data. It avoids coupling the new page to existing API shapes.

## Interaction Coverage

- Search filters the coverage list by name, code, or industry.
- Choosing a company updates the dossier identity, quote, thesis, and position.
- Research navigation switches the active tab.
- The compact-screen drawer opens and closes from the menu button or backdrop.

## Contract Impact

No backend API, database schema, existing frontend component, or existing
business logic is changed. The only existing-file change registers the new
frontend route in `smartinvestor_fe/src/router/index.ts`.

## Validation

- `npm run build`: passed (`vue-tsc -b && vite build`).
- Browser smoke test: `/opt/stock-research-dashboard` rendered coverage list,
  dossier, valuation, trend, fundamentals, and event panel.
- Browser interaction smoke test: selecting `600066.SH` changed the dossier to
  Yutong Bus; switching to the traditional-valuation tab rendered its view.

## Rollback

Remove the `/opt/stock-research-dashboard` route registration and the new
`opt-stock-research` modules. No persisted data or external interface needs
rollback.

## Observation Stock API v1

- Endpoint: `GET /api/opt/v1/stock-observation/?limit=200&offset=0`
- Backend module: `smartinvestor_be/opt_api/`
- Data source: PostgreSQL `users.UserWatchlist`, filtered to the current user's
  enabled observation or holding records:
  `is_enabled=true AND (observe_only=true OR hold_a_position=true)`.
- Returned list fields: `ts_code`, `name`, `industry`, `tags`, `is_watchlist`,
  `is_holding`, and `is_observed`.
- Tag order is deterministic: `自`, `持`, `注`. All returned rows are enabled
  watchlist records; `持` and `注` are included only when their corresponding
  flags are set.

The opt Dashboard calls only this versioned opt URL. It displays the API tags
alongside each company name. The left rail never falls back to prototype stocks:
an API failure renders an explicit unavailable message, and a successful empty
response renders an empty observation-and-holding list.

## Observation API Validation

- `manage.py check`: passed.
- `py_compile opt_api/views.py opt_api/urls.py opt_api/tests.py`: passed.
- Read-only `APIRequestFactory` smoke test against PostgreSQL: `limit=3`
  returned `200` with three observation rows; invalid `limit=0` returned `400`.
- Read-only PostgreSQL smoke test after the scope change: returned `200`,
  `total=34`, and included all seven enabled legacy Dashboard holdings with no
  missing holding code.
- Browser end-to-end check: the Dashboard requested only
  `/api/opt/v1/stock-observation/?limit=200` and rendered 34 real rows. The
  seven legacy Dashboard holdings all displayed `持`; `600309.SH` displayed
  `自`/`持`/`注`.

The isolated Django test suite could not complete because the pre-existing
`test_smartinvestor` database has an unrelated valuation migration mismatch:
`valuation.0002` references a missing `valuation_stockvaluationsnapshothistory`
table. No test or production database was deleted to work around that state.