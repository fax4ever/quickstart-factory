---
name: pgvector
description: "PostgreSQL with pgvector extension for relational data and vector search in AI Quickstarts on RHOAI"
summary: "pgvector serves as combined relational store (SQLAlchemy/Alembic with asyncpg driver, UUID primary keys via sqlalchemy.dialects.postgresql) and LlamaStack vector_io provider (provider_id: \"pgvector\", embedding_model: \"all-MiniLM-L6-v2\" in agent templates) for RHOAI quickstarts needing both structured application state and RAG vector search. Use when a single PostgreSQL instance should handle both relational data (users, agents, sessions, knowledge bases) and vector similarity search through LlamaStack -- extraDatabases entries use vectordb: false because LlamaStack manages vector operations independently rather than the pgvector extension on the app database. Deployed as Helm subchart v0.5.5 from ai-architecture-charts with DATABASE_URL constructed from configurable pgSecret keys plus extraDatabases[0].name; credentials passed via install_with_env.sh --set flags; Alembic migrations rewrite postgresql+asyncpg:// to synchronous postgresql:// driver; session uses expire_on_commit=False. Common gotchas: Settings.DATABASE_URL defaults to sqlite+aiosqlite:///:memory: causing silent SQLite fallback if env var missing; local dev compose uses postgres:15 without pgvector extension (need pgvector/pgvector:pg15 for vector features); deployment template fails if extraDatabases is empty or reordered."
metadata:
  type: component
tags:
  tech_stack: [postgresql, fastapi, sqlalchemy, alembic, asyncpg]
  ai_pattern: [vector-search, rag, embeddings]
  platform: [openshift, rhoai]
  data_layer: [pgvector]
source_examples:
  - quickstart: "ai-virtual-agent"
    repo: "https://github.com/rh-ai-quickstart/ai-virtual-agent"
    notes: "PostgreSQL as primary relational store with pgvector subchart; vector search delegated to LlamaStack provider"
    approach: "A"
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
