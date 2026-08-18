---
name: postgresql
description: "PostgreSQL database deployed as a Kubernetes Deployment with PVC, psycopg2 access, and batched async writes"
summary: "PostgreSQL 16-alpine deployed as a single-replica Kubernetes Deployment (not StatefulSet) with PVC and pg_isready probes, providing structured relational storage with JSONB/GIN indexes and idempotent schema migrations (CREATE/ADD IF NOT EXISTS with FK cascade upgrade path); see pgvector.md if vector search is needed. Choose Approach A (psycopg2-binary, sync, single database) for detection tracking with batched async writes via DbWriterThread and postgres-mcp sidecar for LLM agent SQL access, or Approach B (psycopg v3 + asyncpg + SQLAlchemy async, multi-database) for agentic platforms needing LISTEN/NOTIFY real-time SSE, SQLite/PostgreSQL dual-backend auto-detection, and Bitnami Helm chart with Secrets-based credentials. Approach A uses inline Helm templates gated by `postgresql.enabled` with GCR mirror image, `init_database()` retry loop (10 attempts, 3s delay), `DbWriterThread` queue (maxsize=5000, `executemany` in dependency order, persistent connection reconnected on `OperationalError`), and postgres-mcp sidecar (`--access-mode=restricted`) with `app_config_id` scoping plus SELECT-only injection guards; Approach B uses multi-database init script via `docker-entrypoint-initdb.d`, URL normalization across three simultaneous drivers, TTL-based engine caching (`pool_size=5`, `max_overflow=10`), and healthcheck validating both databases. Common gotchas: `PGDATA` must be set to subdirectory (`/var/lib/postgresql/data/pgdata`) to avoid `lost+found` conflicts; DbWriterThread silently drops writes when queue is full (throughput over completeness trade-off); LISTEN/NOTIFY incompatible with PgBouncer transaction pooling (use `AIQ_LISTEN_DB_URL` for direct connection); checkpoint tables must be pre-created in init-db.sql or backends crash on PostgreSQL restart; CI uses `docker.io` image while Helm uses GCR mirror (Approach A) or Bitnami (Approach B)."
metadata:
  type: component
tags:
  tech_stack: [postgresql, psycopg2, psycopg3, asyncpg, sqlalchemy, python, helm, docker-compose]
  ai_pattern: [multimodal, agents, rag]
  platform: [openshift, kubernetes]
  data_layer: [postgresql]
source_examples:
  - quickstart: "multimodal-compliance-monitor"
    repo: "https://github.com/rh-ai-quickstart/multimodal-compliance-monitor"
    notes: "PostgreSQL 16-alpine as Deployment with PVC, psycopg2-binary for app access, DbWriterThread for batched async writes, postgres-mcp sidecar for LLM agent SQL access"
    approach: "A"
  - quickstart: "rh-research"
    repo: "https://github.com/rh-ai-quickstart/rh-research"
    notes: "PostgreSQL 16-alpine via Docker Compose and Bitnami Helm chart, multi-database init script, psycopg3 + asyncpg + SQLAlchemy async engines, LISTEN/NOTIFY for real-time SSE, SQLite/PostgreSQL dual-backend support"
    approach: "B"
---

# PostgreSQL

## Overview

PostgreSQL serves as the primary relational data store for tracking detection results in the multimodal-compliance-monitor quickstart. It is deployed as a single-replica Kubernetes Deployment (not a StatefulSet) backed by a PVC, with the application layer using psycopg2-binary for synchronous database access. A companion postgres-mcp sidecar deployment provides read-only SQL access for LLM agents via SSE transport.

## Tech Stack & Dependencies

- **Runtime:** PostgreSQL 16-alpine (`mirror.gcr.io/library/postgres:16-alpine`)
- **Container image:** `mirror.gcr.io/library/postgres` (GCR mirror, not Docker Hub directly)
- **Key dependencies:** psycopg2-binary >= 2.9.11 (Python driver), PersistentVolumeClaim for data persistence
- **Helm subchart:** None -- deployed as inline Helm templates (Deployment, Service, PVC) within the parent chart, not a Bitnami or external subchart
- **Companion service:** postgres-mcp (`docker.io/crystaldba/postgres-mcp`) for LLM agent access

## Key Patterns

### Inline Helm Templates (Not a Subchart)

PostgreSQL is deployed via three inline templates in the parent chart, gated by `.Values.postgresql.enabled`:

```yaml
# deploy/helm/ppe-compliance-monitor/templates/postgresql-deployment.yaml
{{- if .Values.postgresql.enabled }}
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ include "ppe-compliance-monitor.fullname" . }}-postgresql
spec:
  replicas: 1
  template:
    spec:
      containers:
        - name: postgresql
          image: "{{ .Values.postgresql.image.repository }}:{{ .Values.postgresql.image.tag }}"
          env:
            - name: PGDATA
              value: /var/lib/postgresql/data/pgdata
```

The `PGDATA` env var is set to a subdirectory (`/var/lib/postgresql/data/pgdata`) within the mount path (`/var/lib/postgresql/data`). This is required because PostgreSQL refuses to initialize into a non-empty directory, and PVC mounts may contain a `lost+found` directory.

### Readiness and Liveness Probes

Both probes use `pg_isready` with the configured user and database:

```yaml
# deploy/helm/ppe-compliance-monitor/templates/postgresql-deployment.yaml
readinessProbe:
  exec:
    command:
      - /bin/sh
      - -c
      - pg_isready -U {{ .Values.postgresql.user }} -d {{ .Values.postgresql.database }}
  initialDelaySeconds: 5
  periodSeconds: 5
livenessProbe:
  exec:
    command:
      - /bin/sh
      - -c
      - pg_isready -U {{ .Values.postgresql.user }} -d {{ .Values.postgresql.database }}
  initialDelaySeconds: 30
  periodSeconds: 10
```

### Application-Side Retry on Startup

The backend handles the race between PostgreSQL and the application starting up with a retry loop in `init_database()`:

```python
# app/backend/database.py
def init_database():
    max_retries = 10
    for attempt in range(max_retries):
        try:
            _init_schema()
            return
        except Exception as e:
            if attempt < max_retries - 1:
                log.warning(
                    "Database not ready (attempt %s/%s): %s. Retrying in 3s...",
                    attempt + 1, max_retries, e,
                )
                time.sleep(3)
            else:
                raise
```

### Schema Initialization with Idempotent Migrations

The schema uses `CREATE TABLE IF NOT EXISTS` and `ADD COLUMN IF NOT EXISTS` for forward-compatible migrations. Foreign key constraints are dropped and recreated to upgrade old databases to CASCADE deletes:

```python
# app/backend/database.py
cursor.execute(
    "ALTER TABLE detection_tracks DROP CONSTRAINT IF EXISTS "
    "detection_tracks_detection_classes_id_fkey"
)
cursor.execute("""
    ALTER TABLE detection_tracks
    ADD CONSTRAINT detection_tracks_detection_classes_id_fkey
    FOREIGN KEY (detection_classes_id)
    REFERENCES detection_classes(id) ON DELETE CASCADE
""")
```

### JSONB for Flexible Attributes

Detection observations store per-frame attributes in a JSONB column with a GIN index for efficient querying:

```python
# app/backend/database.py
cursor.execute("""
    CREATE TABLE IF NOT EXISTS detection_observations (
        id SERIAL PRIMARY KEY,
        track_id INTEGER NOT NULL,
        timestamp TIMESTAMP NOT NULL,
        attributes JSONB NOT NULL DEFAULT '{}',
        FOREIGN KEY (track_id) REFERENCES detection_tracks(track_id)
            ON DELETE CASCADE
    )
""")
cursor.execute("""
    CREATE INDEX IF NOT EXISTS idx_detection_observations_attributes
    ON detection_observations USING GIN (attributes)
""")
```

### Batched Async DB Writer Thread

A background `DbWriterThread` class batches writes from a queue to reduce per-row commit overhead during high-frequency inference:

```python
# app/backend/database.py
class DbWriterThread:
    def __init__(self, max_batch: int = 10, poll_timeout: float = 0.05):
        self._queue: queue_mod.Queue = queue_mod.Queue(maxsize=5000)
        self._stop = threading.Event()
        self._max_batch = max_batch

    def enqueue(self, op: str, args: tuple) -> None:
        try:
            self._queue.put_nowait((op, args))
        except queue_mod.Full:
            log.warning("DB writer queue full, dropping %s", op)
```

Operations are grouped by type and executed in dependency order (tracks before observations) within a single transaction using `executemany`. The connection is persistent and reconnected on `OperationalError`.

### Read-Only Connection for LLM Queries

A dedicated read-only connection context manager prevents LLM-generated SQL from modifying data:

```python
# app/backend/database.py
@contextmanager
def get_readonly_connection():
    conn = psycopg2.connect(get_connection_string())
    try:
        conn.set_session(readonly=True, autocommit=False)
        yield conn
    finally:
        conn.rollback()
        conn.close()
```

### Postgres-MCP Sidecar for LLM Agent Access

A separate postgres-mcp deployment provides SSE-based SQL access for LLM agents. The backend uses `langchain-mcp-adapters` to load tools from it and wraps `execute_sql` with app_config_id scoping to enforce data isolation:

```python
# app/backend/tools/mcp_tools.py
def _wrap_execute_sql(original_tool):
    async def _scoped_execute(sql: str) -> str:
        config_id = current_app_config_id.get()
        if config_id is not None:
            sql_lower = sql.lower()
            touches_scoped = any(t in sql_lower for t in _SCOPED_TABLES)
            has_filter = f"app_config_id = {config_id}" in sql_lower
            if touches_scoped and not has_filter:
                return (
                    f"ERROR: Query rejected. You MUST include "
                    f"'detection_classes.app_config_id = {config_id}' ..."
                )
        return await original_tool.ainvoke({"sql": sql})
```

The postgres-mcp deployment itself uses an initContainer to wait for PostgreSQL readiness and runs in `--access-mode=restricted` mode.

## Configuration

- **Environment variables (Helm -> container):**
  - `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` -- PostgreSQL server init
  - `PGDATA` -- set to `/var/lib/postgresql/data/pgdata` (subdirectory of mount)
- **Environment variables (app -> database):**
  - `DB_HOST` (default: `localhost`) -- PostgreSQL hostname
  - `DB_PORT` (default: `5432`) -- PostgreSQL port
  - `DB_NAME` (default: `ppe_tracking`) -- database name
  - `DB_USER` (default: `ppe_user`) -- database user
  - `DB_PASSWORD` (default: `ppe_password`) -- database password
  - `POSTGRES_MCP_URL` -- SSE endpoint for postgres-mcp sidecar
- **Helm values:**
  - `postgresql.enabled` (bool) -- gates all PostgreSQL resources
  - `postgresql.image.repository` / `postgresql.image.tag` -- image (`mirror.gcr.io/library/postgres:16-alpine`)
  - `postgresql.database` / `postgresql.user` / `postgresql.password` -- credentials
  - `postgresql.storage.size` (default: `5Gi`) -- PVC size
  - `postgresMcp.enabled` (bool) -- gates postgres-mcp sidecar
  - `postgresMcp.accessMode` (default: `restricted`) -- MCP access mode
  - `postgresMcp.port` (default: `8000`) -- SSE port

## Known Gotchas

- **PGDATA subdirectory required:** The `PGDATA` env var is set to `/var/lib/postgresql/data/pgdata` rather than the mount root `/var/lib/postgresql/data`. PostgreSQL will not initialize into a non-empty directory, and PVC mounts can contain a `lost+found` directory. This is explicitly handled in the Helm template.
- **FK cascade upgrade path:** The schema initialization drops and recreates foreign key constraints to add `ON DELETE CASCADE`. The comment in `database.py` explains: "Upgrade old DBs: FKs without ON DELETE CASCADE block deleting app_config when tracks/observations exist."
- **Queue overflow drops writes:** The `DbWriterThread` queue has a `maxsize=5000`. When full, writes are silently dropped with a warning log: `"DB writer queue full, dropping %s"`. This is a deliberate trade-off for inference throughput over data completeness.
- **Init container ordering:** The postgres-mcp deployment includes a `wait-for-postgresql` initContainer using busybox `nc -z` to check TCP readiness. The backend deployment similarly has a `wait-for-postgres-mcp` initContainer when both `postgresql.enabled` and `postgresMcp.enabled` are true, creating a startup dependency chain: PostgreSQL -> postgres-mcp -> backend.
- **GCR mirror image:** The Helm values use `mirror.gcr.io/library/postgres` instead of `docker.io/library/postgres`, while the CI workflow uses `docker.io/library/postgres:16-alpine`. This avoids Docker Hub rate limiting in cluster deployments.

## Testing Notes

- CI uses a GitHub Actions service container (`postgres:16-alpine`) with health checks via `pg_isready` before running pytest
- The test `conftest.py` calls `init_database()` once per session as an autouse fixture
- Unit tests override the parent conftest to skip `init_database()` (no Postgres needed for unit tests)
- The `execute_query` function has built-in SQL injection guards: only SELECT queries allowed, dangerous keywords (DROP, DELETE, UPDATE, INSERT, ALTER, TRUNCATE, CREATE, GRANT, REVOKE) are blocked

## Related Patterns

- See `pgvector.md` for PostgreSQL with pgvector extension for vector search
- The postgres-mcp sidecar pattern could apply to any quickstart needing LLM-driven SQL queries

---

## Approach B: Multi-Database with SQLAlchemy Async and LISTEN/NOTIFY (from rh-research)

### When to Use

When PostgreSQL serves as the persistence layer for an agentic research platform that requires multiple databases (job store, LangGraph checkpoints, document summaries), real-time SSE streaming via LISTEN/NOTIFY, and a SQLite/PostgreSQL dual-backend design for local dev vs production.

### Differences from Approach A

- **Drivers:** psycopg (v3) + asyncpg + SQLAlchemy async engines instead of psycopg2-binary with direct connections
- **Deployment:** Docker Compose service with `init-db.sql` entrypoint script; Kubernetes uses `bitnami/postgresql` with ConfigMap-mounted init script and Secrets-based credentials (not inline Helm templates)
- **Multiple databases:** Two PostgreSQL databases (`aiq_jobs`, `aiq_checkpoints`) created by init script, not a single application database
- **Dual-backend:** Application auto-detects SQLite vs PostgreSQL from URL scheme, enabling local dev without PostgreSQL
- **Real-time events:** Uses PostgreSQL LISTEN/NOTIFY via asyncpg for sub-10ms SSE event delivery, falling back to polling for SQLite
- **Connection pooling:** psycopg_pool `AsyncConnectionPool` for LangGraph checkpoints; SQLAlchemy engines with TTL-based cache management

### Docker Compose Service

PostgreSQL is deployed as a standalone Compose service with an init script mounted into the entrypoint directory:

```yaml
# deploy/compose/docker-compose.yaml
postgres:
  image: postgres:16-alpine
  container_name: aiq-postgres
  environment:
    POSTGRES_USER: aiq
    POSTGRES_PASSWORD: aiq_dev
    POSTGRES_DB: aiq_jobs
  volumes:
    - postgres-data:/var/lib/postgresql/data
    - ./init-db.sql:/docker-entrypoint-initdb.d/init-db.sql:ro
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U aiq -d aiq_jobs && pg_isready -U aiq -d aiq_checkpoints"]
    interval: 5s
    timeout: 5s
    retries: 5
```

The healthcheck validates both databases are ready, not just the default one. Resource limits are set to 2 CPUs / 4G memory with 1 CPU / 2G reservations.

### Multi-Database Init Script

The init script creates a second database and all tables across both databases using `\gexec` for conditional creation and `\connect` for cross-database DDL:

```sql
-- deploy/compose/init-db.sql
SELECT 'CREATE DATABASE aiq_checkpoints' WHERE NOT EXISTS
  (SELECT FROM pg_database WHERE datname = 'aiq_checkpoints')\gexec

GRANT ALL PRIVILEGES ON DATABASE aiq_jobs TO aiq;
GRANT ALL PRIVILEGES ON DATABASE aiq_checkpoints TO aiq;

\connect aiq_jobs
CREATE TABLE IF NOT EXISTS job_info (
    job_id VARCHAR PRIMARY KEY,
    status VARCHAR NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE,
    updated_at TIMESTAMP WITH TIME ZONE,
    expiry_seconds INTEGER,
    is_expired BOOLEAN DEFAULT FALSE
);
```

The comment in `init-db.sql` explains the checkpoint tables are pre-created: "Previously left to the app, but if postgres restarts without a backend restart, the tables are lost and running backends crash with 'relation checkpoints does not exist'."

### Dual-Backend Auto-Detection

The application detects the database backend from the URL scheme and provisions the appropriate checkpointer:

```python
# src/aiq_agent/common/__init__.py
def is_postgres_dsn(value: str) -> bool:
    """Return True when the checkpoint DSN is a Postgres URL."""
    parsed = urlparse(value)
    return parsed.scheme in ("postgresql", "postgres")

async def get_checkpointer(checkpoint_db: str) -> BaseCheckpointSaver:
    if is_postgres_dsn(checkpoint_db):
        pool = AsyncConnectionPool(
            conninfo=checkpoint_db,
            min_size=1, max_size=3,
            kwargs={"autocommit": True, "row_factory": dict_row},
        )
        checkpointer = AsyncPostgresSaver(pool)
    else:
        conn = await aiosqlite.connect(checkpoint_db)
        checkpointer = AsyncSqliteSaver(conn)
    await checkpointer.setup()
    return checkpointer
```

Checkpointers and pools are cached by DSN to avoid multiple connections to the same database.

### URL Normalization for Multiple Drivers

Both EventStore and SummaryStore normalize incoming URLs to use consistent SQLAlchemy drivers, stripping existing driver suffixes before applying the correct one:

```python
# frontends/aiq_api/src/aiq_api/jobs/event_store.py
def _normalize_db_url(db_url: str, async_mode: bool = True) -> str:
    if db_url.startswith("postgresql") or db_url.startswith("postgres"):
        base_url = db_url.replace("+asyncpg", "").replace("+psycopg2", "").replace("+psycopg", "")
        return f"{base_url.replace('postgresql://', 'postgresql+psycopg://')}"
    elif db_url.startswith("sqlite"):
        base_url = db_url.replace("+aiosqlite", "")
        return base_url.replace("sqlite:///", "sqlite+aiosqlite:///") if async_mode else base_url
    return db_url
```

### PostgreSQL LISTEN/NOTIFY for Real-Time SSE

The EventStore uses `pg_notify` when storing events for real-time push to SSE clients. The SSE generator uses asyncpg `LISTEN` on a per-job channel:

```python
# frontends/aiq_api/src/aiq_api/jobs/event_store.py
channel = f"job_events_{self.job_id.replace('-', '_')}"
payload = json.dumps({"id": event_id, "type": event_type})
conn.execute(text("SELECT pg_notify(:channel, :payload)"),
             {"channel": channel, "payload": payload})
```

The SSE route falls back to polling if pub-sub fails. The code also notes a PgBouncer incompatibility: "LISTEN/NOTIFY needs a persistent session -- incompatible with PgBouncer transaction pooling. Use AIQ_LISTEN_DB_URL to point directly at PostgreSQL."

### SQLAlchemy Engine Caching with TTL

Both EventStore and SummaryStore maintain class-level engine caches with TTL-based cleanup (1 hour default, max 10 engines) to reuse connections across requests:

```python
# frontends/aiq_api/src/aiq_api/jobs/event_store.py
ENGINE_CACHE_TTL_SECONDS = 3600
ENGINE_CACHE_MAX_SIZE = 10

class EventStore:
    _async_engine_cache: dict[str, tuple[Any, float]] = {}
    _sync_engine_cache: dict[str, tuple[Any, float]] = {}
```

PostgreSQL engine creation uses `pool_size=5`, `max_overflow=10`, and `pool_recycle=1800`.

### Kubernetes Deployment with Bitnami Image

On Kubernetes, PostgreSQL uses `bitnami/postgresql` (not the upstream Alpine image) with Secrets-based credentials and a ConfigMap for the init script:

```yaml
# deploy/helm/deployment-k8s/values.yaml
postgres:
  enabled: true
  image:
    repository: bitnami/postgresql
    tag: latest
  secretEnv:
    POSTGRES_USER: DB_USER_NAME
    POSTGRES_PASSWORD: DB_USER_PASSWORD
  env:
    POSTGRES_DB: aiq_jobs
    POSTGRESQL_MAX_CONNECTIONS: '200'
  persistence:
  - name: aiq-postgres-data
    accessModes: [ReadWriteOnce]
    size: 10Gi
```

The backend uses an initContainer to wait for PostgreSQL and run the init script:

```yaml
# deploy/helm/deployment-k8s/values.yaml
initContainers:
- name: db-init
  image: bitnami/postgresql:latest
  command: [sh, -c]
  args:
  - |
    until pg_isready -h aiq-postgres -U $(DB_USER_NAME) -d aiq_jobs; do
      sleep 2
    done
    psql -h aiq-postgres -U $(DB_USER_NAME) -d aiq_jobs -f /db-init/init.sql
```

### Configuration (Approach B)

- **Environment variables (Docker Compose defaults):**
  - `NAT_JOB_STORE_DB_URL` -- job store connection (`postgresql+asyncpg://aiq:aiq_dev@postgres:5432/aiq_jobs`)
  - `AIQ_CHECKPOINT_DB` -- LangGraph checkpoints (`postgresql://aiq:aiq_dev@postgres:5432/aiq_checkpoints`)
  - `AIQ_SUMMARY_DB` -- document summaries (`postgresql+psycopg://aiq:aiq_dev@postgres:5432/aiq_jobs`)
  - `AIQ_LISTEN_DB_URL` -- optional direct PostgreSQL URL for LISTEN/NOTIFY (bypasses PgBouncer)
- **Environment variables (Kubernetes):**
  - `DB_USER_NAME` / `DB_USER_PASSWORD` -- from Kubernetes Secret `aiq-credentials`
  - `POSTGRESQL_MAX_CONNECTIONS` -- Bitnami-specific, set to `200`
- **Python dependencies:**
  - `langgraph-checkpoint-postgres>=3.0.0` -- LangGraph async PostgreSQL checkpointer
  - `psycopg[binary]>=3.0.0` -- psycopg v3 for SQLAlchemy async
  - `asyncpg>=0.29.0` -- for LISTEN/NOTIFY and async job store

### Known Gotchas (Approach B)

- **Checkpoint tables must be pre-created:** The init-db.sql comment explains: "Previously left to the app, but if postgres restarts without a backend restart, the tables are lost and running backends crash with 'relation checkpoints does not exist'." The init script creates all LangGraph checkpoint tables (checkpoints, checkpoint_blobs, checkpoint_writes, checkpoint_migrations) upfront.
- **Three different PostgreSQL drivers used simultaneously:** `asyncpg` for LISTEN/NOTIFY SSE and job store, `psycopg` (v3) for SQLAlchemy async engines (EventStore, SummaryStore), and `langgraph-checkpoint-postgres` which internally uses psycopg_pool. URL normalization strips and re-adds driver suffixes to route correctly.
- **PgBouncer incompatibility with LISTEN/NOTIFY:** The code at `frontends/aiq_api/src/aiq_api/routes/jobs.py:1186` notes: "LISTEN/NOTIFY needs a persistent session -- incompatible with PgBouncer transaction pooling. Use AIQ_LISTEN_DB_URL to point directly at PostgreSQL."
- **Healthcheck validates both databases:** The Compose healthcheck runs `pg_isready -U aiq -d aiq_jobs && pg_isready -U aiq -d aiq_checkpoints`, ensuring both databases are ready before the backend starts (via `depends_on: postgres: condition: service_healthy`).
- **Bitnami vs upstream image divergence:** Docker Compose uses `postgres:16-alpine` (upstream) while Kubernetes uses `bitnami/postgresql:latest`. Bitnami has different env var conventions (`POSTGRESQL_MAX_CONNECTIONS` vs upstream `max_connections` in postgresql.conf).
- **Upsert pattern differs per backend:** The SummaryStore in `src/aiq_agent/knowledge/summary_store.py` uses `ON CONFLICT ... DO UPDATE` for PostgreSQL and `INSERT OR REPLACE` for SQLite, handled via an `is_postgres` branch.

### Testing Notes (Approach B)

- CI workflow (`.github/workflows/skills-eval.yml`) starts both `aiq-agent` and `postgres` services via `docker compose up -d --build aiq-agent postgres` with a 5-minute timeout to cover postgres init and first build
- SQLite fallback enables local testing without a PostgreSQL instance by leaving `NAT_JOB_STORE_DB_URL`, `AIQ_CHECKPOINT_DB`, and `AIQ_SUMMARY_DB` unset (configs default to SQLite paths)

---

## Choosing Between Approaches

| Criteria | Approach A | Approach B |
|----------|-----------|-----------|
| **Use case** | Detection tracking, structured relational data | Job store, LangGraph checkpoints, document summaries |
| **Python driver** | psycopg2-binary (sync) | psycopg v3 + asyncpg + SQLAlchemy async |
| **Database count** | Single database | Multiple databases (aiq_jobs, aiq_checkpoints) |
| **Init pattern** | Application-side retry loop (`init_database()`) | Init SQL script via `/docker-entrypoint-initdb.d/` |
| **Real-time events** | N/A | PostgreSQL LISTEN/NOTIFY via asyncpg |
| **SQLite fallback** | No | Yes, auto-detected from URL scheme |
| **Helm deployment** | Inline templates, `mirror.gcr.io/library/postgres` | Bitnami chart image, ConfigMap init script, Secrets |
| **Connection model** | Persistent single connection, reconnect on error | Connection pools with TTL-based engine caching |
| **Write pattern** | Batched queue (DbWriterThread, maxsize=5000) | SQLAlchemy transactions with upsert |
| **LLM SQL access** | postgres-mcp sidecar with SELECT-only guards | N/A |
