---
name: mock-eventing-service
description: "FastAPI mock of Knative Broker for CloudEvents routing in dev/CI, with partition-key ordered delivery"
summary: "FastAPI mock of Knative Broker replacing full Knative Eventing + Kafka for dev/CI, providing subscription-based CloudEvent routing with partition-key FIFO delivery via per-(subscriber_url, partition_key) async queues (auto-cleanup at 5min idle) and differentiated httpx retry backoff (3 retries/1s for timeouts, 10/2s for 5xx aligned with Kafka config). Use as the default eventing mode for local/CI when a full Knative + Kafka stack is unavailable — Helm compound conditional (requestManagement.enabled AND NOT knative.eventing.enabled) auto-deploys the mock and switches BROKER_URL via _env-helpers.tpl; disable when real Knative eventing is enabled. Auto-initializes 10 default subscriptions at startup covering integration-dispatcher, request-manager, and agent-service; parses both structured (application/cloudevents+json) and binary (ce-* header) CloudEvent formats; debug endpoints GET /events, POST /subscriptions, POST /reset support CI inspection; built on UBI9 python-312 via shared Containerfile.services-template with OpenTelemetry instrumentation and structlog. Must run single replica (partition-key FIFO ordering breaks with multiple); DELIVERY_TIMEOUT (default 130s) must exceed AGENT_TIMEOUT (120s) or deliveries time out before agent completes; mock injects ce-broker/ce-delivery headers absent from real Knative; events without partitionkey attribute bypass ordered queues and are fire-and-forget via asyncio.create_task."
metadata:
  type: component
tags:
  tech_stack: [fastapi, python, cloudevents, uvicorn, structlog, httpx, pydantic, opentelemetry]
  ai_pattern: [agents]
  platform: [openshift, kubernetes]
source_examples:
  - quickstart: "it-self-service-agent"
    repo: "https://github.com/rh-ai-quickstart/it-self-service-agent"
    notes: "Mock Knative Eventing broker for dev/CI replacing real Knative + Kafka eventing"
    approach: "A"
---

# Mock Eventing Service

## Overview

A FastAPI service that simulates Knative Broker behavior for CloudEvents routing in development and CI environments. It replaces the need for a full Knative Eventing + Kafka stack by providing in-process subscription matching, event delivery with retries, and partition-key-ordered processing. The service is deployed as a single-replica Deployment on OpenShift and is the default eventing mode, toggled off only when full Knative eventing is enabled.

## Tech Stack & Dependencies

- **Runtime:** Python 3.12 / FastAPI >= 0.104.0
- **Container image:** Built via shared `Containerfile.services-template` multi-stage build (UBI9 `python-312:9.7` builder, `python-312-minimal:9.7` runtime)
- **Key dependencies:** cloudevents >= 1.9.0 (CloudEvent parsing/serialization), httpx >= 0.25.0 (async event delivery), structlog >= 23.2.0 (structured logging), opentelemetry-instrumentation-fastapi (tracing), pydantic >= 2.5.0
- **Internal dependencies:** `self-service-agent-shared-models` (health check, logging config), `tracing-config` (OpenTelemetry auto-tracing)
- **Helm subchart:** None (deployed as part of the parent `self-service-agent` chart via `helm/templates/mock-eventing-service-deployment.yaml`)

## Key Patterns

### Conditional Deployment: Mock vs Real Knative Eventing

The mock eventing service is enabled by default and disabled when real Knative eventing is active. The Helm template uses a compound conditional:

```yaml
# helm/templates/mock-eventing-service-deployment.yaml (line 1)
{{- if and .Values.requestManagement.enabled
         (not .Values.requestManagement.knative.eventing.enabled)
         .Values.requestManagement.knative.mockEventing.enabled }}
```

The `BROKER_URL` env var set on other services auto-switches between the mock and real broker based on this flag:

```yaml
# helm/templates/_env-helpers.tpl (line 120-121)
- name: BROKER_URL
  value: {{ if .Values.requestManagement.knative.eventing.enabled }}
    {{ printf "%s/%s/%s" .Values.requestManagement.knative.broker.url
       .Release.Namespace .Values.requestManagement.knative.broker.name }}
  {{ else }}
    {{ printf "http://%s-mock-eventing.%s.svc.cluster.local:8080/%s/%s"
       (include "self-service-agent.fullname" .)
       .Release.Namespace .Release.Namespace
       .Values.requestManagement.knative.broker.name }}
  {{ end }}
```

### Subscription-Based Event Routing

Events are routed to subscribers based on event type and optional filter attributes. Default subscriptions are created at startup matching the multi-service architecture (integration-dispatcher, request-manager, agent-service):

```python
# mock-eventing-service/src/mock_eventing_service/main.py (lines 296-367)
async def initialize_default_subscriptions() -> None:
    service_name = os.getenv("SERVICE_NAME", "self-service-agent")
    namespace = os.getenv("NAMESPACE", "default")
    default_subscriptions = [
        {
            "event_type": "com.self-service-agent.request.created",
            "subscriber_url": f"http://{service_name}-request-manager.{namespace}.svc.cluster.local/api/v1/events/cloudevents",
            "filter_attributes": {"source": "integration-dispatcher"},
        },
        # ... more subscriptions
    ]
```

### Partition-Key Ordered Delivery

Events with a `partitionkey` attribute are delivered in FIFO order per (subscriber_url, partition_key) pair, mirroring Kafka partition semantics. Per-partition async queues with background workers handle this:

```python
# mock-eventing-service/src/mock_eventing_service/main.py (lines 135-179)
def _enqueue_partitioned_delivery(
    self, event: CloudEvent, subscription: EventSubscription, partition_key: str
) -> None:
    key = (subscription.subscriber_url, partition_key)
    if key not in self._partition_queues:
        self._partition_queues[key] = asyncio.Queue()
        self._partition_workers[key] = asyncio.create_task(
            self._partition_delivery_worker(key)
        )
    self._partition_queues[key].put_nowait((event, subscription))
```

Idle partition workers auto-clean up after 5 minutes (IDLE_TIMEOUT_SEC = 300) to prevent memory leaks.

### Retry with Differentiated Backoff

Event delivery retries differentiate between timeouts (max 3 retries, 1s backoff) and retriable 5xx errors like 502/503/504 (max 10 retries, 2s backoff). The 10-retry limit for 5xx aligns with the Kafka broker retry configuration:

```python
# mock-eventing-service/src/mock_eventing_service/main.py (lines 268-271)
max_retries = (
    10 if is_retriable_5xx else 3
)  # Align with Kafka broker (retry: 10)
```

### CloudEvent Parsing (Structured and Binary)

The broker endpoint at `POST /{namespace}/{broker_name}` accepts CloudEvents in both structured (`application/cloudevents+json`) and binary (HTTP header-based `ce-*` prefixed attributes) formats:

```python
# mock-eventing-service/src/mock_eventing_service/main.py (lines 426-501)
if headers.get("content-type", "").startswith("application/cloudevents+json"):
    event_data = json.loads(body)
    event_data_field = event_data.get("data")
    event_attributes = {k: v for k, v in event_data.items() if k != "data"}
    event = CloudEvent(event_attributes, event_data_field)
else:
    # Binary format - strip ce- prefix from headers
    ce_headers = {
        key[3:].lower(): value
        for key, value in headers.items()
        if key.lower().startswith("ce-")
    }
    event = CloudEvent(ce_headers, body_data)
```

## Configuration

- **Environment variables:**
  - `PORT` (default `8080`): HTTP listen port
  - `HOST` (default `0.0.0.0`): Listen address
  - `DELIVERY_TIMEOUT` (default `130`): Seconds for httpx delivery timeout; must exceed agent processing time (AGENT_TIMEOUT=120)
  - `SERVICE_NAME` (default `self-service-agent`): Used to construct subscriber URLs for default subscriptions
  - `NAMESPACE` (default `default`): Kubernetes namespace for subscriber URL construction
  - `LOG_LEVEL`: Structured log level
  - `UVICORN_WORKERS`: Number of uvicorn worker processes (set to 4 in Helm values)
  - `OTEL_EXPORTER_OTLP_ENDPOINT`: OpenTelemetry collector endpoint (optional)
- **Helm values:** Under `requestManagement.knative.mockEventing`:
  - `enabled` (default `true`): Toggle mock vs real Knative eventing
  - `replicas` (default `1`): Must stay 1 for partition-key ordering
  - `logLevel`, `uvicornWorkers`, `resources`, `healthChecks`

## Known Gotchas

- **Single replica required:** The comment in `values.yaml` (line 357) explicitly states `replicas: 1` because partition-key ordering depends on a single pod. Scaling to multiple replicas would break FIFO delivery guarantees for partitioned events.
- **DELIVERY_TIMEOUT must exceed AGENT_TIMEOUT:** The code comment at line 24 of `main.py` notes that `DELIVERY_TIMEOUT` (default 130s) must exceed the agent processing timeout (120s), or deliveries will time out before the agent completes.
- **Mock broker headers injected:** Delivered events include `ce-broker: mock-broker` and `ce-delivery: <attempt_count>` headers (lines 218-219), which do not exist in real Knative broker deliveries. Downstream services should not depend on these.
- **Events without partition key are fire-and-forget:** Events without a `partitionkey` attribute bypass the ordered queue and are dispatched via `asyncio.create_task` with no ordering guarantee (line 131).

## Testing Notes

- Use `POST /subscriptions` to dynamically add subscriptions and `GET /subscriptions` to list them
- Use `GET /events` to inspect the event history (useful for debugging event flow in CI)
- Use `POST /reset` to clear all state (subscriptions, event history, delivery attempts, partition workers)
- Health check at `GET /health` uses the shared `simple_health_check` utility
- The service auto-initializes 10 default subscriptions on startup covering the full request lifecycle

## Related Patterns

- Architecture: Event-driven agentic service communication via CloudEvents
- Deployment: Conditional Helm template rendering for dev vs production eventing stack
