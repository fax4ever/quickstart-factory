---
name: korrel8r
description: "Korrel8r signal correlation engine bridging k8s, alerts, logs, metrics, netflow, and traces for observability"
summary: "Korrel8r (quay.io/korrel8r/korrel8r:0.8.4) is a Go-based signal correlation engine deployed via Helm subchart in openshift-cluster-observability-operator, serving HTTPS on port 9443 with auto-generated TLS via OpenShift serving-cert annotation, bridging k8s resources, Prometheus alerts, LokiStack logs, Thanos metrics, and TempoStack traces through a ConfigMap-driven multi-domain store configuration. Use when building observability tooling that needs cross-signal correlation for LLM prompt enrichment — requires multi-layer RBAC with ClusterRoleBindings across three Loki tenants (application, infrastructure, audit) plus a post-install Helm hook Job to patch the logging-collector CRB, consumed via a Python REST client forwarding bearer tokens for store impersonation. MCP tools implement three-phase log retrieval (Korrel8r goal correlation, direct query fallback, Prometheus kube_pod_info glob-to-exact pod name resolution) with deduplication by (namespace, pod, level, message) and trace correlation via Tempo with semaphore-limited concurrency of 10, controlled by KORREL8R_URL, KORREL8R_TIMEOUT_SECONDS, MAX_NUM_LOG_ROWS, and MAX_NUM_TRACE_SPANS. Critical gotchas: Loki tenant-logs ClusterRole name is computed as lokiNamespace-releaseName-tenant-logs — set releaseName to empty string for umbrella chart or \"loki-stack\" for standalone, wrong value silently breaks log access; log queries require exact pod names (no globs); _choose_verify_param uses different CA paths for .svc/cluster.local vs external routes; deployment runs with runAsNonRoot: true and drops all capabilities for restricted SCC."
metadata:
  type: component
tags:
  tech_stack: [korrel8r, python, requests, helm]
  ai_pattern: [observability, signal-correlation]
  platform: [openshift, kubernetes, loki, tempo, prometheus, thanos]
  data_layer: [lokistack, tempostack]
source_examples:
  - quickstart: "openshift-ai-observability-summarizer"
    repo: "https://github.com/rh-ai-quickstart/openshift-ai-observability-summarizer"
    notes: "Deploys Korrel8r as a standalone Helm subchart with multi-domain store configuration and a Python client for MCP/LLM prompt enrichment"
    approach: "A"
---

# Korrel8r

## Overview

Korrel8r is an observability signal correlation engine that connects Kubernetes resources, Prometheus alerts, Loki logs, Thanos metrics, netflow data, and Tempo traces into a single queryable graph. In the observability-summarizer quickstart it runs as a sidecar-style deployment in the `openshift-cluster-observability-operator` namespace and is consumed by the MCP server's Python client to enrich LLM prompts with correlated log and trace context for vLLM and OpenShift analysis flows.

## Tech Stack & Dependencies

- **Runtime:** Go binary (`korrel8r web`) served over HTTPS on port 9443
- **Container image:** `quay.io/korrel8r/korrel8r:0.8.4`
- **Key dependencies:** LokiStack (logs), TempoStack (traces), Thanos Querier (metrics/alerts), Alertmanager, OpenShift service-ca (TLS)
- **Helm subchart:** `deploy/helm/observability/korrel8r` (v0.1.0), wired as a file dependency in the `aiobs-stack` umbrella chart
- **Python client:** `src/core/korrel8r_client.py` -- REST client using `requests` with bearer-token forwarding and in-cluster CA handling

## Key Patterns

### Multi-Domain Store Configuration via ConfigMap

Korrel8r is configured through a YAML ConfigMap that declares stores for each observability domain. Each store points to a cluster-internal service URL and uses the injected service-ca for TLS.

```yaml
# From deploy/helm/observability/korrel8r/templates/configmap.yaml
stores:
  - domain: k8s
  - domain: alert
    metrics: https://thanos-querier.openshift-monitoring.svc:9091
    alertmanager: https://alertmanager-main.openshift-monitoring.svc:9094
    certificateAuthority: ./run/secrets/kubernetes.io/serviceaccount/service-ca.crt
  - domain: log
    lokiStack: {{ .Values.korrel8r.stores.log.lokiStackUrl | quote }}
    certificateAuthority: ./run/secrets/kubernetes.io/serviceaccount/service-ca.crt
  - domain: trace
    tempoStack: {{ .Values.korrel8r.stores.trace.tempoStackUrl | quote }}
    certificateAuthority: ./run/secrets/kubernetes.io/serviceaccount/service-ca.crt
include:
  - /etc/korrel8r/rules/all.yaml
```

### TLS via OpenShift Serving Cert Annotation

The Service uses the `service.beta.openshift.io/serving-cert-secret-name` annotation to auto-generate a TLS secret, which the Deployment mounts at `/secrets/`. This eliminates manual cert management.

```yaml
# From deploy/helm/observability/korrel8r/templates/service.yaml
annotations:
  service.beta.openshift.io/serving-cert-secret-name: {{ .Values.korrel8r.name }}
```

The deployment then references the secret as a volume:

```yaml
# From deploy/helm/observability/korrel8r/templates/deployment.yaml
command:
- korrel8r
- web
- --https=:9443
- --cert=/secrets/tls.crt
- --key=/secrets/tls.key
- --config=/config/korrel8r.yaml
- --verbose={{ .Values.korrel8r.verbose }}
volumes:
- name: serving-cert
  secret:
    secretName: {{ .Values.korrel8r.name }}
```

### Multi-Layer RBAC for Log Access

Korrel8r requires ClusterRoleBindings to read logs from LokiStack across three log tenants (application, infrastructure, audit). The chart defines static bindings plus a dynamic Loki tenant-logs binding whose ClusterRole name is computed from the Loki release name.

```yaml
# From deploy/helm/observability/korrel8r/templates/clusterrolebinding.yaml
roleRef:
  kind: ClusterRole
  name: collect-application-logs
subjects:
- kind: ServiceAccount
  name: {{ include "korrel8r.serviceAccountName" . }}
  namespace: {{ .Values.global.namespace }}
```

Additionally, a post-install Helm hook Job patches the `logging-collector-logs-writer` ClusterRoleBinding to add the Korrel8r service account, handling the case where that CRB is managed by the logging operator.

```yaml
# From deploy/helm/aiobs-stack/templates/loki-korrel8r-rbac-job.yaml
annotations:
  "helm.sh/hook": post-install,post-upgrade
  "helm.sh/hook-weight": "10"
  "helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded
```

### Python REST Client with Bearer Token Forwarding

The `Korrel8rClient` forwards the cluster bearer token so Korrel8r can impersonate to backend stores (Prometheus, Loki). It also selects the right CA verification strategy based on the URL pattern.

```python
# From src/core/korrel8r_client.py
def _choose_verify_param(self, full_url: str) -> Any:
    try:
        host = urlparse(full_url).hostname or ""
        if ".svc" in host or "cluster.local" in host or host == "localhost":
            return VERIFY_SSL
        return True
    except Exception:
        return True
```

### Two-Phase Log Retrieval Strategy

The MCP tools implement a two-phase log retrieval pattern. Phase 1 uses Korrel8r's goal-based correlation (k8s resource to logs), which works for pods with errors/alerts. Phase 2 falls back to direct log queries when correlation returns nothing (healthy pods with only INFO logs). A Phase 3 resolves glob pod names to exact names via Prometheus since Korrel8r log queries require exact pod names.

```python
# From src/mcp_server/tools/korrel8r_tools.py
# Phase 1: Correlation from k8s resource
all_logs = _fetch_logs_via_correlation(namespace, pod_name)

# Phase 2: Direct query fallback if correlation returned nothing
if not all_logs:
    all_logs = _fetch_logs_via_direct_query(namespace, pod_name)

# Phase 3: Resolve exact pod names via Prometheus and retry
if not all_logs and pod_name:
    resolved_pods = _resolve_pod_names(namespace, pod_name + "*")
```

### Log Simplification and Deduplication

The client normalizes Korrel8r log objects into a standard shape, strips ANSI escape codes, extracts log levels via regex, and deduplicates by `(namespace, pod, level, message)` keeping the latest timestamp.

```python
# From src/core/korrel8r_client.py
simplified.append({
    "namespace": str(namespace) if namespace is not None else "",
    "pod": str(pod) if pod is not None else "",
    "level": level,
    "message": message,
    "timestamp": str(timestamp) if timestamp is not None else "",
})
```

### Trace Correlation via Tempo

For trace goals, the service extracts unique trace IDs from Korrel8r results, fetches full trace details from Tempo concurrently (with a semaphore-limited concurrency of 10), and simplifies Jaeger/Tempo spans. Trace IDs are sorted by timestamp descending and capped by `max_traces_per_query`.

```python
# From src/core/korrel8r_service.py
trace_ids = _extract_unique_trace_ids(obj_result, max_traces=max_traces_per_query)
ids_to_fetch = [tid for tid in trace_ids if tid not in seen_trace_ids]
all_traces = _get_trace_details_sync(ids_to_fetch)
```

## Configuration

- **Environment variables:**
  - `KORREL8R_URL`: Base URL for the Korrel8r service (default empty; set via Helm values for mcp-server, e.g., `https://korrel8r-summarizer.openshift-cluster-observability-operator.svc.cluster.local:9443`)
  - `KORREL8R_TIMEOUT_SECONDS`: HTTP timeout for Korrel8r requests (default `8`)
  - `MAX_NUM_LOG_ROWS`: Maximum log lines appended to LLM prompts (default `10`, exposed via mcp-server Helm chart)
  - `MAX_NUM_TRACE_SPANS`: Maximum trace spans included (default `10`)
  - `INJECT_VLLM_ERROR_LOG_MSG`: Testing-only flag to inject a synthetic error log line
- **Config files:** `korrel8r.yaml` (mounted via ConfigMap at `/config/`) defines all store endpoints and rule includes
- **Helm values:**
  - `korrel8r.stores.log.lokiStackUrl`: LokiStack gateway URL (default: `https://logging-loki-gateway-http.openshift-logging.svc:8080`)
  - `korrel8r.stores.trace.tempoStackUrl`: TempoStack gateway URL
  - `korrel8r.verbose`: Logging verbosity (0=notice, 1=info, 2=debug, 3=trace-per-request)
  - `global.namespace`: Deployment namespace (default: `openshift-cluster-observability-operator`)
  - `loki.releaseName`: Loki chart release name, used to compute the tenant-logs ClusterRole name; empty string triggers dynamic naming via `.Release.Name`
  - `route.tls.termination`: TLS termination mode (default: `reencrypt`)

## Known Gotchas

- The Loki tenant-logs ClusterRole name is dynamically computed as `{{ lokiNamespace }}-{{ releaseName }}-tenant-logs`. When deployed standalone (`make install`), `releaseName` defaults to `"loki-stack"`. When deployed via the umbrella chart, it must be set to `""` so `.Release.Name` is used instead. Getting this wrong silently breaks log access. This is documented in `deploy/helm/observability/korrel8r/values.yaml`.
- Korrel8r log domain queries do not support glob patterns -- only exact pod names work. LLMs almost never pass full Kubernetes pod names with deployment/replicaset hash suffixes, so the MCP tool layer includes a `_resolve_pod_names` function that queries `kube_pod_info` via Prometheus to resolve patterns to exact names. This is documented in `src/mcp_server/tools/korrel8r_tools.py`.
- The `_choose_verify_param` method on the client uses different CA verification for in-cluster `.svc` / `cluster.local` URLs versus external route URLs. This avoids the injected service CA bundle overriding public CA trust when calling external routes. Documented in `src/core/korrel8r_client.py`.
- The async trace fetching in `_get_trace_details_sync` falls back to a separate thread when `asyncio.run()` is called from within an already-running event loop, suppressing `RuntimeWarning` about coroutines that were never awaited. This is an explicit workaround documented in `src/core/korrel8r_service.py`.
- The deployment runs with `securityContext.allowPrivilegeEscalation: false`, `runAsNonRoot: true`, and drops all capabilities -- suitable for restricted SCC on OpenShift.

## Testing Notes

- Verify the Korrel8r pod is running in `openshift-cluster-observability-operator` namespace
- Confirm the Route is accessible and returns HTTPS responses
- Test log correlation by querying: `k8s:Pod.v1:{"namespace":"<ns>","name":"<pod>"}` via the `korrel8r_query_objects` MCP tool
- Test trace correlation with goals `["trace:span"]` via the `korrel8r_get_correlated` MCP tool
- Check that the `logging-collector-logs-writer` CRB includes the `korrel8r-summarizer` service account (the post-install Job should handle this)
- Unit tests exist at `tests/core/test_korrel8r_trace_limiting.py` for trace ID extraction and limiting behavior

## Related Patterns

- Cluster Observability Operator (`components/cluster-observability-operator.md`) -- prerequisite operator
- Tempo (`components/tempo.md`) -- trace storage backend consumed by Korrel8r
- OTel Collector (`components/otel-collector.md`) -- instrumentation pipeline feeding traces to Tempo
- Observability Stack (`components/observability-stack.md`) -- umbrella deployment pattern
