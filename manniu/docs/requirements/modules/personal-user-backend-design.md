# Personal User Module Requirements

## 1. Module Positioning

`personal_user` is the user-owned preference and position module for Manniu. It
provides the minimum personal workspace needed to manage:

- personal profile information;
- watchlist stocks (`自选股`);
- observation stocks (`观察股`);
- held stocks (`持仓股`);
- user-defined holding portfolios (`持仓组合`).

The module persists to PostgreSQL. It uses the authenticated Django user as the
identity source and references the canonical `market_data.Security` record for
securities. It must not maintain a second user table or a second security
master.

This document is a first-stage requirements design. It defines the business
contract and leaves implementation details such as serializer classes and
pagination helpers to the backend implementation design.

## 2. Ownership Boundaries

| Capability | Owner | `personal_user` responsibility |
| --- | --- | --- |
| Login, password, token, session, role and scope | `manniu_auth` | Consume the authenticated user context supplied by API Gateway |
| Canonical security, `ts_code`, name and listing status | `market_data` | Validate and reference a `Security` |
| Personal profile and contact fields | `personal_user` | Store and expose the user's own data |
| Watchlist and observation relationships | `personal_user` | Store, order and manage user selections |
| Holding quantities, cost basis and portfolio membership | `personal_user` | Store user-entered position ledger |
| Quotes, valuation, recommendations and market analysis | Their owning modules | Read-only aggregation only when explicitly required |
| Orders, brokerage connection and automatic trading | Out of scope | Must not be implemented |

The resources are exposed through the API Gateway under `/api/v1/me/*`. The
Gateway owns route registration, request context and the public API envelope.
`personal_user` must reuse the Gateway authentication facade, which delegates
Bearer token validation to `manniu_auth`; it must not independently parse or
validate access tokens. The Gateway must call `personal_user` query/command
services rather than performing direct cross-module ORM writes.

The API catalog exposed by the Gateway includes a `personal_user` group for
frontend discovery and trial calls. Catalog access remains protected by the
Gateway's existing `market_analysis:read` scope; access to `/api/v1/me/*`
requires a valid authenticated user but does not require market-analysis
scope.

## 3. User and Data Model

All business rows include `created_at` and `updated_at` timestamps. User-owned
rows are isolated by `user_id`; an authenticated user can never read or modify
another user's rows through an ordinary personal-user API.

### 3.1 `PersonalProfile`

One row per authenticated user. The row is created lazily on first profile
read/write or as part of user registration.

| Field | Type | Rules |
| --- | --- | --- |
| `id` | bigint | Primary key |
| `user_id` | FK to `auth.User` | Unique, cascade on user deletion |
| `display_name` | varchar(128) | Optional; UI display name |
| `email` | varchar(254) | Optional initially; normalized and verified state exposed separately |
| `email_verified_at` | timestamptz | Nullable; no verification means null |
| `mobile` | varchar(32) | Optional; normalized to one documented format |
| `mobile_verified_at` | timestamptz | Nullable; no verification means null |
| `timezone` | varchar(64) | Default follows `AuthProfile` or system default |
| `avatar_url` | varchar(512) | Optional URL; no binary upload in first stage |
| `created_at` / `updated_at` | timestamptz | Automatically maintained |

The profile must not store passwords, access tokens, raw identity documents or
unhashed security answers. Email/mobile uniqueness, verification delivery and
whether either contact can become a login identifier require product/security
confirmation before implementation. Until then, the existing `username`
login contract remains unchanged.

### 3.2 `UserSecurityListItem`

This is the common persistence model for `自选股` and `观察股`.

| Field | Type | Rules |
| --- | --- | --- |
| `id` | bigint | Primary key |
| `user_id` | FK | Owner |
| `security_id` | FK to `market_data.Security` | Required; canonical security reference |
| `list_type` | enum | `WATCHLIST` or `OBSERVATION` |
| `sort_order` | integer | Non-negative; user-defined order |
| `note` | varchar(512) | Optional private note |
| `created_at` / `updated_at` | timestamptz | Automatically maintained |

Unique constraint: `(user_id, security_id, list_type)`.

The same security may exist in both list types. Adding an item is idempotent;
repeated add requests return the existing item. Deleting an item only removes
the user's relationship and never deletes `Security` or market history.

### 3.3 `HoldingPortfolio`

A named container for a user's positions. Every user has a default portfolio
created on first holding write; additional portfolios are optional.

| Field | Type | Rules |
| --- | --- | --- |
| `id` | bigint | Primary key |
| `user_id` | FK | Owner |
| `name` | varchar(128) | Required; unique per user after normalization |
| `description` | varchar(512) | Optional |
| `is_default` | boolean | At most one default portfolio per user |
| `sort_order` | integer | Non-negative |
| `created_at` / `updated_at` | timestamptz | Automatically maintained |
| `archived_at` | timestamptz | Nullable; archived portfolios are read-only |

The first version supports manual portfolio management only. Deleting a
portfolio requires either moving its positions to another portfolio or an
explicit confirmation that its positions will be deleted. The default
portfolio cannot be deleted while it is the only active portfolio.

### 3.4 `HoldingPosition`

Represents the current user-entered position of one security in one portfolio.
It is a position snapshot, not a complete transaction ledger.

| Field | Type | Rules |
| --- | --- | --- |
| `id` | bigint | Primary key |
| `user_id` | FK | Denormalized owner for isolation and query efficiency |
| `portfolio_id` | FK to `HoldingPortfolio` | Must belong to the same user |
| `security_id` | FK to `market_data.Security` | Required |
| `quantity` | decimal(20,4) | Non-negative; shares held |
| `available_quantity` | decimal(20,4) | Non-negative and not greater than `quantity` |
| `average_cost` | decimal(20,6) | Non-negative; user-entered average cost per share |
| `cost_currency` | char(3) | Default `CNY` |
| `note` | varchar(512) | Optional private note |
| `as_of_date` | date | Date represented by the snapshot |
| `created_at` / `updated_at` | timestamptz | Automatically maintained |

Unique constraint: `(portfolio_id, security_id)`.

Zero-quantity positions may be retained for history-free UI purposes only if
the API explicitly supports that state; the default behavior is to remove the
position when quantity becomes zero. The module does not infer cost, calculate
taxes, handle corporate actions or claim that the snapshot is broker truth.

## 4. Functional Requirements

### 4.1 Profile

1. The authenticated user can read their own profile.
2. The authenticated user can update display name, email, mobile, timezone and
   avatar URL subject to field validation.
3. The response includes verification timestamps/status but never exposes
   credentials or token data.
4. Partial updates are supported; omitted fields remain unchanged.
5. Invalid email, mobile, timezone or URL input returns a field-level validation
   error without partially applying the update.

### 4.2 Watchlist and Observation List

1. The user can list, add, update note/order, and remove items in each list.
2. List responses include canonical `ts_code`, security name, list type, note,
   sort order and relation timestamps. Market metrics are not owned by this
   module and may be added only through an explicit read aggregation.
3. Add and remove operations are idempotent where practical.
4. Batch reorder accepts an ordered list of this user's item IDs and rejects
   duplicate, missing or foreign IDs atomically.
5. A missing, delisted or invalid security produces a typed business error; the
   API must not create an orphan relationship from an arbitrary text code.

### 4.3 Portfolios and Holdings

1. The user can create, rename, reorder, archive and list their portfolios.
2. The user can create, replace, update and remove one position per security in
   a portfolio.
3. Holding writes validate ownership of both portfolio and security in one
   transaction.
4. Quantity, available quantity, average cost and date are validated before
   persistence; negative values and `available_quantity > quantity` are
   rejected.
5. Portfolio detail returns positions and basic totals based only on stored
   position data. Live market value, daily P/L and return calculations require
   a separate confirmed aggregation contract with `market_data`.
6. A holding may also appear in the watchlist or observation list; these are
   independent relationships and must not be silently synchronized.

## 5. API Requirements

The resource paths are registered by API Gateway under `/api/v1/me` and require
an `Authorization: Bearer <access_token>` header. Gateway route registration
and auth integration are part of this module contract, not a follow-up task.

Gateway integration points:

- Gateway route module: `api_gateway.personal_urls`.
- Personal-user route implementation: `personal_user.api.urls` and
   `personal_user.api.views`.
- Authentication facade: `api_gateway.permissions.authenticate_request`.
- Identity source after authentication: `request.auth_access.session.user`.
- Frontend API catalog: `GET /api/v1/public-api/catalog`, authenticated with
   the Gateway's `market_analysis:read` scope.
- Personal-user endpoint responses use the common Gateway-compatible envelope
   with `success`, `api_version`, `request_id`, `data` or `error`.

| Method | Path | Purpose |
| --- | --- | --- |
| GET/PATCH | `/me/profile` | Read/update current user's profile |
| GET/POST | `/me/watchlist` | List/add watchlist items |
| PATCH/DELETE | `/me/watchlist/{item_id}` | Edit/remove one watchlist item |
| POST | `/me/watchlist/reorder` | Atomically reorder watchlist |
| GET/POST | `/me/observations` | List/add observation items |
| PATCH/DELETE | `/me/observations/{item_id}` | Edit/remove one observation item |
| POST | `/me/observations/reorder` | Atomically reorder observations |
| GET/POST | `/me/portfolios` | List/create portfolios |
| GET/PATCH/DELETE | `/me/portfolios/{portfolio_id}` | Read/edit/archive portfolio |
| POST | `/me/portfolios/reorder` | Reorder portfolios |
| GET/POST | `/me/portfolios/{portfolio_id}/positions` | List/add or replace positions |
| PATCH/DELETE | `/me/portfolios/{portfolio_id}/positions/{position_id}` | Edit/remove position |

Successful writes return the persisted canonical resource and a request ID.
Errors use the common API envelope and stable codes, at minimum:
`AUTH_REQUIRED`, `FORBIDDEN`, `VALIDATION_ERROR`, `SECURITY_NOT_FOUND`,
`PORTFOLIO_NOT_FOUND`, `ITEM_NOT_FOUND`, `DUPLICATE_RELATION` and
`CONFLICTING_VERSION`.

List APIs must have bounded pagination and deterministic ordering:
`sort_order ASC, id ASC` by default. They must not accept an arbitrary ORM
filter or field ordering expression from the client.

## 6. Authorization and Privacy

- All `/me` resources require an authenticated human user.
- API Gateway performs Bearer token authentication by delegating to
   `manniu_auth.services.token_service.authenticate_access_token`; the personal
   user module does not maintain a second token validation path.
- Invalid or missing credentials are returned through the Gateway auth facade
   using the standard `AUTHENTICATION_REQUIRED` or `TOKEN_INVALID` error codes.
- Ordinary users may access only their own profile, lists, portfolios and
  positions.
- Staff/operator access is not implicitly granted by this module; a separate
  audited support/admin capability is required for cross-user access.
- Notes, cost basis, quantities and contact fields are private user data and
  must not appear in public security or market-analysis responses.
- Write operations produce audit context with user ID, resource type, resource
  ID, action and request ID. Raw credentials and contact verification secrets
  must never enter logs.
- There is no sharing, public portfolio URL, social feed or cross-user
  recommendation in the first stage.
- The frontend should obtain the personal-user endpoint definitions from the
   Gateway catalog after login, then send the current user's Bearer token with
   every `/api/v1/me/*` request. The catalog does not grant access to resources;
   endpoint authorization is evaluated on every request.

## 7. Consistency, Deletion and Failure Rules

1. All writes that change a portfolio and its position membership use a
   database transaction.
2. User deletion cascades or anonymizes personal rows according to the final
   account-retention policy; this policy must be confirmed before migrations.
3. Security master deletion is not performed by this module. If a referenced
   security becomes inactive, existing user relationships remain queryable with
   its current canonical identity and an inactive status.
4. Repeated client writes should be safe to retry. The API should accept an
   idempotency key for batch or position replacement operations before the
   frontend introduces automatic retries.
5. Concurrent updates must not silently overwrite a newer user edit. Use an
   `updated_at` precondition or equivalent optimistic concurrency mechanism for
   reorder and position replacement operations.

## 8. Non-Goals for First Release

- Password reset, login identifier migration or MFA; these remain in auth.
- Email/SMS sending and verification provider integration.
- Broker account binding, trade import, order execution or automatic trading.
- Transaction-level buy/sell ledger, realized P/L, tax and corporate-action
  adjustment.
- Automatic synchronization among watchlist, observation and holdings.
- Sharing portfolios with other users.
- Real-time quotes, valuation, predictive signals or investment advice.

## 9. Acceptance Criteria

### Core flows

- A new authenticated user can create/read/update a minimal profile.
- A user can add the same security to both watchlist and observations without
  conflict, but cannot create duplicate entries within one list.
- A user can create a portfolio and maintain one validated position per
  security.
- A user can maintain multiple portfolios and the same security independently
  in different portfolios.
- A second user cannot read, update, reorder or delete the first user's data,
  including by changing path IDs.

### Boundary and failure flows

- Invalid or inactive security references are rejected according to the chosen
  market-data status rule.
- Negative quantities, invalid costs and unavailable quantity greater than
  total quantity are rejected atomically.
- Foreign IDs in a reorder or portfolio-position request fail without partial
  changes.
- Archived portfolios reject new position writes.
- Profile updates do not log passwords, tokens, verification codes or raw
  sensitive headers.

## 10. Product Decisions Required Before Implementation

1. Is email/mobile merely contact data in phase one, or must verification be
   delivered in the first release?
2. Should email and mobile be globally unique, unique only among active users,
   or non-unique until verification?
3. Should an inactive/delisted security remain addable to a new list/portfolio,
   or only remain visible in existing relationships?
4. Are fractional shares supported, and what is the required precision for
   quantity and average cost?
5. Should a zero-quantity position be deleted automatically or retained as an
   explicit closed position?
6. Is a broker-style transaction ledger required immediately, or is the
   snapshot position model sufficient for the first release?
7. Should the first release return only stored holdings, or also calculate live
   market value and P/L through a confirmed market-data aggregation interface?
8. What is the account deletion and personal-data retention policy?

Implementation must wait for these contract decisions, especially the profile
verification, position precision, and live P/L choices, because they affect
database constraints and API response fields.

## 11. TODO: Unimplemented Follow-up Features

- [ ] Implement email verification, including verification delivery, token
   expiration, verification status updates and retry/rate-limit rules.
- [ ] Implement mobile verification, including SMS delivery, verification code
   expiration, retry/rate-limit rules and abuse protection.
- [ ] Implement broker transaction ledger for buy/sell records, including
   transaction date, quantity, price, fees, taxes and source account.
- [ ] Define and implement the relationship between broker transactions and
   the current `HoldingPosition` snapshot.
- [ ] Implement real-time or latest-available market value calculation through
   a confirmed `market_data` aggregation interface.
- [ ] Implement portfolio and position profit/loss calculations, including
   daily P/L, total P/L, return rate and the applicable cost-basis rules.
- [ ] Define stale-price, unavailable-price and market-closed behavior for
   real-time market value and P/L responses.

These items are intentionally excluded from the first implementation. Before
development, confirm the corresponding product decisions in Section 10 and
extend the API, database constraints and acceptance criteria accordingly.