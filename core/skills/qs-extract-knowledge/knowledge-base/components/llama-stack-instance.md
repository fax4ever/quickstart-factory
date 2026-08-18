---
name: llama-stack-instance
description: "Helm chart deploying a LlamaStackDistribution CRD with OTel sidecar, inline Milvus, MCP servers, and MaaS support"
summary: "Deploys an operator-managed LlamaStackDistribution CRD (port 8321) with OTel Collector sidecar for observability-focused LlamaStack on OpenShift AI, wiring dual KServe-backed vLLM providers (inference + Llama Guard safety), inline sentence-transformers embeddings, inline Milvus vector I/O, configurable MCP servers, and optional MaaS remote model. Use as phase 3 in a multi-phase observability stack (after operators and observability infrastructure) when telemetry is a first-class concern and you need a single Helm chart to configure the full LlamaStack provider graph via run.yaml ConfigMap with ${env.VAR:=default} substitution alongside hardcoded CRD env vars. Critical config: custom image quay.io/rhoai-genaiops/llama-stack-vllm-milvus:0.2.11 bundles vLLM+Milvus; MCP servers defined as a values list iterated in the ConfigMap template with /sse suffix conditionally appended; ReadWriteOnce PVC (default 5Gi) persists Milvus DB, SQLite registries, and trace store. Gotchas: OTel endpoint hardcoded to observability-hub namespace requiring template edits, MCP /sse suffix uses hardcoded name checks instead of a per-server flag, VLLM_API_TOKEN defaults to \"fake\", distribution.name has no default causing empty CRD field if omitted, and CRD env vars duplicate ConfigMap defaults requiring synchronized updates."
metadata:
  type: component
tags:
  tech_stack: [llamastack, vllm, helm, milvus, opentelemetry, sentence-transformers, python]
  ai_pattern: [agents, model-serving, rag, vector-search, mcp, embeddings, guardrails, evaluation]
  platform: [openshift, rhoai, kserve]
  data_layer: [milvus, sqlite]
source_examples:
  - quickstart: "lls-observability"
    repo: "https://github.com/rh-ai-quickstart/lls-observability"
    notes: "Standalone Helm chart deploying LlamaStackDistribution CRD with OTel collector sidecar for observability, inline Milvus vector DB, MCP server wiring, and optional MaaS provider"
    approach: "A"
---

# Llama Stack Instance

## Overview

Llama Stack Instance is a standalone Helm chart that deploys a `LlamaStackDistribution` custom resource (managed by the Llama Stack Kubernetes operator) alongside an OpenTelemetry Collector sidecar for distributed tracing and metrics export. It provides a complete, operator-managed LlamaStack deployment with inline Milvus for vector I/O, configurable MCP server endpoints, optional MaaS provider integration, and a PVC for persistent storage. This chart is designed for observability-focused deployments on OpenShift AI where telemetry is a first-class concern.

## Tech Stack & Dependencies

- **Runtime:** LlamaStack distribution server v0.3.0 (appVersion)
- **Container image:** `quay.io/rhoai-genaiops/llama-stack-vllm-milvus:0.2.11`
- **Key dependencies:** Llama Stack Kubernetes operator (pre-installed), vLLM model server via KServe (for inference), Llama Guard via KServe (for safety), MCP servers (weather, HR API, OpenShift), OpenTelemetry operator (for collector sidecar)
- **Helm subchart:** None (standalone chart at `helm/03-ai-services/llama-stack-instance/`)

## Key Patterns

### LlamaStackDistribution CRD with Hardcoded OTel Environment

The chart creates a `LlamaStackDistribution` custom resource with environment variables hardcoded in the template for telemetry sink configuration. Unlike the data-governance-co-pilot approach where env vars use `${env.VAR}` runtime substitution, this chart sets explicit values for all OTel endpoints and model URLs directly in the CRD spec.

```yaml
# templates/llamastackdistribution.yaml
apiVersion: llamastack.io/v1alpha1
kind: LlamaStackDistribution
spec:
  replicas: {{ .Values.llamaStackDistribution.replicas }}
  server:
    containerSpec:
      env:
        - name: TELEMETRY_SINKS
          value: 'console, sqlite, otel_trace, otel_metric'
        - name: OTEL_TRACE_ENDPOINT
          value: http://otel-collector-collector.observability-hub.svc.cluster.local:4318/v1/traces
        - name: OTEL_METRIC_ENDPOINT
          value: http://otel-collector-collector.observability-hub.svc.cluster.local:4318/v1/metrics
    distribution:
      name: {{ .Values.llamaStackDistribution.server.distribution.name }}
    userConfig:
      configMapName: llama-stack-config
```

### OpenTelemetry Collector Sidecar

The chart deploys an `OpenTelemetryCollector` CR in sidecar mode. Any pod annotated with `sidecar.opentelemetry.io/inject: llamastack-otelsidecar` will automatically get a collector sidecar injected. The sidecar forwards traces to a central observability hub collector via OTLP HTTP.

```yaml
# templates/otel-collector-sidecar.yaml
apiVersion: opentelemetry.io/v1beta1
kind: OpenTelemetryCollector
metadata:
  name: {{ .Values.otelCollector.name | default "llamastack-otelsidecar" }}
spec:
  mode: {{ .Values.otelCollector.mode | default "sidecar" }}
  config:
    exporters:
      otlphttp:
        endpoint: {{ .Values.otelCollector.exporter.endpoint | quote }}
        tls:
          insecure: {{ .Values.otelCollector.exporter.tls.insecure }}
    receivers:
      otlp:
        protocols:
          grpc: {}
          http: {}
    service:
      pipelines:
        traces:
          exporters:
            - debug
            - otlphttp
          receivers:
            - otlp
```

### Comprehensive Run Config via ConfigMap

The chart generates a `run.yaml` ConfigMap that declares all LlamaStack API providers. The config wires multiple inference providers (vLLM for inference, vLLM for safety, inline sentence-transformers for embeddings), inline Milvus for vector I/O, and a full set of tool runtime providers (Brave Search, Tavily, RAG runtime, MCP, Wolfram Alpha).

```yaml
# templates/configmap.yaml (abbreviated)
providers:
  inference:
  - provider_id: vllm-inference
    provider_type: remote::vllm
    config:
      url: {{ .Values.llamaStackDistribution.vllmUrl | default "http://llama3-2-3b-predictor/v1" | quote }}
  - provider_id: sentence-transformers
    provider_type: inline::sentence-transformers
    config: {}
  vector_io:
  - provider_id: milvus
    provider_type: inline::milvus
    config:
      db_path: ${env.MILVUS_DB_PATH:=~/.llama/distributions/remote-vllm/milvus_store.db}
```

### MCP Server Configuration via Helm Values

MCP servers are configured as a list in `values.yaml` and iterated in the ConfigMap template. Each MCP server is registered as a `mcp::<name>` tool group with the `model-context-protocol` provider. The `/sse` suffix is conditionally appended based on server name.

```yaml
# values.yaml
mcpServers:
  - name: "weather"
    uri: "http://mcp-weather.llama-serve.svc.cluster.local:80"
  - name: "hr-api-tools"
    uri: "http://hr-enterprise-api.llama-serve.svc.cluster.local:80"
  - name: "openshift"
    uri: "http://ocp-mcp-server.llama-serve.svc.cluster.local:8000"
```

```yaml
# templates/configmap.yaml
{{- range .Values.mcpServers }}
- toolgroup_id: mcp::{{ .name }}
  provider_id: model-context-protocol
  mcp_endpoint:
    uri: {{ .uri }}{{ if or (eq .name "weather") (eq .name "hr-api-tools") (eq .name "openshift") }}/sse{{ end }}
{{- end }}
```

### Optional MaaS Provider

The chart supports an optional Model-as-a-Service provider that adds a remote vLLM inference provider pointing to an external endpoint. When enabled, it registers an additional model and provider in the run config.

```yaml
# values.yaml
maas:
  enabled: false
  apiToken: "your_token"
  url: "https://litellm-litemaas.apps.prod.rhoai.rh-aiservices-bu.com/v1"
  maxTokens: 200000
  tlsVerify: false
  modelId: "Llama-4-Scout-17B-16E-W4A16"
```

### Persistent Volume for LlamaStack Storage

The chart creates a PVC (`llama-stack-persist`) with `ReadWriteOnce` access mode for persisting LlamaStack's internal storage (Milvus DB, SQLite registries, trace store). This differs from approaches using `emptyDir` or PostgreSQL-backed persistence.

```yaml
# templates/pvc.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: llama-stack-persist
  finalizers:
  - kubernetes.io/pvc-protection
spec:
  accessModes:
  - ReadWriteOnce
  resources:
    requests:
      storage: {{ .Values.llamaStack.storage.size }}
```

### Dual Inference + Safety Provider Pattern

The run config registers separate vLLM providers for inference and safety, each pointing to different KServe predictor endpoints. The safety provider uses Llama Guard with its own token limit and TLS settings.

```yaml
# templates/configmap.yaml
- provider_id: vllm-inference
  provider_type: remote::vllm
  config:
    url: {{ .Values.llamaStackDistribution.vllmUrl | default "http://llama3-2-3b-predictor/v1" | quote }}
    max_tokens: {{ .Values.llamaStackDistribution.vllmMaxTokens | default 60000 }}
- provider_id: vllm-safety
  provider_type: remote::vllm
  config:
    url: {{ .Values.llamaStackDistribution.safetyUrl | default "http://llama-guard-3-1b-predictor/v1" | quote }}
    max_tokens: {{ .Values.llamaStackDistribution.safetyMaxTokens | default 20000 }}
```

## Configuration

- **Environment variables (set in LlamaStackDistribution CRD):**
  - `OTEL_SERVICE_NAME` -- Service name for telemetry (default: `llamastack`)
  - `TELEMETRY_SINKS` -- Comma-separated sink list (`console, sqlite, otel_trace, otel_metric`)
  - `OTEL_TRACE_ENDPOINT` -- OTLP HTTP endpoint for traces (`http://otel-collector-collector.observability-hub.svc.cluster.local:4318/v1/traces`)
  - `OTEL_METRIC_ENDPOINT` -- OTLP HTTP endpoint for metrics (`http://otel-collector-collector.observability-hub.svc.cluster.local:4318/v1/metrics`)
  - `INFERENCE_MODEL` -- Model name for inference (default: `llama3-2-3b`)
  - `SAFETY_MODEL` -- Model name for safety shield (default: `meta-llama/Llama-Guard-3-1B`)
  - `VLLM_URL` -- vLLM inference endpoint URL
  - `VLLM_API_TOKEN` -- API token for vLLM (default: `fake`)
  - `VLLM_TLS_VERIFY` -- TLS verification for vLLM (default: `false`)
  - `MILVUS_DB_PATH` -- Path for inline Milvus database file
  - `SQLITE_STORE_DIR` -- Base directory for all SQLite databases
- **Config files:**
  - `llama-stack-config` ConfigMap -- Contains `run.yaml` with full provider/model/toolgroup configuration
- **Helm values:**
  - `llamaStackDistribution.server.distribution.image` -- Distribution container image (default: `quay.io/rhoai-genaiops/llama-stack-vllm-milvus:0.2.11`)
  - `llamaStackDistribution.replicas` -- Number of replicas (default: `1`)
  - `llamaStackDistribution.server.containerSpec.port` -- Server port (default: `8321`)
  - `mcpServers` -- List of MCP server endpoints with name and URI
  - `maas.enabled` -- Enable MaaS remote model provider (default: `false`)
  - `otelCollector.enabled` -- Enable OTel collector sidecar (default: `true`)
  - `otelCollector.exporter.endpoint` -- Central OTel collector endpoint
  - `llamaStack.storage.size` -- PVC size (default: `5Gi`)

## Known Gotchas

- The `llamastackdistribution.yaml` template hardcodes the OTel collector endpoint as `http://otel-collector-collector.observability-hub.svc.cluster.local:4318`. This assumes the observability hub is deployed in the `observability-hub` namespace. If deploying the observability stack in a different namespace, the template must be updated (see `templates/llamastackdistribution.yaml` lines 23-25).
- The MCP server `/sse` suffix is conditionally appended using a hardcoded name check (`if or (eq .name "weather") (eq .name "hr-api-tools") (eq .name "openshift")`). Adding a new MCP server that requires the SSE transport requires updating the template condition, rather than using a configurable flag per server (see `templates/configmap.yaml` line 171).
- The PVC uses `ReadWriteOnce` access mode, which limits this deployment to a single node. Multi-replica deployments across nodes would require switching to a shared storage class or PostgreSQL-backed persistence (see `templates/pvc.yaml`).
- The `pvc.yaml` metadata comment says "MinIO Persistent Volume Claim" but the PVC is actually used for LlamaStack's internal storage (Milvus, SQLite). This is a misleading comment carried over from another chart (see `templates/pvc.yaml` line 1).
- The distribution image `quay.io/rhoai-genaiops/llama-stack-vllm-milvus:0.2.11` is a custom build that bundles vLLM and Milvus support. The `values.yaml` also has a commented-out alternative image `quay.io/eformat/distribution-remote-vllm:0.2.15` (see `values.yaml` line 63-64).
- The `llamaStackDistribution.server.distribution.name` field in `values.yaml` is not set (no default), but the CRD template references it directly. The Helm install must provide this value or the LlamaStackDistribution CRD will have an empty distribution name (see `templates/llamastackdistribution.yaml` line 59).
- The `VLLM_API_TOKEN` defaults to `"fake"` in both the values and the CRD template. This is acceptable for in-cluster communication where KServe predictors do not require authentication, but should be overridden in production environments with external model endpoints.
- The `run.yaml` ConfigMap uses `${env.VAR:=default}` syntax for runtime variable substitution by LlamaStack, but the CRD template hardcodes the same values. This creates a duplication where changes in the CRD env vars must also be reflected in the ConfigMap defaults to stay consistent (see `templates/configmap.yaml` vs `templates/llamastackdistribution.yaml`).

## Testing Notes

- Verify the LlamaStackDistribution is reconciled by the operator: `oc get llamastackdistribution -n <namespace>`
- Check LlamaStack pod logs for provider initialization: `oc logs -l app.kubernetes.io/name=llama-stack-instance -n <namespace>`
- Verify the OTel collector sidecar is injected: check for a second container in the LlamaStack pod (`oc get pod -l app.kubernetes.io/name=llama-stack-instance -n <namespace> -o jsonpath='{.items[0].spec.containers[*].name}'`)
- Verify traces reach the observability hub: check the Grafana/Tempo UI for traces with service name `llamastack`
- Test MCP server connectivity: ensure MCP services (weather, HR API, OpenShift) are running in the same namespace before deploying LlamaStack
- The chart is deployed as phase 3 in the lls-observability stack -- phases 1 (operators) and 2 (observability infrastructure) must be deployed first

## Related Patterns

- Architecture: observability pipeline (OTel sidecar to central collector to tracing backend)
- Deployment: operator-managed CRD lifecycle with Helm chart
- Components: llamastack (general LlamaStack patterns), mcp-servers (MCP server deployment), observability-stack (Tempo/Grafana/OTel infrastructure)
