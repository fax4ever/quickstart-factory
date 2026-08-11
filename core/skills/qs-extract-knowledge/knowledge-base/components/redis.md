---
name: redis
description: "Redis as NV-Ingest message broker and status tracker in NVIDIA RAG pipelines on RHOAI"
summary: "Redis is bundled inside the nv-ingest Helm subchart (v26.1.1 from NGC) as both the message broker for NV-Ingest document ingestion (task queue ingest_task_queue via MESSAGE_CLIENT_TYPE: \"redis\") and a cross-chart summary status tracker for the separately deployed rag-server — not deployed standalone. Use when building NVIDIA NV-Ingest RAG pipelines on RHOAI where both nv-ingest and rag-server charts need shared Redis; image is pinned via nv-ingest.redis.image override (8.2.1) and service name follows Bitnami <release-name>-redis-master convention (StatefulSet pod <release-name>-redis-master-0). Critical: the ingest chart's __RELEASE_NAME__ placeholder substitution does not work inside nv-ingest subchart templates, so MESSAGE_CLIENT_HOST must be hardcoded to the expected service name (e.g., \"ingest-redis-master\"); ENABLE_REDIS_BACKEND: \"False\" controls a separate optional ingestor backend, not the mandatory message queue. Changing the Helm release name from ingest requires manually updating REDIS_HOST in both ingestor-server and rag-server values — omitting this causes silent connection failures (fixed in commit df2efc3)."
metadata:
  type: component
tags:
  tech_stack: [redis]
  ai_pattern: [rag, data-pipeline]
  platform: [rhoai, openshift]
  data_layer: [redis]
source_examples:
  - quickstart: "aml-rag-nvidia"
    repo: "https://github.com/rh-ai-quickstart/aml-rag-nvidia"
    notes: "Redis deployed via nv-ingest subchart as message broker and summary status tracker"
    approach: "A"
---

# Redis

## Overview

Redis serves as the message broker and optional status-tracking store within NVIDIA NV-Ingest RAG pipelines on RHOAI. It is not deployed as a standalone chart; instead it ships as a bundled dependency inside the `nv-ingest` Helm subchart from NVIDIA's NGC registry. Both the ingestor-server and rag-server components connect to the same Redis instance for different purposes.

## Tech Stack & Dependencies

- **Runtime:** Redis 8.2.1
- **Container image:** `redis:8.2.1`
- **Helm subchart:** Bundled inside `nv-ingest` chart (v26.1.1) from `https://helm.ngc.nvidia.com/nvidia/nemo-microservices`
- **Key dependents:** nv-ingest (message queue), ingestor-server (optional backend), rag-server (summary status tracking)

## Key Patterns

### NV-Ingest Message Broker

Redis acts as the message queue for the NV-Ingest document processing pipeline. NV-Ingest uses it to coordinate ingestion tasks via a dedicated task queue.

```yaml
# charts/ingest/values.yaml — nv-ingest section
nv-ingest:
  envVars:
    MESSAGE_CLIENT_HOST: "ingest-redis-master"
    MESSAGE_CLIENT_PORT: 6379
    MESSAGE_CLIENT_TYPE: "redis"
    REDIS_INGEST_TASK_QUEUE: "ingest_task_queue"
```

### Cross-Chart Status Tracking

The rag-server (a separate Helm chart) connects to the same Redis instance deployed by the ingest chart's nv-ingest subchart, using it for summary status tracking.

```yaml
# charts/rag-server/values.yaml
envVars:
  ##===Redis configurations for summary status tracking===
  REDIS_HOST: "ingest-redis-master"  # Set dynamically; matches nv-ingest redis
  REDIS_PORT: "6379"
  REDIS_DB: "0"
```

### Release-Name Templating Split

The ingest chart's own templates support a `__RELEASE_NAME__` placeholder that gets replaced at render time via Helm's `replace` function. The ingestor-server uses this for its Redis connection.

```yaml
# charts/ingest/values.yaml — ingestor-server section
ingestor-server:
  envVars:
    REDIS_HOST: "__RELEASE_NAME__-redis-master"  # Uses release name
    REDIS_PORT: "6379"
    REDIS_DB: "0"
    ENABLE_REDIS_BACKEND: "False"
```

The template performs the substitution:

```yaml
# charts/ingest/templates/ingestor-server-deployment.yaml (line 108)
value: "{{ $v | replace \"__RELEASE_NAME__\" $.Release.Name }}"
```

### Redis Image Override

The nv-ingest subchart's Redis image is overridden in the parent chart's values to pin a specific version.

```yaml
# charts/ingest/values.yaml — nv-ingest section
nv-ingest:
  redis:
    image:
      repository: redis
      tag: 8.2.1
```

## Configuration

- **Environment variables (nv-ingest):** `MESSAGE_CLIENT_HOST`, `MESSAGE_CLIENT_PORT`, `MESSAGE_CLIENT_TYPE`, `REDIS_INGEST_TASK_QUEUE`
- **Environment variables (ingestor-server):** `REDIS_HOST`, `REDIS_PORT`, `REDIS_DB`, `ENABLE_REDIS_BACKEND`
- **Environment variables (rag-server):** `REDIS_HOST`, `REDIS_PORT`, `REDIS_DB`
- **Helm values:** Redis image is configured under `nv-ingest.redis.image` in the ingest chart's values

## Known Gotchas

- **NV-Ingest subchart does not support `__RELEASE_NAME__` placeholder substitution.** The ingest chart's own deployment templates use a Helm `replace` function to swap `__RELEASE_NAME__` with the actual release name, but the nv-ingest subchart renders its own templates without this logic. Therefore `MESSAGE_CLIENT_HOST` in the `nv-ingest` section must be hardcoded to the expected service name (e.g., `"ingest-redis-master"` when the release name is `ingest`). This was fixed in commit `df2efc3` ("ensuring redis services match environment variable naming") after an earlier attempt to use `__RELEASE_NAME__` caused connection failures.
- **Redis host must be coordinated across charts.** The rag-server chart is deployed separately from the ingest chart but must reference the same Redis service name. Since rag-server's templates also lack the `__RELEASE_NAME__` replacement logic, `REDIS_HOST` is hardcoded to `"ingest-redis-master"` (commit `df2efc3`). Changing the ingest chart's release name requires updating the rag-server's `REDIS_HOST` value manually.
- **Redis service name follows `<release-name>-redis-master` convention.** This naming is determined by the nv-ingest subchart's bundled Redis dependency. The `-master` suffix comes from Redis's Bitnami-style Helm chart conventions.
- **`ENABLE_REDIS_BACKEND` is disabled by default** (`"False"` in ingestor-server). This controls an optional Redis backend for the ingestor and is separate from nv-ingest's mandatory use of Redis as a message broker.

## Testing Notes

- Verify Redis pod is running: the pod will be named `<release-name>-redis-master-0` (StatefulSet pattern from nv-ingest subchart)
- Confirm nv-ingest can reach Redis by checking nv-ingest logs for successful message queue connection
- Confirm rag-server can reach Redis by checking rag-server logs for summary status tracking initialization
- If changing the Helm release name from `ingest`, update `MESSAGE_CLIENT_HOST` in `nv-ingest` values and `REDIS_HOST` in both ingestor-server and rag-server values

## Related Patterns

- `components/ingestion-pipeline.md` — NV-Ingest pipeline that depends on Redis as its message broker
