---
name: helm-llamastack-crd-mcp-remote-providers
description: LlamaStackDistribution CRD deployed via Helm with ConfigMap run.yaml wiring remote vLLM and MCP providers
summary: "Deploys a Llama Stack agent orchestration layer on OpenShift via the LlamaStackDistribution CRD (Llama Stack Operator), using a Helm chart that generates the CR, a run.yaml ConfigMap wiring five providers (remote::vllm inference, inline::meta-reference agents, inline::llama-guard safety, inline FAISS vector I/O, remote::model-context-protocol tool_runtime), and an optional vLLM API key Secret. Use when deploying Llama Stack as an alternative agent orchestration mode (PROVIDER_MODE=llama_stack) that routes inference to a remote vLLM endpoint and tool calls to a remote MCP server, rather than direct MCP tool calling. Environment variables INFERENCE_MODEL (must be prefixed with \"vllm-inference/\"), VLLM_URL (defaults via helper to https://<model>-predictor.<ns>.svc.cluster.local:8443/v1), and VLLM_API_TOKEN are set on the CR's containerSpec and referenced as ${env.VARIABLE} in run.yaml; MCP endpoint resolves to http://<service>.<ns>.svc.cluster.local:<port>/sse and distribution.imageName must match run.yaml image_name. MCP endpoint hardcodes /sse because Llama Stack only supports SSE transport (not streamable-http), VLLM_TLS_VERIFY must be \"false\" for self-signed cluster certs, the operator checks DeploymentReady condition (not pod readiness) via oc wait --for=jsonpath, and storage uses operator-provided kv_sqlite/sql_sqlite at /opt/app-root/src/.llama/distributions/rh/ rather than a chart-defined PVC."
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
