---
name: shared-models
description: Shared Python library providing SQLAlchemy models, database management, CloudEvent utilities, and cross-service contracts
summary: "Centralizes SQLAlchemy ORM models, Pydantic inter-service schemas, dual connection pools, CloudEvent eventing, PostgreSQL advisory locks, transactional outbox, multi-layer channel behavior policy resolution (code registry -> env -> DB), and FastAPI app scaffolding as a shared monorepo path dependency (`self-service-agent-shared-models`) consumed by all microservices via uv workspace. Use when multiple microservices need consistent database models, eventing contracts, Alembic migration gating, and standardized app lifecycle -- replaces per-service boilerplate with a single Hatchling-built package; only one approach exists (shared library, not per-service duplication). Critical pattern: `DatabaseManager` maintains async `create_async_engine` (asyncpg with `pool_pre_ping`, `statement_timeout`, `idle_in_transaction_session_timeout`) alongside sync `psycopg_pool.ConnectionPool` (for LangGraph `PostgresSaver` requiring synchronous connections), while `create_shared_lifespan` blocks startup until `wait_for_migration()` confirms `alembic_version` matches `EXPECTED_MIGRATION_VERSION` (default \"003\"). Advisory lock namespace separation is critical -- request-manager uses single-arg `pg_try_advisory_lock(key)` while agent-service uses two-arg `pg_try_advisory_lock(1, key_lo)` to prevent cross-service deadlocks; `_broker_safe_event_id` SHA-256 hashes email Message-IDs containing `<>@`; stale event re-claim timeout must exceed `AGENT_TIMEOUT`; `server_default=text(\"CURRENT_TIMESTAMP\")` avoids multi-pod clock skew; `RequestSession.version` provides optimistic locking but callers skipping `expected_version` lose protection; and `UserIntegrationMapping` partial unique index excludes `__NOT_FOUND__` sentinels at DB level only."
metadata:
  type: component
tags:
  tech_stack: [python, sqlalchemy, asyncpg, pydantic, fastapi, alembic, structlog, cloudevents, postgresql]
  ai_pattern: [agents]
  platform: [openshift]
  data_layer: [pgvector]
source_examples:
  - quickstart: "it-self-service-agent"
    repo: "https://github.com/rh-ai-quickstart/it-self-service-agent"
    notes: "Shared Python package providing consolidated ORM models, database pool management, CloudEvent eventing, advisory locks, channel behavior policies, and standardized FastAPI app creation across all microservices"
    approach: "A"
---

# Shared Models

## Overview

Shared-models is an internal Python package (`self-service-agent-shared-models`) that centralizes SQLAlchemy ORM models, Pydantic inter-service schemas, database connection pooling, CloudEvent construction/sending, PostgreSQL advisory lock helpers, structured logging, health checks, and FastAPI app scaffolding. It is consumed as a path dependency by every microservice in the it-self-service-agent quickstart (agent-service, request-manager, integration-dispatcher) and ensures schema consistency across the system. Alembic migrations live inside this package, run as an init container before services start, and the services wait for migration readiness on startup.

## Tech Stack & Dependencies

- **Runtime:** Python >= 3.12
- **Build system:** Hatchling (`hatch.build.targets.wheel`)
- **Key dependencies:**
  - `sqlalchemy[asyncio] >= 2.0.0` with `asyncpg >= 0.29.0` (async engine)
  - `psycopg[binary] >= 3.1.0` + `psycopg-pool >= 3.2.0` (sync pool for LangGraph PostgresSaver)
  - `alembic >= 1.13.0` (schema migrations)
  - `pydantic >= 2.5.0` (inter-service request/response models)
  - `fastapi >= 0.129.0` (shared app factory, health endpoints)
  - `cloudevents >= 1.6.0` + `httpx >= 0.25.0` (event construction and sending)
  - `structlog >= 23.2.0` (structured JSON logging)
  - `langgraph-checkpoint-postgres >= 2.0.0` (LangGraph checkpoint integration)
  - `langchain >= 1.2.7`
- **Consumed as:** workspace path dependency (`self-service-agent-shared-models = { path = "shared-models" }` in root `pyproject.toml`)

## Key Patterns

### Path Dependency for Monorepo Sharing

The package is installed as a path dependency in the uv workspace so every service imports the same models and utilities:

```toml
# root pyproject.toml
[tool.uv.sources]
self-service-agent-shared-models = { path = "shared-models" }
```

```toml
# shared-models/pyproject.toml
[tool.hatch.build.targets.wheel]
packages = ["src/shared_models"]
```

### Dual Connection Pool Architecture

The `DatabaseManager` maintains two separate connection pools: an async SQLAlchemy engine for service queries and a sync `psycopg_pool.ConnectionPool` for LangGraph's `PostgresSaver` which requires synchronous connections:

```python
# Async engine for service queries
self.engine = create_async_engine(
    self.config.connection_string,
    pool_pre_ping=True,
    pool_recycle=self.config.pool_recycle,
    pool_size=self.config.pool_size,
    max_overflow=self.config.max_overflow,
    connect_args={
        "command_timeout": self.config.statement_timeout_ms // 1000,
        "server_settings": {
            "statement_timeout": str(self.config.statement_timeout_ms),
            "idle_in_transaction_session_timeout": str(
                self.config.idle_transaction_timeout_ms
            ),
        },
    },
)

# Sync pool for LangGraph PostgresSaver
self._sync_pool = psycopg_pool.ConnectionPool(
    conn_string,
    min_size=self.config.sync_pool_min_size,
    max_size=self.config.sync_pool_max_size,
    kwargs={"row_factory": psycopg.rows.dict_row, "autocommit": True},
)
```

### Standardized FastAPI App Factory

`create_standard_fastapi_app` and `create_shared_lifespan` provide a consistent startup/shutdown pattern across all services: wait for Alembic migration, log DB config, run custom startup hooks, then yield:

```python
app = create_standard_fastapi_app(
    service_name="request-manager",
    version="0.1.0",
    description="Request Manager Service",
)
```

The lifespan waits for migration via `wait_for_migration()` which polls the `alembic_version` table and verifies key tables exist before allowing service startup.

### CloudEvent Builder and Sender with Retry

`CloudEventBuilder` creates typed CloudEvents with partition keys for Kafka ordering. `CloudEventSender` wraps sending with configurable exponential backoff and jitter on transient failures:

```python
class EventTypes:
    REQUEST_CREATED = "com.self-service-agent.request.created"
    AGENT_RESPONSE_READY = "com.self-service-agent.agent.response-ready"
    SESSION_CREATE_OR_GET = "com.self-service-agent.session.create-or-get"
    SESSION_READY = "com.self-service-agent.session.ready"
```

Event IDs for email-originated requests are hashed to avoid broker issues with special characters (`<`, `>`, `@` in RFC 5322 Message-IDs):

```python
def _broker_safe_event_id(request_id: str) -> str:
    if request_id.startswith("<") and "@" in request_id:
        digest = hashlib.sha256(request_id.encode()).hexdigest()[:32]
        return f"email-{digest}"
    return request_id
```

### PostgreSQL Advisory Locks for Cross-Pod Serialization

Two namespaced advisory lock strategies prevent collisions between services:
- **Request-manager:** single-arg `pg_try_advisory_lock(key)` for per-session FIFO dequeue
- **Agent-service:** two-arg `pg_try_advisory_lock(1, key_lo)` using a separate namespace

```python
_AGENT_NAMESPACE = 1

def session_id_to_lock_key(session_id: str) -> int:
    try:
        key = int(uuid.UUID(session_id).hex[:16], 16) & 0x7FFF_FFFF_FFFF_FFFF
    except (ValueError, TypeError):
        digest = hashlib.sha256(session_id.encode("utf-8")).digest()
        key = int.from_bytes(digest[:8], "big") & 0x7FFF_FFFF_FFFF_FFFF
    return key
```

The `with_advisory_lock` wrapper uses short-lived connections per poll attempt to avoid holding connections during wait, with configurable timeout (default 180s) and poll interval (50ms).

### Transactional Outbox Pattern

The `outbox.py` module implements the transactional outbox pattern using PostgreSQL's `ON CONFLICT DO NOTHING` for idempotent inserts, with status tracking (`pending` -> `published` | `exhausted`):

```python
stmt = (
    insert(EventOutbox)
    .values(
        source_service=source_service,
        event_type=event_type,
        idempotency_key=idempotency_key,
        payload=payload,
        status="pending",
    )
    .on_conflict_do_nothing(
        index_elements=["source_service", "event_type", "idempotency_key"]
    )
    .returning(EventOutbox.id)
)
```

### Channel Behavior Policy System

A multi-layer policy resolution chain determines per-integration session scope, routing agents, and delivery bindings: code registry defaults -> env overrides (`CHANNEL_BEHAVIOR_OVERRIDES` JSON) -> optional DB override (`integration_default_configs.config.channel_behavior`). Policies are snapshotted onto session metadata at creation time:

```python
async def resolve_channel_behavior(
    integration_type: Any,
    db: Optional[AsyncSession] = None,
) -> ChannelBehaviorPolicy:
    """Resolve: registry -> env overrides -> optional DB override -> agent ids -> validate."""
    base = _resolve_from_registry(integration_type)
    base = _merge_policy_dict(base, load_channel_behavior_env_override(integration_type))
    if channel_behavior_allow_db_override() and db is not None:
        db_blob = await load_channel_behavior_from_db(integration_type, db)
        base = _merge_policy_dict(base, db_blob)
    return _finalize_policy(base)
```

### Atomic Event Claiming for Deduplication

`try_claim_event_for_processing` uses the database unique constraint as a distributed lock. It handles stale claims (stuck in "processing" beyond a configurable timeout) by allowing re-claim:

```python
processed_event = ProcessedEvent(
    event_id=event_id,
    event_type=event_type,
    event_source=event_source,
    processed_by=processed_by,
    processing_result="processing",  # Claimed but not yet completed
)
db.add(processed_event)
await db.commit()
```

The composite unique constraint `(event_id, processed_by)` allows multiple services to independently claim the same event.

### Consolidated Alembic Migrations

Migrations live in `shared-models/alembic/versions/` and run as a single init-container job. The Alembic env reads DB config from `DatabaseConfig` and uses the sync connection string:

```python
# alembic/env.py
db_config = get_db_config()
config.set_main_option("sqlalchemy.url", db_config.sync_connection_string)
target_metadata = Base.metadata
```

## Configuration

- **Environment variables:**
  - `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` -- database connection
  - `DB_POOL_SIZE` (default 5), `DB_MAX_OVERFLOW` (10), `DB_POOL_TIMEOUT` (30), `DB_POOL_RECYCLE` (3600) -- async pool
  - `DB_SYNC_POOL_MIN_SIZE` (1), `DB_SYNC_POOL_MAX_SIZE` (5), `DB_SYNC_POOL_TIMEOUT` (30) -- sync pool for LangGraph
  - `DB_STATEMENT_TIMEOUT` (30000ms), `DB_IDLE_TRANSACTION_TIMEOUT` (300000ms) -- PostgreSQL session timeouts
  - `SQL_DEBUG` -- echo SQL statements
  - `EXPECTED_MIGRATION_VERSION` (default "003") -- migration version to wait for at startup
  - `LOG_LEVEL` (default INFO), `LOG_FORMAT` (default json) -- structlog configuration
  - `EVENT_MAX_RETRIES` (3), `EVENT_BASE_DELAY` (1.0s), `EVENT_MAX_DELAY` (10.0s), `EVENT_BACKOFF_MULTIPLIER` (2.0) -- CloudEvent sender retry
  - `DEFAULT_AGENT_ID` (default "routing-agent") -- fallback router agent
  - `AGENT_ID_ALLOWLIST` -- comma-separated allowed agent ids
  - `SESSION_PER_INTEGRATION_TYPE` -- isolate sessions by integration type
  - `CHANNEL_BEHAVIOR_ALLOW_DB_OVERRIDE` -- enable DB-layer policy overrides
  - `CHANNEL_BEHAVIOR_OVERRIDES` -- JSON blob for deploy-time per-type policy overrides
- **Config files:** `shared-models/alembic.ini` for Alembic migration runner
- **Helm values:** N/A (shared-models is a library, not a deployed service)

## Known Gotchas

- **Dual pool management:** The `DatabaseManager` must maintain both async (`asyncpg`) and sync (`psycopg`) connection pools because LangGraph's `PostgresSaver` requires synchronous connections. Forgetting to close both pools in shutdown leaks connections. The `close()` method handles both: `await self.engine.dispose()` then `self._sync_pool.close()` then `await self._async_pool.close()`.

- **Server-default timestamps for multi-pod ordering:** Several models (`RequestLog`, `RequestSession`, `ProcessedEvent`) override `TimestampMixin.created_at` with `server_default=text("CURRENT_TIMESTAMP")` instead of Python-side `datetime.now()`. The comment in `RequestSession` explains: "DB server_default for multi-pod ordering (avoids clock skew)".

- **Advisory lock namespace separation:** Request-manager and agent-service use different PostgreSQL advisory lock key spaces to avoid blocking each other. Request-manager uses single-arg `pg_try_advisory_lock(key)` while agent uses two-arg `pg_try_advisory_lock(1, key_lo)`. Mixing these would cause cross-service deadlocks.

- **Email Message-ID handling:** `request_id` and `cloudevent_id` columns use `VARCHAR(255)` instead of UUID to accommodate email Message-IDs like `<CAPbJ+...@mail.gmail.com>`. The `_broker_safe_event_id` function hashes these to avoid broker issues with special characters. This is documented in migration 001.

- **Partial unique index for sentinel values:** `UserIntegrationMapping` uses a partial unique INDEX at the database level (not a SQLAlchemy constraint) that excludes `__NOT_FOUND__` sentinel values. The comment in the model warns: "The UniqueConstraint declaration below is for SQLAlchemy documentation; the actual DB uses a unique index."

- **Optimistic locking on sessions:** `RequestSession` uses a `version` column for optimistic locking. `update_session` increments it atomically (`RequestSession.version + 1`) and optionally checks `expected_version` to detect concurrent modifications. Callers that skip `expected_version` lose this protection.

- **Stale event re-claim:** `try_claim_event_for_processing` allows re-claiming events stuck in "processing" state beyond `stale_timeout_seconds` (default 120s). This handles pod crashes but the timeout must be tuned relative to `AGENT_TIMEOUT` to avoid premature re-claims.

## Testing Notes

- Tests use `pytest-asyncio` with `asyncio_mode = "auto"` (configured in `pyproject.toml`)
- Test suite covers channel behavior policy resolution, channel registry wiring, CloudEvent sending, delivery binding filters, session management, and utility functions
- The `wait_for_migration` method polls `alembic_version` table every 5 seconds with a default 300s timeout; verify that the init-container migration completes within this window on RHOAI
- To verify health: each service exposes `GET /health` using `create_health_check_endpoint` which checks DB connectivity and integration handler status

## Related Patterns

- Database setup and connection: `pgvector.md`
- FastAPI backend patterns: `fastapi-backend.md`
