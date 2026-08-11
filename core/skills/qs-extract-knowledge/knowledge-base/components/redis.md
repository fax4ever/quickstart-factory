---
name: redis
description: "Redis as message broker for NV-Ingest RAG pipelines and queue backend for LangFuse observability on RHOAI"
summary: "Redis provides two RHOAI deployment patterns: (A) NV-Ingest Helm subchart (v26.1.1, Redis 8.2.1 pinned via nv-ingest.redis.image) bundles Redis as message broker (MESSAGE_CLIENT_TYPE: \"redis\", queue ingest_task_queue) and cross-chart status tracker for RAG document ingestion across nv-ingest, ingestor-server, and rag-server; (B) inline Helm template (Redis 7.2) deploys Redis conditionally via langfuse.enabled as LangFuse v3 event queue and cache with password authentication via Secret, OpenShift restricted SCC (runAsNonRoot, drop ALL, seccomp RuntimeDefault), and AOF+RDB persistence on PVC. Choose Approach A for NVIDIA NV-Ingest RAG pipelines where three charts share one Redis instance (Bitnami <release>-redis-master service naming); choose Approach B for LangFuse observability needing password-authenticated Redis with REDIS_CONNECTION_STRING built from Secret-sourced REDIS_AUTH — ENABLE_REDIS_BACKEND: \"False\" in A controls an optional ingestor backend, not the mandatory message queue. In Approach A, MESSAGE_CLIENT_HOST must be hardcoded to the expected service name (e.g., \"ingest-redis-master\") because nv-ingest subchart templates lack the __RELEASE_NAME__ replace function present in the parent ingest chart; in Approach B, langfuse.redis.password defaults to \"changeme\" (must override for production) and health probes exec redis-cli --no-auth-warning -a $(REDIS_PASSWORD) ping. Changing the Helm release name from \"ingest\" in A requires manually updating REDIS_HOST in both ingestor-server and rag-server values or connections silently fail (fixed in commit df2efc3); in B, PVCs from StatefulSet volumeClaimTemplates persist after helm uninstall and the service is named <fullname>-langfuse-redis not <fullname>-redis."
metadata:
  type: component
tags:
  tech_stack: [redis]
  ai_pattern: [rag, data-pipeline, agents]
  platform: [rhoai, openshift]
  data_layer: [redis]
source_examples:
  - quickstart: "aml-rag-nvidia"
    repo: "https://github.com/rh-ai-quickstart/aml-rag-nvidia"
    notes: "Redis deployed via nv-ingest subchart as message broker and summary status tracker"
    approach: "A"
  - quickstart: "it-self-service-agent"
    repo: "https://github.com/rh-ai-quickstart/it-self-service-agent"
    notes: "Redis deployed as inline Helm StatefulSet for LangFuse v3 observability queue and cache"
    approach: "B"
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

---

## Approach B: LangFuse Observability Queue (from it-self-service-agent)

### When to Use

When deploying LangFuse v3 as an observability platform for LLM tracing alongside an agentic quickstart. Redis serves as the queue backend that LangFuse web and worker containers use for event processing. This pattern deploys Redis as an inline Helm template (not a subchart) conditionally gated behind `langfuse.enabled`.

### Differences from Approach A

- **Deployment method:** Inline Helm template (Secret + Service + StatefulSet in a single file) vs Bitnami subchart bundled inside nv-ingest
- **Purpose:** LangFuse event queue and cache vs NV-Ingest message broker and status tracker
- **Security model:** Explicit OpenShift-restricted SCC at both pod and container level (runAsNonRoot, drop ALL capabilities, seccomp RuntimeDefault)
- **Authentication:** Password stored in a dedicated Kubernetes Secret, injected via `REDIS_PASSWORD` env var and referenced by health probes
- **Persistence:** AOF with RDB snapshots (`--appendonly yes`, `--save` intervals), PVC via `volumeClaimTemplates`
- **Version:** Redis 7.2 (vs 8.2.1 in Approach A)

### Key Patterns

#### Conditional Deployment Gated by LangFuse

The entire Redis manifest (Secret, Service, StatefulSet) is wrapped in a single `langfuse.enabled` conditional. Redis only deploys when LangFuse observability is turned on.

```yaml
# helm/templates/redis-deployment.yaml (line 1)
{{- if .Values.langfuse.enabled }}
```

#### StatefulSet with Password Authentication

Redis is deployed as a StatefulSet with password authentication via a Kubernetes Secret. The password is passed to `redis-server` via CLI args and also used by liveness/readiness probes.

```yaml
# helm/templates/redis-deployment.yaml (lines 74-85)
command:
- redis-server
- --requirepass
- $(REDIS_PASSWORD)
- --appendonly
- "yes"
- --save
- "900 1"
- --save
- "300 10"
- --save
- "60 10000"
```

#### OpenShift-Restricted Security Context

Both pod-level and container-level security contexts enforce OpenShift restricted SCC compliance.

```yaml
# helm/templates/redis-deployment.yaml (lines 58-71)
securityContext:
  runAsNonRoot: true
  seccompProfile:
    type: RuntimeDefault
containers:
- name: redis
  securityContext:
    allowPrivilegeEscalation: false
    capabilities:
      drop:
      - ALL
    runAsNonRoot: true
    seccompProfile:
      type: RuntimeDefault
```

#### Redis Connection String for LangFuse

Both the LangFuse web container and LangFuse worker consume Redis via `REDIS_CONNECTION_STRING` built from Secret-sourced password, templated host, and port.

```yaml
# helm/templates/langfuse-deployment.yaml (lines 426-438)
- name: LANGFUSE_REDIS_ENABLED
  value: "true"
- name: REDIS_HOST
  value: {{ include "self-service-agent.fullname" . }}-langfuse-redis
- name: REDIS_PORT
  value: "6379"
- name: REDIS_AUTH
  valueFrom:
    secretKeyRef:
      name: {{ include "self-service-agent.fullname" . }}-langfuse-redis-secret
      key: password
- name: REDIS_CONNECTION_STRING
  value: "redis://:$(REDIS_AUTH)@$(REDIS_HOST):$(REDIS_PORT)"
```

### Configuration

- **Environment variables (Redis container):** `REDIS_PASSWORD` — injected from Secret, used by `--requirepass` and health probes
- **Environment variables (LangFuse web/worker):** `LANGFUSE_REDIS_ENABLED`, `REDIS_HOST`, `REDIS_PORT`, `REDIS_AUTH`, `REDIS_CONNECTION_STRING`
- **Helm values:** `langfuse.redis.version` (default `"7.2"`), `langfuse.redis.password` (default `"changeme"`), `langfuse.redis.storage` (default `"2Gi"`), `langfuse.redis.storageClass`, `langfuse.redis.resources`, `langfuse.redis.healthChecks`

### Known Gotchas

- **Default password is `"changeme"`.** The `langfuse.redis.password` value defaults to `"changeme"` (line 12 of `redis-deployment.yaml`: `password: {{ .Values.langfuse.redis.password | default "changeme" | quote }}`). Must be overridden for production deployments.
- **Health probes use `redis-cli` with `--no-auth-warning` flag.** The liveness and readiness probes exec `redis-cli --no-auth-warning -a $(REDIS_PASSWORD) ping`, which suppresses the CLI warning about passing passwords on the command line. This is intentional — without `--no-auth-warning`, probe stderr output could flood container logs.
- **PVC is not cleaned up on uninstall.** The StatefulSet uses `volumeClaimTemplates` for the `/data` mount. Helm does not delete PVCs created by StatefulSets on `helm uninstall`, so the 2Gi PVC persists and must be manually cleaned up.
- **Service name includes `-langfuse-redis` suffix.** The service is named `<fullname>-langfuse-redis` (not just `<fullname>-redis`), so consumers must use the full templated name. Both the LangFuse web and worker deployments correctly reference this via `{{ include "self-service-agent.fullname" . }}-langfuse-redis`.

### Testing Notes

- Verify Redis pod is running: the pod will be a StatefulSet pod named `<fullname>-langfuse-redis-0`
- Confirm LangFuse web container has `LANGFUSE_REDIS_ENABLED=true` and `REDIS_CONNECTION_STRING` resolves correctly
- Confirm LangFuse worker container similarly has the Redis env vars injected
- Redis is only deployed when `langfuse.enabled` is `true` — check `helm/values.yaml` to confirm the feature flag

### Related Patterns

- `components/observability-stack.md` — LangFuse observability platform that depends on this Redis instance

---

## Choosing Between Approaches

| Criteria | Approach A (NV-Ingest Subchart) | Approach B (LangFuse Inline Template) |
|----------|-------------------------------|--------------------------------------|
| Deployment method | Bitnami subchart bundled in nv-ingest | Inline Helm template (Secret + Service + StatefulSet) |
| Purpose | Message broker + status tracker for RAG ingestion | Event queue + cache for LangFuse observability |
| Redis version | 8.2.1 | 7.2 |
| Authentication | No explicit password (subchart defaults) | Password via Kubernetes Secret |
| Persistence | Subchart-managed storage | AOF + RDB snapshots, PVC via volumeClaimTemplates |
| Security context | Subchart defaults | Explicit OpenShift restricted SCC |
| Conditional deploy | Always deployed with ingest chart | Gated behind `langfuse.enabled` |
| Service naming | `<release>-redis-master` (Bitnami convention) | `<fullname>-langfuse-redis` (custom template) |
| Consumers | nv-ingest, ingestor-server, rag-server | LangFuse web, LangFuse worker |
