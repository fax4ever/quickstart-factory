---
name: ollama
description: "Ollama local model server for dev environments, fronted by LlamaStack as inference provider"
summary: "Ollama (`ollama/ollama:latest`) provides a local dev model server for docker-compose quickstarts, running behind LlamaStack as a `remote::ollama` inference provider at `http://ollama:11434/v1` with matching `registered_resources` model IDs — the backend never calls Ollama directly, all inference flows through LlamaStack. Use for local development (docker-compose only, no Helm subchart) when you need a self-contained model server that auto-downloads and preloads models on startup; dynamic provider registration via `ProviderConfigOllama(url=...)` REST API allows runtime addition of Ollama instances, triggering LlamaStack ConfigMap updates and Kubernetes deployment restarts. Critical pattern: custom entrypoint runs `ollama serve & sleep 10; ollama run llama3.2:1b --keepalive 60m hi; wait`, healthcheck greps `ollama list` for the model (retries: 30, interval: 30s, ~15 min window), and the backend overrides production model names via `DEFAULT_INFERENCE_MODEL=ollama/llama3.2:1b` when `LOCAL_DEV_ENV_MODE` is true. Common gotcha: DEVELOPMENT.md references `llama3.2:3b-instruct-fp16` but actual compose/LlamaStack config uses `llama3.2:1b`; the hardcoded `sleep 10` may fail on slow systems or large first-time downloads; without `--keepalive 60m` the model unloads after Ollama's 5-minute default causing cold-start latency; models persist via `ollama:/root/.ollama` volume."
metadata:
  type: component
tags:
  tech_stack: [ollama, llamastack, docker-compose]
  ai_pattern: [model-serving]
  platform: []
  data_layer: []
source_examples:
  - quickstart: "ai-virtual-agent"
    repo: "https://github.com/rh-ai-quickstart/ai-virtual-agent"
    notes: "Ollama as local dev model server behind LlamaStack, with model preloading entrypoint"
    approach: "A"
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
