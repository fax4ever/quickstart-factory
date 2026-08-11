---
name: clickhouse
description: "ClickHouse column-oriented database deployed as StatefulSet for Langfuse v3 trace storage on OpenShift"
summary: "ClickHouse Server 24.3 is deployed as a single-node StatefulSet with PVC (volumeClaimTemplates) to provide Langfuse v3 analytics and trace storage on OpenShift, gated behind langfuse.enabled and consumed exclusively by Langfuse web/worker containers — not directly by application code. Use this pattern when deploying Langfuse v3 observability; it enforces OpenShift restricted SCC security context, auto-generates 32-char passwords via Helm randAlphaNum when langfuse.clickhouse.password is empty, and exposes dual protocols (HTTP :8123 for CLICKHOUSE_URL/health checks, native TCP :9000 for CLICKHOUSE_MIGRATION_URL). Critical config: wait-for-clickhouse init container polls /ping before Langfuse starts because schema migrations run on the web container at startup; server tuning is delivered via custom.xml ConfigMap mounted to /etc/clickhouse-server/config.d/ setting max_concurrent_queries (100), max_connections (1024), and LZ4 compression. Gotchas: default values.yaml ships password \"langgraph_password\" bypassing auto-generation, init container uses ubi9-minimal with runtime microdnf curl install adding startup latency, CLICKHOUSE_CLUSTER_ENABLED is hardcoded false (single-node only), never set LANGFUSE_AUTO_CLICKHOUSE_MIGRATION_DISABLED to \"true\" on the worker, and omitting either CLICKHOUSE_URL or CLICKHOUSE_MIGRATION_URL causes Langfuse startup failure."
metadata:
  type: component
tags:
  tech_stack: [clickhouse, langfuse, helm]
  ai_pattern: [evaluation]
  platform: [openshift, kubernetes]
  data_layer: [clickhouse]
source_examples:
  - quickstart: "it-self-service-agent"
    repo: "https://github.com/rh-ai-quickstart/it-self-service-agent"
    notes: "ClickHouse as analytics backend for Langfuse v3 observability, deployed via StatefulSet with PVC"
    approach: "A"
---

# ClickHouse

## Overview

ClickHouse is deployed as a single-node StatefulSet to serve as the analytics and trace storage backend for Langfuse v3. In the it-self-service-agent quickstart, it is not accessed directly by application code but is exclusively consumed by Langfuse web and worker components for storing observability traces. The entire ClickHouse stack is gated behind the `langfuse.enabled` Helm flag.

## Tech Stack & Dependencies

- **Runtime:** ClickHouse Server 24.3
- **Container image:** `clickhouse/clickhouse-server:{{ .Values.langfuse.clickhouse.version }}`
- **Key dependencies:** Langfuse v3 (web and worker containers consume ClickHouse for trace storage)
- **Helm subchart:** None -- deployed as raw Helm templates within the parent chart

## Key Patterns

### StatefulSet with PVC for Data Persistence

ClickHouse is deployed as a StatefulSet (not a Deployment) to get stable storage via `volumeClaimTemplates`. This ensures trace data survives pod restarts.

```yaml
kind: StatefulSet
spec:
  serviceName: {{ include "self-service-agent.fullname" . }}-clickhouse
  replicas: 1
  # ...
  volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: {{ .Values.langfuse.clickhouse.storage }}
```

### OpenShift-Compatible Security Context

The deployment uses a restricted security context compatible with OpenShift's restricted SCC -- no privilege escalation, all capabilities dropped, non-root user, and RuntimeDefault seccomp profile.

```yaml
securityContext:
  runAsNonRoot: true
  seccompProfile:
    type: RuntimeDefault
containers:
- name: clickhouse
  securityContext:
    allowPrivilegeEscalation: false
    capabilities:
      drop:
      - ALL
    runAsNonRoot: true
    seccompProfile:
      type: RuntimeDefault
```

### Auto-Generated Password via Kubernetes Secret

The password is auto-generated with `randAlphaNum 32` if not explicitly provided in values, avoiding hardcoded credentials in production.

```yaml
apiVersion: v1
kind: Secret
type: Opaque
stringData:
  {{- if .Values.langfuse.clickhouse.password }}
  password: {{ .Values.langfuse.clickhouse.password | quote }}
  {{- else }}
  password: {{ randAlphaNum 32 | quote }}
  {{- end }}
```

### Init Container Readiness Gate

Both the Langfuse web and worker deployments use a `wait-for-clickhouse` init container that polls the `/ping` HTTP endpoint before starting. This is critical because Langfuse schema migrations run on container startup and require ClickHouse to be available.

```yaml
# From langfuse-deployment.yaml comment:
# This is critical because schema migrations run from the WEB container on startup
- name: wait-for-clickhouse
  image: registry.access.redhat.com/ubi9/ubi-minimal:latest
  command:
  - /bin/sh
  - -c
  - |
    microdnf install -y curl
    until curl -sf http://...-clickhouse:8123/ping >/dev/null 2>&1; do
      echo "Waiting for ClickHouse to be ready..."
      sleep 2
    done
```

### Custom XML Configuration via ConfigMap

Server-level tuning is delivered through a ConfigMap mounted into `/etc/clickhouse-server/config.d/`. Key settings include listen address, concurrency limits, and LZ4 compression.

```xml
<clickhouse>
  <listen_host>::</listen_host>
  <max_concurrent_queries>100</max_concurrent_queries>
  <max_connections>1024</max_connections>
  <keep_alive_timeout>3</keep_alive_timeout>
  <compression>
    <case>
      <min_part_size>10485760</min_part_size>
      <min_part_size_ratio>0.01</min_part_size_ratio>
      <method>lz4</method>
    </case>
  </compression>
</clickhouse>
```

### Dual-Protocol Service Exposure

The Service exposes both the HTTP interface (port 8123, used for health checks and `CLICKHOUSE_URL`) and the native TCP protocol (port 9000, used for `CLICKHOUSE_MIGRATION_URL`).

```yaml
spec:
  ports:
  - name: http
    port: 8123
    targetPort: http
  - name: native
    port: 9000
    targetPort: native
```

## Configuration

- **Environment variables:**
  - `CLICKHOUSE_USER` -- Database user (default: `langfuse`)
  - `CLICKHOUSE_PASSWORD` -- From Kubernetes Secret (auto-generated or explicit)
  - `CLICKHOUSE_DB` -- Database name (default: `langfuse`)
  - `CLICKHOUSE_DEFAULT_ACCESS_MANAGEMENT` -- Set to `"1"` to enable SQL-based user management
- **Consumer environment variables (set on Langfuse containers):**
  - `CLICKHOUSE_URL` -- HTTP protocol URL (`http://user:pass@host:8123/db`)
  - `CLICKHOUSE_MIGRATION_URL` -- Native protocol URL (`clickhouse://user:pass@host:9000/db`)
  - `CLICKHOUSE_CLUSTER_ENABLED` -- Set to `"false"` for single-node deployment
- **Config files:** `custom.xml` ConfigMap mounted to `/etc/clickhouse-server/config.d/`
- **Helm values:**
  - `langfuse.clickhouse.version` -- ClickHouse image tag (default: `24.3`)
  - `langfuse.clickhouse.user` -- Database user (default: `langfuse`)
  - `langfuse.clickhouse.database` -- Database name (default: `langfuse`)
  - `langfuse.clickhouse.password` -- Explicit password (auto-generated if empty)
  - `langfuse.clickhouse.storage` -- PVC size (default: `10Gi`)
  - `langfuse.clickhouse.storageClass` -- Storage class (empty for cluster default)
  - `langfuse.clickhouse.resources` -- Resource requests/limits
  - `langfuse.clickhouse.healthChecks` -- Liveness/readiness probe timing

## Known Gotchas

- **Migrations must not be disabled on the worker:** The langfuse-worker-deployment.yaml contains an explicit comment: `IMPORTANT: Do NOT set LANGFUSE_AUTO_CLICKHOUSE_MIGRATION_DISABLED to "true"` -- ClickHouse migrations run automatically on worker startup and are required.
- **Two different URL protocols required:** Langfuse needs both an HTTP URL (`CLICKHOUSE_URL` on port 8123) and a native protocol URL (`CLICKHOUSE_MIGRATION_URL` on port 9000). Missing either causes startup failures.
- **Init container installs curl at runtime:** The `wait-for-clickhouse` init container uses `ubi9/ubi-minimal` and runs `microdnf install -y curl` on every pod start. This adds startup latency and requires network access to Red Hat package repos.
- **Default password in values.yaml:** The default `langfuse.clickhouse.password` is set to `langgraph_password` in values.yaml. The Secret template auto-generates a 32-char random password only when the value is empty -- the shipped default bypasses this safety net.
- **Single-node only:** `CLICKHOUSE_CLUSTER_ENABLED` is hardcoded to `"false"`. The deployment is not designed for ClickHouse clustering.

## Testing Notes

- Verify ClickHouse is running: `curl -sf http://<clickhouse-svc>:8123/ping` should return `Ok.`
- Check that the PVC is bound: `oc get pvc -l app.kubernetes.io/component=clickhouse`
- Confirm both Langfuse web and worker pods pass the init container stage (not stuck in `Init:0/N`)
- Verify the Secret was created: `oc get secret <release>-clickhouse-secret`

## Related Patterns

- Langfuse observability stack (langfuse-deployment, langfuse-worker-deployment)
- Redis (also required by Langfuse v3, co-deployed under the same `langfuse.enabled` gate)
- PostgreSQL/pgvector (Langfuse uses PostgreSQL for relational data alongside ClickHouse for traces)
