---
name: request-manager
description: "FastAPI request management layer with multi-channel normalization, session serialization, and CloudEvent-based eventing"
summary: "Provides a unified FastAPI/Uvicorn (Python 3.12) ingress layer that normalizes requests from six channels (Web, CLI, Slack, Email, Zammad, Tool) into a common NormalizedRequest via Pydantic v2 isinstance-based routing with per-ticket session scoping, then dispatches to downstream agent services via CloudEvents through a Knative broker; deployed via parent Helm chart helper self-service-agent.requestManagementService with structlog and OpenTelemetry tracing. Use when building a multi-channel agentic application requiring exactly-once event processing, cross-replica session serialization, and Knative eventing integration -- single approach sourced from it-self-service-agent. Enforces one in-flight request per session using PostgreSQL advisory locks in a two-phase durable-accept/process flow with pg_try_advisory_lock polling (PG BUG #17686 workaround), atomic event claiming via unique-constraint check-and-set, dual response delivery via per-pod DB polling plus CloudEvent asyncio.Future fast path, pod heartbeat with stuck request reclaim (RECLAIM_ACTION: requeue or fail), and four startup background tasks (polling, heartbeat, reclaim, session cleanup). SESSION_LOCK_WAIT_TIMEOUT must be >= AGENT_TIMEOUT or queued requests get premature 503s; cross-pod response polling intentionally omits pod_name filter so accepting pod receives responses processed elsewhere; JWT signature verification is unimplemented (TODO); circuit breaker ignores self-sourced events except SESSION_CREATE_OR_GET/SESSION_READY; user UUIDs are replaced with emails before agent dispatch for llama-stack compatibility."
metadata:
  type: component
tags:
  tech_stack: [fastapi, python, pydantic, cloudevents, structlog, opentelemetry, sqlalchemy, httpx, pyjwt]
  ai_pattern: [agents, prompt-chaining]
  platform: [openshift, kubernetes]
  data_layer: [pgvector]
source_examples:
  - quickstart: "it-self-service-agent"
    repo: "https://github.com/rh-ai-quickstart/it-self-service-agent"
    notes: "Multi-channel request manager with session serialization, CloudEvent eventing, and per-pod polling"
    approach: "A"
---

# Request Manager

## Overview

The request manager is a FastAPI service that acts as the unified ingress layer for a multi-channel agentic application. It accepts requests from Web, CLI, Slack, Email, Zammad (ticketing), and Tool integrations, normalizes them into a common internal format, manages user sessions (including per-ticket scoping), and dispatches work to downstream agent services via CloudEvents through a Knative broker. It guarantees exactly-once processing through database-level atomic event claiming and session-level advisory locks in PostgreSQL.

## Tech Stack & Dependencies

- **Runtime:** Python 3.12, FastAPI >= 0.129.0, Uvicorn
- **Container image:** `quay.io/rh-ai-quickstart/self-service-agent-request-manager`
- **Key dependencies:** pydantic >= 2.5.0, cloudevents >= 1.10.0, httpx >= 0.25.0, structlog >= 23.2.0, pyjwt[crypto] >= 2.8.0, opentelemetry-api >= 1.37.0, langchain-core >= 1.2.11, sqlalchemy (async), orjson
- **Internal packages:** `self-service-agent-shared-models`, `self-service-agent-shared-clients`, `self-service-agent-service`, `tracing-config` (all resolved via uv path dependencies)
- **Helm:** Deployed via parent chart helper `self-service-agent.requestManagementService`; no standalone subchart

## Key Patterns

### Multi-Channel Request Normalization

Each integration type has a dedicated Pydantic schema and normalizer method. All requests are converted to a `NormalizedRequest` model before dispatching. The `RequestNormalizer` class routes to integration-specific methods by `isinstance` check.

```python
# request-manager/src/request_manager/normalizer.py
class RequestNormalizer:
    def normalize_request(
        self, request: InboundRequest, session_id: str,
        current_agent_id: Optional[str] = None,
    ) -> NormalizedRequest:
        if isinstance(request, SlackRequest):
            return self._normalize_slack_request(request, base_data)
        elif isinstance(request, WebRequest):
            return self._normalize_web_request(request, base_data)
        # ... CLIRequest, EmailRequest, ZammadRequest, ToolRequest
```

Supported channels are defined in `schemas.py` via a `TypeAlias`:

```python
# request-manager/src/request_manager/schemas.py
InboundRequest: TypeAlias = Union[
    BaseRequest, SlackRequest, WebRequest,
    CLIRequest, EmailRequest, ToolRequest, ZammadRequest,
]
```

### Session Serialization with PostgreSQL Advisory Locks

The service enforces one in-flight request per session across all replicas using PostgreSQL advisory locks. The two-phase flow ensures durability and FIFO ordering:

```
Phase 1 (durable accept): acquire lock -> insert RequestLog (status=pending) -> register future -> release
Phase 2 (process):        acquire lock -> reclaim stuck -> dequeue oldest pending -> release ->
                           send to agent -> wait for response -> loop until our request processed
```

Lock acquisition uses `pg_try_advisory_lock` with polling to avoid PG BUG #17686 (race between `pg_advisory_lock` and `lock_timeout`):

```python
# request-manager/src/request_manager/session_lock.py
while time.monotonic() < deadline:
    result = await db.execute(
        text("SELECT pg_try_advisory_lock(:key)"), {"key": lock_key},
    )
    row = result.fetchone()
    if row and row[0]:
        return True
    await asyncio.sleep(SESSION_LOCK_POLL_INTERVAL_SECONDS)
```

### CloudEvent-Based Eventing with Atomic Claiming

All inter-service communication uses CloudEvents via a Knative broker. Duplicate event processing is prevented through database-level atomic claiming (check-and-set pattern using unique constraints):

```python
# request-manager/src/request_manager/main.py
event_claimed = await try_claim_event_for_processing(
    db, event_id, event_type, event_source, "request-manager",
)
if not event_claimed:
    return {"status": "skipped", "reason": "duplicate event (already claimed by another pod)"}
```

A circuit breaker prevents feedback loops by ignoring self-generated events (except session events):

```python
# request-manager/src/request_manager/main.py
if ("request-manager" in event_source or event_source == "request-manager"
) and event_type not in [EventTypes.SESSION_CREATE_OR_GET, EventTypes.SESSION_READY]:
    return {"status": "ignored", "reason": "self-generated event"}
```

### Per-Pod Response Polling with Event Fast Path

Response delivery uses a dual mechanism. A single background polling task per pod checks the database for completed responses. If a response arrives via CloudEvent on the same pod, it resolves the asyncio.Future immediately (fast path). Otherwise, database polling picks it up:

```python
# request-manager/src/request_manager/communication_strategy.py
async def _pod_response_poller(pod_name: str) -> None:
    poll_interval = float(os.getenv("DB_POLL_INTERVAL", "0.5"))
    while True:
        waiting_request_ids = list(_response_futures_registry.keys())[:100]
        if not waiting_request_ids:
            await asyncio.sleep(poll_interval)
            continue
        # Query DB for responses (does NOT filter by pod_name)
        async with db_manager.get_session() as db:
            stmt = select(RequestLog).where(
                RequestLog.request_id.in_(waiting_request_ids),
                RequestLog.response_content.isnot(None),
            )
```

### Pod Heartbeat and Stuck Request Reclaim

Pods periodically UPSERT to a `pod_heartbeats` table. Stuck request detection uses two signals: time-based cutoff (AGENT_TIMEOUT + buffer) and pod heartbeat liveness (pod not checked in within grace period):

```python
# request-manager/src/request_manager/session_orchestrator.py
stuck_by_time = coalesced < stuck_cutoff
recent_pods_subq = select(PodHeartbeat.pod_name).where(
    PodHeartbeat.last_check_in_at >= grace_cutoff
)
stuck_by_heartbeat = and_(
    RequestLog.pod_name.isnot(None),
    ~RequestLog.pod_name.in_(recent_pods_subq),
)
```

### JWT and API Key Authentication

The service supports three authentication methods tried in order: JWT token validation, API key lookup, and legacy header-based auth (x-user-id, x-forwarded-user, x-remote-user). JWT validation is configurable via environment variables and supports multi-issuer configuration:

```python
# request-manager/src/request_manager/main.py
JWT_ENABLED = os.getenv("JWT_ENABLED", "false").lower() == "true"
JWT_ISSUERS = json.loads(os.getenv("JWT_ISSUERS", "[]"))
API_KEYS_ENABLED = os.getenv("API_KEYS_ENABLED", "true").lower() == "true"
WEB_API_KEYS = json.loads(os.getenv("WEB_API_KEYS", "{}"))
```

## Configuration

- **Environment variables:**
  - `BROKER_URL` - Knative broker endpoint (default: `http://knative-broker:8080`)
  - `AGENT_TIMEOUT` - Timeout waiting for agent response in seconds (default: `120`)
  - `SESSION_TIMEOUT_HOURS` - Session expiry (default: `336` = 2 weeks)
  - `SESSION_LOCK_WAIT_TIMEOUT` - Lock acquisition timeout (default: `180`)
  - `SESSION_LOCK_POLL_INTERVAL_SECONDS` - Lock polling interval (default: `0.05`)
  - `SESSION_LOCK_STUCK_BUFFER_SECONDS` - Buffer added to agent timeout for reclaim (default: `30`)
  - `POD_HEARTBEAT_INTERVAL_SECONDS` - Heartbeat frequency (default: `15`)
  - `POD_HEARTBEAT_GRACE_SECONDS` - Grace period before pod considered dead (default: `30`)
  - `BACKGROUND_RECLAIM_INTERVAL_SECONDS` - Background reclaim scan interval (default: `45`)
  - `RECLAIM_ACTION` - What to do with stuck requests: `requeue` or `fail` (default: `requeue`)
  - `DB_POLL_INTERVAL` - Response polling interval in seconds (default: `0.5`)
  - `USE_SESSION_EVENTING` - Use CloudEvents for session creation (default: `true`)
  - `SESSION_CLEANUP_INTERVAL_HOURS` - Cleanup task interval (default: `24`)
  - `INACTIVE_SESSION_RETENTION_DAYS` - Retention for inactive sessions (default: `30`)
  - `JWT_ENABLED`, `JWT_ISSUERS`, `JWT_VERIFY_SIGNATURE`, `JWT_VERIFY_EXPIRATION`, `JWT_VERIFY_AUDIENCE`, `JWT_VERIFY_ISSUER`, `JWT_LEEWAY` - JWT configuration
  - `API_KEYS_ENABLED`, `WEB_API_KEYS` - API key authentication
  - `SNOW_API_KEY`, `HR_API_KEY`, `MONITORING_API_KEY` - Tool integration API keys
  - `PORT` (default: `8080`), `HOST` (default: `0.0.0.0`), `LOG_LEVEL`, `RELOAD`

- **Helm values:**
  - `requestManagement.requestManager.replicas` - Pod replicas (default: `1`)
  - `requestManagement.requestManager.database.poolSize` - Connection pool size (default: `8`)
  - `requestManagement.requestManager.database.maxOverflow` - Pool overflow (default: `8`)
  - `requestManagement.requestManager.uvicornWorkers` - Uvicorn worker count (default: `4`)
  - `requestManagement.requestManager.sessionSerialization.*` - Lock, heartbeat, and reclaim tuning
  - `requestManagement.requestManager.sessions.*` - Session timeout, cleanup, eventing toggles

## Known Gotchas

- **PG BUG #17686 workaround:** The code explicitly uses `pg_try_advisory_lock` with polling instead of `pg_advisory_lock` with `lock_timeout` because the blocking variant can race -- the timeout may fire even when the lock was granted, or the grant may be delayed past the timeout. This is documented in `session_lock.py`.
- **Cross-pod response delivery:** The database poller intentionally does NOT filter by `pod_name` when checking for responses. When pod A accepts a request and pod B processes it, the `RequestLog.pod_name` will be pod B, but pod A still needs to receive the result via polling. The comment in `communication_strategy.py` explains this design.
- **JWT signature verification is a TODO:** The code contains `# TODO: Implement proper JWKS fetching and signature verification` in `main.py`. Currently it falls back to decoding without signature verification even when `JWT_VERIFY_SIGNATURE` is true.
- **SESSION_LOCK_WAIT_TIMEOUT must be >= AGENT_TIMEOUT:** The Helm values and `session_config.py` note that the lock timeout must be at least as large as the agent timeout so queued requests can wait for the current one to finish. Mismatching causes premature 503s.
- **RECLAIM_ACTION validation at import time:** `session_config.py` validates the `RECLAIM_ACTION` env var at module load and logs a warning for invalid values, defaulting to `requeue`. This prevents silent misconfiguration.
- **Circuit breaker for self-events:** The CloudEvent handler in `main.py` has a circuit breaker that ignores events sourced from `request-manager` to prevent feedback loops, but explicitly allows `SESSION_CREATE_OR_GET` and `SESSION_READY` events through since the service intentionally sends these to itself.
- **User ID UUID-to-email replacement:** Before sending requests to the agent service, the request manager looks up the user's email from the canonical UUID because llama-stack and agent-service expect email-based user IDs, not UUIDs. This is done in `_prepare_request` in `communication_strategy.py`.

## Testing Notes

- Unit tests exist in `request-manager/tests/` covering authentication, channel behavior sessions, conversations, normalizer, session serialization, and wired ingress matching.
- Health check at `GET /health` is lightweight (no DB dependency); `GET /health/detailed` checks database and communication strategy health.
- The service starts four background tasks on startup: pod polling, pod heartbeat, background reclaim, and session cleanup.

## Related Patterns

- Session management shares logic with `shared-models` package (canonical user resolution, channel behavior policies, advisory lock utilities)
- Communicates with agent-service and integration-dispatcher via CloudEvents through a Knative broker
- Response forwarding to integration-dispatcher includes email threading headers (RFC 5322) and Slack user ID resolution from user mapping tables
