# Django Bootstrap Design

## Ownership

`manniu_backend` owns backend configuration and future server-side APIs.

## Database Contract

The project reads its PostgreSQL connection settings from these required environment variables:

- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `POSTGRES_HOST`
- `POSTGRES_PORT`

The Django `DATABASES["default"]` engine is `django.db.backends.postgresql`. SQLite is not configured as a fallback.

## API Contract

No application API is introduced by this initial empty-project bootstrap.

## Test Case Definition

### Core Flow

- A unit test asserts the configured database engine is PostgreSQL.
- `manage.py check` loads project settings successfully when test PostgreSQL variables are supplied.

### Boundary Scenarios

- Missing required database variables produce an explicit startup configuration error.

### Failure Scenarios

- Database configuration cannot silently select SQLite after a PostgreSQL configuration failure.