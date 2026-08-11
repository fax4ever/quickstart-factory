---
name: pgvector
description: "PostgreSQL with pgvector extension for relational data and vector search in AI Quickstarts on RHOAI"
summary: "pgvector serves as combined relational store (SQLAlchemy/Alembic with asyncpg driver, UUID primary keys via sqlalchemy.dialects.postgresql) and LlamaStack vector_io provider (provider_id: \"pgvector\", embedding_model: \"all-MiniLM-L6-v2\" in agent templates) for RHOAI quickstarts needing both structured application state and RAG vector search. Use Approach A (ai-virtual-agent) when a single service needs vector search plus relational data with LlamaStack managing vector operations (extraDatabases vectordb: false, DATABASE_URL assembled from pgSecret keys); use Approach B (ansible-log-analysis) when multiple services (backend, annotation-interface, phoenix) share one PostgreSQL as relational store with pre-built URI secret key, ConfigMap init scripts running CREATE EXTENSION VECTOR, SQLModel.metadata.create_all instead of Alembic, psycopg2 sync driver swap for non-async consumers, and embeddings stored externally in MinIO. Deployed as Helm subchart from ai-architecture-charts (v0.5.5 for A, v0.1.0 bundled for B) with credentials via install_with_env.sh --set flags; Approach A Alembic rewrites postgresql+asyncpg:// to synchronous postgresql:// with expire_on_commit=False sessions; Approach B secret embeds namespace-qualified DNS in pre-built uri and pg_isready init containers gate startup. Common gotchas: Settings.DATABASE_URL defaults to sqlite+aiosqlite:///:memory: causing silent SQLite fallback if env var missing; local dev compose uses postgres:15 without pgvector extension (need pgvector/pgvector:pg15 or pg17); Approach B chained .replace() URL normalization is fragile if URI already contains \"postgresql+asyncpg://\"; deployment template fails if extraDatabases is empty or reordered; SQLModel.metadata.create_all has no migration framework so schema changes require table drops."
metadata:
  type: component
tags:
  tech_stack: [postgresql, fastapi, sqlalchemy, sqlmodel, alembic, asyncpg, psycopg2, gradio]
  ai_pattern: [vector-search, rag, embeddings]
  platform: [openshift, rhoai]
  data_layer: [pgvector]
source_examples:
  - quickstart: "ai-virtual-agent"
    repo: "https://github.com/rh-ai-quickstart/ai-virtual-agent"
    notes: "PostgreSQL as primary relational store with pgvector subchart; vector search delegated to LlamaStack provider"
    approach: "A"
  - quickstart: "ansible-log-analysis"
    repo: "https://github.com/rh-ai-quickstart/ansible-log-analysis"
    notes: "PostgreSQL as shared relational store for multiple services (backend, annotation-interface, phoenix); vector extension enabled but embeddings stored in MinIO"
    approach: "B"
---

# pgvector

## Overview

pgvector provides PostgreSQL with the pgvector extension, serving as the combined relational and vector database for AI Quickstarts on RHOAI. In the ai-virtual-agent quickstart it handles all application state (users, agents, chat sessions, knowledge bases) via SQLAlchemy/Alembic, while also acting as the vector store provider for LlamaStack-based RAG knowledge bases. It is deployed as a Helm subchart from the shared `ai-architecture-charts` repository.

## Tech Stack & Dependencies

- **Runtime:** PostgreSQL 15 (cluster: pgvector subchart image; local dev: `postgres:15` container)
- **Container image (local dev):** `postgres:15` (compose.yaml) or `pgvector/pgvector:pg15` (CONTRIBUTING.md standalone compose)
- **Key dependencies:** SQLAlchemy (async via `asyncpg`), Alembic for migrations, LlamaStack (registers pgvector as a `vector_io` provider)
- **Helm subchart:** `pgvector` v0.5.5 from `https://rh-ai-quickstart.github.io/ai-architecture-charts`

## Key Patterns

### Helm Subchart Dependency

The pgvector database is declared as a Helm subchart dependency in the parent chart, not deployed standalone. The subchart creates the StatefulSet, Service, PVC, and Secret automatically.

```yaml
# deploy/cluster/helm/Chart.yaml
dependencies:
  - name: pgvector
    version: 0.5.5
    repository: https://rh-ai-quickstart.github.io/ai-architecture-charts
```

### Extra Database Creation via Values

The subchart supports creating additional databases beyond the default one. The quickstart uses `extraDatabases` to create its application database, and the database name is referenced by the deployment template.

```yaml
# deploy/cluster/helm/values.yaml
pgvector:
  extraDatabases:
  - name: ai_virtual_agent
    vectordb: false
```

### Secret-Based Connection Wiring

The deployment template constructs the `DATABASE_URL` from individual secret keys provided by the pgvector subchart's Secret, combined with the database name from `extraDatabases`. The secret name is configurable via `pgSecret`.

```yaml
# deploy/cluster/helm/templates/deployment.yaml
- name: DB_HOST
  valueFrom:
    secretKeyRef:
      name: {{ .Values.pgSecret }}
      key: host
- name: DB_NAME
  value: {{ (index .Values.pgvector.extraDatabases 0).name }}
- name: DATABASE_URL
  value: 'postgresql+asyncpg://$(DB_USER):$(DB_PASS)@$(DB_HOST):$(DB_PORT)/$(DB_NAME)'
```

```yaml
# deploy/cluster/helm/values.yaml
pgSecret: pgvector
```

### Install Script Credential Passthrough

The install script passes pgvector credentials via `--set` flags, letting operators supply them at install time without editing values files.

```bash
# deploy/cluster/scripts/install_with_env.sh
cmd_args+=("--set" "pgvector.secret.user=$POSTGRES_USER")
cmd_args+=("--set" "pgvector.secret.password=$POSTGRES_PASSWORD")
cmd_args+=("--set" "pgvector.secret.dbname=$POSTGRES_DBNAME")
```

### Async SQLAlchemy Engine

The backend connects using `asyncpg` as the async PostgreSQL driver. The engine is created once at module level and sessions are provided via a FastAPI dependency.

```python
# backend/app/database.py
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from .config import settings

engine = create_async_engine(settings.DATABASE_URL, echo=settings.DEBUG)
AsyncSessionLocal = sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False
)
```

### Alembic Async URL Rewrite

Alembic migrations run synchronously, so the migration env.py rewrites the async `postgresql+asyncpg://` URL to the synchronous `postgresql://` driver before running migrations.

```python
# backend/migrations/env.py
if db_url_from_env and db_url_from_env.startswith("postgresql+asyncpg://"):
    db_url_from_env = db_url_from_env.replace(
        "postgresql+asyncpg://", "postgresql://", 1
    )
```

### PostgreSQL Dialect Types in Models

Models use PostgreSQL-specific column types from `sqlalchemy.dialects.postgresql`, particularly `UUID` for primary keys.

```python
# backend/app/models/knowledge_bases.py
from sqlalchemy.dialects.postgresql import UUID

class KnowledgeBase(Base):
    __tablename__ = "knowledge_bases"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vector_store_name = Column(String(255), nullable=False, unique=True)
    provider_id = Column(String(255))
```

### pgvector as LlamaStack Vector Store Provider

Agent templates reference `pgvector` as the `provider_id` for knowledge bases, meaning LlamaStack uses pgvector for vector storage and similarity search behind the scenes.

```yaml
# backend/agent_templates/travel_hospitality.yaml
knowledge_base_config:
  name: "Travel Agent Reference"
  version: "1.0"
  embedding_model: "all-MiniLM-L6-v2"
  provider_id: "pgvector"
  vector_store_name: "travel_agent_kb"
  is_external: false
```

## Configuration

- **Environment variables:**
  - `DATABASE_URL` -- Full async connection string (`postgresql+asyncpg://user:pass@host:port/db`). Built from individual components on cluster; set directly in local compose.
  - `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_PORT` -- Configure the PostgreSQL container in local dev.
- **Config files:**
  - `backend/app/config.py` -- `Settings.DATABASE_URL` defaults to `sqlite+aiosqlite:///:memory:` when env var is missing, enabling tests without a real database.
  - `backend/migrations/env.py` -- Alembic config; handles async-to-sync URL rewrite and seeds admin users after migrations.
- **Helm values:**
  - `pgvector.extraDatabases` -- List of databases to create; first entry's name is used for `DB_NAME`.
  - `pgvector.secret.user`, `pgvector.secret.password`, `pgvector.secret.dbname` -- Credentials passed via install script.
  - `pgSecret` -- Name of the Kubernetes Secret containing connection details (default: `pgvector`).

## Known Gotchas

- **Async vs sync URL mismatch:** The app uses `postgresql+asyncpg://` but Alembic requires synchronous connections. The migration env.py has an explicit string replace to handle this (see `backend/migrations/env.py` lines 34-37). If a new async driver is used, this replace must be updated.
- **SQLite fallback in config:** `Settings.DATABASE_URL` defaults to `sqlite+aiosqlite:///:memory:` (see `backend/app/config.py` line 20). This lets unit tests run without PostgreSQL, but means a missing `DATABASE_URL` env var will silently use an in-memory SQLite database rather than failing.
- **extraDatabases index assumption:** The deployment template accesses `(index .Values.pgvector.extraDatabases 0).name` directly (see `deploy/cluster/helm/templates/deployment.yaml` line 109). If `extraDatabases` is empty or reordered, the template will fail.
- **Local dev uses plain postgres:15, not pgvector image:** The main `deploy/local/compose.yaml` uses `postgres:15` (without the pgvector extension), while the standalone compose in `CONTRIBUTING.md` uses `pgvector/pgvector:pg15`. Vector search features may not work in local compose unless the image is changed.
- **vectordb: false flag:** The `extraDatabases` entry has `vectordb: false`, indicating this particular database does not enable the pgvector extension. Vector operations are handled by LlamaStack using its own vector store management.

## Testing Notes

- Unit tests run against SQLite in-memory by not setting `DATABASE_URL`, relying on the fallback in `backend/app/config.py`.
- On cluster, verify the pgvector Secret exists: `oc get secret pgvector -o yaml` and confirm keys `host`, `port`, `user`, `password` are populated.
- Verify the extra database was created: connect to the pod and run `psql -U admin -l | grep ai_virtual_agent`.
- Check that Alembic migrations ran on startup by looking at backend pod logs for migration output.

## Related Patterns

- `deployment/helm-subchart-wiring.md` -- How the parent chart wires subchart dependencies and secrets
- `architectures/rag-pipeline.md` -- How pgvector fits into the RAG pipeline as a vector store provider via LlamaStack

---

## Approach B: Shared Relational Store with Pre-Built URI Secret (from ansible-log-analysis)

### When to Use

When PostgreSQL serves as a shared relational database for multiple services (backend, annotation interface, observability/tracing) and the pgvector extension is enabled at init time but vector storage is handled externally (e.g., MinIO). Use this approach when consumers need a ready-to-use connection URI from the secret rather than assembling it in deployment templates.

### Differences from Approach A

- **Secret provides pre-built URIs:** The pgvector subchart secret includes `uri` and `jdbc-uri` keys with fully-constructed connection strings, so consumers reference the `uri` key directly instead of assembling the URL from individual `host`, `port`, `user`, `password` keys in the deployment template.
- **ConfigMap init script for DB and extension:** Database creation and `CREATE EXTENSION VECTOR` are handled by a shell script mounted from a ConfigMap into `/docker-entrypoint-initdb.d`, rather than the `extraDatabases` values mechanism.
- **SQLModel instead of SQLAlchemy ORM + Alembic:** Schema creation uses `SQLModel.metadata.create_all` at startup (no migration framework), and models are defined with `SQLModel` + `Field` instead of raw SQLAlchemy `Column` definitions.
- **Multiple consumers share one database:** Three services (backend, annotation-interface, phoenix) all consume the same `pgvector` secret's `uri` key via different env vars (`DATABASE_URL`, `PHOENIX_SQL_DATABASE_URL`).
- **Vector extension enabled but unused for storage:** The init script runs `CREATE EXTENSION VECTOR` but actual embeddings are stored in MinIO; PostgreSQL is used purely for relational data (alert records, tracing).

### Helm Subchart Dependency (Bundled Chart)

The pgvector chart is bundled as a `.tgz` in the charts directory, pulled from the same `ai-architecture-charts` repository at v0.1.0. The image uses PostgreSQL 17.

```yaml
# deploy/helm/ansible-log-monitor/Chart.yaml
dependencies:
  - name: pgvector
    version: 0.1.0
    repository: https://rh-ai-quickstart.github.io/ai-architecture-charts
```

### Pre-Built URI in Secret

The pgvector subchart secret includes fully-constructed `uri` and `jdbc-uri` keys using Go template string formatting, incorporating the release namespace for cross-namespace DNS.

```yaml
# pgvector/templates/secret.yaml
data:
  user: {{ .Values.secret.user | b64enc | quote }}
  password: {{ .Values.secret.password | b64enc | quote }}
  host: {{ .Values.secret.host | b64enc | quote }}
  port: {{ .Values.secret.port | b64enc | quote }}
  dbname: {{ .Values.secret.dbname | b64enc | quote }}
  uri: {{ printf "postgresql://%s:%s@%s.%s:%s/%s" .Values.secret.user .Values.secret.password .Values.secret.host .Release.Namespace .Values.secret.port .Values.secret.dbname | b64enc | quote }}
```

### ConfigMap Init Script

Database creation and extension setup are handled by a ConfigMap-mounted shell script. The `extraDatabases` values allow creating additional databases with optional vector extension.

```yaml
# pgvector/templates/configmap.yaml
data:
  init-db.sh: |
    #!/bin/bash
    set -e
    psql -U postgres -c "CREATE DATABASE ${POSTGRES_DBNAME};"
    psql -U postgres -d ${POSTGRES_DBNAME} -c "CREATE EXTENSION VECTOR;"
    {{- range .Values.extraDatabases }}
    psql -U postgres -c "CREATE DATABASE {{ .name }};"
    {{- if .vectordb }}
    psql -U postgres -d {{ .name }} -c "CREATE EXTENSION VECTOR;"
    {{- end }}
    {{- end }}
```

### Direct Secret URI Consumption

Consumers reference the `uri` key from the pgvector secret directly, without constructing the URL in the deployment template. Each service uses a different env var name but the same secret key.

```yaml
# deploy/helm/ansible-log-monitor/charts/backend/values.yaml
env:
  - name: DATABASE_URL
    valueFrom:
      secretKeyRef:
        name: pgvector
        key: uri

# deploy/helm/ansible-log-monitor/charts/phoenix/values.yaml
env:
  - name: PHOENIX_SQL_DATABASE_URL
    valueFrom:
      secretKeyRef:
        name: pgvector
        key: uri
```

### SQLModel with Async URL Normalization

The backend uses SQLModel instead of raw SQLAlchemy ORM. The connection URL from the secret is normalized to use the `asyncpg` driver via string replacement at engine creation time.

```python
# src/alm/database.py
engine = create_async_engine(
    os.getenv("DATABASE_URL")
    .replace("+asyncpg", "")
    .replace("postgresql", "postgresql+asyncpg")
)

async def init_tables(delete_tables=False):
    async with engine.begin() as conn:
        if delete_tables:
            await conn.run_sync(GrafanaAlert.metadata.drop_all)
        await conn.run_sync(GrafanaAlert.metadata.create_all)
```

### Sync Driver Swap for Annotation Interface

The annotation interface uses synchronous SQLAlchemy with `psycopg2` instead of `asyncpg`, applying a similar URL replacement to switch the driver.

```python
# services/annotation_interface/app.py
self.engine = create_engine(
    os.getenv("DATABASE_URL")
    .replace("+asyncpg", "")
    .replace("postgresql", "postgresql+psycopg2")
)
```

### Wait-for-Postgres Init Container

The backend deployment and init job use an init container that waits for PostgreSQL readiness before starting, using `pg_isready` with the full `DATABASE_URL`.

```yaml
# deploy/helm/ansible-log-monitor/charts/backend/templates/deployment.yaml
initContainers:
  - name: wait-for-postgres
    image: postgres:15-alpine
    command:
      - sh
      - -c
      - |
        until pg_isready -d "$DATABASE_URL"; do
          echo "Waiting for PostgreSQL to be ready..."
          sleep 2
        done
    env:
      - name: DATABASE_URL
        valueFrom:
          secretKeyRef:
            name: pgvector
            key: uri
```

### StatefulSet with Readiness Probe for Multiple Databases

The StatefulSet readiness probe iterates over the primary database and all `extraDatabases` to verify all databases are accepting connections.

```yaml
# pgvector/templates/statefulset.yaml
readinessProbe:
  exec:
    command:
      - /bin/sh
      - -c
      - |
        for db in "$POSTGRES_DBNAME" {{- range .Values.extraDatabases }} "{{ .name }}"{{- end }}; do
          pg_isready -U "$POSTGRES_USER" -d "$db" -h 127.0.0.1 -p "$POSTGRES_PORT" || exit 1
        done
```

### Configuration (Approach B)

- **Environment variables:**
  - `DATABASE_URL` -- Pre-built PostgreSQL URI from the `pgvector` secret `uri` key. Consumers normalize the driver scheme in application code.
  - `PHOENIX_SQL_DATABASE_URL` -- Same `pgvector` secret `uri` key, consumed by Phoenix for observability tracing storage.
  - `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DBNAME`, `POSTGRES_PORT` -- Set on the pgvector container from secret keys.
- **Helm values:**
  - `pgvector.secret.user`, `pgvector.secret.password`, `pgvector.secret.dbname`, `pgvector.secret.host`, `pgvector.secret.port` -- Credential values baked into the chart's Secret.
  - `pgvector.extraDatabases` -- Optional list of additional databases with per-database `vectordb` boolean.
  - `pgvector.image.tag` -- Defaults to `pg17` (`docker.io/pgvector/pgvector:pg17`).

### Known Gotchas (Approach B)

- **URL normalization fragility:** Both the async backend and sync annotation interface apply string replacements to the `DATABASE_URL` to swap the driver (`+asyncpg` or `+psycopg2`). The chained `.replace("+asyncpg", "").replace("postgresql", "postgresql+asyncpg")` in `src/alm/database.py` first strips any existing `+asyncpg` then adds it back, which works for plain `postgresql://` URIs but could break if the URI already contains `postgresql+asyncpg://` with additional path segments containing the word "postgresql".
- **Local dev uses plain postgres:15 without pgvector extension:** The `deploy/local/compose.yaml` uses `postgres:15` (line 158) while the Helm chart uses `pgvector/pgvector:pg17`. The `CREATE EXTENSION VECTOR` in the init script will fail on plain `postgres:15` unless the pgvector extension is installed separately.
- **Namespace in URI:** The secret template embeds `.Release.Namespace` in the host portion of the URI (`pgvector.<namespace>:5432`), creating namespace-qualified DNS names. This works for cross-namespace access but means the secret value changes per namespace.
- **No migration framework:** Using `SQLModel.metadata.create_all` means schema changes require manual table drops or custom migration logic. The `init_tables(delete_tables=True)` parameter exists but drops all tables, losing data.

---

## Choosing Between Approaches

| Criteria | Approach A (ai-virtual-agent) | Approach B (ansible-log-analysis) |
|----------|-------------------------------|-----------------------------------|
| **pgvector chart version** | v0.5.5 | v0.1.0 (bundled .tgz) |
| **PostgreSQL version** | 15 | 17 |
| **URL construction** | Assembled from individual secret keys in deployment template | Pre-built `uri` key consumed directly from secret |
| **DB initialization** | `extraDatabases` values mechanism | ConfigMap init script with `CREATE EXTENSION VECTOR` |
| **Schema management** | Alembic migrations (async-to-sync URL rewrite) | `SQLModel.metadata.create_all` at startup |
| **ORM** | SQLAlchemy ORM with PostgreSQL dialect types | SQLModel with JSON column type |
| **Vector search usage** | Active via LlamaStack `vector_io` provider | Extension enabled but unused; embeddings in MinIO |
| **Number of consumers** | Single backend service | Multiple services (backend, annotation-interface, phoenix) |
| **Credential passthrough** | Install script `--set` flags | Values file defaults |
| **Best for** | Apps needing vector search + relational data in one DB | Multi-service apps using PostgreSQL as shared relational store |
