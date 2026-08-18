---
name: helm-llamastack-crd-mcp-remote-providers
description: LlamaStackDistribution CRD deployed via Helm with ConfigMap run.yaml wiring remote vLLM and MCP providers
summary: "Deploys a Llama Stack agent orchestration layer on OpenShift via the LlamaStackDistribution CRD (Llama Stack Operator), using a Helm chart that generates the CR, a run.yaml ConfigMap wiring five provider types (remote::vllm inference, inline::meta-reference agents, inline::llama-guard safety, vector I/O, remote::model-context-protocol tool_runtime), and an optional vLLM API key Secret. Use Approach A (data-governance-co-pilot) for minimal setup with inline FAISS, single remote MCP server, operator-provided storage, and distribution.name: rh-dev; use Approach B (lls-observability) when needing inline Milvus vector storage, multiple MCP servers via mcpServers values list generating tool_groups entries, OTel telemetry sinks (traces + metrics to central collector), dedicated vLLM safety endpoint, inline::sentence-transformers embeddings, chart-defined 5Gi PVC, custom distribution.image, and optional MaaS provider -- deploy either when PROVIDER_MODE=llama_stack. Environment variables INFERENCE_MODEL (must prefix model with \"vllm-inference/\" for provider ID), VLLM_URL (defaults via _helpers.tpl to https://<model>-predictor.<ns>.svc.cluster.local:8443/v1), and VLLM_API_TOKEN are set on the CR's containerSpec and referenced as ${env.VARIABLE} in run.yaml; MCP endpoint resolves via helper to http://<service>.<ns>.svc.cluster.local:<port>/sse and distribution.imageName must match run.yaml image_name. MCP endpoint hardcodes /sse because Llama Stack only supports SSE transport (not streamable-http), VLLM_TLS_VERIFY must be \"false\" for self-signed cluster certs, the operator checks DeploymentReady condition (not pod readiness) via oc wait --for=jsonpath, and Approach A uses operator-provided kv_sqlite/sql_sqlite at /opt/app-root/src/.llama/distributions/rh/ while Approach B uses a chart-defined PVC with inline Milvus backed by SQLite kvstore."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, llama-stack, vllm]
  ai_pattern: [agents, model-serving]
  platform: [openshift, rhoai]
source_examples:
  - quickstart: "data-governance-co-pilot"
    repo: "https://github.com/rh-ai-quickstart/data-governance-co-pilot"
    notes: "LlamaStackDistribution CRD with run.yaml ConfigMap wiring remote vLLM inference and remote MCP tool_runtime"
    approach: "A"
  - quickstart: "lls-observability"
    repo: "https://github.com/rh-ai-kickstart/llama-stack-observability"
    notes: "Operator-managed LlamaStackDistribution with inline Milvus, 3 MCP servers, OTel telemetry, safety model, sentence-transformers, chart-defined PVC, and OTel sidecar"
    approach: "B"
---

# Llama Stack Distribution CRD with Remote MCP and vLLM Providers

## Overview

This pattern deploys a Llama Stack agent orchestration layer via the `LlamaStackDistribution` Custom Resource (managed by the Llama Stack Operator), configured through a Helm chart that generates a `run.yaml` ConfigMap. The run.yaml wires five provider types: remote vLLM for inference, inline meta-reference for agents, inline llama-guard for safety, inline FAISS for vector I/O, and remote MCP for tool runtime. This enables an alternative agent orchestration mode alongside direct MCP tool calling.

## Pattern Description

The Helm chart creates three resources: a LlamaStackDistribution CR (the operator's primary resource), a ConfigMap containing the full `run.yaml` provider configuration, and an optional Secret for the vLLM API key. The operator manages the lifecycle of the Llama Stack pod, which acts as a lightweight proxy routing inference to vLLM and tool calls to the MCP server. Environment variables for model name, vLLM URL, and API token are set on the CR's containerSpec and referenced as `${env.VARIABLE}` in the run.yaml.

## Implementation

### LlamaStackDistribution CR

```yaml
# helm/copilot-llama-stack/templates/llamastackdistribution.yaml
apiVersion: llamastack.io/v1alpha1
kind: LlamaStackDistribution
metadata:
  name: {{ .Values.distribution.name }}
spec:
  replicas: {{ .Values.distribution.replicas }}
  server:
    distribution:
      name: {{ .Values.distribution.imageName | quote }}
    userConfig:
      configMapName: {{ .Values.distribution.name }}-config
    containerSpec:
      name: {{ .Values.container.name }}
      port: {{ .Values.container.port }}
      resources:
        {{- toYaml .Values.container.resources | nindent 8 }}
      env:
        - name: INFERENCE_MODEL
          value: {{ printf "vllm-inference/%s" .Values.model.name | quote }}
        - name: VLLM_URL
          value: {{ include "copilot-llama-stack.vllmUrl" . | quote }}
        - name: VLLM_API_TOKEN
          valueFrom:
            secretKeyRef:
              name: {{ .Values.distribution.name }}-api-key
              key: api_key
        - name: VLLM_TLS_VERIFY
          value: 'false'
```

### run.yaml ConfigMap with Provider Wiring

```yaml
# helm/copilot-llama-stack/templates/configmap.yaml (run.yaml data)
providers:
  inference:
    - provider_id: vllm-inference
      provider_type: remote::vllm
      config:
        url: ${env.VLLM_URL}
        api_token: ${env.VLLM_API_TOKEN}
        model: ${env.INFERENCE_MODEL}
  agents:
    - provider_id: meta-agents
      provider_type: inline::meta-reference
      config:
        inference_model: ${env.INFERENCE_MODEL}
  safety:
    - provider_id: llama-guard
      provider_type: inline::llama-guard
      config: {}
  tool_runtime:
    - provider_id: mcp-tools
      provider_type: remote::model-context-protocol
      config:
        mcp_endpoint:
          uri: {{ include "copilot-llama-stack.mcpEndpoint" . }}
```

### MCP Endpoint URI Helper

The MCP endpoint uses the fully-qualified cluster DNS name with SSE transport:

```go
# helm/copilot-llama-stack/templates/_helpers.tpl
{{- define "copilot-llama-stack.mcpEndpoint" -}}
{{- printf "http://%s.%s.svc.cluster.local:%d/sse"
    .Values.mcp.serviceName .Release.Namespace (.Values.mcp.port | int) }}
{{- end }}
```

### vLLM URL Fallback Helper

```go
# helm/copilot-llama-stack/templates/_helpers.tpl
{{- define "copilot-llama-stack.vllmUrl" -}}
{{- if .Values.model.url }}
{{- .Values.model.url }}
{{- else }}
{{- printf "https://%s-predictor.%s.svc.cluster.local:8443/v1"
    .Values.model.name .Release.Namespace }}
{{- end }}
{{- end }}
```

## Configuration

- **Key settings:** `distribution.imageName` (must match run.yaml `image_name`, default `rh-dev`), `container.port` (default 8321), `mcp.serviceName` (default `pg-airman-mcp-service`), `mcp.port` (default 8000)
- **Defaults:** Resources set to 500m CPU / 512Mi memory limits; replicas: 1; model values are empty placeholders populated by the Makefile at deploy time
- **Dependencies:** Requires the Llama Stack Operator to be installed on the cluster (provides the `llamastack.io/v1alpha1` CRD); the MCP server must be deployed with SSE transport (not streamable-http) when using Llama Stack mode

## Gotchas

- The model name is prefixed with `vllm-inference/` in the INFERENCE_MODEL env var (e.g., `vllm-inference/qwen3-14b`) because Llama Stack requires the provider ID prefix in model references (see `helm/copilot-llama-stack/templates/llamastackdistribution.yaml`)
- `VLLM_TLS_VERIFY` is set to `false` because the vLLM service uses self-signed certificates within the cluster (see `helm/copilot-llama-stack/templates/llamastackdistribution.yaml`)
- The MCP endpoint hardcodes `/sse` path because Llama Stack's MCP client only supports SSE transport, not streamable-http -- this requires the pg-airman-mcp chart to be deployed with `mcp.transport=sse` (see `helm/copilot-llama-stack/templates/_helpers.tpl`)
- The operator waits for `DeploymentReady` condition on the CR, not pod readiness -- the Makefile checks this with `oc wait --for=jsonpath='{.status.conditions[?(@.type=="DeploymentReady")].status}=True'` (see `helm/Makefile` lines 754-756)
- Storage uses `kv_sqlite` and `sql_sqlite` backends at `/opt/app-root/src/.llama/distributions/rh/` which is an operator-provided volume mount, not a PVC defined by the chart (see `helm/copilot-llama-stack/values.yaml`)

## Related Patterns

- `mcp-service-session-affinity-transport-toggle.md` -- the MCP server that Llama Stack connects to as a tool runtime
- `makefile-feature-flag-conditional-deploy-model-extract.md` -- the Makefile that conditionally deploys Llama Stack when PROVIDER_MODE=llama_stack

---

## Approach B: Operator-Managed LlamaStackDistribution with Inline Milvus, Multiple MCP Servers, and OTel Telemetry (from lls-observability)

### When to Use

When the Llama Stack Operator is deployed on the cluster (not just using the CRD directly), the distribution needs inline Milvus for vector storage, multiple MCP servers for diverse tool capabilities, OTel-based telemetry for distributed tracing, and a safety model for content guardrailing.

### Differences from Approach A

- The Llama Stack Operator manages the pod lifecycle (Approach A templates the CRD only, operator manages deployment)
- Uses `distribution.image` with a custom image reference instead of `distribution.name: rh-dev` for distro resolution
- Full provider suite: remote::vllm inference + vllm-safety, inline::sentence-transformers embeddings, inline::milvus vector_io, inline::llama-guard safety, inline::meta-reference agents/eval, remote::model-context-protocol for 3 MCP servers, inline telemetry with OTel sinks
- Chart deploys its own PVC (`llama-stack-persist`) for persistence rather than relying on operator-provided storage
- An OTel collector sidecar CR is templated directly in the chart for trace collection
- MCP servers are configured via a `mcpServers` values list that generates `tool_groups` entries with `/sse` endpoint suffix
- Includes optional MaaS (Model as a Service) provider for cloud-hosted inference

### LlamaStackDistribution with OTel Environment

```yaml
# helm/03-ai-services/llama-stack-instance/templates/llamastackdistribution.yaml
spec:
  replicas: 1
  server:
    containerSpec:
      env:
        - name: OTEL_SERVICE_NAME
          value: llamastack
        - name: TELEMETRY_SINKS
          value: 'console, sqlite, otel_trace, otel_metric'
        - name: OTEL_TRACE_ENDPOINT
          value: http://otel-collector-collector.observability-hub.svc.cluster.local:4318/v1/traces
        - name: OTEL_METRIC_ENDPOINT
          value: http://otel-collector-collector.observability-hub.svc.cluster.local:4318/v1/metrics
    distribution:
      image: "quay.io/rhoai-genaiops/llama-stack-vllm-milvus:0.2.11"
    userConfig:
      configMapName: llama-stack-config
```

### Multiple MCP Servers in run.yaml

```yaml
# helm/03-ai-services/llama-stack-instance/values.yaml
mcpServers:
  - name: "weather"
    uri: "http://mcp-weather.llama-serve.svc.cluster.local:80"
  - name: "hr-api-tools"
    uri: "http://hr-enterprise-api.llama-serve.svc.cluster.local:80"
  - name: "openshift"
    uri: "http://ocp-mcp-server.llama-serve.svc.cluster.local:8000"
```

These generate tool_groups entries in the ConfigMap:

```yaml
# helm/03-ai-services/llama-stack-instance/templates/configmap.yaml (generated)
tool_groups:
{{- range .Values.mcpServers }}
- toolgroup_id: mcp::{{ .name }}
  provider_id: model-context-protocol
  mcp_endpoint:
    uri: {{ .uri }}{{ if or (eq .name "weather") (eq .name "hr-api-tools") (eq .name "openshift") }}/sse{{ end }}
{{- end }}
```

### Inline Milvus Vector Store

```yaml
# helm/03-ai-services/llama-stack-instance/templates/configmap.yaml (run.yaml excerpt)
vector_io:
- provider_id: milvus
  provider_type: inline::milvus
  config:
    db_path: ${env.MILVUS_DB_PATH:=~/.llama/distributions/remote-vllm/milvus_store.db}
    kvstore:
      type: sqlite
      db_path: ${env.SQLITE_STORE_DIR:=~/.llama/distributions/remote-vllm}/milvus_registry.db
```

### Chart-Defined PVC and OTel Sidecar

```yaml
# helm/03-ai-services/llama-stack-instance/templates/pvc.yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: llama-stack-persist
spec:
  accessModes: [ReadWriteOnce]
  resources:
    requests:
      storage: 5Gi
```

---

## Choosing Between Approaches

| Criteria | Approach A | Approach B |
|----------|-----------|-----------|
| Operator management | CRD templated, operator manages pod | Operator-managed CRD + full lifecycle |
| Vector storage | Inline FAISS | Inline Milvus with SQLite kvstore |
| MCP servers | 1 server (pg-airman-mcp) | 3 servers (weather, HR API, OpenShift) via values list |
| Telemetry | Not configured | OTel traces + metrics via env vars to central collector |
| Safety model | inline::llama-guard (no dedicated vLLM) | Dedicated vLLM safety endpoint (llama-guard-3-1b-predictor) |
| Embeddings | Not configured | inline::sentence-transformers (all-MiniLM-L6-v2) |
| Storage | Operator-provided paths | Chart-defined 5Gi PVC |
| Distribution image | `distribution.name: rh-dev` | `distribution.image: quay.io/rhoai-genaiops/llama-stack-vllm-milvus:0.2.11` |
| MaaS support | Not available | Optional remote MaaS provider toggle |
