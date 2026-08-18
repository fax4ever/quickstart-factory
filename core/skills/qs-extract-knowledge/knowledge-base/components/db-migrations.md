---
name: db-migrations
description: Alembic-based PostgreSQL migration package with init-container pattern for schema management and data seeding
summary: "Provides a standalone hatchling-built Python database package (packages/db/) that owns Alembic-versioned schema migrations, pgvector extension setup, CSV seed data loading via pandas, and optional Keycloak user sync for PostgreSQL-backed quickstarts, deployed as a Helm post-install/post-upgrade Job with an initContainer waiting on pg_isready. Use when a monorepo quickstart needs a dedicated database package with migration lifecycle management — the single approach pairs Alembic with SQLAlchemy ORM models, asyncpg for app runtime (auto-swapped to psycopg2 in env.py for migrations), pydantic BaseSettings for config, and pnpm/uv run scripts for local dev against a pgvector/pgvector:pg16 compose service. Critical config: DATABASE_URL follows three-tier precedence (env var then alembic.ini then hardcoded default) with automatic +asyncpg to +psycopg2 driver swap; Helm Job sets PYTHONPATH to /app/packages/db/src:/app/packages/api/src, backoffLimit:1 (config issues won't self-heal), and 2Gi memory limit to accommodate torch/sentence-transformers for embedding generation during data loading. Gotchas: pgvector extension must be created in both init-scripts SQL and the initial Alembic migration (both IF NOT EXISTS) to cover fresh containers and migration-only paths; run `alembic heads` before adding migrations to catch merge conflicts from parallel branches; startup.sh Keycloak sync uses set +e with BYPASS_AUTH toggle so failures are non-critical; tests use pytest.skip() when no live database is available."
metadata:
  type: component
tags:
  tech_stack: [alembic, sqlalchemy, postgresql, asyncpg, psycopg2, python, pydantic-settings, pgvector, hatchling]
  ai_pattern: [embeddings, vector-search]
  platform: [openshift, kubernetes]
  data_layer: [pgvector, postgresql]
source_examples:
  - quickstart: "spending-transaction-monitor"
    repo: "https://github.com/rh-ai-quickstart/spending-transaction-monitor"
    notes: "Standalone db package with Alembic migrations, Helm Job for init-container pattern, CSV data loading, and pgvector extension setup"
    approach: "A"
---

# DB Migrations

## Overview

A standalone Python database package that owns schema management, migrations, and seed data for a PostgreSQL-backed quickstart. It uses Alembic for versioned migrations with SQLAlchemy ORM models, runs as a Kubernetes Job (Helm post-install/post-upgrade hook) in production, and provides pnpm script shortcuts for local development. The package also handles pgvector extension setup and optional Keycloak user sync during initialization.

## Tech Stack & Dependencies

- **Runtime:** Python 3.12, hatchling build system
- **Container image:** `python:3.12-slim` (with `gcc`, `libpq-dev`, `postgresql-client`)
- **Key dependencies:** SQLAlchemy >= 2.0 (async via asyncpg), Alembic >= 1.13, psycopg2-binary (for migrations), pydantic-settings, pgvector, pandas
- **Optional ML dependencies:** sentence-transformers, torch (CPU/CUDA variant via build arg), openai
- **Helm subchart:** Not a subchart; deployed as a `batch/v1 Job` via Helm hook in the parent chart

## Key Patterns

### Monorepo Database Package

The database layer lives in `packages/db/` as an installable Python package using hatchling. Other packages (e.g., `packages/api/`) depend on it. The package exposes models, config, and database session utilities.

```toml
# packages/db/pyproject.toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "spending-monitor-db"
requires-python = ">=3.12"
dependencies = [
    "sqlalchemy>=2.0.0",
    "alembic>=1.13.0",
    "asyncpg>=0.29.0",
    "psycopg2-binary>=2.9.0",
    "pgvector>=0.2.0",
]

[tool.hatch.build.targets.wheel]
packages = ["src/db"]
```

### Async-to-Sync Driver Swap in Alembic

The application uses `asyncpg` for async database operations, but Alembic requires a synchronous driver. The `env.py` automatically swaps `+asyncpg` to `+psycopg2` for migration runs.

```python
# alembic/env.py
# Ensure Alembic uses a sync driver for migrations when the app uses asyncpg
if os.environ.get('DATABASE_URL') or config.get_main_option('sqlalchemy.url'):
    url = os.environ.get('DATABASE_URL') or config.get_main_option('sqlalchemy.url')
    if '+asyncpg' in url:
        config.set_main_option('sqlalchemy.url', url.replace('+asyncpg', '+psycopg2'))
```

### DATABASE_URL Precedence in env.py

The migration `env.py` follows a three-tier URL resolution: environment variable first, then alembic.ini config, then a hardcoded default fallback. The `alembic.ini` itself comments out the URL and defers to `env.py`.

```python
# alembic/env.py — run_migrations_online()
database_url = (
    os.environ.get('DATABASE_URL')
    or config.get_main_option('sqlalchemy.url')
    or 'postgresql+psycopg2://user:password@localhost:5432/spending-monitor'
)
```

### pgvector Extension Setup (Dual Path)

pgvector is enabled in two places to cover both fresh database creation and migration scenarios:
1. An init-script SQL file (`init-scripts/01-enable-pgvector.sql`) that runs on first container start via the `docker-entrypoint-initdb.d` volume mount
2. The initial Alembic migration also runs `CREATE EXTENSION IF NOT EXISTS vector`

```sql
-- init-scripts/01-enable-pgvector.sql
CREATE EXTENSION IF NOT EXISTS vector;
GRANT USAGE ON SCHEMA public TO "user";
```

```python
# alembic/versions/ac92703bd365_initial_schema.py
def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    op.create_table('users', ...)
```

### Helm Job as Post-Install/Post-Upgrade Hook

Migrations run as a Kubernetes Job triggered by Helm hooks. An `initContainer` waits for PostgreSQL readiness before the migration container runs `startup.sh`.

```yaml
# deploy/helm/spending-monitor/templates/migration-job.yaml
apiVersion: batch/v1
kind: Job
metadata:
  annotations:
    "helm.sh/hook": post-install,post-upgrade
    "helm.sh/hook-weight": "1"
    "helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded
spec:
  backoffLimit: 1
  template:
    spec:
      initContainers:
        - name: wait-for-database
          image: postgres:16-alpine
          command: ["/bin/sh", "-c", "until pg_isready -h {{ .Values.database.name }} -p 5432; do sleep 3; done"]
```

### Startup Script Orchestration

The `startup.sh` script orchestrates the full initialization sequence: wait for PostgreSQL, run Alembic migrations, load CSV seed data, and optionally sync Keycloak users. It handles each step with error reporting and graceful fallbacks.

```bash
# packages/db/startup.sh (key steps)
# 1. Wait for PostgreSQL with retry loop (30 attempts, 5s intervals)
pg_isready -h ${POSTGRES_HOST:-postgres} -U ${POSTGRES_USER:-user} -d ${POSTGRES_DB:-spending-monitor}

# 2. Run Alembic migrations
cd /app/packages/db
alembic upgrade head

# 3. Load CSV data if files exist
python3 -m db.scripts.load_csv_data

# 4. Keycloak sync (non-critical, won't fail the job)
if [ "${BYPASS_AUTH:-true}" = "false" ] && [ -n "${KEYCLOAK_URL}" ]; then
    /app/venv/bin/python3 -m keycloak.cli setup --sync-users
fi
```

### Data Migration with Alembic (Seed Data in Migrations)

Beyond schema changes, Alembic migrations are used to prepopulate reference data. The category synonyms migration uses table reflection and batch insert to seed data.

```python
# alembic/versions/4a13a47c8ec1_prepopulate_category_data.py
def upgrade() -> None:
    connection = op.get_bind()
    metadata = MetaData()
    metadata.reflect(bind=connection)
    synonyms_table = metadata.tables['merchant_category_synonyms']
    connection.execute(synonyms_table.delete())  # idempotent
    connection.execute(synonyms_table.insert(), synonym_data)
```

### Custom PostgreSQL Functions via Migrations

Alembic migrations can create PostgreSQL stored functions and views. The Haversine distance function migration demonstrates raw SQL execution within Alembic for domain-specific database logic.

```python
# alembic/versions/e35d4db01ac2_add_location_distance_function.py
def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION haversine_distance_km(
            lat1 DOUBLE PRECISION, lon1 DOUBLE PRECISION,
            lat2 DOUBLE PRECISION, lon2 DOUBLE PRECISION
        ) RETURNS DOUBLE PRECISION AS $$ ... $$ LANGUAGE plpgsql IMMUTABLE;
    """)
    op.execute("""CREATE OR REPLACE VIEW transaction_location_analysis AS ...""")
```

### Merge Migrations for Branch Conflicts

The project contains multiple merge migrations to resolve Alembic head conflicts from parallel feature development. These are empty pass-through migrations that unify divergent revision chains.

```python
# alembic/versions/merge_all_heads_final.py
revision = 'merge_all_heads_final'
down_revision = ('5dd200df62e6', 'eb7dc605eb0f')

def upgrade() -> None:
    pass
```

### pnpm Script Interface for Local Development

The `package.json` provides developer-friendly pnpm shortcuts for common database operations, using `uv run` to invoke Alembic and Python scripts.

```json
{
  "scripts": {
    "dev": "pnpm db:start && pnpm upgrade && pnpm db:logs",
    "db:start": "podman-compose up -d || docker compose up -d",
    "upgrade": "uv run alembic upgrade head",
    "downgrade": "uv run alembic downgrade -1",
    "revision": "uv run alembic revision --autogenerate",
    "seed": "uv run python -m db.scripts.seed",
    "reset": "uv run python -m db.scripts.reset_database"
  }
}
```

## Configuration

- **Environment variables:**
  - `DATABASE_URL` — Full PostgreSQL connection string (supports both `asyncpg` and `psycopg2` schemes; Alembic auto-converts)
  - `POSTGRES_HOST`, `POSTGRES_USER`, `POSTGRES_DB`, `POSTGRES_PASSWORD` — Used by `startup.sh` for `pg_isready` checks
  - `BYPASS_AUTH` — When `"false"`, enables Keycloak user sync during migration (default: `"true"`)
  - `KEYCLOAK_URL`, `KEYCLOAK_REALM`, `KEYCLOAK_ADMIN_PASSWORD` — Keycloak connection for user sync
  - `PYTHONPATH` — Set to `/app/packages/db/src:/app/packages/api/src` in Helm Job
  - `TORCH_VARIANT` — Containerfile build arg to select CPU or CUDA PyTorch (`cpu` default)
- **Config files:**
  - `alembic.ini` — Alembic configuration; URL is dynamically set in `env.py`, not in the ini file
  - `src/db/config.py` — Pydantic BaseSettings with `DATABASE_URL` default for local development
- **Helm values:**
  - `migration.enabled` — Toggle migration Job on/off
  - `migration.backoffLimit: 1` — Only retry once (config issues won't self-heal)
  - `migration.resources.limits.memory: "2Gi"` — Increased to accommodate torch/sentence-transformers for embedding generation

## Known Gotchas

- **asyncpg vs psycopg2 driver mismatch:** The app uses `postgresql+asyncpg://` in `DATABASE_URL` but Alembic requires synchronous `psycopg2`. The `env.py` handles this swap automatically, but if you add a new entry point for migrations, you must replicate this logic. The swap appears in both `run_migrations_online()` and `run_migrations_offline()` in `env.py`.
- **Dual pgvector extension creation:** The pgvector extension is created both in `init-scripts/01-enable-pgvector.sql` (for fresh PostgreSQL containers) and in the initial Alembic migration (for databases that skip the init script). Both use `IF NOT EXISTS` to be idempotent.
- **Migration Job memory:** The migration container needs 2Gi memory limit because it installs PyTorch and sentence-transformers for embedding generation during data loading. The Helm values comment documents this: "Increased from 1Gi to accommodate torch/sentence-transformers".
- **Merge migration proliferation:** The project has multiple merge migrations (`5dd200df62e6`, `merge_all_heads_final`) to resolve Alembic head conflicts from parallel branches. When adding new migrations, run `alembic heads` first to check for multiple heads.
- **Startup script Keycloak sync is non-critical:** The `startup.sh` uses `set +e` around Keycloak sync so failures do not abort the migration Job. The script documents: "This is non-critical, migration continues. Run 'make keycloak-sync-users' later if needed."
- **Local compose uses `pgvector/pgvector:pg16` image:** The local `compose.yml` uses the `pgvector/pgvector:pg16` image which has pgvector pre-installed, while the init-script also runs `CREATE EXTENSION IF NOT EXISTS vector` for redundancy.

## Testing Notes

- The test suite (`tests/test_database.py`) uses `pytest.skip()` when the database is not running, making tests safe to run without a live PostgreSQL instance
- For local testing: `pnpm db:start` spins up PostgreSQL via `podman-compose` or `docker compose`, then `pnpm upgrade` runs migrations
- Verify migration history with `pnpm history` (runs `alembic history`)
- Check current migration state with `pnpm current` (runs `alembic current`)

## Related Patterns

- `pgvector.md` — pgvector extension setup and vector column usage
- `postgresql.md` — PostgreSQL database deployment patterns
- `fastapi-backend.md` — Backend that consumes this database package
