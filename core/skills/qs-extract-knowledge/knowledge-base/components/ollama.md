---
name: ollama
description: "Ollama local model server for dev environments, fronted by LlamaStack as inference provider"
summary: "Ollama (`ollama/ollama:latest`) serves as a model server in two approaches: Approach A (docker-compose, from ai-virtual-agent) runs behind LlamaStack as `remote::ollama` provider at `http://ollama:11434/v1` with dynamic `ProviderConfigOllama(url=...)` registration triggering ConfigMap updates and deployment restarts; Approach B (Helm StatefulSet, from peoplemesh) deploys on OpenShift with initContainer polling `until ollama list` before pulling from a configurable `values.yaml` model list (e.g., `granite4:3b`, `granite-embedding:30m`), 50Gi PVC at `/var/lib/ollama`, conditional GPU via `gpu.enabled`/`nvidia.com/gpu`, and direct OpenAI-compatible API with dummy key `\"ollama-no-key-needed\"`. Use Approach A for local dev needing a LlamaStack inference gateway with `DEFAULT_INFERENCE_MODEL` override and `LOCAL_DEV_ENV_MODE`; use Approach B for cluster deployment requiring non-root OpenShift compatibility, optional GPU acceleration, PVC persistence, or umbrella chart LLM mode switching (`ollama/vllm/external` via `peoplemesh.llm.mode` with `ollama.enabled` toggle). Critical patterns: Approach A's entrypoint runs `ollama serve & sleep 10; ollama run llama3.2:1b --keepalive 60m hi; wait` with healthcheck grepping `ollama list` (retries: 30, interval: 30s, ~15 min window) and models persisted via `ollama:/root/.ollama` volume; Approach B's initContainer polls API readiness then checks/pulls each model, serves via `http://ollama-service.<namespace>.svc.cluster.local:11434/v1`, and sets `QUARKUS_LANGCHAIN4J_OPENAI_TIMEOUT=240s` for CPU-based inference. Common gotchas: DEVELOPMENT.md references `llama3.2:3b-instruct-fp16` but config uses `llama3.2:1b`; Approach A's hardcoded `sleep 10` may fail on slow systems and without `--keepalive 60m` models unload after Ollama's 5-minute default; Approach B requires `OLLAMA_MODELS` and `HOME` env vars pointing to PVC path (`/var/lib/ollama`) since OpenShift runs non-root with `/root` not writable; GPU tolerations remain in pod spec even when `gpu.enabled=false` (harmless by design)."
metadata:
  type: component
tags:
  tech_stack: [ollama, llamastack, docker-compose, helm, granite]
  ai_pattern: [model-serving, embeddings]
  platform: [openshift, kubernetes]
  data_layer: []
source_examples:
  - quickstart: "ai-virtual-agent"
    repo: "https://github.com/rh-ai-quickstart/ai-virtual-agent"
    notes: "Ollama as local dev model server behind LlamaStack, with model preloading entrypoint"
    approach: "A"
  - quickstart: "peoplemesh"
    repo: "https://github.com/francescopace/peoplemesh"
    notes: "Ollama as Helm subchart StatefulSet on OpenShift with initContainer model pre-pulling, GPU toggle, and OpenAI-compatible API"
    approach: "B"
---

# Ollama

## Overview

Ollama serves as the local development model server in the ai-virtual-agent quickstart. It runs as a docker-compose service that auto-downloads and preloads a model on startup, then sits behind LlamaStack which exposes it as a `remote::ollama` inference provider. The backend never talks to Ollama directly -- all inference requests flow through LlamaStack.

## Tech Stack & Dependencies

- **Runtime:** `ollama/ollama:latest` container image
- **Container image:** `ollama/ollama:latest`
- **Key dependencies:** LlamaStack (consumes Ollama as an inference backend)
- **Helm subchart:** None (docker-compose only for local dev)

## Key Patterns

### Model Preloading via Custom Entrypoint

Ollama uses a custom bash entrypoint instead of the default to ensure the model is downloaded and loaded into memory before any dependent service starts. The entrypoint starts the server in the background, waits, then runs the model with a long keepalive to prevent unloading.

```yaml
# From deploy/local/compose.yaml
entrypoint:
  - bash
  - -c
  - "OLLAMA_DEBUG=1 ollama serve & sleep 10; ollama run llama3.2:1b --keepalive 60m hi; wait"
```

### Model-Based Healthcheck

Rather than checking if the HTTP port is open, the healthcheck verifies the target model is actually loaded by grepping `ollama list` output. This prevents dependent services from starting before the model download completes.

```yaml
# From deploy/local/compose.yaml
healthcheck:
  test: ["CMD-SHELL", "ollama list | grep -q llama3.2:1b"]
  interval: 30s
  timeout: 10s
  retries: 30
```

### LlamaStack Integration as Remote Provider

LlamaStack connects to Ollama using the `remote::ollama` provider type. The model is registered in LlamaStack's run config with matching model IDs.

```yaml
# From deploy/local/llamastack-run.yaml
providers:
  inference:
  - provider_id: ollama
    provider_type: remote::ollama
    config:
      base_url: http://ollama:11434/v1

registered_resources:
  models:
  - model_id: llama3.2:1b
    provider_model_id: llama3.2:1b
    provider_id: ollama
```

### Backend Model Name Prefix Convention

The backend references Ollama-hosted models with an `ollama/` prefix (e.g., `ollama/llama3.2:1b`). In local dev mode, the `DEFAULT_INFERENCE_MODEL` env var overrides template model names so agents work with the local Ollama model instead of production model names.

```python
# From backend/app/config.py
# Default inference model for local dev (e.g. Ollama model name).
# When set and LOCAL_DEV_ENV_MODE is true, template-initialized agents use
# this model instead of the template's production model name.
DEFAULT_INFERENCE_MODEL: Optional[str] = os.getenv("DEFAULT_INFERENCE_MODEL")
```

```yaml
# From deploy/local/compose.yaml - backend service environment
- DEFAULT_INFERENCE_MODEL=${DEFAULT_INFERENCE_MODEL:-ollama/llama3.2:1b}
```

### Dynamic Provider Registration

The backend supports runtime registration of new Ollama providers via a REST API. The `ProviderConfigOllama` schema requires only a URL field, and registration updates the LlamaStack ConfigMap and triggers a deployment restart on Kubernetes.

```python
# From backend/app/schemas/providers.py
class ProviderConfigOllama(BaseModel):
    """Configuration for Ollama provider."""
    url: str = Field(..., description="Ollama server URL (e.g., http://ollama:11434)")
```

## Configuration

- **Environment variables:**
  - `OLLAMA_PORT` -- host port mapping, defaults to `11434`
  - `OLLAMA_DEBUG=1` -- enabled in the entrypoint for verbose logging during startup
  - `DEFAULT_INFERENCE_MODEL` -- backend uses this to override template models in local dev (defaults to `ollama/llama3.2:1b`)
- **Config files:**
  - `deploy/local/llamastack-run.yaml` -- LlamaStack run config that registers Ollama as the inference provider
- **Volumes:**
  - `ollama:/root/.ollama` -- persists downloaded models between container restarts

## Known Gotchas

- The DEVELOPMENT.md references `llama3.2:3b-instruct-fp16` as the required model, but the compose.yaml entrypoint and LlamaStack config both use `llama3.2:1b`. The actual running configuration uses the 1b variant.
- The entrypoint uses a hardcoded `sleep 10` between starting the server and pulling the model. On slow systems or first-time downloads of large models, this may not be sufficient for the server to be fully ready.
- The `--keepalive 60m` flag in the entrypoint prevents Ollama from unloading the model from memory for 60 minutes. Without this, the model would unload after 5 minutes of inactivity (Ollama default), causing cold-start latency on subsequent requests.
- The healthcheck has `retries: 30` with `interval: 30s`, allowing up to 15 minutes for the initial model download to complete.

## Testing Notes

- Integration tests use `ollama/llama3.2:1b` as the model name when creating virtual agents and validating API endpoints.
- The test configuration checks for `required_models: ["ollama/llama3.2:1b"]` as a precondition before running endpoint tests.

## Related Patterns

- LlamaStack (the inference gateway that fronts Ollama)
- Provider management API (runtime registration of Ollama instances)

---

## Approach B: Helm StatefulSet with InitContainer Model Pre-Pulling (from peoplemesh)

### When to Use

Use this approach when deploying Ollama as a persistent model server on OpenShift/Kubernetes via Helm, with optional GPU acceleration, PVC-backed model storage, and direct OpenAI-compatible API access (no intermediary like LlamaStack).

### Differences from Approach A

- **Deployment method:** Helm subchart in an umbrella chart (conditional via `ollama.enabled`) vs docker-compose service
- **Model loading:** InitContainer starts Ollama in background, polls readiness via `until ollama list`, then checks/pulls each model from a configurable list -- vs custom entrypoint with hardcoded `sleep 10`
- **Storage:** PVC via StatefulSet `volumeClaimTemplates` (50Gi) mounted at `/var/lib/ollama` -- vs Docker named volume at `/root/.ollama`
- **Security:** Non-root compatible for OpenShift (sets `OLLAMA_MODELS` and `HOME` to writable PVC path) -- vs root-based `/root/.ollama`
- **Integration:** App connects directly to Ollama's OpenAI-compatible `/v1` endpoint -- vs routing through LlamaStack as `remote::ollama` provider
- **GPU:** Conditional `nvidia.com/gpu` resource requests via `gpu.enabled` flag with pre-configured GPU node tolerations

### Key Patterns

#### InitContainer Model Pre-Pulling

The StatefulSet uses an initContainer that starts Ollama in the background, waits for the API to be ready via a polling loop, then iterates over a configurable model list checking if each is already present before pulling.

```yaml
# From charts/ollama/templates/statefulset.yaml
initContainers:
  - name: pull-models
    image: {{ .Values.image.repository }}:{{ .Values.image.tag }}
    env:
      - name: OLLAMA_MODELS
        value: /var/lib/ollama/models
      - name: HOME
        value: /var/lib/ollama
    command:
      - /bin/sh
      - -c
      - |
        set -e
        /bin/ollama serve &
        until ollama list >/dev/null 2>&1; do
          sleep 2
        done
        {{- range .Values.models }}
        if ollama list | grep -q "{{ . }}"; then
          echo "Model {{ . }} already exists, skipping pull"
        else
          ollama pull {{ . }}
        fi
        {{- end }}
        kill $OLLAMA_PID
```

#### Conditional GPU Resource Requests

GPU resources are toggled via a single `gpu.enabled` boolean. When false, the pod runs CPU-only but still tolerates GPU node taints (harmless when GPU is not requested).

```yaml
# From charts/ollama/values.yaml
gpu:
  enabled: false
# ...
tolerations:
  - key: g5-gpu
    operator: Exists
    effect: NoSchedule
  - key: nvidia.com/gpu
    operator: Exists
    effect: NoSchedule
```

```yaml
# From charts/ollama/templates/statefulset.yaml (resource block)
resources:
  requests:
    cpu: {{ .Values.resources.requests.cpu }}
    memory: {{ .Values.resources.requests.memory }}
    {{- if .Values.gpu.enabled }}
    nvidia.com/gpu: "1"
    {{- end }}
```

#### OpenAI-Compatible Direct Access

The app connects to Ollama's built-in OpenAI-compatible endpoint with a dummy API key, avoiding the need for an intermediate gateway.

```yaml
# From charts/peoplemesh/templates/config-map.yaml
{{- if eq .Values.llm.mode "ollama" }}
OPENAI_BASE_URL: "http://{{ .Values.llm.ollama.serviceName }}.{{ .Release.Namespace }}.svc.cluster.local:{{ .Values.llm.ollama.port }}/v1"
LLM_MODEL: {{ .Values.llm.ollama.chatModel | quote }}
EMBEDDING_MODEL: {{ .Values.llm.ollama.embeddingModel | quote }}
QUARKUS_LANGCHAIN4J_OPENAI_TIMEOUT: "240s"
```

```yaml
# From charts/peoplemesh/templates/secrets.yaml
{{- if eq .Values.llm.mode "ollama" }}
OPENAI_API_KEY: "ollama-no-key-needed"
{{- end }}
```

#### Multi-Model Configuration via Values

Models to pre-pull are specified as a list in `values.yaml`, supporting both chat and embedding models with a single Ollama instance.

```yaml
# From charts/ollama/values.yaml
models:
  - granite4:3b            # Chat model
  - granite-embedding:30m  # Embedding model (384D)
```

#### PVC-Backed Persistence via StatefulSet

Uses `volumeClaimTemplates` for stable, pod-specific storage that survives pod restarts and reschedules.

```yaml
# From charts/ollama/templates/statefulset.yaml
volumeClaimTemplates:
  - metadata:
      name: ollama-data
    spec:
      accessModes: ["ReadWriteOnce"]
      resources:
        requests:
          storage: {{ .Values.persistence.size }}
```

### Configuration

- **Environment variables:**
  - `OLLAMA_MODELS=/var/lib/ollama/models` -- redirects model storage to writable PVC path (OpenShift non-root)
  - `HOME=/var/lib/ollama` -- Ollama config directory on writable PVC (OpenShift non-root)
  - `OPENAI_BASE_URL` -- app-side, points to `http://ollama-service.<namespace>.svc.cluster.local:11434/v1`
  - `OPENAI_API_KEY="ollama-no-key-needed"` -- dummy value when llm.mode is ollama
  - `QUARKUS_LANGCHAIN4J_OPENAI_TIMEOUT="240s"` -- extended timeout for CPU-based inference
- **Helm values:**
  - `ollama.enabled` -- toggle in umbrella chart to enable/disable the subchart
  - `ollama.gpu.enabled` -- enable GPU resource requests
  - `ollama.models` -- list of models to pre-pull
  - `ollama.persistence.size` -- PVC size (default 50Gi)
  - `ollama.resources` -- CPU/memory requests and limits
  - `peoplemesh.llm.mode` -- set to `"ollama"`, `"vllm"`, or `"external"` to select LLM backend

### Known Gotchas

- The `OLLAMA_MODELS` and `HOME` env vars must point to the PVC mount path (`/var/lib/ollama`), not the default `/root/.ollama`, because OpenShift runs containers as non-root and `/root` is not writable.
- GPU tolerations are always present in the pod spec even when `gpu.enabled=false`. This is by design -- they are harmless without a GPU resource request and allow the pod to schedule on GPU nodes if needed.
- The `QUARKUS_LANGCHAIN4J_OPENAI_TIMEOUT` is set to 240s for ollama mode because CPU-based inference can take 30-60s per request, and concurrent requests or complex queries need extra headroom.
- The umbrella chart supports swapping between `ollama`, `vllm`, and `external` LLM modes via `peoplemesh.llm.mode`. When switching from ollama to vllm, set `ollama.enabled=false` and `vllm.enabled=true`.

### Testing Notes

- Verify the initContainer completes model pulls by checking `oc logs ollama-0 -c pull-models`
- Confirm GPU allocation with `oc describe pod ollama-0 | grep nvidia.com/gpu`
- The pod name is `ollama-0` (StatefulSet ordinal naming)

---

## Choosing Between Approaches

| Criteria | Approach A (docker-compose + LlamaStack) | Approach B (Helm StatefulSet) |
|----------|------------------------------------------|-------------------------------|
| Deployment target | Local dev only (docker-compose) | OpenShift/Kubernetes cluster |
| Inference gateway | LlamaStack (`remote::ollama` provider) | Direct OpenAI-compatible API |
| Model loading | Custom entrypoint with `sleep 10` delay | InitContainer with API readiness polling |
| Storage | Docker named volume at `/root/.ollama` | PVC volumeClaimTemplate at `/var/lib/ollama` |
| Non-root support | No (uses `/root/.ollama`) | Yes (custom HOME/OLLAMA_MODELS paths) |
| GPU support | Not configured | Conditional via `gpu.enabled` with tolerations |
| Model list | Hardcoded in entrypoint | Configurable via `values.yaml` models list |
| LLM backend switching | N/A | Umbrella chart supports ollama/vllm/external modes |
