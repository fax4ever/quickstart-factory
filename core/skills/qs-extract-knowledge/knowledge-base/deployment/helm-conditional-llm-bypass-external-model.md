---
name: helm-conditional-llm-bypass-external-model
description: Helm conditional that skips local vLLM InferenceService deployment when external model endpoint is configured
summary: "Enables a single Helm chart to deploy either a local GPU-bound vLLM Llama 3.2 3B Instruct InferenceService or bypass it entirely for an external Model-as-a-Service (MaaS) endpoint, allowing the same chart to work on clusters with and without GPU nodes. Use when the quickstart needs optional GPU independence -- the entire LLM template (ServingRuntime + InferenceService) is gated by {{ if not .Values.model }}; default model: {} deploys local vLLM on KServe with quay.io/modh/vllm:rhoai-2.19-cuda and OCI modelcar storage, while populating any model sub-key (name, endpoint, port, api_key) skips local deployment and wires the orchestrator ConfigMap to the external endpoint. The orchestrator defaults hostname to llama-32-predictor and port to 8080 via Helm | default, the application references the API key from a Secret defaulting to \"fake\" for local mode, and VLLM_MODEL resolves via {{ .Values.model.name | default \"llama32\" }}. Critical gotcha: model: {} (commented-out sub-keys) is falsy and deploys local LLM, but setting any sub-key makes the object truthy and skips deployment; model.name must match the served-model-name expected by the external MaaS endpoint or inference calls will fail."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, vllm]
  ai_pattern: [model-serving]
  platform: [kserve, rhoai, openshift]
source_examples:
  - quickstart: "lemonade-stand-assistant"
    repo: "https://github.com/rh-ai-quickstart/lemonade-stand-assistant"
    notes: "Wraps entire LLM template in {{ if not .Values.model }} to skip local vLLM when external MaaS endpoint is provided"
    approach: "A"
---

# Conditional LLM Bypass for External Model Endpoint

## Overview

This pattern uses a Helm conditional to optionally skip deploying a local GPU-bound LLM (vLLM on KServe) when the user provides an external Model-as-a-Service (MaaS) endpoint. This allows the same chart to work on clusters with and without GPU nodes, switching between a self-hosted LLM and an external API by toggling a single values key.

## Pattern Description

The entire LLM template file (ServingRuntime + InferenceService) is wrapped in `{{ if not .Values.model }}...{{- end }}`. When the `model` values key is empty (the default), the local vLLM-based Llama 3.2 InferenceService is deployed requiring a GPU. When the user provides `model.name`, `model.endpoint`, and optionally `model.port` and `model.api_key`, the local LLM is skipped entirely. The orchestrator ConfigMap references the model endpoint dynamically, defaulting to the local KServe predictor hostname.

## Implementation

### Conditional LLM Template

The entire LLM template (both ServingRuntime and InferenceService) is gated on the absence of the `model` values key:

```yaml
# chart/templates/llm-llama32.yaml
{{ if not .Values.model }}
---
apiVersion: serving.kserve.io/v1alpha1
kind: ServingRuntime
metadata:
  name: llama-32
spec:
  containers:
    - args:
        - '--dtype=half'
        - '--gpu-memory-utilization=0.95'
        - '--enable-chunked-prefill'
        - '--port=8080'
        - '--model=/mnt/models'
        - '--served-model-name=llama32'
      image: 'quay.io/modh/vllm:rhoai-2.19-cuda'
      name: kserve-container
---
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  name: llama-32
spec:
  predictor:
    model:
      resources:
        limits:
          nvidia.com/gpu: '1'
      runtime: llama-32
      storageUri: 'oci://quay.io/redhat-ai-services/modelcar-catalog:llama-3.2-3b-instruct'
{{- end }}
```

### Dynamic Orchestrator Endpoint

The orchestrator ConfigMap uses defaults that point to the local KServe predictor when no external model is configured:

```yaml
# chart/templates/fms-orchestr8-config-nlp.yaml
data:
  config.yaml: |
    openai:
      service:
        hostname: {{ .Values.model.endpoint | default "llama-32-predictor" }}
        port: {{ .Values.model.port | default "8080" }}
```

### Values Structure

The `model` key defaults to an empty object, which is falsy for the `{{ if not .Values.model }}` check:

```yaml
# chart/values.yaml
model: {}
  # name: my-model
  # endpoint: my-maas-instance
  # port: 443
  # api_key: my-api-key
```

### Application Secret for API Key

The application deployment references the API key from a Secret, defaulting to `"fake"` for the local model:

```yaml
# chart/templates/lemonade-stand-app.yaml
- name: VLLM_API_KEY
  valueFrom:
    secretKeyRef:
      name: lemonade-stand-secrets
      key: vllm-api-key
      optional: true
---
# In the same file:
apiVersion: v1
kind: Secret
metadata:
  name: lemonade-stand-secrets
stringData:
  vllm-api-key: {{ .Values.model.api_key | default "fake" }}
```

## Configuration

- **Key settings:** `model` (empty object `{}` by default) -- when populated with `name`, `endpoint`, `port`, `api_key`, the local LLM is skipped; orchestrator endpoint defaults to `llama-32-predictor` (local KServe); model port defaults to `8080` (local) vs `443` (typical external MaaS)
- **Defaults:** With default values, deploys local Llama 3.2 3B Instruct via vLLM requiring 1 GPU with 20Gi memory; the API key defaults to `"fake"` string
- **Dependencies:** Local mode requires 1 NVIDIA GPU and access to `oci://quay.io/redhat-ai-services/modelcar-catalog` for model weights; external mode requires network connectivity to the MaaS endpoint

## Gotchas

- The `{{ if not .Values.model }}` conditional tests the truthiness of the entire `model` object -- setting `model: {}` (commented-out sub-keys as in the default) evaluates as falsy, deploying the local LLM; setting any sub-key (e.g., `model.name: foo`) makes the object truthy, skipping local deployment (see `chart/templates/llm-llama32.yaml` line 1)
- The orchestrator config uses `| default "llama-32-predictor"` for the hostname, but KServe creates the predictor service as `llama-32-predictor` only when the InferenceService `llama-32` is deployed -- if the user sets `model.endpoint` without setting `model.name`, the local LLM is still skipped but the orchestrator correctly uses the provided endpoint (see `chart/templates/fms-orchestr8-config-nlp.yaml`)
- The application deployment's `VLLM_MODEL` env var defaults to `llama32` (the `--served-model-name` from the local vLLM) via `{{ .Values.model.name | default "llama32" }}`, which must match the model name expected by the external endpoint when using MaaS (see `chart/templates/lemonade-stand-app.yaml`)

## Related Patterns

- `helm-trustyai-orchestrator-configmap-detector-wiring.md` -- the orchestrator ConfigMap that references the model endpoint
- `kserve-rawdeployment-detector-fleet-gpu-toggle.md` -- the detector InferenceServices that work alongside this conditional LLM
