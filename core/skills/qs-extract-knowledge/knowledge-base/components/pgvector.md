---
name: pgvector
description: "PostgreSQL with pgvector extension for relational data and vector search in AI Quickstarts on RHOAI"
summary: "pgvector serves as combined relational store (SQLAlchemy/Alembic with asyncpg, SQLModel, raw psycopg2, or pgvector.sqlalchemy Vector type) and vector database (via LlamaStack vector_io provider with all-MiniLM-L6-v2 384-dim or nomic-embed-text-v1.5 768-dim embeddings, direct SQL <=> cosine operator with HNSW index, Feast retrieve_online_documents with vector_enabled: true, or direct <-> L2 distance for semantic category matching) for RHOAI quickstarts needing structured application state, RAG vector search, distributed session serialization via advisory locks, regulatory data isolation via dual PostgreSQL roles, curated data views with MCP read-only access, feature-store-backed recommendation search, or semantic merchant category normalization with interchangeable embedding providers. Use Approach A (ai-virtual-agent, f5-ai-guardrails, f5-api-security, RAG, openshift-ai-observability-summarizer) with subchart v0.5.5/v0.5.6 when a single service needs LlamaStack-managed vector search plus relational data (extraDatabases vectordb: false, DATABASE_URL assembled from pgSecret keys); Approach B (ansible-log-analysis) with bundled v0.1.0 subchart when multiple services share one PostgreSQL as relational store with pre-built namespace-qualified URI secret, SQLModel.metadata.create_all, psycopg2 sync driver swap, ConfigMap init CREATE EXTENSION VECTOR, and embeddings stored in MinIO; Approach C (data-governance-co-pilot, peoplemesh) with standalone chart when deploying quay.io/rh-aiservices-bu Red Hat PG15 image with Helm post-install Job seeding ~45MB CSV via OpenShift BuildConfig (bypassing ConfigMap 3MB limit), mcp_readonly SELECT-only user for MCP defense-in-depth, CERTIFIED/DEPRECATED governance views, raw psycopg2, and pre-delete cleanup Job; Approach D (it-self-service-agent) with v0.1.0 subchart when 6+ services need dual connection pools (async SQLAlchemy + psycopg_pool for LangGraph PostgresSaver), pg_try_advisory_lock polling avoiding PG BUG #17686, Alembic migration Job with wait_for_migration() gating, LlamaStack multi-store backends (metadataStore, kv_postgres, sql_postgres across rag_blueprint/llama_agents/llama_responses), max_connections=200, _env-helpers.tpl template helpers, database-level clock SELECT now(), and get_db_utc_now() for cross-pod consistency; Approach E (multi-agent-loan-origination) with inline Helm StatefulSet PG16 when needing dual PostgreSQL roles (lending_app/compliance_app) for HMDA data isolation, direct pgvector <=> cosine search with tier-based boosting (federal 1.5x, agency 1.2x, internal 1.0x), HNSW index vector_cosine_ops, Vector(768) via pgvector.sqlalchemy, per-table GRANT in Alembic migrations, database.enabled toggle for external DB support, and separate mlflow database for observability; Approach F (product-recommender-system) with v0.1.0 subchart as Feast online store with vector_enabled: true, FeatureStore CRD (feast.dev/v1alpha1) managing online/offline/registry services, 6 embedding feature views (item, user, text, CLIP, category) with vector_index=True and cosine search, hybrid SQL deterministic + Feast retrieve_online_documents semantic search, and mixed sync/async DB access; Approach G (spending-transaction-monitor) with inline Helm Deployment PG16 (quay.io/rh-ai-quickstart/pgvector:pg16) when needing pgvector for semantic merchant category normalization via Vector(384) <-> L2 distance with interchangeable embedding providers (OpenAI text-embedding-3-small 1536-dim, sentence-transformers all-MiniLM-L6-v2 384-dim, Ollama all-minilm 384-dim) that dynamically ALTER COLUMN embedding dimensions, custom PostgreSQL haversine_distance_km function and transaction_location_analysis risk-classified view via Alembic, Helm migration Job running startup.sh init pipeline (pg_isready wait -> Alembic upgrade head -> CSV seed -> optional Keycloak sync), pydantic-settings with .env file support, and pgvector extension enabled both in SQL init script (/docker-entrypoint-initdb.d) and Alembic initial migration. Deployed as ai-architecture-charts subchart (v0.5.5/v0.5.6 for A, v0.1.0 bundled for B, v0.1.0 for D/F), standalone chart (C), or inline templates (E/G); A's DATABASE_URL assembled from pgSecret individual keys with Alembic rewriting postgresql+asyncpg:// to synchronous postgresql:// and expire_on_commit=False; B's secret embeds Release.Namespace in URI and pg_isready init containers gate startup; C's data loader connects via pod DNS (pgvector-0) assuming single replica; D's DatabaseManager creates dual pools with configurable DB_POOL_SIZE/DB_MAX_OVERFLOW and provider_id: \"pgvector\" required in extra_body for llama-stack 0.3.3+; E maintains separate SQLAlchemy session factories per role with dual DATABASE_URL/COMPLIANCE_DATABASE_URL connection strings; F's Feast config uses vector_enabled: true with env var substitution and backend rewrites postgresql:// to postgresql+asyncpg://; G's Alembic env.py rewrites +asyncpg to +psycopg2 (not stripping to plain postgresql://) and DatabaseSettings uses pydantic-settings with .env file support. Common gotchas: Settings.DATABASE_URL defaults to sqlite+aiosqlite:///:memory: causing silent SQLite fallback; local dev postgres:15 lacks pgvector extension (need pgvector/pgvector:pg15 or pg17); B's chained .replace() URL normalization fragile if URI already contains \"postgresql+asyncpg://\"; A's deployment template fails if extraDatabases empty or reordered; C's readonlyPassword appears plaintext in rendered Job manifest, mcp_readonly grants don't auto-apply to future tables, and values.yaml placeholder strings cause broken deployments if --set flags omitted; D's dual statement timeout required so advisory lock polling queries aren't cancelled and connection pool budget across 6+ services approaches max_connections=200; E's lending_app/compliance_app role passwords hardcoded in init scripts need parameterization for production, per-table GRANT in migrations must be repeated for every new table, and local compose port 5433 differs from cluster port 5432; F's Base.metadata.drop_all in db-init Job destroys data on every post-upgrade run, db-init waits indefinitely if training pipeline hasn't populated model_version table, and backend initContainer requires oc CLI image with job-viewer RBAC; G's populate_embeddings.py validates 1536-dim but model column is Vector(384) causing dimension mismatch unless populate_embeddings_local.py is used, and dual pgvector extension enablement (init-script SQL + Alembic migration) is redundant but harmless."
metadata:
  type: component
tags:
  tech_stack: [postgresql, fastapi, sqlalchemy, sqlmodel, alembic, asyncpg, psycopg2, psycopg, gradio, pandas, streamlit, langgraph, feast, pydantic-settings, sentence-transformers]
  ai_pattern: [vector-search, rag, embeddings, data-pipeline, guardrails, agents, model-serving, semantic-matching]
  platform: [openshift, rhoai, kserve]
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
  - quickstart: "data-governance-co-pilot"
    repo: "https://github.com/rh-ai-quickstart/data-governance-co-pilot"
    notes: "Standalone pgvector Helm chart with StatefulSet, post-install data loader Job via OpenShift BuildConfig, read-only MCP user, and data governance views"
    approach: "C"
  - quickstart: "f5-ai-guardrails"
    repo: "https://github.com/rh-ai-quickstart/f5-ai-guardrails"
    notes: "pgvector v0.1.0 subchart as LlamaStack vector_io backend for RAG; Streamlit frontend queries pgvector directly via asyncpg for document listing and deletion"
    approach: "A"
  - quickstart: "f5-api-security"
    repo: "https://github.com/rh-ai-quickstart/f5-api-security"
    notes: "pgvector v0.1.0 subchart as LlamaStack vector_io backend for RAG; Streamlit frontend queries pgvector directly via asyncpg for document listing/deletion; PGVECTOR_* env vars hardcoded in parent chart values"
    approach: "A"
  - quickstart: "it-self-service-agent"
    repo: "https://github.com/rh-ai-quickstart/it-self-service-agent"
    notes: "pgvector v0.1.0 subchart shared by 6+ services; dual async/sync connection pools; PostgreSQL advisory locks for distributed session serialization; Helm template helpers for env var generation; LlamaStack multi-store backends (metadata, kv, sql); Alembic migration Job"
    approach: "D"
  - quickstart: "RAG"
    repo: "https://github.com/rh-ai-quickstart/RAG"
    notes: "pgvector v0.5.6 subchart as pure LlamaStack vector_io backend for multi-domain RAG; PGVECTOR_* env vars injected from .Values.pgvector.secret.* in deployment template; multiple named vector stores per document domain; ingestion pipeline populates stores via LlamaStack API"
    approach: "A"
  - quickstart: "multi-agent-loan-origination"
    repo: "https://github.com/rh-ai-quickstart/multi-agent-loan-origination"
    notes: "PostgreSQL 16 with pgvector as inline Helm StatefulSet (not subchart); dual PostgreSQL roles for HMDA data isolation; direct pgvector cosine similarity search with tier-based boosting for compliance KB; Vector(768) with HNSW index; Alembic migrations with pgvector.sqlalchemy"
    approach: "E"
  - quickstart: "openshift-ai-observability-summarizer"
    repo: "https://github.com/rh-ai-quickstart/openshift-ai-observability-summarizer"
    notes: "pgvector v0.5.5 subchart as LlamaStack vector_io backend within nested umbrella chart (aiobs-stack -> rag -> pgvector); POSTGRES_* env vars auto-injected by llama-stack chart when pgvector.enabled=true; ingestion pipeline with all-MiniLM-L6-v2 embeddings; credentials via Makefile --set flags"
    approach: "A"
  - quickstart: "product-recommender-system"
    repo: "https://github.com/rh-ai-quickstart/product-recommender-system"
    notes: "pgvector v0.1.0 subchart as Feast online store with vector_enabled: true; FeatureStore CRD (feast.dev/v1alpha1) manages online/offline/registry services; multiple embedding feature views (item, user, text, CLIP, category) with vector_index=True and cosine search; SQLAlchemy async for relational data; hybrid SQL deterministic + Feast retrieve_online_documents semantic search"
    approach: "F"
  - quickstart: "peoplemesh"
    repo: "https://github.com/francescopace/peoplemesh"
    notes: "Standalone pgvector chart with same Red Hat PG15 image as Approach C; Helm hook (pre-install/pre-upgrade) secret with _helpers.tpl password lookup from existing secrets; pre-delete cleanup Job with dedicated ServiceAccount/Role/RoleBinding; GPU tolerations on StatefulSet for shared node pools; umbrella chart dependency with pgvector.enabled condition toggle; JDBC/Quarkus consumer via existingSecret reference"
    approach: "C"
  - quickstart: "spending-transaction-monitor"
    repo: "https://github.com/rh-ai-quickstart/spending-transaction-monitor"
    notes: "Inline Helm Deployment (not subchart/StatefulSet) with pgvector for semantic merchant category matching; Vector(384) with all-MiniLM-L6-v2; three interchangeable embedding providers (OpenAI/sentence-transformers/Ollama) with dynamic column dimension alteration; Alembic migrations with custom haversine distance function; Helm migration Job with startup.sh init pipeline (wait -> migrate -> CSV seed -> Keycloak sync)"
    approach: "G"
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

## Approach C: Standalone Chart with Data Loader Job and MCP Read-Only User (from data-governance-co-pilot)

### When to Use

When PostgreSQL with pgvector is deployed as a standalone Helm chart (not an ai-architecture-charts subchart) that needs to load large seed datasets (exceeding ConfigMap 3MB limits) and expose a read-only database user for MCP server access with defense-in-depth security. Use this approach when the quickstart focuses on data governance patterns with curated views (CERTIFIED/DEPRECATED) and structured relational data rather than vector search.

### Differences from Approach A

- **Standalone Helm chart:** Has its own `Chart.yaml`, templates directory, and `values.yaml` -- not pulled as a dependency from `ai-architecture-charts`.
- **Different container image:** Uses `quay.io/rh-aiservices-bu/postgresql-15-pgvector-c9s:latest` (Red Hat-published image with pgvector baked in) rather than the `pgvector/pgvector` community image.
- **Data loader Job pattern:** A Kubernetes Job runs as a Helm post-install hook to seed the database with CSV data via a custom container image built through OpenShift BuildConfig, bypassing ConfigMap size limits.
- **Read-only MCP user:** Creates a `mcp_readonly` PostgreSQL user with SELECT-only grants for defense-in-depth when an MCP server connects to the database.
- **No ORM or migrations:** Schema is created via raw SQL in a Python data loader script using `psycopg2` directly -- no SQLAlchemy, SQLModel, or Alembic.
- **Data governance views:** Creates CERTIFIED and DEPRECATED views with table/view comments indicating PII classifications and deprecation status.

### StatefulSet with PVC and Headless Service

The pgvector database is deployed as a StatefulSet with a 20Gi PersistentVolumeClaim and a headless Service for stable pod DNS. The init script is mounted from a ConfigMap to enable the vector extension at startup.

```yaml
# helm/pgvector/templates/stateful-set.yaml
spec:
  serviceName: pgvector-postgres-service
  replicas: 1
  template:
    spec:
      containers:
        - name: pgvector
          image: quay.io/rh-aiservices-bu/postgresql-15-pgvector-c9s:latest
          env:
            - name: POSTGRESQL_USER
              valueFrom:
                secretKeyRef:
                  name: vector-database
                  key: DATABASE_USER
          volumeMounts:
            - name: pgvector-data
              mountPath: /var/lib/pgsql/data
            - name: init-script
              mountPath: /opt/app-root/src/postgresql-start/
  volumeClaimTemplates:
    - metadata:
        name: pgvector-data
      spec:
        accessModes: [ReadWriteOnce]
        resources:
          requests:
            storage: 20Gi
```

### ConfigMap Init Script for Extension Creation

The vector extension is enabled via a ConfigMap-mounted shell script placed at `/opt/app-root/src/postgresql-start/`. The script waits for PostgreSQL readiness and creates the database if it does not exist before enabling the extension.

```bash
# helm/pgvector/templates/config-map.yaml (init-vector.sh)
until pg_isready -U "$POSTGRESQL_USER" -d postgres -q; do
  echo "Waiting for PostgreSQL to start..."
  sleep 1
done
if ! psql -U "$POSTGRESQL_USER" -d postgres -lqt | cut -d \| -f 1 | grep -qw "$POSTGRESQL_DATABASE"; then
  psql -U "$POSTGRESQL_USER" -d postgres -c "CREATE DATABASE $POSTGRESQL_DATABASE;"
fi
psql -v ON_ERROR_STOP=1 --username "$POSTGRESQL_USER" --dbname "$POSTGRESQL_DATABASE" <<-EOSQL
  CREATE EXTENSION IF NOT EXISTS vector CASCADE;
EOSQL
```

### Data Loader Job as Helm Post-Install Hook

A Kubernetes Job loads CSV data into PostgreSQL after chart installation. The Job uses Helm hook annotations to run after install/upgrade, with automatic cleanup before re-creation. The data loader image is either pulled from Quay or built on-cluster via OpenShift BuildConfig.

```yaml
# helm/pgvector/templates/data-loader-job.yaml
metadata:
  annotations:
    "helm.sh/hook": post-install,post-upgrade
    "helm.sh/hook-weight": "5"
    "helm.sh/hook-delete-policy": before-hook-creation
spec:
  ttlSecondsAfterFinished: 300
  backoffLimit: 3
  template:
    spec:
      containers:
        - name: data-loader
          image: {{ .Values.dataLoader.image | default (printf "image-registry.openshift-image-registry.svc:5000/%s/pgvector-data-loader:latest" .Release.Namespace) }}
          env:
            - name: POSTGRES_HOST
              value: "pgvector-0.pgvector-postgres-service.{{ .Release.Namespace }}.svc.cluster.local"
```

### OpenShift Binary Build for Large Datasets

Because CSV data exceeds the ConfigMap 3MB limit (~45MB), a Binary Build strategy uploads the data directory to OpenShift which builds the data loader container image in the cluster's internal registry.

```yaml
# helm/pgvector/buildconfig.yaml
apiVersion: build.openshift.io/v1
kind: BuildConfig
metadata:
  name: pgvector-data-loader
spec:
  output:
    to:
      kind: ImageStreamTag
      name: pgvector-data-loader:latest
  source:
    type: Binary
  strategy:
    type: Docker
    dockerStrategy:
      dockerfilePath: Dockerfile.data-loader
```

### Read-Only User for MCP Server Security

The data loader script creates a `mcp_readonly` PostgreSQL user with SELECT-only grants, providing defense-in-depth when an MCP server connects to the database. The script checks for existing users to support idempotent re-runs.

```python
# helm/pgvector/scripts/load_data.py
def create_readonly_user(conn, readonly_password):
    """
    Create read-only database user for MCP server.
    Purpose: Defense-in-depth security - limits blast radius if MCP server is compromised.
    Note: Does NOT auto-grant on future tables - privileges must be re-granted if schema changes.
    """
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM pg_catalog.pg_user WHERE usename = 'mcp_readonly'")
    user_exists = cursor.fetchone() is not None
    if not user_exists:
        cursor.execute(f"CREATE USER mcp_readonly WITH PASSWORD %s", (readonly_password,))
    cursor.execute("GRANT CONNECT ON DATABASE postgres TO mcp_readonly")
    cursor.execute("GRANT USAGE ON SCHEMA public TO mcp_readonly")
    cursor.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO mcp_readonly")
    cursor.execute("GRANT pg_read_all_stats TO mcp_readonly")
```

### Data Governance Views with Certification and Deprecation

The data loader creates views with explicit CERTIFIED/DEPRECATED labels and table comments indicating PII classifications, supporting data governance use cases.

```python
# helm/pgvector/scripts/load_data.py
cursor.execute("""
    COMMENT ON TABLE dim_customer IS
    'Core customer table. CONTAINS PII (PCI, address). DO NOT USE FOR general BI. Only for auth_service.';
""")

cursor.execute("""
    COMMENT ON VIEW v_rpt_customer_ltv_certified IS
    '[CERTIFIED] Gold-standard, PII-scrubbed view for all customer LTV reporting. Aggregated daily. Maintained by: Finance BI Team';
""")

cursor.execute("""
    COMMENT ON VIEW v_cust_ltv_agg_DEPRECATED IS
    '[DEPRECATED] Old LTV calculation. Only includes data before 2018. DEPRECATED as of Q3 2024. Do not use for new reporting. Use v_rpt_customer_ltv_certified instead.';
""")
```

### OpenShift-Compatible Data Loader Container

The data loader container image uses UBI9 Python 3.11 base image and switches to non-root user (UID 1001) for OpenShift restricted SCC compatibility.

```dockerfile
# helm/pgvector/Containerfile
FROM registry.access.redhat.com/ubi9/python-311:latest
USER root
RUN pip install --no-cache-dir pandas psycopg2-binary
RUN mkdir -p /data /scripts && chown -R 1001:0 /data /scripts && chmod -R g=u /data /scripts
COPY data/*.csv /data/
COPY scripts/load_data.py /scripts/load_data.py
USER 1001
CMD ["python3", "/scripts/load_data.py"]
```

### Configuration (Approach C)

- **Environment variables:**
  - `POSTGRESQL_USER`, `POSTGRESQL_PASSWORD`, `POSTGRESQL_DATABASE` -- Set on the StatefulSet container from the `vector-database` Secret.
  - `POSTGRESQL_ADMIN_PASSWORD` -- Set to the same value as `POSTGRESQL_PASSWORD` in the StatefulSet.
  - `PGDATA` -- Set to `/var/lib/pgsql/data/pgdata` to place data inside the PVC mount.
  - `POSTGRES_HOST` -- Data loader Job uses the fully-qualified pod DNS name (`pgvector-0.pgvector-postgres-service.<namespace>.svc.cluster.local`).
  - `POSTGRES_READONLY_PASSWORD` -- Passed to the data loader Job to set the `mcp_readonly` user password; sourced from `values.yaml` `postgres.readonlyPassword`.
- **Helm values:**
  - `postgres.userId`, `postgres.password`, `postgres.databaseName` -- Credentials passed at install time via `--set` flags (placeholders in default `values.yaml`).
  - `postgres.readonlyPassword` -- Required; sets the password for the `mcp_readonly` database user.
  - `dataLoader.image` -- Defaults to `quay.io/rh-ai-quickstart/pgvector-data-loader:latest`; falls back to OpenShift internal registry image if building on-cluster.

### Known Gotchas (Approach C)

- **readonlyPassword in plaintext in Job spec:** The `POSTGRES_READONLY_PASSWORD` env var is set as a plaintext Helm value interpolation (`value: "{{ .Values.postgres.readonlyPassword }}"`) in the data loader Job template rather than using a secretKeyRef, so the password appears in the rendered Job manifest (see `templates/data-loader-job.yaml` line 47).
- **mcp_readonly grants do not auto-apply to future tables:** The `GRANT SELECT ON ALL TABLES` only covers tables that exist at the time the data loader runs. If new tables are created later, the `mcp_readonly` user will not have access to them unless the script is re-run (documented in the `create_readonly_user` function comment).
- **Data loader Job connects to pod DNS, not service DNS:** The `POSTGRES_HOST` is set to `pgvector-0.pgvector-postgres-service.<namespace>.svc.cluster.local` (pod-specific DNS) rather than the headless service name. This assumes exactly one replica and the pod name `pgvector-0`.
- **POSTGRESQL_ADMIN_PASSWORD same as POSTGRESQL_PASSWORD:** The StatefulSet sets `POSTGRESQL_ADMIN_PASSWORD` from the same secret key as `POSTGRESQL_PASSWORD` (see `templates/stateful-set.yaml` lines 48-50), meaning the admin and regular user share the same password.
- **Binary Build uploads ~45MB:** The OpenShift BuildConfig binary build strategy uploads the entire pgvector directory including CSV data files on every build, which may take 1-2 minutes depending on network speed (documented in README.md).
- **values.yaml placeholders not valid defaults:** The `values.yaml` uses placeholder strings like `<postgres user id>` which are not valid defaults -- Helm will install with these literal strings if `--set` flags are omitted, leading to a broken deployment.

### Testing Notes (Approach C)

- Verify the data loader Job completes: `oc get job pgvector-data-loader -n <namespace>` and check logs with `oc logs -f job/pgvector-data-loader`.
- Verify the `mcp_readonly` user exists and has correct grants: connect to the pgvector pod and run `psql -U <user> -d <dbname> -c "\du mcp_readonly"`.
- Verify views exist: `psql -U <user> -d <dbname> -c "\dv"` should show `v_rpt_customer_ltv_certified`, `v_cust_ltv_agg_DEPRECATED`, `sales_rpt_v2`.
- If the data loader Job fails with `ImagePullBackOff`, ensure `make build-data-loader-image` was run before `make install`.

---

## Approach D: Multi-Service Hub with Advisory Locks and Dual Connection Pools (from it-self-service-agent)

### When to Use

When pgvector serves as the central database for a multi-service agentic architecture (6+ consumers) that requires distributed session serialization via PostgreSQL advisory locks, dual connection pools (async SQLAlchemy for application queries and sync/async psycopg pools for LangGraph checkpointing), and LlamaStack multi-store backends (metadata, kv, sql) all pointing at the same PostgreSQL instance. Use this approach when multiple replicas of each service must coordinate request processing through database-level locking and pod heartbeats.

### Differences from Approach A

- **Multi-service consumer pattern:** Six services (agent-service, request-manager, integration-dispatcher, db-migration-job, langfuse, langfuse-worker) all consume the same pgvector secret, versus Approach A's single backend service.
- **Helm template helpers for env vars:** Database env vars are generated through reusable `_env-helpers.tpl` named templates (`self-service-agent.dbEnvVars`, `self-service-agent.dbEnvVarsNoStatementTimeout`) rather than inline env definitions in each deployment template.
- **Dual connection pools:** The `DatabaseManager` maintains both an async SQLAlchemy pool (for application queries) and separate sync/async `psycopg_pool` instances (for LangGraph's `PostgresSaver`/`AsyncPostgresSaver`), all configurable via Helm values.
- **PostgreSQL advisory locks:** Uses `pg_try_advisory_lock`/`pg_advisory_unlock` for per-session request serialization across replicas, with polling-based acquisition to avoid PG BUG #17686.
- **Alembic migrations via Kubernetes Job:** Schema migrations run as a Kubernetes Job (`db-migration-job`) rather than at service startup, with services waiting for the expected migration version before accepting traffic.
- **LlamaStack multi-store backends:** PostgreSQL serves as metadataStore, vectorIOKvstore (kv_postgres), and sql storage (sql_postgres) for llama-stack, using separate databases (`rag_blueprint`, `llama_agents`, `llama_responses`).
- **max_connections=200 tuning:** PostgreSQL args explicitly set `max_connections=200` with unified pool sizes across test/prod environments.
- **Database-level clock:** `get_db_utc_now()` uses `SELECT now()` from PostgreSQL rather than pod-local `datetime.now()` to avoid clock skew when ordering requests across pods.

### Helm Subchart Dependency

The pgvector database is declared as a subchart dependency at v0.1.0 from the shared ai-architecture-charts repository.

```yaml
# helm/Chart.yaml
dependencies:
  - name: pgvector
    version: 0.1.0
    repository: https://rh-ai-quickstart.github.io/ai-architecture-charts
```

### Extra Databases and max_connections Configuration

The pgvector subchart creates additional databases for LlamaStack backends, with `vectordb: false` since vector operations are managed by LlamaStack's own provider. PostgreSQL is tuned with `max_connections=200`.

```yaml
# helm/values.yaml
pgvector:
  args:
    - "-c"
    - "max_connections=200"
  extraDatabases:
    - name: llama_agents
      vectordb: false
    - name: llama_responses
      vectordb: false
```

### Helm Template Helpers for Database Env Vars

A reusable named template generates database env vars from the pgvector secret, including connection pool configuration. A variant (`dbEnvVarsNoStatementTimeout`) exists for services like request-manager that override `DB_STATEMENT_TIMEOUT` for lock wait operations.

```yaml
# helm/templates/_env-helpers.tpl
{{- define "self-service-agent.dbEnvVars" -}}
- name: POSTGRES_HOST
  valueFrom:
    secretKeyRef:
      name: pgvector
      key: host
# ... POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD ...
- name: DB_POOL_SIZE
  value: {{ .Values.requestManagement.database.poolSize | default "8" | quote }}
- name: DB_MAX_OVERFLOW
  value: {{ .Values.requestManagement.database.maxOverflow | default "8" | quote }}
# ... DB_POOL_TIMEOUT, DB_POOL_RECYCLE, DB_STATEMENT_TIMEOUT ...
- name: DB_SYNC_POOL_MIN_SIZE
  value: {{ .Values.requestManagement.database.syncPoolMinSize | default "1" | quote }}
{{- end }}
```

### Dual Connection Pool Architecture

The `DatabaseManager` creates an async SQLAlchemy engine for application queries and separate sync/async `psycopg_pool` instances for LangGraph checkpointing. Pool sizes are configurable via Helm values and environment variables.

```python
# shared-models/src/shared_models/database.py
class DatabaseManager:
    def __init__(self) -> None:
        self.engine = create_async_engine(
            self.config.connection_string,
            pool_pre_ping=True,
            pool_size=self.config.pool_size,
            max_overflow=self.config.max_overflow,
            connect_args={
                "server_settings": {
                    "statement_timeout": str(self.config.statement_timeout_ms),
                    "idle_in_transaction_session_timeout": str(
                        self.config.idle_transaction_timeout_ms
                    ),
                },
            },
        )
        self._sync_pool: Optional[psycopg_pool.ConnectionPool] = None
        self._async_pool: Optional[psycopg_pool.AsyncConnectionPool] = None
```

### PostgreSQL Advisory Locks for Session Serialization

Per-session advisory locks ensure one in-flight request per session across all replicas. The implementation uses `pg_try_advisory_lock` with polling (not `pg_advisory_lock` with `lock_timeout`) to avoid PG BUG #17686 where lock_timeout can race with lock grants.

```python
# request-manager/src/request_manager/session_lock.py
async def acquire_session_lock(
    session_id: str, db: AsyncSession,
    timeout_seconds: float = DEFAULT_LOCK_TIMEOUT,
) -> bool:
    lock_key = session_id_to_lock_key(session_id)
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        result = await db.execute(
            text("SELECT pg_try_advisory_lock(:key)"), {"key": lock_key},
        )
        row = result.fetchone()
        if row and row[0]:
            return True
        await asyncio.sleep(SESSION_LOCK_POLL_INTERVAL_SECONDS)
    return False
```

### Alembic Migration Job

Database schema is managed through Alembic migrations run as a Kubernetes Job before services start. Services use `wait_for_migration()` to block until the expected migration version is reached.

```yaml
# helm/templates/db-migration-job.yaml
spec:
  backoffLimit: 3
  activeDeadlineSeconds: 300
  template:
    spec:
      containers:
      - name: db-migration
        image: "{{ .Values.image.registry }}/{{ .Values.image.agentService }}:{{ .Values.image.tag }}"
        command: ["python3", "shared-models/scripts/migrate.py"]
        env:
        - name: POSTGRES_HOST
          valueFrom:
            secretKeyRef:
              name: pgvector
              key: host
```

### LlamaStack Multi-Store PostgreSQL Backends

LlamaStack uses three separate PostgreSQL databases for different storage backends: the default database for metadata/registry, `llama_agents` for kv storage (agent state), and `llama_responses` for sql storage (response history).

```yaml
# helm/values.yaml
llama-stack:
  metadataStore:
    type: postgres
    host: ${env.POSTGRES_HOST:=pgvector}
    db: ${env.POSTGRES_DBNAME:=rag_blueprint}
    namespace: llamastack_registry
  storage:
    backends:
      kv_default:
        type: kv_postgres
        host: ${env.POSTGRES_HOST:=pgvector}
        db: llama_agents
      sql_default:
        type: sql_postgres
        host: ${env.POSTGRES_HOST:=pgvector}
        db: llama_responses
```

### pgvector as LlamaStack Vector Store Provider

Knowledge bases are registered with the pgvector provider via LlamaStack's OpenAI-compatible API. The `provider_id: "pgvector"` must be specified in `extra_body` for llama-stack 0.3.3+.

```python
# agent-service/src/agent_service/knowledge/kb_manager.py
vector_store = self._llama_client.vector_stores.create(
    name=vector_store_name, extra_body={"provider_id": "pgvector"}
)
```

### Database-Level Clock for Cross-Pod Consistency

To avoid pod clock skew when ordering requests across replicas, a utility function uses PostgreSQL's `now()` instead of local `datetime.now()`.

```python
# shared-models/src/shared_models/database.py
async def get_db_utc_now() -> datetime:
    db_manager = get_database_manager()
    async with db_manager.get_session() as db:
        result = await db.execute(text("SELECT now()"))
        ts = result.scalar()
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return cast(datetime, ts)
```

### Configuration (Approach D)

- **Environment variables:**
  - `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` -- From pgvector secret, injected via Helm template helpers.
  - `DB_POOL_SIZE`, `DB_MAX_OVERFLOW`, `DB_POOL_TIMEOUT`, `DB_POOL_RECYCLE` -- Async SQLAlchemy pool configuration (default: 8/8/30/3600).
  - `DB_SYNC_POOL_MIN_SIZE`, `DB_SYNC_POOL_MAX_SIZE`, `DB_SYNC_POOL_TIMEOUT` -- Sync psycopg pool for LangGraph (default: 1/5/30).
  - `DB_STATEMENT_TIMEOUT` -- Per-query timeout in ms (default: 30000; request-manager overrides to match lock wait timeout).
  - `DB_IDLE_TRANSACTION_TIMEOUT` -- Idle transaction timeout in ms (default: 300000).
  - `EXPECTED_MIGRATION_VERSION` -- Version string services wait for before accepting traffic (default: "003").
  - `SESSION_LOCK_WAIT_TIMEOUT` -- Advisory lock acquisition timeout in seconds (default: 180).
  - `SESSION_LOCK_POLL_INTERVAL_SECONDS` -- Polling interval for lock acquisition (default: 0.05).
- **Helm values:**
  - `pgvector.args` -- PostgreSQL server arguments (e.g., `max_connections=200`).
  - `pgvector.extraDatabases` -- Additional databases for LlamaStack backends.
  - `requestManagement.database.*` -- Connection pool sizes, timeouts, and statement timeouts.
  - `requestManagement.requestManager.database.poolSize` -- Per-service pool override for request-manager.
  - `requestManagement.requestManager.sessionSerialization.*` -- Advisory lock polling and reclaim configuration.

### Known Gotchas (Approach D)

- **Dual statement timeout for request-manager:** The request-manager needs `DB_STATEMENT_TIMEOUT` set higher than `SESSION_LOCK_WAIT_TIMEOUT` (lock wait timeout in ms) so advisory lock polling queries are not cancelled. The `_env-helpers.tpl` provides a `dbEnvVarsNoStatementTimeout` variant, and `requestManagerEnvVars` adds the override computed as `lockWaitTimeoutSeconds * 1000` (see `helm/templates/_env-helpers.tpl` lines 57-106, 198-200).
- **pg_try_advisory_lock polling instead of pg_advisory_lock:** The codebase explicitly uses polling with `pg_try_advisory_lock` rather than blocking `pg_advisory_lock` with `lock_timeout` to avoid PG BUG #17686. The polling interval (0.05s default) means there is a small latency cost on lock acquisition (see `request-manager/src/request_manager/session_lock.py` lines 36-42).
- **Connection pool budget for max_connections=200:** With 6+ services each having pool_size=8 and max_overflow=8, plus sync pools (min=1, max=5 each), the total potential connections can approach the 200 limit under load. The comment in `values.yaml` (line 133) notes this is unified for test/prod.
- **provider_id required in extra_body:** When creating vector stores via LlamaStack's OpenAI-compatible API, `provider_id: "pgvector"` must be passed in `extra_body` for llama-stack 0.3.3+. Without this, the vector store may not be associated with the pgvector provider (see `agent-service/src/agent_service/knowledge/kb_manager.py` lines 87-91).
- **Alembic defaults in alembic.ini override at runtime:** The `alembic.ini` hardcodes `sqlalchemy.url = postgresql://pgvector:pgvector@pgvector:5432/llama_agents` but the `env.py` overrides this from `DatabaseConfig` at runtime (see `shared-models/alembic/env.py` line 24). This default only matters for local `alembic` CLI usage.

### Testing Notes (Approach D)

- Verify migration Job completes: `oc get job <release>-db-migration` and check logs for version output.
- Verify services waited for migration: search pod logs for "Database migration completed successfully" with `version=003`.
- Verify advisory locks are functioning: check request-manager logs for "Session lock acquired" entries with lock_key values.
- Verify connection pool health: look for "Database configuration initialized successfully" logs showing pool_size and max_overflow values.
- Verify multiple databases exist: connect to pgvector pod and run `psql -U postgres -l | grep -E 'rag_blueprint|llama_agents|llama_responses'`.

---

## Approach E: Inline Helm StatefulSet with Dual Roles and Direct Vector Search (from multi-agent-loan-origination)

### When to Use

When PostgreSQL with pgvector is deployed as an inline Helm StatefulSet within the parent chart (not an ai-architecture-charts subchart), the application requires dual PostgreSQL roles for regulatory data isolation (HMDA), and vector search is performed via direct SQL queries with pgvector operators (not delegated to LlamaStack). Use this approach when the quickstart needs role-based database access control where different application concerns (lending vs compliance) use separate connection strings with different PostgreSQL roles, and vector search results require domain-specific post-processing such as tier-based boosting.

### Differences from Approach A

- **Inline Helm templates, not subchart:** Database StatefulSet, Service, ConfigMap, and Secret templates are defined directly in the parent chart (`deploy/helm/mortgage-ai/templates/database-*.yaml`), not pulled as a dependency from ai-architecture-charts.
- **Dual PostgreSQL roles for data isolation:** Two application roles (`lending_app`, `compliance_app`) with different GRANT permissions enforce HMDA regulatory data separation at the database level. The init script creates both roles with separate credentials.
- **Dual connection strings:** `DATABASE_URL` connects as `lending_app` (or default user) for all lending operations; `COMPLIANCE_DATABASE_URL` connects as `compliance_app` for HMDA demographic data access. The API maintains separate SQLAlchemy session factories.
- **Direct pgvector SQL queries:** Vector search uses raw SQL with the pgvector `<=>` cosine distance operator via SQLAlchemy `text()`, not through LlamaStack's vector_io provider.
- **Tier-based result boosting:** Search results apply score multipliers based on document tier (federal 1.5x, agency 1.2x, internal 1.0x) to prioritize authoritative regulatory sources.
- **HNSW index with cosine ops:** Migration explicitly creates an HNSW index with `vector_cosine_ops` operator class for fast approximate nearest neighbor search.
- **Vector(768) dimension:** Uses 768-dimensional embeddings (nomic-embed-text-v1.5) versus Approach A's 384-dimensional (all-MiniLM-L6-v2).
- **Secrets from Kubernetes Secret via secretKeyRef:** Database credentials are stored in a Kubernetes Secret and injected into the StatefulSet via `secretKeyRef`, not assembled from individual keys in deployment templates.
- **Multiple databases via init script:** The init script creates an additional `mlflow` database for observability alongside the main application database, rather than using `extraDatabases` values.

### Inline Helm StatefulSet

The database is deployed as a StatefulSet with optional PVC persistence, defined directly in the parent chart templates. The `database.enabled` flag controls whether the in-cluster database is deployed (set to `false` for external databases).

```yaml
# deploy/helm/mortgage-ai/templates/database-deployment.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: {{ .Values.database.name }}
spec:
  replicas: 1
  serviceName: {{ .Values.database.name }}
  template:
    spec:
      containers:
        - name: postgres
          image: "docker.io/{{ .Values.database.image.repository }}:{{ .Values.database.image.tag }}"
          env:
            - name: POSTGRES_DB
              valueFrom:
                secretKeyRef:
                  name: {{ include "mortgage-ai.fullname" . }}-secret
                  key: POSTGRES_DB
            - name: PGDATA
              value: /var/lib/postgresql/data/pgdata
          volumeMounts:
            - name: init-scripts
              mountPath: /docker-entrypoint-initdb.d
              readOnly: true
```

```yaml
# deploy/helm/mortgage-ai/values.yaml
database:
  enabled: true
  name: mortgage-ai-db
  image:
    repository: pgvector/pgvector
    tag: pg16
  persistence:
    enabled: true
    size: 10Gi
    accessMode: ReadWriteOnce
```

### ConfigMap Init Script with Role Creation

The init script enables the pgvector extension, creates an additional database for MLflow observability, and creates dual PostgreSQL roles with separate credentials for HMDA data isolation. The Helm ConfigMap version uses idempotent `IF NOT EXISTS` checks for role creation.

```yaml
# deploy/helm/mortgage-ai/templates/database-configmap.yaml
data:
  init-databases.sh: |
    #!/bin/bash
    set -e
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
        CREATE EXTENSION IF NOT EXISTS vector;
        DO \$\$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'lending_app') THEN
                CREATE ROLE lending_app WITH LOGIN PASSWORD 'lending_pass';
            END IF;
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'compliance_app') THEN
                CREATE ROLE compliance_app WITH LOGIN PASSWORD 'compliance_pass';
            END IF;
        END
        \$\$;
        GRANT CONNECT ON DATABASE "${POSTGRES_DB}" TO lending_app;
        GRANT CONNECT ON DATABASE "${POSTGRES_DB}" TO compliance_app;
    EOSQL
```

### Dual Connection Strings for Data Isolation

The API maintains two separate connection strings. `DATABASE_URL` uses the default user (or `lending_app`) for all lending operations, while `COMPLIANCE_DATABASE_URL` uses the `compliance_app` role for HMDA demographic data access. This enforces regulatory data isolation at the database connection level.

```python
# packages/api/src/core/config.py
DATABASE_URL: str = Field(
    default="postgresql+asyncpg://user:password@localhost:5433/mortgage-ai",
    description="Async SQLAlchemy connection string (asyncpg driver).",
)
COMPLIANCE_DATABASE_URL: str = Field(
    default="postgresql+asyncpg://compliance_app:compliance_pass@localhost:5433/mortgage-ai",
    description="Async connection string for compliance_app role (HMDA schema access).",
)
```

### Alembic Migration with pgvector.sqlalchemy

The compliance KB tables are created via an Alembic migration that enables the pgvector extension, creates `kb_documents` and `kb_chunks` tables with `Vector(768)` columns, builds an HNSW index, and applies role-specific GRANT permissions.

```python
# packages/db/alembic/versions/f7a8b9c0d1e2_add_compliance_kb_tables.py
from pgvector.sqlalchemy import Vector

def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table("kb_chunks",
        sa.Column("embedding", Vector(768), nullable=True),
        # ...
    )
    op.execute(
        "CREATE INDEX ix_kb_chunks_embedding ON kb_chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )
    for table in ("kb_documents", "kb_chunks"):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO lending_app")
        op.execute(f"GRANT SELECT ON {table} TO compliance_app")
```

### Direct pgvector Vector Search with Tier Boosting

Vector search uses raw SQL with the pgvector `<=>` cosine distance operator, fetches 3x the requested results, applies tier-based boost factors, re-sorts, and truncates. This bypasses LlamaStack and gives full control over result ranking.

```python
# packages/api/src/services/compliance/knowledge_base/search.py
_TIER_BOOST = {1: 1.5, 2: 1.2, 3: 1.0}
_MIN_SIMILARITY = 0.3

sql = text("""
    SELECT c.id, c.chunk_text, c.section_ref, d.title, d.tier,
           d.effective_date,
           1 - (c.embedding <=> :query_vec) AS similarity
    FROM kb_chunks c
    JOIN kb_documents d ON c.document_id = d.id
    WHERE c.embedding IS NOT NULL
    ORDER BY c.embedding <=> :query_vec
    LIMIT :fetch_limit
""")
```

### SQLAlchemy 2.0 Models with pgvector Column Type

The ORM models use the `pgvector.sqlalchemy.Vector` column type directly in SQLAlchemy model definitions. The `KBDocument` model includes a tier field (1=federal, 2=agency, 3=internal) for the boosting system.

```python
# packages/db/src/db/models.py
from pgvector.sqlalchemy import Vector

class KBChunk(Base):
    __tablename__ = "kb_chunks"
    id = Column(Integer, primary_key=True, autoincrement=True)
    document_id = Column(Integer, ForeignKey("kb_documents.id", ondelete="CASCADE"))
    chunk_text = Column(Text, nullable=False)
    embedding = Column(Vector(768), nullable=True)
    document = relationship("KBDocument", back_populates="chunks")
```

### Configuration (Approach E)

- **Environment variables:**
  - `DATABASE_URL` -- Async SQLAlchemy connection string for lending operations (`postgresql+asyncpg://user:password@host:port/db`). Connects as default user or `lending_app` role.
  - `COMPLIANCE_DATABASE_URL` -- Async connection string for HMDA compliance operations. Connects as `compliance_app` role with restricted access.
  - `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` -- Set on the StatefulSet container from the Helm Secret via `secretKeyRef`.
- **Config files:**
  - `packages/api/src/core/config.py` -- Pydantic Settings with both `DATABASE_URL` and `COMPLIANCE_DATABASE_URL` fields.
  - `config/postgres/init-databases.sh` -- Init script mounted into `/docker-entrypoint-initdb.d` for local compose; inline in ConfigMap for Helm.
- **Helm values:**
  - `database.enabled` -- Toggle in-cluster database deployment (default: `true`). Set to `false` for external PostgreSQL.
  - `database.image.repository`, `database.image.tag` -- Container image (default: `pgvector/pgvector:pg16`).
  - `database.persistence.enabled`, `database.persistence.size` -- PVC configuration (default: `true`, `10Gi`).
  - `secrets.DATABASE_URL`, `secrets.COMPLIANCE_DATABASE_URL` -- Override connection strings for external databases.
- **Python dependencies:**
  - `pgvector>=0.3.0` in `packages/db/pyproject.toml` for `pgvector.sqlalchemy.Vector` type.

### Known Gotchas (Approach E)

- **Hardcoded role passwords in init script:** The `lending_app` and `compliance_app` role passwords (`lending_pass`, `compliance_pass`) are hardcoded in both the local compose init script (`config/postgres/init-databases.sh` lines 14-15) and the Helm ConfigMap template. These are not sourced from Helm secrets and would need to be parameterized for production.
- **PGDATA subdirectory required for StatefulSet:** The StatefulSet sets `PGDATA=/var/lib/postgresql/data/pgdata` (a subdirectory of the PVC mount at `/var/lib/postgresql/data`). This is required because the pgvector image's entrypoint expects the data directory to be empty on first init, but the PVC mount point may contain a `lost+found` directory (see `database-deployment.yaml` line 51).
- **Per-table GRANT in migration:** The Alembic migration applies GRANT statements per table (`GRANT SELECT, INSERT, UPDATE, DELETE ON kb_documents TO lending_app`). New tables added by future migrations must include their own GRANT statements or the roles will not have access.
- **Local compose port offset:** The local compose maps PostgreSQL to port 5433 (not the default 5432) to avoid conflicts with a host PostgreSQL installation. The `.env.example` `DATABASE_URL` uses port 5433 while the Helm `values.yaml` uses port 5432 -- this difference can cause confusion when switching between local and cluster environments.
- **MLflow database creation only in local init script:** The local `config/postgres/init-databases.sh` creates an additional `mlflow` database (line 9), but the Helm ConfigMap version does not. MLflow on the cluster uses its own database configuration separate from the application database.

### Testing Notes (Approach E)

- Verify the pgvector extension is enabled: connect to the database and run `SELECT extname FROM pg_extension WHERE extname = 'vector'`.
- Verify dual roles exist: `SELECT rolname FROM pg_roles WHERE rolname IN ('lending_app', 'compliance_app')`.
- Verify HNSW index: `SELECT indexname FROM pg_indexes WHERE tablename = 'kb_chunks' AND indexname = 'ix_kb_chunks_embedding'`.
- Verify role isolation: connect as `lending_app` and confirm it cannot query `hmda.borrower_demographics`; connect as `compliance_app` and confirm SELECT-only access to `kb_documents` and `kb_chunks`.

---

## Approach F: Feast Online Store with Vector-Enabled pgvector (from product-recommender-system)

### When to Use

When PostgreSQL with pgvector serves as both the relational application database (users, products, reviews, categories) via SQLAlchemy async and the Feast online store with `vector_enabled: true` for multiple embedding types (item, user, text, CLIP, category). Use this approach when the quickstart needs a feature store pattern with Feast-managed vector search rather than LlamaStack or direct pgvector SQL queries, and when a `feast.dev/v1alpha1` FeatureStore CRD manages the online/offline/registry services.

### Differences from Approach A

- **Feast as vector search layer, not LlamaStack:** Vector search is performed via Feast's `retrieve_online_documents` API backed by pgvector's `vector_enabled: true` online store configuration, not through LlamaStack's `vector_io` provider.
- **FeatureStore CRD for service orchestration:** The Feast operator creates online store, offline store (DuckDB), and registry services as separate pods via the `feast.dev/v1alpha1` FeatureStore custom resource, each mounting the `pgvector` secret.
- **Multiple embedding feature views:** Six distinct Feast feature views with `vector_index=True` and `vector_search_metric="cosine"` (item_embedding, user_embedding, item_textual_features_embed, item_name_features_embed, item_category_features_embed, item_clip_features_embed), each backed by a PushSource.
- **Hybrid SQL + semantic search:** Text search combines deterministic SQL (exact, prefix, substring matching via `regexp_replace` in PostgreSQL) with Feast's `retrieve_online_documents` for semantic vector search as a fallback.
- **No Alembic migrations:** Schema created via `Base.metadata.drop_all` + `Base.metadata.create_all` in the db-init Job, not via Alembic migration framework.
- **Helm post-install Job for db-init:** A Kubernetes Job with Helm hook annotations runs `init_backend.py` to seed categories, products, users, and reviews; the backend Deployment has an initContainer that polls for the Job's completion via `oc get job`.
- **Mixed sync/async access:** The backend uses async SQLAlchemy with `asyncpg` for API routes, while the Feast service uses sync SQLAlchemy with `psycopg2-binary` for direct database queries (name boosting, model version lookup).

### Helm Subchart Dependency

The pgvector database is declared as a subchart dependency at v0.1.0 from the shared ai-architecture-charts repository.

```yaml
# helm/product-recommender-system/Chart.yaml
dependencies:
  - name: pgvector
    version: 0.1.0
    repository: https://rh-ai-quickstart.github.io/ai-architecture-charts
```

### Feast Online Store with vector_enabled

The Feast feature store configuration enables pgvector's vector capabilities in the online store, allowing Feast to use PostgreSQL-native vector operations for similarity search.

```yaml
# recommendation-core/src/recommendation_core/feature_repo/feature_store.yaml
online_store:
  type: postgres
  host: ${DB_HOST}
  port: ${DB_PORT}
  database: ${DB_NAME}
  user: ${DB_USER}
  password: ${DB_PASSWORD}
  vector_enabled: true
```

### FeatureStore CRD with pgvector Secret

The Feast operator manages online/offline/registry services via a custom resource. Each service receives the pgvector secret via `envFrom`, and the online store persists to PostgreSQL with a secret reference for connection details.

```yaml
# helm/product-recommender-system/templates/featurestore.yaml
apiVersion: feast.dev/v1alpha1
kind: FeatureStore
metadata:
  name: feast-recommendation
spec:
  feastProject: {{ .Values.feast.project }}
  services:
    onlineStore:
      persistence:
        store:
          type: postgres
          secretRef:
            name: feast-data-stores
      server:
        envFrom:
        - secretRef:
            name: pgvector
    registry:
      local:
        persistence:
          store:
            type: sql
            secretRef:
              name: feast-data-stores
```

### Multiple Embedding Feature Views with Vector Index

Feast feature views define multiple embedding types with `vector_index=True` and cosine similarity metric. Each view is backed by a PushSource, meaning embeddings are pushed into the online store during the training pipeline.

```python
# recommendation-core/src/recommendation_core/feature_repo/feature_views.py
item_embedding_view = FeatureView(
    name="item_embedding",
    entities=[item_entity],
    ttl=timedelta(days=365 * 5),
    schema=[
        Field(name="item_id", dtype=String),
        Field(
            name="embedding",
            dtype=Array(Float32),
            vector_index=True,
            vector_search_metric="cosine",
        ),
    ],
    source=item_embed_push_source,
    online=True,
)
```

### Feast Vector Search via retrieve_online_documents

New user recommendations use the Feast `retrieve_online_documents` API to find similar items by encoding the user's features into an embedding and querying the vector index.

```python
# backend/src/services/feast/feast_service.py
def load_items_new_user(self, user: User, k: int = 10):
    user_as_df = pd.DataFrame([user.model_dump()])
    self.user_encoder.eval()
    user_embed = self.user_encoder(**data_preproccess(user_as_df))[0]
    top_k = self.store.retrieve_online_documents(
        query=user_embed.tolist(), top_k=k, features=["item_embedding:item_id"]
    )
    top_item_ids = top_k.to_df()["item_id"].tolist()
    return self._item_ids_to_product_list(top_item_ids)
```

### Hybrid Deterministic + Semantic Text Search

Text search combines SQL deterministic matching (exact, prefix, contains) using PostgreSQL `regexp_replace` with Feast semantic vector search as a fallback when deterministic results are insufficient.

```python
# backend/src/services/feast/feast_service.py
def search_item_by_text(self, text: str, k=5):
    # Deterministic name boosting via SQL
    norm_expr = "regexp_replace(lower(name), '[^a-z0-9]', '', 'g')"
    exact_ids = _query_item_ids(f"{norm_expr} = :qn", {"qn": qn}, exact_limit)
    prefix_ids = _query_item_ids(f"{norm_expr} LIKE :prefix", {"prefix": f"{qn}%"}, ...)
    contains_ids = _query_item_ids(f"{norm_expr} LIKE :contains", {"contains": f"%{qn}%"}, ...)
    # If deterministic results >= k, return immediately
    if len(merged) >= k:
        return self._item_ids_to_product_list(merged[:k])
    # Otherwise fill with semantic vector search via Feast
    semantic_df = search_service.search_by_text(text, semantic_k)
```

### Async SQLAlchemy with URL Rewrite

The backend connects using async SQLAlchemy with asyncpg. The `DATABASE_URL` from the pgvector secret `uri` key is rewritten from `postgresql://` to `postgresql+asyncpg://` at engine creation time.

```python
# backend/src/database/db.py
def get_engine():
    engine = create_async_engine(
        os.getenv("DATABASE_URL", None).replace("postgresql://", "postgresql+asyncpg://"),
        echo=True,
    )
    return engine
```

### Secret-Based Connection Wiring with Individual Keys

The parent chart values wire database credentials from the pgvector secret via individual `secretKeyRef` keys (host, port, user, password, dbname) and also reference the `uri` key for the assembled `DATABASE_URL`.

```yaml
# helm/product-recommender-system/values.yaml
env:
  - name: DB_HOST
    valueFrom:
      secretKeyRef:
        name: pgvector
        key: host
backend:
  additionalEnv:
    - name: DATABASE_URL
      valueFrom:
        secretKeyRef:
          name: pgvector
          key: uri
```

### Helm Post-Install Job for Database Initialization

A Kubernetes Job seeds the database after chart installation. The Job's initContainer waits for the `model_version` table (populated by the training pipeline) before running the backend init script that creates tables and seeds data.

```yaml
# helm/product-recommender-system/templates/backend.yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ include "product-recommender-system.fullname" . }}-db-init
  annotations:
    "helm.sh/hook": "post-install,post-upgrade"
    "helm.sh/hook-weight": "1"
    "helm.sh/hook-delete-policy": "before-hook-creation"
spec:
  template:
    spec:
      initContainers:
        - name: wait-until-model-training-workflow
          image: postgres:15-alpine
          command:
            - /bin/sh
            - -c
            - |
              until PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -U $DB_USER -d $DB_NAME -c "SELECT 1 FROM model_version LIMIT 1" > /dev/null 2>&1; do
                echo "Waiting for model_version table..."
                sleep 10
              done
```

### Readiness Probe via Database Connectivity

The backend health check verifies database connectivity by executing a simple query.

```python
# backend/src/routes/health.py
@router.get("/health/ready")
async def readiness_check(db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception:
        return Response(status_code=503)
```

### Configuration (Approach F)

- **Environment variables:**
  - `DATABASE_URL` -- Pre-built PostgreSQL URI from the `pgvector` secret `uri` key. The backend rewrites `postgresql://` to `postgresql+asyncpg://` at engine creation.
  - `DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME` -- Individual secret keys from `pgvector` secret, consumed by env vars for Feast online store config, db-init Job, and pipeline Job.
  - `USE_LLM_FOR_REVIEWS` -- Controls whether init_backend.py uses an LLM to generate synthetic reviews (default: `"true"` in values.yaml).
  - `LLM_API_BASE`, `LLM_API_KEY`, `LLM_MODEL` -- LLM connection for review generation during db-init.
- **Config files:**
  - `recommendation-core/src/recommendation_core/feature_repo/feature_store.yaml` -- Feast feature store config with `vector_enabled: true` and env var substitution for DB credentials.
  - `backend/src/database/db.py` -- Async SQLAlchemy engine creation with `postgresql://` to `postgresql+asyncpg://` rewrite.
- **Helm values:**
  - `feast.project` -- Feast project name (default: `feast_rec_sys`).
  - `feast.secret` -- TLS secret name for Feast registry communication.
  - `feast.registry` -- Feast registry service name.
  - `dbName` -- Application database name (default: `product_recommender_system`).
  - `backend.additionalEnv` -- Includes `DATABASE_URL` from pgvector secret `uri` key.
- **Python dependencies:**
  - `feast[postgres]==0.49.0` -- Feast with PostgreSQL online store support.
  - `asyncpg==0.29.0` -- Async PostgreSQL driver for SQLAlchemy.
  - `psycopg2-binary>=2.9.10` -- Sync PostgreSQL driver for Feast service direct queries.
  - `sqlalchemy==2.0.30` -- ORM for relational data models.

### Known Gotchas (Approach F)

- **DATABASE_URL rewrite assumes plain postgresql:// prefix:** The `db.py` engine creation uses `.replace("postgresql://", "postgresql+asyncpg://")` which is a non-anchored string replace. If the URI already contains `postgresql+asyncpg://` or has `postgresql` in the password or path, the replace may produce an invalid URL (see `backend/src/database/db.py` line 9).
- **Base.metadata.drop_all in init script:** The `create_tables()` function in `init_backend.py` runs `Base.metadata.drop_all` before `Base.metadata.create_all` (see `backend/src/init_backend.py` lines 512-514), which destroys all existing data on every db-init Job run. The comment notes "dev only" but the Helm hook runs on both post-install and post-upgrade.
- **db-init Job waits for model_version table:** The initContainer polls for the `model_version` table via psql, which is populated by the KFP training pipeline. If the pipeline has not run, the db-init Job will wait indefinitely (see `backend.yaml` lines 236-240).
- **Backend initContainer uses oc CLI:** The backend Deployment's initContainer uses `oc get job product-recommender-system-db-init` to poll for Job completion (see `backend.yaml` lines 76-79). This requires the `registry.redhat.io/openshift4/ose-cli:latest` image and RBAC permissions (job-viewer Role/RoleBinding) to query Job status.
- **Mixed sync/async database access:** The FeastService uses synchronous SQLAlchemy (`create_engine` with `psycopg2`) for direct SQL queries (model version lookup, name boosting) while the FastAPI routes use async SQLAlchemy (`asyncpg`). These are separate connection pools that may compete for database connections (see `feast_service.py` lines 64-67, 202-205).
- **feast-data-stores Secret assembles connection strings from variable substitution:** The `feast-data-stores` Secret uses `${user}`, `${password}`, `${host}`, etc. placeholders that must be resolved from the pgvector secret environment variables at Feast pod startup (see `featurestore.yaml` lines 7-23).

### Testing Notes (Approach F)

- Verify the pgvector secret exists with all required keys: `oc get secret pgvector -o jsonpath='{.data}' | jq -r 'keys[]'` should show `host`, `port`, `user`, `password`, `dbname`, `uri`.
- Verify the Feast FeatureStore CR is ready: `oc get featurestore feast-recommendation -o jsonpath='{.status}'`.
- Verify the db-init Job completed: `oc get job product-recommender-system-db-init` and check logs.
- Verify readiness probe: `curl -k https://<route>/health/ready` should return `{"status": "ready"}`.
- Verify Feast online store has vector data: connect to the backend pod and run a test query via the Feast API.

---

## Approach G: Inline Helm Deployment with Semantic Category Matching and Interchangeable Embedding Providers (from spending-transaction-monitor)

### When to Use

When PostgreSQL with pgvector is deployed as an inline Helm Deployment (not a subchart or StatefulSet) within the parent chart, and pgvector is used for semantic merchant category normalization rather than RAG or compliance KB search. Use this approach when the quickstart needs to match free-text merchant names to canonical categories via vector similarity, supports multiple interchangeable embedding providers (OpenAI, sentence-transformers, Ollama) with dynamic column dimension alteration, and requires custom PostgreSQL functions (e.g., haversine distance) managed through Alembic migrations.

### Differences from Approach A

- **Inline Helm Deployment, not subchart:** Database Deployment, Service, PVC, ConfigMap, and migration Job templates are defined directly in the parent chart (`deploy/helm/spending-monitor/templates/database-*.yaml`), not pulled as a dependency from ai-architecture-charts.
- **Deployment, not StatefulSet:** Uses a Kubernetes Deployment with a separate PVC (not StatefulSet volumeClaimTemplates), with `strategy.type: Recreate` to avoid dual-attach issues on the PVC.
- **Semantic category matching, not RAG:** pgvector stores merchant category embeddings in a `MerchantCategoryEmbedding` table with `Vector(384)` columns. L2 distance (`<->`) queries match transaction merchant names to canonical categories -- this is semantic normalization, not document retrieval.
- **Three interchangeable embedding providers:** Separate scripts populate embeddings via OpenAI (`text-embedding-3-small`, 1536 dim), sentence-transformers (`all-MiniLM-L6-v2`, 384 dim), or Ollama (`all-minilm`, 384 dim). The local/Ollama scripts dynamically ALTER the embedding column dimension before populating.
- **Custom PostgreSQL functions via Alembic:** Alembic migrations create a `haversine_distance_km` PL/pgSQL function and a `transaction_location_analysis` view with risk-level classification (VERY_HIGH_RISK/HIGH_RISK/MEDIUM_RISK/LOW_RISK/NORMAL based on distance thresholds).
- **Comprehensive startup.sh init pipeline:** A migration Job runs `startup.sh` that sequentially waits for PostgreSQL readiness (`pg_isready`), runs Alembic migrations, loads CSV seed data, and optionally sets up Keycloak realm/user sync.
- **Dual pgvector extension enablement:** The vector extension is enabled both by a SQL init script in `/docker-entrypoint-initdb.d` (runs on first container start) and by the Alembic initial migration (`CREATE EXTENSION IF NOT EXISTS vector`). The `IF NOT EXISTS` clause makes the redundancy harmless.
- **Custom container image on Quay:** The Helm chart uses `quay.io/rh-ai-quickstart/pgvector:pg16` rather than the upstream `pgvector/pgvector:pg16` or the community `postgres:16` images.

### Inline Helm Deployment with PVC

The database is deployed as a Deployment (not StatefulSet) with an external PVC for persistence. The `database.enabled` flag controls whether the in-cluster database is deployed.

```yaml
# deploy/helm/spending-monitor/templates/database-deployment.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Values.database.name }}
spec:
  replicas: 1
  strategy:
    type: Recreate
  template:
    spec:
      containers:
        - name: postgres
          image: "{{ .Values.database.image.repository }}:{{ .Values.database.image.tag}}"
          env:
            - name: PGDATA
              value: /var/lib/postgresql/data/pgdata
          volumeMounts:
            - name: postgres-storage
              mountPath: /var/lib/postgresql/data
            - name: init-scripts
              mountPath: /docker-entrypoint-initdb.d
      volumes:
        - name: postgres-storage
          persistentVolumeClaim:
            claimName: {{ .Values.database.name }}-pvc
```

```yaml
# deploy/helm/spending-monitor/values.yaml
database:
  enabled: true
  name: spending-monitor-db
  image:
    repository: quay.io/rh-ai-quickstart/pgvector
    tag: pg16
  persistence:
    enabled: true
    size: 10Gi
    accessMode: ReadWriteOnce
```

### pgvector Extension Init Script with Verification

The SQL init script enables the vector extension, grants schema usage, and runs a self-test that verifies vector creation, insertion, and L2 distance search before the database is considered ready.

```sql
-- packages/db/init-scripts/01-enable-pgvector.sql
CREATE EXTENSION IF NOT EXISTS vector;
GRANT USAGE ON SCHEMA public TO "user";

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
        RAISE NOTICE 'pgvector extension successfully installed';
    ELSE
        RAISE EXCEPTION 'Failed to install pgvector extension';
    END IF;
END
$$;
```

### Merchant Category Embedding Model with Vector(384)

The ORM model uses `pgvector.sqlalchemy.Vector` with 384 dimensions matching the `all-MiniLM-L6-v2` model. A companion `MerchantCategorySynonym` table provides deterministic synonym-to-canonical mappings.

```python
# packages/db/src/db/models.py
from pgvector.sqlalchemy import Vector

class MerchantCategoryEmbedding(Base):
    __tablename__ = 'merchant_category_embeddings'
    category: Mapped[str] = mapped_column(String, primary_key=True)
    embedding: Mapped[list[float]] = mapped_column(Vector(384))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
```

### Interchangeable Embedding Providers with Dynamic Schema Alteration

Three separate scripts support different embedding providers. The local and Ollama scripts dynamically alter the embedding column dimension to match the model output before populating, allowing the same database schema to work with different model dimensions.

```python
# packages/db/src/db/scripts/populate_embeddings_local.py
MODEL_NAME = 'sentence-transformers/all-MiniLM-L6-v2'
EXPECTED_DIMENSIONS = 384

async def update_database_schema(session: AsyncSession) -> None:
    await session.execute(
        text('ALTER TABLE merchant_category_embeddings DROP COLUMN IF EXISTS embedding')
    )
    await session.execute(
        text(f'ALTER TABLE merchant_category_embeddings ADD COLUMN embedding vector({EXPECTED_DIMENSIONS})')
    )
```

### L2 Distance Search for Category Matching

Semantic category search uses the pgvector `<->` L2 distance operator via raw SQL `text()` queries. The query embedding is serialized to PostgreSQL vector format and cast to the `vector` type.

```python
# packages/db/src/db/scripts/populate_embeddings_local.py
vector_str = '[' + ','.join(map(str, query_embedding)) + ']'
result = await session.execute(
    text(f"""
        SELECT category, embedding <-> '{vector_str}'::vector as distance
        FROM merchant_category_embeddings
        ORDER BY embedding <-> '{vector_str}'::vector
        LIMIT 1
    """)
)
```

### Custom Haversine Distance Function via Alembic

An Alembic migration creates a PL/pgSQL function for geographic distance calculation and a view that classifies transaction risk based on distance between user location and merchant location.

```python
# packages/db/alembic/versions/e35d4db01ac2_add_location_distance_function.py
def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION haversine_distance_km(
            lat1 DOUBLE PRECISION, lon1 DOUBLE PRECISION,
            lat2 DOUBLE PRECISION, lon2 DOUBLE PRECISION
        ) RETURNS DOUBLE PRECISION AS $$
        DECLARE
            r DOUBLE PRECISION := 6371;
        BEGIN
            IF lat1 IS NULL OR lon1 IS NULL OR lat2 IS NULL OR lon2 IS NULL THEN
                RETURN NULL;
            END IF;
            -- Haversine formula ...
            RETURN r * c;
        END;
        $$ LANGUAGE plpgsql IMMUTABLE;
    """)
```

### Alembic Async-to-Sync URL Rewrite (asyncpg to psycopg2)

Alembic migrations rewrite the async `+asyncpg` driver to the synchronous `+psycopg2` driver. Unlike Approach A which strips to plain `postgresql://`, this quickstart explicitly targets `psycopg2`.

```python
# packages/db/alembic/env.py
if '+asyncpg' in url:
    config.set_main_option('sqlalchemy.url', url.replace('+asyncpg', '+psycopg2'))
```

### Async SQLAlchemy Engine with pydantic-settings

The database module uses `pydantic-settings` with `.env` file support for configuration. The engine is created once at module level with the `asyncpg` driver, and a `DatabaseService` class provides health check functionality.

```python
# packages/db/src/db/config.py
class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    DATABASE_URL: str = (
        'postgresql+asyncpg://user:password@localhost:5432/spending-monitor'
    )

# packages/db/src/db/database.py
engine = create_async_engine(settings.DATABASE_URL, echo=False)
SessionLocal = sessionmaker(
    autocommit=False, autoflush=False, bind=engine, class_=AsyncSession
)
```

### Helm Migration Job with startup.sh Pipeline

A Kubernetes Job runs as a Helm `post-install,post-upgrade` hook. It uses an init container to wait for PostgreSQL readiness, then executes `startup.sh` which sequentially runs Alembic migrations, loads CSV seed data, and optionally syncs Keycloak users.

```yaml
# deploy/helm/spending-monitor/templates/migration-job.yaml
metadata:
  annotations:
    "helm.sh/hook": post-install,post-upgrade
    "helm.sh/hook-weight": "1"
    "helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded
spec:
  template:
    spec:
      initContainers:
        - name: wait-for-database
          image: postgres:16-alpine
          command:
            - /bin/sh
            - -c
            - |
              until pg_isready -h {{ .Values.database.name }} -p 5432; do
                sleep 3
              done
      containers:
        - name: migration
          command:
            - /app/startup.sh
```

### Local Dev Compose with pgvector Image

Local development uses the `pgvector/pgvector:pg16` community image (which includes the pgvector extension pre-installed) via a dedicated compose file in the db package. The init script is volume-mounted from `init-scripts/`.

```yaml
# packages/db/compose.yml
services:
  postgres:
    image: docker.io/pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: spending-monitor
      POSTGRES_USER: user
      POSTGRES_PASSWORD: password
    ports:
      - "${DB_PORT:-5432}:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./init-scripts:/docker-entrypoint-initdb.d
```

### Configuration (Approach G)

- **Environment variables:**
  - `DATABASE_URL` -- Async SQLAlchemy connection string (`postgresql+asyncpg://user:password@host:5432/spending-monitor`). Sourced from Helm Secret via `secretKeyRef`.
  - `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` -- Set on the Deployment container from the Helm Secret.
  - `POSTGRES_HOST` -- Set on the migration Job to the database Service name (default: `spending-monitor-db`).
  - `PGDATA` -- Set to `/var/lib/postgresql/data/pgdata` to place data inside the PVC mount subdirectory.
  - `DB_PORT` -- Local dev compose port override (default: 5432).
  - `BYPASS_AUTH` -- Controls whether the startup.sh pipeline attempts Keycloak realm/user sync (default: `true` to skip).
  - `PYTHONPATH` -- Set on the migration Job to `/app/packages/db/src:/app/packages/api/src` for module imports.
- **Config files:**
  - `packages/db/src/db/config.py` -- `DatabaseSettings` (pydantic-settings) with `DATABASE_URL` defaulting to localhost asyncpg connection. Supports `.env` file loading.
  - `packages/db/alembic/env.py` -- Handles async-to-sync URL rewrite (`+asyncpg` to `+psycopg2`) and imports all models for autogenerate.
- **Helm values:**
  - `database.enabled` -- Toggle in-cluster database deployment.
  - `database.name` -- Service and deployment name (default: `spending-monitor-db`).
  - `database.image.repository`, `database.image.tag` -- Container image (default: `quay.io/rh-ai-quickstart/pgvector:pg16`).
  - `database.persistence.enabled`, `database.persistence.size`, `database.persistence.accessMode` -- PVC configuration (default: `true`, `10Gi`, `ReadWriteOnce`).
  - `database.resources` -- Resource requests/limits (default: 256Mi/512Mi memory, 100m/500m CPU).
  - `secrets.DATABASE_URL` -- Full connection string for the API service.
  - `secrets.POSTGRES_DB`, `secrets.POSTGRES_USER`, `secrets.POSTGRES_PASSWORD` -- Individual credential overrides.
- **Python dependencies:**
  - `pgvector>=0.2.0` in `packages/db/pyproject.toml` for `pgvector.sqlalchemy.Vector` type.
  - `sentence-transformers>=2.2.0` (optional, for local embedding generation).
  - `openai>=1.109.1` (optional, for OpenAI embedding generation).
  - `asyncpg>=0.29.0` for async PostgreSQL driver.
  - `psycopg2-binary>=2.9.0` for Alembic sync migrations.

### Known Gotchas (Approach G)

- **populate_embeddings.py dimension mismatch with model column:** The `populate_embeddings.py` (OpenAI) script uses `text-embedding-3-small` which produces 1536-dimensional embeddings and validates against 1536 dimensions (see `validate_embeddings` line 106), but the `MerchantCategoryEmbedding` model defines `Vector(384)`. Inserting 1536-dim vectors into a `Vector(384)` column will fail. Use `populate_embeddings_local.py` (384-dim) or `populate_embeddings_ollama.py` (384-dim) instead, which dynamically ALTER the column dimension before populating.
- **Dual pgvector extension enablement is redundant but harmless:** The vector extension is enabled both by `init-scripts/01-enable-pgvector.sql` (on first container start via `/docker-entrypoint-initdb.d`) and by the Alembic initial migration (`CREATE EXTENSION IF NOT EXISTS vector` in `ac92703bd365`). The `IF NOT EXISTS` clause prevents errors, but the redundancy means the init script test runs on first boot while the migration re-enables on every `alembic upgrade head` (see `alembic/versions/ac92703bd365_initial_schema.py` line 23).
- **Deployment with PVC requires Recreate strategy:** The Deployment uses `strategy.type: Recreate` (see `database-deployment.yaml` line 11) because `ReadWriteOnce` PVCs cannot be mounted by two pods simultaneously. A rolling update would fail when the new pod tries to attach the PVC while the old pod still holds it.
- **startup.sh non-critical Keycloak sync:** The startup.sh script uses `set +e` around the Keycloak sync section (lines 101-109) to prevent sync failures from failing the entire migration Job. The exit code from the sync is captured but not used to set the Job's exit status -- this means a sync failure is logged as a warning but the Job still succeeds.
- **Alembic env.py uses separate declarative_base:** The Alembic `env.py` creates its own `Base = declarative_base()` (line 12) rather than importing the one from `db.database`. The `from db.models import *` on line 29 imports all models but they register on the `db.database.Base`, not the local one. The `target_metadata` is set to the local `Base.metadata` which may not include all model tables for autogenerate (see `alembic/env.py` lines 12, 29, 32).
- **ConfigMap init script creates keycloak database, not pgvector init:** The Helm ConfigMap (`database-init-configmap.yaml`) creates a `keycloak` database for Keycloak authentication storage -- it does not enable the pgvector extension. The extension enablement is handled by the local-dev init script and the Alembic migration, not the Helm ConfigMap (see `templates/database-init-configmap.yaml` lines 12-31).

### Testing Notes (Approach G)

- Verify the pgvector extension is enabled: connect to the database and run `SELECT extname FROM pg_extension WHERE extname = 'vector'`.
- Verify the haversine distance function exists: `SELECT haversine_distance_km(40.7128, -74.0060, 34.0522, -118.2437)` should return approximately 3944 km.
- Verify the `transaction_location_analysis` view exists: `SELECT * FROM transaction_location_analysis LIMIT 1`.
- Verify the migration Job completed: `oc get job <release>-migration` and check logs for "Database migrations completed successfully".
- Verify CSV data was loaded: check migration Job logs for "Sample data loaded successfully" and query `SELECT count(*) FROM transactions`.
- Test category embeddings (after running populate_embeddings_local.py): `SELECT category FROM merchant_category_embeddings ORDER BY embedding <-> (SELECT embedding FROM merchant_category_embeddings WHERE category = 'dining') LIMIT 3`.

---

## Choosing Between Approaches

| Criteria | Approach A (ai-virtual-agent) | Approach B (ansible-log-analysis) | Approach C (data-governance-co-pilot) | Approach D (it-self-service-agent) | Approach E (multi-agent-loan-origination) | Approach F (product-recommender-system) | Approach G (spending-transaction-monitor) |
|----------|-------------------------------|-----------------------------------|---------------------------------------|-------------------------------------|------------------------------------------|----------------------------------------|------------------------------------------|
| **pgvector chart version** | v0.5.5 (subchart) | v0.1.0 (bundled .tgz) | v0.1.0 (standalone chart) | v0.1.0 (subchart) | N/A (inline Helm templates) | v0.1.0 (subchart) | N/A (inline Helm templates) |
| **PostgreSQL version** | 15 | 17 | 15 | Subchart default | 16 | Subchart default | 16 |
| **Container image** | ai-architecture-charts subchart default | `pgvector/pgvector:pg17` | `quay.io/rh-aiservices-bu/postgresql-15-pgvector-c9s:latest` | ai-architecture-charts subchart default | `pgvector/pgvector:pg16` | ai-architecture-charts subchart default | `quay.io/rh-ai-quickstart/pgvector:pg16` (Helm); `pgvector/pgvector:pg16` (local) |
| **Chart relationship** | Dependency subchart | Dependency subchart (bundled) | Standalone Helm chart | Dependency subchart | Inline templates in parent chart | Dependency subchart | Inline templates in parent chart |
| **URL construction** | Assembled from individual secret keys in deployment template | Pre-built `uri` key consumed directly from secret | Pod DNS hardcoded in data loader Job | Helm template helpers (`_env-helpers.tpl`) generate env vars from secret | Full connection strings in Helm Secret; dual URLs for lending vs compliance | Both individual secret keys (DB_HOST, etc.) and pre-built `uri` key for DATABASE_URL | Full `DATABASE_URL` from Helm Secret via `secretKeyRef`; individual `POSTGRES_*` keys for container env |
| **DB initialization** | `extraDatabases` values mechanism | ConfigMap init script with `CREATE EXTENSION VECTOR` | ConfigMap init script with `CREATE EXTENSION IF NOT EXISTS vector CASCADE` | `extraDatabases` values + `max_connections=200` args | ConfigMap init script with pgvector extension + dual role creation + extra database (mlflow) | Subchart default + Helm post-install Job running `init_backend.py` (drop_all + create_all) | SQL init script (pgvector extension + verification test) + Alembic initial migration (redundant `CREATE EXTENSION`) + startup.sh pipeline (migrate + CSV seed + optional Keycloak sync) |
| **Schema management** | Alembic migrations (async-to-sync URL rewrite) | `SQLModel.metadata.create_all` at startup | Raw SQL in Python data loader script | Alembic migrations via Kubernetes Job (services wait for version) | Alembic migrations with `pgvector.sqlalchemy.Vector` type and per-table GRANT statements | `Base.metadata.drop_all` + `create_all` in db-init Job (no migration framework) | Alembic migrations with `pgvector.sqlalchemy.Vector` type + custom PL/pgSQL functions; async-to-psycopg2 URL rewrite |
| **ORM** | SQLAlchemy ORM with PostgreSQL dialect types | SQLModel with JSON column type | None (raw psycopg2) | SQLAlchemy ORM + psycopg_pool for LangGraph | SQLAlchemy 2.0 with `pgvector.sqlalchemy.Vector` + raw SQL for vector search | SQLAlchemy ORM async (asyncpg) + sync (psycopg2) for Feast direct queries | SQLAlchemy 2.0 async (asyncpg) with `pgvector.sqlalchemy.Vector` + `Mapped` type annotations |
| **Data seeding** | None | None | Kubernetes Job with OpenShift BuildConfig for large CSV datasets | None | None | Helm post-install Job seeds categories, products, users, reviews from parquet files; optional LLM-generated reviews | startup.sh loads CSV users/transactions via `db.scripts.load_csv_data` + Alembic migration pre-populates category data |
| **Vector search usage** | Active via LlamaStack `vector_io` provider | Extension enabled but unused; embeddings in MinIO | Extension enabled; used for data governance, not RAG | Active via LlamaStack `vector_io` + metadata/kv/sql backends | Active via direct SQL with `<=>` cosine operator; HNSW index; tier-based result boosting | Active via Feast `retrieve_online_documents` with `vector_enabled: true` online store; 6 embedding feature views with cosine search | Active via direct SQL with `<->` L2 distance for semantic merchant category matching; Vector(384) with interchangeable embedding providers |
| **Security** | Standard credentials via secret | Standard credentials via secret | Read-only `mcp_readonly` user for MCP server defense-in-depth | Standard credentials via secret; advisory locks for session isolation | Dual PostgreSQL roles (`lending_app`, `compliance_app`) for HMDA data isolation; per-table GRANT permissions | Standard credentials via secret; job-viewer RBAC for db-init polling | Standard credentials via Helm Secret; Keycloak integration for user authentication (optional) |
| **Number of consumers** | Single backend service | Multiple services (backend, annotation-interface, phoenix) | Data loader Job + MCP server | 6+ services (agent, request-manager, dispatcher, migration, langfuse, langfuse-worker) | Single API service with two connection pools (lending + compliance) + MLflow | Backend + Feast online/offline/registry services + db-init Job + pipeline Job | Single API backend + migration Job |
| **Connection pooling** | Single async SQLAlchemy pool | Single async SQLAlchemy pool | No pooling (raw psycopg2) | Dual pools: async SQLAlchemy + sync/async psycopg_pool for LangGraph | Dual async SQLAlchemy pools (one per role/connection string) | Async SQLAlchemy pool (asyncpg) for API routes + ad-hoc sync engines (psycopg2) for Feast queries | Single async SQLAlchemy pool (asyncpg) |
| **Distributed coordination** | None | None | None | PostgreSQL advisory locks for per-session request serialization | None | None | None |
| **Credential passthrough** | Install script `--set` flags | Values file defaults | `--set` flags (placeholder defaults in values.yaml) | Helm template helpers; values defaults | Helm Secret with `secretKeyRef` in StatefulSet; `--set secrets.*` overrides | Values env list with secretKeyRef for pgvector secret keys | Helm Secret with `secretKeyRef` in Deployment; `secrets.*` values overrides |
| **Best for** | Apps needing vector search + relational data in one DB | Multi-service apps using PostgreSQL as shared relational store | Data governance demos with seed data, MCP server access, and curated views | Multi-service agentic apps needing distributed session serialization, LangGraph checkpointing, and LlamaStack multi-store backends | Regulated-domain apps needing role-based data isolation, direct pgvector queries with domain-specific result ranking, and compliance KB with tiered boosting | Recommendation systems using Feast as the feature/vector store layer with pgvector backend; hybrid deterministic + semantic search; multiple embedding types (item, user, text, CLIP) | Transaction monitoring apps needing semantic category normalization with switchable embedding providers (OpenAI/local/Ollama); custom spatial functions; comprehensive init pipeline with CSV seeding |
