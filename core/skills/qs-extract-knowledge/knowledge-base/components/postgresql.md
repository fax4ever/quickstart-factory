---
name: postgresql
description: "PostgreSQL database deployed as a Kubernetes Deployment with PVC, psycopg2 access, and batched async writes"
summary: "PostgreSQL 16-alpine deployed as a single-replica Kubernetes Deployment (not StatefulSet) with PVC via inline Helm templates gated by `postgresql.enabled`, using GCR mirror image (`mirror.gcr.io/library/postgres`) to avoid Docker Hub rate limiting, with `pg_isready` readiness/liveness probes. Use for structured relational storage needing batched async writes and optional LLM agent SQL access via a postgres-mcp sidecar — supports JSONB columns with GIN indexes for flexible attributes and idempotent schema migrations (CREATE/ADD IF NOT EXISTS with FK cascade upgrade path); see pgvector.md if vector search is needed. Critical pattern: application connects via psycopg2-binary with `init_database()` retry loop (10 attempts, 3s delay); `DbWriterThread` batches writes from a queue (maxsize=5000) using `executemany` in dependency order within single transactions, with persistent connection reconnected on `OperationalError`; postgres-mcp sidecar (crystaldba/postgres-mcp, SSE transport, `--access-mode=restricted`) loads tools via `langchain-mcp-adapters` and wraps `execute_sql` with `app_config_id` scoping plus SELECT-only SQL injection guards. Common gotchas: `PGDATA` must be set to subdirectory (`/var/lib/postgresql/data/pgdata`) within PVC mount to avoid `lost+found` conflicts; DbWriterThread silently drops writes when queue is full (throughput over completeness trade-off); initContainer dependency chain PostgreSQL -> postgres-mcp -> backend must be maintained; CI uses `docker.io` image directly while Helm uses GCR mirror."
metadata:
  type: component
tags:
  tech_stack: [postgresql, psycopg2, python, helm]
  ai_pattern: [multimodal]
  platform: [openshift, kubernetes]
  data_layer: [postgresql]
source_examples:
  - quickstart: "multimodal-compliance-monitor"
    repo: "https://github.com/rh-ai-quickstart/multimodal-compliance-monitor"
    notes: "PostgreSQL 16-alpine as Deployment with PVC, psycopg2-binary for app access, DbWriterThread for batched async writes, postgres-mcp sidecar for LLM agent SQL access"
    approach: "A"
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
