---
name: llm-service
description: "Helm subchart for deploying LLM model servers (vLLM/TGI) as KServe InferenceServices on RHOAI"
summary: "Deploys LLM model servers (vLLM/TGI) as KServe InferenceServices on RHOAI via the llm-service Helm subchart (v0.5.9 from ai-architecture-charts), with LlamaStack orchestrating inference between backend and model servers across three runner types -- LlamaStack (via LLAMASTACK_URL), LangGraph (direct OpenAI-compat API, falls back to LlamaStack /v1), and CrewAI (LiteLLM routing requiring `openai/`-prefixed model names via `_to_litellm_model()`). Use when deploying GPU-backed LLM inference on RHOAI/OpenShift AI (24GB+ VRAM, HF_TOKEN for gated models) with support for multiple runner frameworks; pre-existing model URLs skip InferenceService creation, and local dev uses Ollama via LlamaStack's `remote::ollama` provider with silent fallback to first available model. Models configured entirely through `global.models.<name>.enabled/id/url/apiToken/tolerations` at `helm install` via install_with_env.sh (values.yaml only has commented examples), GPU tolerations passed as `--set-json`, safety/shield models share same mechanism with separate SAFETY parameter and are filtered from `/api/v1/llama-stack/llms`, and dynamic provider registration patches the LlamaStack ConfigMap at runtime with deployment restart. Gotchas: no explicit `llm-service:` block in values.yaml (check install script or `helm get values`), LLM (YAML-safe config key) vs LLM_ID (model identifier) distinction where LLM_ID defaults to LLM, LlamaStack API breaks between 0.3.x and 0.6.1 handled by multi-attribute fallback helpers, init container waits for LlamaStack not llm-service causing 10-30min startup for large model downloads, and CrewAI install script auto-prepends `openai/` prefix for LiteLLM routing."
metadata:
  type: component
tags:
  tech_stack: [vllm, kserve, helm, llamastack, langchain, crewai, litellm, ollama]
  ai_pattern: [model-serving, agents, guardrails]
  platform: [kserve, vllm, tgi, rhoai, openshift]
  data_layer: []
source_examples:
  - quickstart: "ai-virtual-agent"
    repo: "https://github.com/rh-ai-quickstart/ai-virtual-agent"
    notes: "Multi-runner LLM serving via llm-service subchart + LlamaStack + MaaS fallback"
    approach: "A"
---

# LLM Service

## Overview

The llm-service component is a reusable Helm subchart from `ai-architecture-charts` that deploys LLM model servers (vLLM or TGI) as KServe InferenceService resources on RHOAI/OpenShift AI. In the ai-virtual-agent quickstart, it acts as the GPU-backed inference layer that LlamaStack connects to as an inference provider, while the backend application supports multiple inference routing paths (LlamaStack, LangGraph, CrewAI) for different agent runner types.

## Tech Stack & Dependencies

- **Runtime:** KServe InferenceService with vLLM or TGI serving runtime
- **Container image:** Model-specific (e.g., `meta-llama/Llama-3.1-8B-Instruct` via Hugging Face)
- **Key dependencies:** RHOAI/OpenShift AI operator, GPU nodes (24GB+ VRAM), Hugging Face token for gated models
- **Helm subchart:** `llm-service` v0.5.9 from `https://rh-ai-quickstart.github.io/ai-architecture-charts`

## Key Patterns

### Global Model Configuration via Helm Values

Models are configured through `global.models` during `helm install`, not through static values.yaml entries. The values.yaml only has a commented-out example; real configuration comes from the install script.

```bash
# From deploy/cluster/scripts/install_with_env.sh
cmd_args+=("--set" "global.models.$LLM.enabled=true")
cmd_args+=("--set" "global.models.$LLM.id=${LLM_ID:-$LLM}")
cmd_args+=("--set" "llm-service.secret.hf_token=$HF_TOKEN")
```

The commented values.yaml block shows the expected structure:

```yaml
# global:
#   models:
#     llama-3-1-8b-instruct:
#       id: meta-llama/Llama-3.1-8B-Instruct
#       enabled: true
#       url: http://llama-3-1-8b-instruct-predictor...svc.cluster.local:8080/v1
```

### Makefile Model Discovery

The `list-models` target uses Helm's template rendering with a debug flag to enumerate models defined in the subchart:

```makefile
# From deploy/cluster/Makefile
list-models: deps
	@helm template dummy-release $(AI_VIRTUAL_AGENT_CHART) \
	  --set llm-service._debugListModels=true | grep ^model:
```

### GPU Tolerations for Tainted Nodes

GPU scheduling tolerations are passed as JSON during install, allowing the model server pods to run on tainted GPU nodes:

```bash
# From deploy/cluster/scripts/install_with_env.sh
cmd_args+=("--set-json" \
  "global.models.$LLM.tolerations=[{\"key\":\"$LLM_TOLERATION\",\"effect\":\"NoSchedule\",\"operator\":\"Exists\"}]")
```

### Pre-installed Model Support

When models are already served elsewhere (remote vLLM or Vertex AI), URLs are passed directly, skipping local InferenceService creation:

```bash
# From deploy/cluster/scripts/install_with_env.sh
if [ -n "$LLM_URL" ]; then
    cmd_args+=("--set" "global.models.$LLM.url=$LLM_URL")
fi
if [ -n "$LLM_API_TOKEN" ]; then
    cmd_args+=("--set" "global.models.$LLM.apiToken=$LLM_API_TOKEN")
fi
```

### LlamaStack as Inference Orchestration Layer

LlamaStack sits between the backend and the model servers. For cluster deployments, it connects to the vLLM InferenceService created by llm-service. For local dev, it connects to Ollama:

```yaml
# From deploy/local/llamastack-run.yaml (local dev config)
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

### Multi-Runner Inference Architecture

The backend supports three runner types, each with its own LLM connection pattern:

```python
# From backend/app/config.py - runner config resolution
# LlamaStack Runner: uses LLAMASTACK_URL (connects to llm-service via LlamaStack)
LLAMA_STACK_URL: Optional[str] = os.getenv("LLAMA_STACK_URL")

# LangGraph Runner: uses OpenAI-compatible API directly
LANGGRAPH_LLM_API_BASE: Optional[str] = os.getenv("LANGGRAPH_LLM_API_BASE")
LANGGRAPH_LLM_API_KEY: str = os.getenv("LANGGRAPH_LLM_API_KEY", "no-key")

# CrewAI Runner: uses LiteLLM routing with provider-qualified model names
CREWAI_LLM_API_BASE: Optional[str] = os.getenv("CREWAI_LLM_API_BASE")
CREWAI_LLM_API_KEY: str = os.getenv("CREWAI_LLM_API_KEY", os.getenv("OPENAI_API_KEY", "no-key"))
```

### Dynamic Provider Registration

Providers (vLLM/Ollama) can be registered at runtime by patching the LlamaStack ConfigMap and restarting the deployment:

```python
# From backend/app/api/v1/providers_management.py
CONFIGMAP_NAME = "run-config"
DEPLOYMENT_NAME = "llamastack"

# Adds new inference provider to config, patches configmap, restarts
new_provider = {
    "provider_id": provider_data.provider_id,
    "provider_type": provider_data.provider_type,  # "remote::vllm" or "remote::ollama"
    "config": provider_data.config,
}
inference_providers.append(new_provider)
core_v1.patch_namespaced_config_map(CONFIGMAP_NAME, namespace, configmap)
```

### LlamaStack API Version Compatibility

The codebase handles breaking changes across LlamaStack API versions (0.3.x vs 0.6.1) with multi-attribute fallback helpers:

```python
# From backend/app/api/v1/llama_stack.py
def _get_model_id(model):
    """Get model ID from various API versions (identifier in 0.3.x, id in 0.6.1)"""
    return getattr(model, "identifier", None) or getattr(model, "id", "unknown")

def _get_model_type(model):
    """Get model type (api_model_type in 0.3.x, model_type in 0.6.1)"""
    for attr in ("api_model_type", "model_type"):
        val = getattr(model, attr, None)
        if val is not None:
            return val
    meta = getattr(model, "custom_metadata", None) or {}
    return meta.get("model_type")
```

## Configuration

- **Environment variables:**
  - `LLAMASTACK_URL` - LlamaStack endpoint (default `http://llamastack:8321` on cluster, `http://localhost:8321` locally)
  - `DEFAULT_INFERENCE_MODEL` - Model override for local dev mode (e.g., `ollama/llama3.2:1b`)
  - `LANGGRAPH_LLM_API_BASE` / `LANGGRAPH_LLM_API_KEY` / `LANGGRAPH_DEFAULT_MODEL` - LangGraph runner MaaS config
  - `CREWAI_LLM_API_BASE` / `CREWAI_LLM_API_KEY` / `CREWAI_DEFAULT_MODEL` - CrewAI runner MaaS config
  - `HF_TOKEN` - Hugging Face token for downloading gated models

- **Helm values:**
  - `llm-service.secret.hf_token` - Hugging Face token for model downloads
  - `global.models.<name>.enabled` - Enable a specific model
  - `global.models.<name>.id` - Model identifier (e.g., `meta-llama/Llama-3.1-8B-Instruct`)
  - `global.models.<name>.url` - Pre-existing model URL (skips InferenceService creation)
  - `global.models.<name>.apiToken` - API token for remote model endpoints
  - `global.models.<name>.tolerations` - GPU node tolerations (JSON array)
  - `llm-service._debugListModels` - Debug flag to enumerate available model definitions

- **Config files:**
  - `deploy/local/llamastack-run.yaml` - LlamaStack provider config for local dev (Ollama-backed)
  - `deploy/cluster/scripts/install_with_env.sh` - Install script that wires `global.models` to Helm
  - `deploy/cluster/scripts/collect_env_vars.sh` - Interactive env var collection for install

## Known Gotchas

- **No explicit `llm-service:` block in values.yaml:** The llm-service subchart is configured entirely through `global.models` at install time. The values.yaml only has a commented-out example. This means you cannot see the model configuration by reading values.yaml alone; you must look at the install script or the `helm get values` output from a running deployment.

- **Model name vs config key distinction:** The Makefile exposes `LLM` (a YAML-safe config key like `llama-3-1-8b-instruct`) and `LLM_ID` (the actual model identifier like `meta-llama/Llama-3.1-8B-Instruct`). When only `LLM` is set, `LLM_ID` defaults to the same value. This is from `install_with_env.sh`: `cmd_args+=("--set" "global.models.$LLM.id=${LLM_ID:-$LLM}")`.

- **CrewAI model name requires LiteLLM provider prefix:** CrewAI uses LiteLLM routing, so model names must be provider-qualified (e.g., `openai/llama-4-scout-17b-16e-w4a16`). The install script automatically prepends `openai/` for CrewAI: `cmd_args+=("--set" "runners.crewai.default_model=openai/$MAAS_MODEL_NAME")`. The backend runner code also enforces this with `_to_litellm_model()`.

- **LangGraph falls back to LlamaStack's OpenAI-compat layer:** When `LANGGRAPH_LLM_API_BASE` is not set, the LangGraph runner falls back to `LLAMA_STACK_URL + "/v1"`, using LlamaStack's OpenAI-compatible API. This is from `langgraph_runner.py`: `if not base_url and settings.LLAMA_STACK_URL: base_url = f"{settings.LLAMA_STACK_URL}/v1"`.

- **Local dev auto-fallback for unavailable models:** In local dev mode, the LlamaStack runner checks if the requested model is actually available and silently falls back to the first available model. This prevents errors when templates reference production models not present locally.

- **Init container waits for LlamaStack, not llm-service:** The deployment has a `wait-for-llamastack` init container that polls LlamaStack readiness, but LlamaStack itself depends on the llm-service InferenceService being ready. This means total startup time depends on model download speed (10-30 minutes for large models).

- **Safety models share the same llm-service pattern:** Safety/shield models (e.g., `llama-guard-3-8b`) are deployed via the same `global.models` mechanism with a separate `SAFETY` parameter. They get their own InferenceService and GPU allocation.

## Testing Notes

- Use `make list-models` to verify available model definitions before installation
- After deployment, check model availability via the LlamaStack API: `GET /api/v1/llama-stack/llms`
- The backend filters out shield models from the LLM list to avoid exposing safety models as inference options
- Monitor model server startup with `make install-status NAMESPACE=<ns>` - llm-service pods need GPU scheduling
- For local dev, confirm Ollama has pulled the model: the compose healthcheck waits for `ollama list | grep llama3.2:1b`

## Related Patterns

- LlamaStack orchestration layer (architecture pattern)
- Helm subchart wiring via `global.models` (deployment pattern)
- Multi-runner inference routing: LlamaStack vs LangGraph vs CrewAI (architecture pattern)
