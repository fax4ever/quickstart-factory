---
name: llm-observability-pipeline
description: End-to-end distributed tracing and metrics for LLM inference using OpenTelemetry, Tempo, and Grafana
summary: "Instruments vLLM model servers and Llama Stack orchestration with end-to-end distributed tracing and metrics using OpenTelemetry, a two-tier collector topology (per-service OTel sidecars forwarding to a central collector with k8sattributes pod metadata enrichment), TempoStack for multitenant trace storage (MinIO-backed), User Workload Monitoring PodMonitors (matchLabels and matchExpressions selectors) for Prometheus metrics, and Grafana plus the OpenShift Distributed Tracing UI Plugin for visualization. Use when you need visibility into inference request latency, token generation, agent tool calls, and safety checks across KServe-served vLLM and Llama Stack services on OpenShift AI -- single approach covers both GPU and CPU vLLM deployments. Enable vLLM tracing via ServingRuntime args (--otlp-traces-endpoint, --collect-detailed-traces all) with sidecar Prometheus scrape on localhost:8000, Llama Stack telemetry via OTEL_TRACE_ENDPOINT/OTEL_METRIC_ENDPOINT/TELEMETRY_SINKS env vars, inject sidecars with sidecar.opentelemetry.io/inject annotation, and authenticate central collector to Tempo gateway with bearer token from SA token at multitenant path /api/traces/v1/dev. CPU vLLM image (opea/vllm-cpu-ubi) lacks OTel packages requiring a custom BuildConfig, central collector needs ClusterRole with create on tempo.grafana.com/dev plus pod/namespace/replicaset access for k8sattributes, TempoStack MinIO uses hardcoded test credentials (admin/minio123), Grafana datasources require a grafana-sa-token Secret, vLLM sidecars handle both traces and metrics but Llama Stack sidecars handle only traces (Llama Stack sends metrics directly to central collector), and UWM requires cluster-wide enableUserWorkload: true in cluster-monitoring-config."
metadata:
  type: architecture
tags:
  tech_stack: [opentelemetry, grafana, tempo, minio, vllm, llamastack, python]
  ai_pattern: [model-serving, agents]
  platform: [rhoai, openshift, kserve, vllm]
  data_layer: [minio]
source_examples:
  - quickstart: "lls-observability"
    repo: "https://github.com/rh-ai-quickstart/lls-observability"
    notes: "Full observability stack (OpenTelemetry sidecar + central collectors, Tempo, Grafana, User Workload Monitoring) instrumenting vLLM and Llama Stack for distributed tracing and metrics"
    approach: "A"
---

# LLM Observability Pipeline

## Overview

This architecture instruments LLM inference infrastructure (vLLM model servers and Llama Stack orchestration) with distributed tracing and metrics using OpenTelemetry. A two-tier collector topology (per-service sidecars forwarding to a central collector) aggregates telemetry from all AI services and exports traces to Tempo and metrics to Prometheus, with Grafana providing unified dashboards. The pattern provides end-to-end visibility into inference request latency, token generation, tool calls, and model serving performance without modifying application code beyond configuration flags and environment variables.

## Data Flow

1. vLLM emits OTLP traces via its built-in `--otlp-traces-endpoint` flag to a co-located OTel sidecar collector on gRPC port 4317
2. Llama Stack emits OTLP traces and metrics via its telemetry provider (configured through `OTEL_TRACE_ENDPOINT` and `OTEL_METRIC_ENDPOINT` env vars) to the central OTel collector on HTTP port 4318
3. The vLLM OTel sidecar also scrapes Prometheus metrics from vLLM at `localhost:8000/metrics` every 15 seconds
4. Sidecar collectors forward all traces and metrics to the central OTel collector at `otel-collector-collector.observability-hub.svc.cluster.local:4318` via OTLP/HTTP
5. The central OTel collector applies processors (k8sattributes for pod metadata enrichment, batch for 100-item batches at 1s timeout, memory_limiter at 95% limit)
6. The central collector exports traces to the Tempo gateway at `tempo-tempostack-gateway.observability-hub.svc.cluster.local:8080` via OTLP/HTTP with bearer token auth and TLS
7. TempoStack persists traces in MinIO S3 storage with multitenant isolation (dev tenant)
8. User Workload Monitoring PodMonitors independently scrape vLLM Prometheus metrics on port h2c at 15-second intervals
9. Grafana queries both Thanos Querier (for Prometheus metrics) and Tempo gateway (for traces) as datasources
10. The Distributed Tracing UI Plugin surfaces traces directly in the OpenShift Console

## Component Wiring

| From | To | Protocol | Purpose |
|------|----|----------|---------|
| vLLM (inference model) | OTel sidecar collector | gRPC (OTLP, port 4317) | Emit inference traces (request lifecycle, token generation) |
| vLLM (safety model) | OTel sidecar collector | gRPC (OTLP, port 4317) | Emit Llama Guard safety check traces |
| Llama Stack | Central OTel collector | HTTP (OTLP, port 4318) | Emit agent/tool/inference telemetry traces and metrics |
| OTel sidecar (vLLM) | vLLM (localhost:8000) | HTTP (Prometheus scrape) | Collect vLLM serving metrics |
| OTel sidecar collectors | Central OTel collector | HTTP (OTLP, port 4318) | Forward traces and metrics upstream |
| Central OTel collector | vLLM predictor | HTTP (Prometheus scrape) | Scrape inference metrics from model endpoint |
| Central OTel collector | Tempo gateway | HTTPS (OTLP, port 8080) | Export traces with bearer token auth and X-Scope-OrgID header |
| TempoStack | MinIO | S3 (port 9000) | Persist trace data to object storage |
| PodMonitor (UWM) | vLLM pods | HTTP (/metrics, port h2c) | Scrape vLLM metrics into OpenShift Prometheus |
| Grafana | Thanos Querier | HTTPS (port 9091) | Query aggregated Prometheus metrics |
| Grafana | Tempo gateway | HTTPS (port 8081) | Query distributed traces |
| Distributed Tracing UI Plugin | TempoStack | HTTPS | Visualize traces in OpenShift Console |

## Key Integration Points

### vLLM Tracing Configuration in ServingRuntime

vLLM's built-in OpenTelemetry support is enabled through ServingRuntime args and env vars. The `--collect-detailed-traces all` flag captures request-level, model-level, and worker-level trace spans.

```yaml
# helm/03-ai-services/llama3.2-3b/templates/servingruntime.yaml (lines 41-56)
{{- if .Values.servingRuntime.tracing.enabled }}
# tracing-specific flags and options
- --otlp-traces-endpoint
- {{ .Values.servingRuntime.tracing.otlpTracesEndpoint }}
- --collect-detailed-traces
- {{ .Values.servingRuntime.tracing.collectDetailedTraces | quote }}
{{- end }}
env:
{{- if .Values.servingRuntime.tracing.enabled }}
- name: OTEL_SERVICE_NAME
  value: {{ .Values.servingRuntime.tracing.serviceName | quote }}
- name: OTEL_EXPORTER_OTLP_TRACES_INSECURE
  value: {{ .Values.servingRuntime.tracing.insecure | quote }}
{{- end }}
```

Default values point the traces to the central OTel collector via gRPC:

```yaml
# helm/03-ai-services/llama3.2-3b/values.yaml (lines 212-218)
tracing:
  enabled: true
  otlpTracesEndpoint: "grpc://otel-collector-collector.observability-hub.svc.cluster.local:4317"
  collectDetailedTraces: "all"
  serviceName: "vllm-llama32b"
  insecure: true
```

### Llama Stack Telemetry Provider Configuration

Llama Stack's built-in telemetry provider exports to OpenTelemetry via environment variables set in the deployment. The `TELEMETRY_SINKS` variable controls which outputs are active.

```yaml
# helm/03-ai-services/llama-stack/templates/deployment.yaml (lines 83-92)
{{- if .Values.otelCollector.enabled }}
- name: OTEL_SERVICE_NAME
  value: llamastack
- name: OTEL_TRACE_ENDPOINT
  value: http://otel-collector-collector.observability-hub.svc.cluster.local:4318/v1/traces
- name: OTEL_METRIC_ENDPOINT
  value: http://otel-collector-collector.observability-hub.svc.cluster.local:4318/v1/metrics
- name: TELEMETRY_SINKS
  value: "console, sqlite, otel_trace, otel_metric"
{{- end }}
```

The corresponding Llama Stack config.yaml registers the telemetry provider that reads these env vars:

```yaml
# helm/03-ai-services/llama-stack/templates/configmap.yaml (lines 105-112)
telemetry:
- provider_id: meta-reference
  provider_type: inline::meta-reference
  config:
    service_name: ${env.OTEL_SERVICE_NAME:llama-stack}
    sinks: ${env.TELEMETRY_SINKS:console, sqlite}
    otel_trace_endpoint: ${env.OTEL_TRACE_ENDPOINT:}
    sqlite_db_path: ${env.SQLITE_DB_PATH:~/.llama/distributions/remote-vllm/trace_store.db}
```

### OTel Sidecar Injection via Pod Annotation

The OpenTelemetry Operator automatically injects a sidecar collector into any pod with a matching annotation. The sidecar name maps to an `OpenTelemetryCollector` CR with `mode: sidecar`.

```yaml
# helm/03-ai-services/llama-stack/templates/deployment.yaml (lines 20-22)
annotations:
  checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
  {{- if .Values.otelCollector.enabled }}
  sidecar.opentelemetry.io/inject: {{ .Values.otelCollector.name | default "llamastack-otelsidecar" }}
  {{- end }}
```

### Two-Tier Collector Topology (Sidecar to Central)

Sidecar collectors forward all telemetry to the central collector, which serves as the single aggregation point before exporting to backends. This pattern decouples per-service collection from backend routing.

```yaml
# helm/02-observability/otel-collector/templates/otel-collector-vllm-sidecar.yaml (lines 38-74)
config:
  exporters:
    debug: {}
    otlphttp:
      # all sidecars can export to the central otel-collector, then be
      # exported to various backends from there (in-cluster, external 3rd party)
      endpoint: {{ include "otel-collector.centralCollectorEndpoint" . }}
      tls:
        insecure: true
  receivers:
    otlp:
      protocols:
        grpc: {}
        http: {}
    prometheus:
      config:
        scrape_configs:
          - job_name: vllm-sidecar
            scrape_interval: 15s
            static_configs:
              - targets:
                  - 'localhost:8000'
  service:
    pipelines:
      traces:
        exporters: [debug, otlphttp]
        receivers: [otlp]
      metrics:
        exporters: [debug, otlphttp]
        receivers: [prometheus, otlp]
```

### Central Collector Trace Export to Tempo

The central collector authenticates to the Tempo gateway using a Kubernetes service account bearer token and routes traces via the multitenant API path (`/api/traces/v1/dev`).

```yaml
# helm/02-observability/otel-collector/values.yaml (lines 109-121)
exporters:
  debug:
    verbosity: basic
  otlphttp/dev:
    endpoint: "https://tempo-tempostack-gateway.observability-hub.svc.cluster.local:8080/api/traces/v1/dev"
    headers:
      X-Scope-OrgID: dev
    tls:
      insecure: false
      ca_file: /var/run/secrets/kubernetes.io/serviceaccount/service-ca.crt
    auth:
      authenticator: bearertokenauth
```

The bearer token auth extension reads the service account token:

```yaml
# helm/02-observability/otel-collector/values.yaml (lines 105-107)
extensions:
  bearertokenauth:
    filename: "/var/run/secrets/kubernetes.io/serviceaccount/token"
```

### Grafana Datasource Wiring

Grafana connects to both Prometheus (via Thanos Querier) and Tempo as datasources, using the Grafana Operator's `GrafanaDatasource` CR. Both use service account token auth.

```yaml
# helm/02-observability/grafana/values.yaml (lines 7-16)
datasources:
  prometheus:
    enabled: true
    url: "https://thanos-querier.openshift-monitoring.svc.cluster.local:9091"
    isDefault: true
  tempo:
    enabled: true
    url: "https://tempo-tempostack-gateway.observability-hub.svc.cluster.local:8081/api/traces/v1/dev/tempo"
    isDefault: false
```

### User Workload Monitoring PodMonitors

PodMonitors scrape vLLM metrics directly from KServe InferenceService pods. Two monitors cover different selector strategies: one uses `matchLabels` with the KServe pod label, the other uses `matchExpressions` for broader model server coverage.

```yaml
# helm/02-observability/uwm/values.yaml (lines 101-118)
vllmMetricsMonitor:
  enabled: true
  name: vllm-metrics
  podMetricsEndpoints:
    - interval: 15s
      path: /metrics
      port: h2c
  selector:
    matchLabels:
      app: isvc.llama3-2-3b-predictor

vllmLlamaServeMonitor:
  enabled: true
  name: vllm-llama-serve-monitor
  podMetricsEndpoints:
    - interval: 30s
      path: /metrics
  selector:
    matchExpressions:
      - key: app
        operator: In
        values: [safety, llama32-3b, granite-8b, llama31-70b]
```

### Custom vLLM Image for CPU with OpenTelemetry Packages

For CPU (Xeon) deployments, vLLM's base image lacks OpenTelemetry support. An OpenShift BuildConfig builds a custom image that adds the required OTel packages on top of the CPU vLLM image.

```yaml
# helm/vllm-xeon-opentelemetry-build-config.yaml (lines 8-29)
spec:
  source:
    dockerfile: |
      FROM docker.io/opea/vllm-cpu-ubi:v0.14.1-ubi9
      USER 0
      RUN pip install \
          "opentelemetry-sdk>=1.26.0,<1.27.0" \
          "opentelemetry-api>=1.26.0,<1.27.0" \
          "opentelemetry-exporter-otlp>=1.26.0,<1.27.0" \
          "opentelemetry-semantic-conventions-ai>=0.4.1,<0.5.0"
      USER 1001
  output:
    to:
      kind: ImageStreamTag
      name: vllm-xeon-opentelemetry:v0.14.1-ubi9
```

## Prompt / Chain Patterns

The observability pipeline itself has no prompt logic. It instruments the inference path transparently. Traces capture:
- vLLM request lifecycle spans (request received, prompt processing, token generation, response streaming)
- Llama Stack agent spans (inference calls to vLLM, tool execution, safety shield checks)
- Detailed per-request metrics (time-to-first-token, inter-token latency, KV cache utilization)

## Gotchas

- The vLLM GPU image (`quay.io/rcarrata/vllm-otlp-tracing`) already includes OpenTelemetry packages, but the CPU image (`docker.io/opea/vllm-cpu-ubi:v0.14.1-ubi9`) does not. CPU deployments require building the custom `vllm-xeon-opentelemetry` image via the BuildConfig in `helm/vllm-xeon-opentelemetry-build-config.yaml`.
- The central OTel collector's RBAC requires a ClusterRole with `create` verb on `tempo.grafana.com/dev` resources (for trace writing) plus `get/watch/list` on pods, namespaces, and replicasets (for the k8sattributes processor). See `helm/02-observability/otel-collector/values.yaml` lines 33-49.
- TempoStack's MinIO backend uses hardcoded test credentials (`admin`/`minio123`) in `helm/02-observability/tempo/values.yaml` lines 58-60. These must be changed for production deployments.
- Grafana datasources authenticate to Thanos Querier and Tempo using a service account token stored in a Secret (`grafana-sa-token`). The token is injected via `valuesFrom.secretKeyRef` in the `GrafanaDatasource` CR (`helm/02-observability/grafana/templates/datasources.yaml` lines 28-32).
- The Llama Stack sidecar collector only handles traces (no metrics pipeline), while the vLLM sidecar handles both traces and metrics. This asymmetry exists because Llama Stack sends metrics directly to the central collector via HTTP, while vLLM exposes metrics only via Prometheus scrape endpoint.
- User Workload Monitoring requires enabling `enableUserWorkload: true` in the `cluster-monitoring-config` ConfigMap in `openshift-monitoring` namespace (`helm/02-observability/uwm/templates/cluster-monitoring-config.yaml`). This is a cluster-wide setting.

## Related Architectures

- [model-serving-gateway](model-serving-gateway.md) -- The vLLM InferenceService being instrumented uses the KServe model serving gateway pattern
- [agent-orchestration](agent-orchestration.md) -- Llama Stack agent operations (tool calls, inference, safety checks) are traced through this pipeline
- [guardrails-layer](guardrails-layer.md) -- Llama Guard safety model traces flow through the same observability pipeline
