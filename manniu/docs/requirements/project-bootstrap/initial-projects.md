# Initial Project Bootstrap

## Scope

Create two independent empty application projects under `UAT/manniu`:

- `manniu_backend`: Django project with PostgreSQL-only persistence configuration.
- `manniu_frontend`: React and TypeScript project created with Vite.

## Constraints

- No automated trading execution behavior.
- Backend persistence must use PostgreSQL through environment-based configuration.
- Do not use SQLite as an application persistence backend.
- Keep the generated projects minimal and independently runnable.

## Test Case Definition

### Core Flow

- Django configuration loads and selects the PostgreSQL database engine.
- The React production build completes successfully.

### Boundary Scenarios

- The backend reports a clear configuration error when required PostgreSQL environment variables are absent.

### Failure Scenarios

- Invalid PostgreSQL connection settings must not silently fall back to SQLite.
