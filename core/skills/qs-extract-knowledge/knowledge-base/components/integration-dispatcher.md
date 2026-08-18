---
name: integration-dispatcher
description: Multi-channel delivery dispatcher with CloudEvent ingestion, smart defaults, outbox pattern, and per-thread FIFO ordering
summary: "Solves multi-channel agent delivery by providing a FastAPI microservice that receives CloudEvents and dispatches templated responses to Slack, Email, Zammad, and Webhooks via a handler registry with database-backed smart defaults (IntegrationDefaultConfig merged at dispatch time, not persisted per-user), while also ingesting inbound Slack events/slash commands, IMAP email polling, and Zammad webhooks as normalized CloudEvents. Use when building an event-driven agent architecture requiring per-user channel resolution with delivery_binding filtering (TICKET_THREAD routes exclusively to Zammad), durable outbox-based event forwarding with exactly-once processing (try_claim_event_for_processing), and per-thread FIFO ordering via PostgreSQL advisory locks -- prefer over direct HTTP dispatch when multi-pod deduplication and ordered delivery guarantees are needed. Critical patterns: outbox publisher polls pending events ordered by thread_order_key (OUTBOX_POLL_INTERVAL_SEC=5.0, MAX_RETRIES=20, BATCH_SIZE=50); IMAP leader election uses 32-bit MD5-derived advisory lock; canonical user identity maps cross-integration IDs to UUID via UserIntegrationMapping with TTL; Jinja2 TemplateEngine formats per channel (mrkdwn, HTML, text, raw); Zammad on-behalf-of posts with From header falling back on 403 via ZAMMAD_TICKET_ARTICLE_FALLBACK_ON_FORBIDDEN; per-integration defaults overridden via INTEGRATION_DEFAULTS_{TYPE}_ENABLED env vars. Gotchas: BROKER_URL is mandatory at startup and validated independently in main.py, SlackService, and EmailService; SMTP port 587 uses STARTTLS vs 465 implicit TLS; negative cache sentinel __NOT_FOUND__ with 5-minute TTL avoids repeated Slack lookups but email deduplication collides when both Message-ID and IMAP sequence ID are missing; dual IntegrationDispatcher instantiation in main.py means only the second instance serves the FastAPI app."
metadata:
  type: component
tags:
  tech_stack: [fastapi, python, pydantic, structlog, jinja2, slack-sdk, aiosmtplib, aioimaplib, httpx, cloudevents, opentelemetry, sqlalchemy]
  ai_pattern: [agents]
  platform: [openshift, kubernetes]
  data_layer: [postgresql]
source_examples:
  - quickstart: "it-self-service-agent"
    repo: "https://github.com/rh-ai-quickstart/it-self-service-agent"
    notes: "Multi-tenant integration dispatcher bridging Slack, Email, Zammad, and Webhook delivery channels with smart defaults, outbox publisher, and per-thread advisory locking"
    approach: "A"
---

# Integration Dispatcher

## Overview

The Integration Dispatcher is a FastAPI microservice that serves as the outbound delivery gateway in a self-service agent architecture. It receives CloudEvents (or direct HTTP calls) containing agent responses, resolves which integration channels are enabled for a given user via smart defaults and database-backed configuration, then dispatches templated messages to Slack, Email, Zammad ticketing, or generic Webhooks. It also acts as the inbound intake for Slack events, slash commands, IMAP email polling, and Zammad webhooks, forwarding normalized requests to a Request Manager via CloudEvents through a durable outbox pattern.

## Tech Stack & Dependencies

- **Runtime:** Python 3.12, FastAPI, uvicorn
- **Container image:** No Dockerfile in component -- built via shared monorepo workspace
- **Key dependencies:** pydantic v2, structlog, jinja2, slack-sdk (async), aiosmtplib, aioimaplib, httpx, cloudevents, sqlalchemy (async), opentelemetry (FastAPI + HTTPX instrumentation), orjson, langchain-core
- **Internal packages:** `self-service-agent-shared-models` (database models, CloudEvent utilities, health checker), `self-service-agent-shared-clients` (Zammad REST client), `tracing-config` (auto-tracing)
- **Helm subchart:** None found -- deployed as part of the monorepo workspace

## Key Patterns

### Handler Registry Pattern

The dispatcher maps `IntegrationType` enum values to handler instances at startup. Each handler extends `BaseIntegrationHandler` with `deliver()`, `validate_config()`, and `health_check()` methods.

```python
# integration-dispatcher/src/integration_dispatcher/main.py
class IntegrationDispatcher:
    def __init__(self) -> None:
        self.handlers: Dict[IntegrationType, BaseIntegrationHandler] = {
            IntegrationType.SLACK: SlackIntegrationHandler(),
            IntegrationType.EMAIL: EmailIntegrationHandler(),
            IntegrationType.WEBHOOK: WebhookIntegrationHandler(),
            IntegrationType.TEST: TestIntegrationHandler(),
            IntegrationType.ZAMMAD: ZammadIntegrationHandler(),
        }
        self.template_engine = TemplateEngine()
```

### Smart Defaults with Lazy Approach

Integration defaults are stored in a database table (`IntegrationDefaultConfig`) and refreshed on startup and per-request when health status changes. User-specific overrides merge on top. Defaults are never persisted per-user -- only computed at dispatch time.

```python
# integration-dispatcher/src/integration_dispatcher/integrations/defaults.py
async def get_smart_defaults(self, user_id, db, context=None):
    # Check if database is in sync with current health status
    current_health = await self._check_integration_health()
    current_enabled = set(i for i, e in current_health.items() if e)
    # ... compare with db_enabled, refresh if mismatch ...
    # Convert to smart defaults format (no database persistence)
    smart_defaults = {}
    for default_config in default_configs:
        config = { ... }
        # Apply context-specific configuration per integration type
        if default_config.integration_type == IntegrationType.SLACK:
            # Resolve slack_user_id from mapping or Slack API
```

Environment variable overrides follow the pattern `INTEGRATION_DEFAULTS_{TYPE}_ENABLED`, `_PRIORITY`, `_RETRY_COUNT`, `_RETRY_DELAY_SECONDS`.

### Delivery Binding Filter

The dispatcher supports `TICKET_THREAD` vs standard delivery. When `delivery_binding` is `TICKET_THREAD`, only ticket-eligible integrations (Zammad) are used. Otherwise, ticket integrations are excluded. This filtering uses `filter_configs_for_delivery_binding()` from shared_models.

```python
# integration-dispatcher/src/integration_dispatcher/main.py
ic = request.integration_context or {}
binding = ic.get("delivery_binding")
is_ticket_thread = binding == "TICKET_THREAD"
configs = filter_configs_for_delivery_binding(configs, binding)
```

### Atomic Event Claiming (Deduplication)

Incoming CloudEvents and Slack messages use a check-and-set pattern (`DatabaseUtils.try_claim_event_for_processing`) to guarantee exactly-once processing across multiple pods.

```python
# integration-dispatcher/src/integration_dispatcher/main.py
event_claimed = await DatabaseUtils.try_claim_event_for_processing(
    db, event_id, event_type, event_source, "integration-dispatcher",
)
if not event_claimed:
    return {"status": "skipped", "reason": "duplicate event"}
```

### Outbox Publisher (Durable Event Forwarding)

Inbound requests (from Slack, Email, Zammad) are written to an `event_outbox` table before publishing to the broker. A background asyncio task polls pending rows with FIFO ordering per thread (`thread_order_key`, `created_at`) and publishes them via `CloudEventSender`.

```python
# integration-dispatcher/src/integration_dispatcher/outbox_publisher.py
POLL_INTERVAL_SEC = float(os.getenv("OUTBOX_POLL_INTERVAL_SEC", "5.0"))
MAX_RETRIES = int(os.getenv("OUTBOX_MAX_RETRIES", "20"))
BATCH_SIZE = int(os.getenv("OUTBOX_BATCH_SIZE", "50"))

# ORDER BY thread_order_key NULLS LAST, created_at for FIFO per thread
result = await db.execute(
    select(EventOutbox)
    .where(EventOutbox.status == "pending", EventOutbox.retry_count < MAX_RETRIES)
    .order_by(EventOutbox.thread_order_key.asc().nulls_last(),
              EventOutbox.created_at.asc())
    .limit(BATCH_SIZE)
)
```

### Per-Thread Advisory Locking (FIFO Ordering)

PostgreSQL advisory locks serialize event publishing per conversation thread so events reach the broker in receipt order. Lock keys are namespaced by platform.

```python
# integration-dispatcher/src/integration_dispatcher/thread_lock.py
def build_slack_thread_key(team_id, channel_id, thread_ts):
    return f"integration:slack:{team_id}:{channel_id}:{thread_ts}"

def build_email_thread_key(from_address, in_reply_to=None, message_id=None):
    part = in_reply_to or message_id or "first"
    return f"integration:email:{from_address}:{part}"
```

### Template Engine (Jinja2 per Integration Type)

The `TemplateEngine` formats messages differently per integration type -- Slack gets mrkdwn with emoji prefixes, Email gets HTML with styled divs, SMS gets truncated text, Webhook gets raw content.

```python
# integration-dispatcher/src/integration_dispatcher/template_engine.py
class TemplateEngine:
    def __init__(self):
        self.jinja_env = jinja2.Environment(...)
        self.jinja_env.filters["markdown_to_slack"] = self._markdown_to_slack
        self.jinja_env.filters["markdown_to_html"] = self._markdown_to_html

    def render(self, integration_type, subject, content, variables):
        rendered_subject, rendered_body = self._apply_default_formatting(
            integration_type, subject, content, template_vars
        )
```

### IMAP Leader Election

For email polling, PostgreSQL advisory locks implement leader election so only one pod polls the IMAP mailbox at a time. The leader maintains a lease and renews it periodically.

```python
# integration-dispatcher/src/integration_dispatcher/email_service.py
# Lock key from consistent hash (fits 32-bit unsigned for pg_try_advisory_lock)
lock_key_bytes = hashlib.md5("imap_leader_election".encode()).digest()[:4]
self._lock_key = int.from_bytes(lock_key_bytes, byteorder="big")

# Non-blocking try to acquire advisory lock
result = await lock_db.execute(
    text("SELECT pg_try_advisory_lock(:key)"), {"key": self._lock_key}
)
```

### Canonical User Identity Resolution

Users are identified by a canonical UUID (`user_id`) resolved from email addresses or integration-specific IDs (Slack user ID). The system maintains cross-integration mapping consistency through `UserIntegrationMapping` records with TTL-based validation.

```python
# integration-dispatcher/src/integration_dispatcher/user_mapping_utils.py
async def resolve_user_id_from_email(email_address, integration_type, db,
                                      integration_specific_id=None, created_by="system"):
    # 1. Check for integration-specific mapping first
    # 2. Check if email exists in any other integration mapping
    # 3. If found, reuse existing canonical user_id
    # 4. If not, create new canonical user and mapping
```

Negative cache entries use a `__NOT_FOUND__` sentinel value with 5-minute TTL to avoid repeated Slack API lookups for non-existent users.

### Zammad On-Behalf-Of Delivery

The Zammad handler resolves the ticket owner email (from webhook snapshot or live API) and posts articles using a `From` header for on-behalf-of attribution. If Zammad rejects the identity (403), it retries without the `From` header.

```python
# integration-dispatcher/src/integration_dispatcher/integrations/zammad.py
on_behalf_of = await self._resolve_on_behalf_of_email(
    client=client, token=token,
    integration_context=ic, ticket_id=ticket_id,
)
if on_behalf_of:
    headers["From"] = on_behalf_of
# ... if 403 and ZAMMAD_TICKET_ARTICLE_FALLBACK_ON_FORBIDDEN ...
# retry without From header
```

## Configuration

- **Environment variables:**
  - `BROKER_URL` (required) -- CloudEvent broker endpoint for forwarding requests
  - `SLACK_BOT_TOKEN` -- Slack bot OAuth token for API calls and message delivery
  - `SLACK_SIGNING_SECRET` -- HMAC signing secret for verifying Slack webhook requests
  - `SMTP_HOST`, `SMTP_PORT` (587), `SMTP_USERNAME`, `SMTP_PASSWORD` -- SMTP sending config
  - `SMTP_USE_TLS` (true) -- STARTTLS for port 587, implicit TLS for port 465
  - `FROM_EMAIL`, `FROM_NAME` -- Sender identity for outbound emails
  - `IMAP_HOST`, `IMAP_PORT` (993), `IMAP_USERNAME`, `IMAP_PASSWORD` -- IMAP polling config
  - `IMAP_MAILBOX` (INBOX), `IMAP_POLL_INTERVAL` (60s), `IMAP_USE_SSL` (true)
  - `IMAP_LEASE_DURATION` (120s), `IMAP_LEASE_RENEWAL_INTERVAL` -- Leader election tuning
  - `ZAMMAD_URL`, `ZAMMAD_HTTP_TOKEN` -- Zammad REST API for ticket article posting
  - `ZAMMAD_WEBHOOK_SECRET` -- HMAC-SHA1 secret for verifying Zammad webhook signatures
  - `ZAMMAD_TICKET_ARTICLE_FALLBACK_ON_FORBIDDEN` (true) -- Retry without `From` on 403
  - `ZAMMAD_SKIP_LIVE_TICKET_OWNER_LOOKUP` -- Skip live ticket owner API call
  - `DEFAULT_WEBHOOK_URL` -- Fallback URL when users have no webhook URL configured
  - `TEST_INTEGRATION_ENABLED` (true) -- Enable/disable test integration handler
  - `OUTBOX_POLL_INTERVAL_SEC` (5.0), `OUTBOX_MAX_RETRIES` (20), `OUTBOX_BATCH_SIZE` (50) -- Outbox publisher tuning
  - `INTEGRATION_THREAD_LOCK_TIMEOUT` (10.0) -- Advisory lock timeout
  - `INTEGRATION_DEFAULTS_{TYPE}_ENABLED`, `_PRIORITY`, `_RETRY_COUNT`, `_RETRY_DELAY_SECONDS` -- Per-integration default overrides
  - `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB` -- Database connection (via shared_models)
  - `PORT` (8080), `HOST` (0.0.0.0), `RELOAD` (false), `LOG_LEVEL` (INFO)
  - `OTEL_EXPORTER_OTLP_ENDPOINT` -- OpenTelemetry exporter endpoint (optional)
- **Config files:** None component-specific; all configuration via environment variables
- **Helm values:** No component-specific Helm chart found; deployed as part of monorepo workspace

## Known Gotchas

- **BROKER_URL is mandatory at startup:** The service raises `ValueError` during startup if `BROKER_URL` is not set. Both `SlackService` and `EmailService` constructors also validate this independently and will fail fast. (Source: `main.py` line 425-431, `slack_service.py` line 54-59)
- **SMTP port 587 vs 465 requires different TLS handling:** Port 587 uses STARTTLS (plain connection first, then upgrade), while port 465 uses implicit SSL/TLS. The email handler has explicit branching for this. (Source: `integrations/email.py` lines 213-233)
- **Slack rate limiting returns `retry_after`:** The Slack handler catches `SlackApiError` and sets `retry_after=60` only when the error is `rate_limited`, letting other errors fail immediately. (Source: `integrations/slack.py` lines 112-118)
- **Negative cache sentinel `__NOT_FOUND__`:** When a Slack user lookup fails with `users_not_found`, a mapping with `integration_user_id="__NOT_FOUND__"` is stored with 5-minute TTL. The database has a partial unique constraint that excludes this sentinel value, allowing multiple `__NOT_FOUND__` entries. (Source: `integrations/defaults.py` lines 56-82, `user_mapping_utils.py` lines 62-68)
- **Dual dispatcher instantiation:** The `IntegrationDispatcher` class is instantiated twice in `main.py` -- once at class level (line 418) and once after lifespan creation (line 506). The second instance is the one used by the FastAPI app. (Source: `main.py` lines 418, 506)
- **IMAP leader election lock key must be 32-bit:** PostgreSQL advisory locks take BIGINT, but the code constrains to 32-bit unsigned to avoid "OID out of range" errors. The key is derived from MD5 hash of `"imap_leader_election"`. (Source: `email_service.py` lines 96-103)
- **Email deduplication falls back without IMAP ID:** When both `Message-ID` header and IMAP sequence ID are missing, the fallback ID (`email-{from}-{date}`) can collide for multiple emails from the same sender on the same day. The code logs a warning about this. (Source: `email_service.py` lines 114-129)
- **Zammad `From` header 403 fallback:** The `ZAMMAD_TICKET_ARTICLE_FALLBACK_ON_FORBIDDEN` env var defaults to `true` (when unset or empty). Setting it to `false`/`0`/`off` disables the fallback retry without `From`. (Source: `integrations/zammad.py` lines 24-32)

## Testing Notes

- 12 test files covering: smart defaults channel behavior merge, delivery context, Zammad dispatch scope, ticket delivery, thread locking, handler-registry wiring, Zammad feedback skip, Zammad integration handler, Zammad webhook parsing and route handling
- Tests use `pytest-asyncio` for async test support and `pytest-cov` for coverage
- Verify outbox publisher processes pending events: check `integration_dispatcher_outbox_published_total` and `_failed_total` OpenTelemetry counters
- Health check: `GET /health` (lightweight, no DB) and `GET /health/detailed` (checks DB + integration handler availability)
- Email health checks test SMTP and IMAP connectivity without sending actual messages (socket-level probes)

## Related Patterns

- Architecture: Event-driven CloudEvent orchestration between Integration Dispatcher and Request Manager
- Deployment: Outbox pattern with PostgreSQL for durable event delivery
- Component: Shared models library (`shared-models`) for database models, CloudEvent utilities, and health checking
- Component: Shared clients library (`shared-clients`) for pooled Zammad REST client
