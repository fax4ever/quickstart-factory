---
name: aiq-api
description: "Unified FastAPI backend combining Knowledge API, async agent jobs via Dask, SSE streaming, and JWT auth"
summary: "Solves unified API backend for AI research agent systems by combining Knowledge API (document/collection management), Dask-based async agent job orchestration with CancellationMonitor, SSE streaming, and reconnectable WebSocket HITL support into a single FastAPI NAT plugin registered via Python entry points. Use when building a multi-agent research backend needing pluggable chain-of-responsibility JWT auth (RS256/ES256 via OIDC JWKS) at raw ASGI level with ContextVar user propagation, dual-database mode (SQLite dev / PostgreSQL prod with auto-selected SSE via LISTEN/NOTIFY sub-10ms or polling 500ms), and an agent registry mapping identifiers to class paths supporting LLM-provider, simple LLM, and LangGraph constructors. Critical config: set REQUIRE_AUTH=true with AIQ_JWT_ISSUER for JWT enforcement, AIQ_LISTEN_DB_URL for direct PostgreSQL bypassing PgBouncer, NAT_DASK_SCHEDULER_ADDRESS for job submission, path allowlisting via EXTERNAL_ALLOWED_PATHS, and BatchingEventStore buffers 10 events/200ms to reduce DB round-trips. Gotchas: PgBouncer breaks LISTEN/NOTIFY requiring AIQ_LISTEN_DB_URL direct connection, PyJWT >= 2.9 silently drops JWKS keys missing use=\"sig\", auth tokens require explicit ContextVar propagation to Dask worker processes, ghost job reaper marks RUNNING jobs FAILURE after 5-min heartbeat timeout with pg_try_advisory_xact_lock ensuring single-pod cleanup in multi-replica deployments, and WebSocket handler re-checks JWT expiry on each inbound message."
metadata:
  type: component
tags:
  tech_stack: [fastapi, python, sqlalchemy, dask, pydantic, langchain, pyjwt, asyncpg, aiosqlite]
  ai_pattern: [agents, rag, embeddings]
  platform: [openshift]
  data_layer: [postgresql, pgvector]
source_examples:
  - quickstart: "rh-research"
    repo: "https://github.com/rh-ai-quickstart/rh-research"
    notes: "Unified API plugin for NVIDIA AI-Q research blueprint: async job orchestration, knowledge management, SSE streaming, and pluggable JWT auth"
    approach: "A"
---

# AIQ API

## Overview

The AIQ API is a unified FastAPI-based backend that serves as the primary API layer for the AI-Q research agent system. It combines three functional areas into a single NAT (NeMo Agent Toolkit) plugin: a Knowledge API for document collection and ingestion management, an Async Job API for submitting and monitoring long-running agent jobs via Dask, and a real-time SSE streaming layer for delivering job progress events to frontends. The component also provides a pluggable authentication middleware with JWT validation, per-job access control, and reconnectable WebSocket support for human-in-the-loop (HITL) interactions.

## Tech Stack & Dependencies

- **Runtime:** Python 3.11-3.13, FastAPI >= 0.100.0
- **Container image:** No component-specific Dockerfile; deployed as a NAT plugin package
- **Key dependencies:**
  - `fastapi` -- web framework and route registration
  - `dask[distributed]` -- async job submission to distributed workers
  - `sqlalchemy` + `aiosqlite` + `asyncpg` -- dual-database support (SQLite for dev, PostgreSQL for production)
  - `pydantic` >= 2.0 -- request/response validation
  - `langchain-core` -- LangChain callback handlers for SSE event streaming
  - `PyJWT[cryptography]` -- RS256/ES256 JWT validation via OIDC JWKS
  - `psycopg[binary]` (optional) -- PostgreSQL driver for production
- **Helm subchart:** None (deployed as a Python package within the NAT server)

## Key Patterns

### NAT Plugin Registration via Entry Points

The component registers as a NAT plugin using Python entry points, making it auto-discoverable by the framework. The plugin inherits from NAT's `FastApiFrontEndPlugin` and overrides worker construction to inject custom routes and middleware.

```toml
# pyproject.toml
[project.entry-points."nat.plugins"]
aiq_api = "aiq_api.register"
```

```python
# plugin.py
class AIQAPIConfig(FastApiFrontEndConfig, name="aiq_api"):
    db_url: str = Field(
        default="sqlite+aiosqlite:///./jobs.db",
        description="Database URL for job store and event store",
    )
    expiry_seconds: int = Field(
        default=86400, ge=600, le=604800,
        description="Job expiry time in seconds (default: 24 hours)",
    )

@register_front_end(config_type=AIQAPIConfig)
async def register_aiq_api(config: AIQAPIConfig, full_config: Config):
    yield AIQAPIPlugin(full_config=full_config, config=config)
```

### Pluggable Auth Validator Chain

Authentication uses a chain-of-responsibility pattern: multiple `TokenValidator` implementations are tried in order, and the first successful one wins. Validators can be registered programmatically via `register_validator()` or discovered automatically through Python entry points.

```python
# auth/base.py -- abstract validator contract
class TokenValidator(ABC):
    @abstractmethod
    async def validate(self, token: str) -> tuple[dict[str, Any] | None, str | None]:
        ...
    @abstractmethod
    def can_handle(self, token: str) -> bool:
        ...

# External packages register via entry points:
# [project.entry-points."aiq_api.validators"]
# my_provider = "mypackage.auth:get_validators"
```

### Raw ASGI Auth Middleware with ContextVar Propagation

The `AuthMiddleware` operates at the raw ASGI level (not Starlette middleware) to avoid response body buffering. It enforces three independent checks: path allowlisting for external requests, token validation, and caller-type detection. The resolved user identity is stored in a `ContextVar` so downstream NAT workflow functions can access it without framework coupling.

```python
# auth/middleware.py
_current_user: ContextVar[dict[str, Any]] = ContextVar(
    "_current_user",
    default={"type": "internal", "skip_clarifier": False},
)

EXTERNAL_ALLOWED_PATHS: list[str] = [
    "/health", "/docs", "/redoc", "/openapi.json",
    "/chat", "/chat/stream", "/v1/chat/completions",
    "/v1/data_sources", "/v1/jobs/async/agents",
    "/v1/jobs/async/submit", "/v1/jobs/async/job/",
]

AUTH_EXEMPT_PATHS: set[str] = {"/health", "/docs", "/redoc", "/openapi.json"}
```

### Agent-Agnostic Async Job System with Dask

Jobs are submitted to a Dask distributed cluster via `submit_agent_job()`. The agent registry maps short identifiers to class paths and NAT config names. The runner dynamically loads agent classes and supports multiple constructor patterns (LLM-provider-based, simple LLM-based, state-based LangGraph). Each job gets a `CancellationMonitor` that polls for `INTERRUPTED` status.

```python
# registry.py
register_agent(
    agent_type="deep_researcher",
    class_path="aiq_agent.agents.deep_researcher.agent.DeepResearcherAgent",
    config_name="deep_research_agent",
    description="Performs comprehensive multi-loop deep research",
)
```

### Dual-Mode SSE Streaming (PostgreSQL pub/sub vs SQLite polling)

The event delivery layer automatically selects between PostgreSQL LISTEN/NOTIFY for sub-10ms latency and SQLite polling at 500ms intervals. Events are stored in a `job_events` table via SQLAlchemy and delivered as SSE to the frontend. A `BatchingEventStore` wrapper reduces database round-trips by batching up to 10 events per 200ms window.

```python
# event_store.py
class BatchingEventStore:
    FLUSH_INTERVAL_MS = 200
    MAX_BATCH_SIZE = 10

    def store(self, event: dict):
        with self._lock:
            self._buffer.append(event)
            if len(self._buffer) >= self.MAX_BATCH_SIZE:
                self._flush_locked()
            elif self._timer is None:
                self._timer = threading.Timer(
                    self.FLUSH_INTERVAL_MS / 1000, self._flush
                )
                self._timer.daemon = True
                self._timer.start()
```

### Reconnectable WebSocket for HITL Interactions

The WebSocket handler supports mid-conversation reconnection for human-in-the-loop interactions. A `WebSocketSessionRegistry` tracks active sockets and pending HITL futures per conversation ID, allowing a new socket to resolve a pending interaction started on a previous connection. JWT expiry is re-checked on each inbound message to prevent stale tokens from authorizing work.

```python
# websocket_reconnect.py
class WebSocketSessionRegistry:
    async def resolve_pending_interaction(
        self, conversation_id: str | None, user_content: TextContent,
    ) -> bool:
        async with self._lock:
            future = self._pending_interactions.get(conversation_id)
            if future is None or future.done():
                return False
            future.set_result(user_content)
            self._pending_interactions.pop(conversation_id, None)
            return True
```

### Ghost Job Reaper and Periodic Cleanup

Background asyncio tasks handle operational hygiene: a ghost job reaper marks RUNNING jobs as FAILURE if no heartbeat events arrive within 5 minutes (catches Dask worker crashes and OOM kills). Periodic cleanup uses PostgreSQL advisory locks (`pg_try_advisory_xact_lock`) so only one pod runs cleanup at a time in multi-replica deployments.

```python
# routes/jobs.py
GHOST_JOB_TIMEOUT_SECONDS = 300   # 5 minutes without events = ghost job
GHOST_REAPER_INTERVAL_SECONDS = 60  # check every 60 seconds
_PG_ADVISORY_LOCK_ID = 0x41495143_4C45414E  # "AIQCLEAN" in hex
```

## Configuration

- **Environment variables:**
  - `REQUIRE_AUTH` -- `"true"` / `"false"` (default: false). Controls whether JWT validation is enforced for external requests.
  - `AIQ_EXTERNAL_HOSTNAMES` -- Comma-separated list of external-facing hostnames for path allowlist enforcement.
  - `AIQ_JWT_ISSUER` -- OIDC issuer URL for JWT signature verification (required when `REQUIRE_AUTH=true`).
  - `AIQ_JWT_AUDIENCE` -- Optional `aud` claim to verify; leave unset to skip audience verification.
  - `AIQ_LISTEN_DB_URL` -- Direct PostgreSQL URL for LISTEN/NOTIFY (bypasses PgBouncer transaction pooling).
  - `AIQ_ENABLE_DEBUG` -- Enable/disable debug console at `/debug` (default: `"true"`).
  - `AIQ_TRACE_USER_IDENTITY_MODE` -- Controls user identity attachment to trace spans (`none`, `id`, `full`).
  - `AIQ_TRACE_USER_IDENTITY_HMAC_SECRET` -- Secret for pseudonymous trace user IDs.
  - `AIQ_TRACE_CLIENT_ID_MODE` -- Controls client identifier attachment (`none`, `ip`).
  - `NAT_DASK_SCHEDULER_ADDRESS` -- Dask scheduler address for async job submission.
  - `NAT_JOB_STORE_DB_URL` -- Database URL for job persistence (default: `sqlite:///./data/jobs.db`).
  - `NAT_CONFIG_FILE` -- Path to NAT workflow config file used by Dask workers.
  - `NAT_FASTAPI_LOG_LEVEL` -- Python logging level for FastAPI workers (default: 20/INFO).
  - `NAT_USE_DASK_THREADS` -- Use thread pool instead of process pool for Dask workers.
- **Config files:** NAT workflow YAML configures the `aiq_api` front-end type with `db_url` and `expiry_seconds` fields.
- **Helm values:** N/A (deployed as a Python package, not a Helm subchart).

## Known Gotchas

- **PgBouncer incompatibility with LISTEN/NOTIFY:** PostgreSQL LISTEN/NOTIFY requires a persistent session, which is incompatible with PgBouncer transaction pooling. The code provides `AIQ_LISTEN_DB_URL` as a workaround to point directly at PostgreSQL for the SSE pub/sub connection (`routes/jobs.py`, `_sse_generator_postgres`).
- **PyJWT >= 2.9 drops keys without `use="sig"`:** The JWKS key fetcher explicitly adds `use: "sig"` to JWK keys that omit the field, because PyJWT >= 2.9 silently drops keys without this attribute (`auth/jwt_validator.py`, `_fetch_jwks_keys` method comment).
- **NAT WebSocket handler returns None from `create_task().add_done_callback()`:** A known upstream NAT issue (NeMo-Agent-Toolkit#1744) causes `_running_workflow_task` to always be None. The reconnectable handler includes a TODO comment noting this (`websocket_reconnect.py`, line 351-354).
- **Auth token must be propagated via ContextVar for Dask workers:** Since Dask workers run in separate processes, the auth token from the HTTP request is explicitly passed as a job argument and stored in a `ContextVar` (`job_auth_token`) so data-source tools that require authentication can retrieve it (`jobs/runner.py`, lines 285-291).
- **SQLAlchemy CancelledError log noise:** When SSE clients disconnect, async task cancellations produce expected but noisy `CancelledError` exceptions in SQLAlchemy pool logs. A custom `SQLAlchemyPoolFilter` is installed at module load time to suppress these (`event_store.py`, lines 33-55).
- **Signal handler double-press for force exit:** The shutdown signal handler uses a module-level `_shutdown_signal_received` flag -- a second SIGINT/SIGTERM calls `os._exit(1)` for immediate termination (`plugin.py`, lines 147-179).

## Testing Notes

- The component includes dedicated test files for auth (`test_auth.py`, `test_auth_errors.py`), job access control (`test_job_access.py`), job submission with data sources (`test_job_submit_data_sources.py`), periodic cleanup (`test_periodic_cleanup.py`), and WebSocket reconnection (`test_websocket_reconnect.py`).
- Tests use `pytest` with `pytest-asyncio` for async test support.
- Verify auth behavior by testing with `REQUIRE_AUTH=true` and `REQUIRE_AUTH=false` -- the middleware enforces path filtering and caller-type detection regardless of the auth flag.
- Health check endpoint at `/health` validates DB connectivity by pinging any cached async engine.

## Related Patterns

- Knowledge retrieval backend configuration via NAT workflow YAML `knowledge_retrieval` function
- Agent implementations in `src/aiq_agent/agents/` (deep_researcher, shallow_researcher)
- Data source registry in `aiq_agent.common.data_source_registry` for UI-driven source toggles
- Phoenix/OpenTelemetry observability via NAT's `ExporterManager`
