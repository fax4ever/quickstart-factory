---
name: llm-service
description: "Helm subchart for deploying LLM model servers (vLLM/TGI) as KServe InferenceServices on RHOAI"
summary: "Deploys LLM model servers (vLLM/TGI) as KServe InferenceServices on RHOAI via the llm-service Helm subchart (v0.5.9+ from ai-architecture-charts), with LlamaStack orchestrating inference between backend and model servers across three runner types -- LlamaStack (via LLAMASTACK_URL), LangGraph (direct OpenAI-compat API, falls back to LlamaStack /v1), and CrewAI (LiteLLM routing requiring `openai/`-prefixed model names via `_to_litellm_model()`). Use when deploying GPU-backed LLM inference on RHOAI/OpenShift AI (24GB+ VRAM, HF_TOKEN for gated models) with multi-device support (cpu/gpu/hpu/xeon via DEVICE variable); pre-existing model URLs skip InferenceService creation, `rawDeploymentMode` bypasses KServe for non-KServe clusters, `llm-service.enabled: false` disables the subchart entirely for MaaS/remote-only paths (with `skipModelWait: true` and empty `initContainers`), and local dev uses Ollama via LlamaStack's `remote::ollama` provider with silent fallback to first available model. Models configured entirely through `global.models.<name>.enabled/id/url/apiToken/tolerations/maxTokens` at `helm install` via install_with_env.sh or Makefile with rag-values.yaml catalog (values.yaml only has commented examples), GPU tolerations passed as `--set-json`, safety/shield models use separate SAFETY parameter and `registerShield: true` flag (filtered from `/api/v1/llama-stack/llms`), per-model `device`/`accelerators` overrides with tool-call-parser/vision model `args` for function-calling models, dynamic provider registration patches the LlamaStack ConfigMap at runtime with deployment restart, and LlamaStack client port resolution uses LLAMASTACK_CLIENT_PORT > LLAMASTACK_SERVICE_PORT > 8321 to avoid K8s `tcp://` format in LLAMASTACK_PORT. Gotchas: no explicit `llm-service:` block in ai-virtual-agent values.yaml (f5-ai-guardrails has one with `secret.enabled` for HF token validation; check install script or `helm get values`), LLM (YAML-safe config key) vs LLM_ID (model identifier) distinction where LLM_ID defaults to LLM, LlamaStack API breaks between 0.3.x and 0.6.1 handled by multi-attribute fallback helpers, init container waits for LlamaStack not llm-service causing 10-30min startup for large model downloads, HPU/Xeon models need different vLLM args (`--max-num-seqs 32`) and max-model-len than GPU counterparts, post-init replica scaling requires dedicated RBAC (ServiceAccount/Role/RoleBinding) for `kubectl scale` hook Job, `maxTokens` is server-side only (Responses API lacks per-request support, default 2048 via LLM_MAX_TOKENS), Chart.yaml vs Chart.lock version drift resolved by `make depend`, and CrewAI install script auto-prepends `openai/` prefix for LiteLLM routing."
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
  - quickstart: "f5-ai-guardrails"
    repo: "https://github.com/rh-ai-quickstart/f5-ai-guardrails"
    notes: "Makefile-driven llm-service deployment with multi-device support (cpu/gpu/hpu), values-file model catalog, rawDeploymentMode, and registerShield for safety models"
    approach: "A"
  - quickstart: "f5-api-security"
    repo: "https://github.com/rh-ai-quickstart/f5-api-security"
    notes: "llm-service v0.5.10 subchart with Xeon device support, vision/multimodal model catalog entries, and tool-call-parser vLLM args"
    approach: "A"
  - quickstart: "it-self-service-agent"
    repo: "https://github.com/rh-ai-quickstart/it-self-service-agent"
    notes: "llm-service v0.5.6 subchart with server-side maxTokens per model, LlamaStack post-init replica scaling, and Kubernetes service discovery for LlamaStack client"
    approach: "A"
  - quickstart: "RAG"
    repo: "https://github.com/rh-ai-quickstart/RAG"
    notes: "llm-service v0.5.10 subchart with conditional enablement, remote LLM as first-class deployment path (LLM=remotellm), MaaS-only e2e testing, FP8/vision model catalog, and tenant bootstrap with llm-service disabled"
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

### Makefile-Driven Model Deployment with Values File (from f5-ai-guardrails)

Unlike script-driven installs, f5-ai-guardrails uses a Makefile with a `rag-values.yaml` values file containing a pre-defined model catalog. Models can be enabled in the file or overridden via CLI:

```makefile
# From deploy/helm/Makefile
helm_llm_service_args = \
    --set llm-service.secret.hf_token=$(HF_TOKEN) \
    $(if $(DEVICE),--set llm-service.device='$(DEVICE)',) \
    $(if $(LLM),--set global.models.$(LLM).enabled=true,) \
    $(if $(SAFETY),--set global.models.$(SAFETY).enabled=true,) \
    $(if $(RAW_DEPLOYMENT),--set llm-service.rawDeploymentMode=$(RAW_DEPLOYMENT),)
```

The example values file (`rag-values.yaml.example`) ships a full model catalog with pre-configured tolerations:

```yaml
# From deploy/helm/rag-values.yaml.example
global:
  models:
    llama-3-2-3b-instruct:
      id: meta-llama/Llama-3.2-3B-Instruct
      enabled: false
      tolerations:
        - key: "nvidia.com/gpu"
          operator: Exists
          effect: NoSchedule
```

### Multi-Device Support (from f5-ai-guardrails)

The llm-service subchart supports three device types configured per model or globally via the `DEVICE` Make variable:

```yaml
# From deploy/helm/rag/values.yaml (commented examples)
# Device Support:
# - Use DEVICE=cpu for CPU-only deployment
# - Use DEVICE=gpu for NVIDIA GPU deployment (default)
# - Use DEVICE=hpu for Intel Gaudi HPU deployment
```

Per-model device and accelerator count can also be set in the model entry:

```yaml
# From deploy/helm/rag/values.yaml (commented example)
#     llama-3-2-3b-instruct:
#       id: meta-llama/Llama-3.2-3B-Instruct
#       enabled: true
#       device: "hpu"
#       accelerators: "1"
```

### Intel Xeon Device Support (from f5-api-security)

In addition to cpu/gpu/hpu, the llm-service subchart supports Intel Xeon processors via `device: "xeon"`. Xeon deployments require explicit `--max-model-len` and `--max-num-seqs` vLLM args:

```yaml
# From deploy/helm/rag-values.yaml.example (f5-api-security)
    llama-3-2-3b-instruct:
      id: meta-llama/Llama-3.2-3B-Instruct
      enabled: true
      device: "xeon"
      args:
      - --max-model-len
      - "14336"
      - --max-num-seqs
      - "32"
```

### Tool-Call and Vision Model Args (from f5-api-security)

Models requiring tool-call parsing or vision capabilities need additional vLLM args. The values.yaml shows per-model `args` for enabling auto tool choice with model-specific parsers:

```yaml
# From deploy/helm/rag/values.yaml (commented examples)
#     granite-vision-3-2-2b:
#       id: ibm-granite/granite-vision-3.2-2b
#       enabled: true
#       device: "gpu"
#       args:
#       - --enable-auto-tool-choice
#       - --tool-call-parser
#       - granite
```

### Safety Model Shield Registration (from f5-ai-guardrails)

Safety/guard models can be registered as LlamaStack shields by setting `registerShield: true` in the model entry. This is separate from the `SAFETY` parameter used to enable the model:

```yaml
# From deploy/helm/rag/values.yaml (commented example)
#     llama-guard-3-8b:
#       id: meta-llama/Llama-Guard-3-8B
#       enabled: true
#       registerShield: true
#       device: "hpu"
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

### Conditional Subchart Enablement (from RAG)

The llm-service subchart can be entirely disabled via `llm-service.enabled` in values. Chart.yaml wires this through a `condition:` field so Helm skips all llm-service templates when disabled:

```yaml
# From deploy/helm/rag/Chart.yaml
dependencies:
  - name: llm-service
    version: 0.5.10
    repository: https://rh-ai-quickstart.github.io/ai-architecture-charts
    condition: llm-service.enabled
```

This is used in the e2e test values to run without GPUs or KServe CRDs:

```yaml
# From tests/e2e/values-e2e.yaml
llm-service:
  enabled: false
```

### Remote LLM as First-Class Deployment Path (from RAG)

RAG documents `LLM=remotellm` as a dedicated deployment path that skips local vLLM deployment entirely. The Makefile wires `LLM_URL`, `LLM_API_TOKEN`, and `LLM_ID` through `global.models`:

```bash
# From README.md installation steps
make install NAMESPACE=llama-stack-rag \
  LLM=remotellm \
  LLM_URL=https://my-model-endpoint.example.com/v1 \
  LLM_API_TOKEN=my-api-token \
  LLM_ID=llm_model_id
```

The same can be set declaratively in the values file:

```yaml
# From deploy/helm/rag/values.yaml (README example)
global:
  models:
    remotellm:
      id: meta-llama/Llama-3.3-70B-Instruct
      url: https://llm-gateway.com/v1
      apiToken: api-token
      enabled: true
```

### MaaS-Only E2E Testing Pattern (from RAG)

For CI (GitHub Actions on Kind), llm-service is disabled and models are injected via `helm --set` from workflow environment variables. This avoids GPU requirements in CI:

```yaml
# From tests/e2e/values-e2e.yaml
global:
  models: {}
    # Populated by workflow:
    # llama-3-2-3b:
    #   url: "https://maas-endpoint/v1"
    #   id: "llama-3-2-3b"
    #   enabled: true
    #   apiToken: "secret-key"

llm-service:
  enabled: false

llama-stack:
  enabled: true
  skipModelWait: true
  initContainers: []
```

The e2e workflow creates stub KServe CRDs (`InferenceService`, `ServingRuntime`) so Helm template rendering succeeds even though no real KServe operator is present.

### Tenant Bootstrap with Remote Models (from RAG)

The tenant bootstrap Helm chart provides a GitOps-ready configuration that defaults to remote models with llm-service disabled:

```yaml
# From tenant/bootstrap/values.yaml
rag:
  values:
    llm-service:
      enabled: false
      secret:
        hf_token: ""
    global:
      models:
        remotellm:
          enabled: false
          apiToken: "paste-your-token-here"
          url: "paste-your-url-here"
          id: "paste-your-model-id-here"
```

### FP8-Dynamic and Vision Model Catalog Entries (from RAG)

The values.yaml model catalog includes FP8-quantized and vision models with model-specific vLLM args:

```yaml
# From deploy/helm/rag/values.yaml (commented examples)
#     qwen25-vl-7b-instruct-fp8-dynamic:
#       id: RedHatAI/Qwen2.5-VL-7B-Instruct-FP8-Dynamic
#       enabled: true
#       resources:
#         limits:
#           nvidia.com/gpu: "1"
#       args:
#       - --distributed-executor-backend=mp
#       - --dtype=auto
#       - --max-model-len=8000
```

### Server-Side Max Tokens per Model (from it-self-service-agent)

The `maxTokens` parameter can be set per model via `global.models.<name>.maxTokens` at install time. This controls server-side max output tokens (useful when the Responses API does not support per-request max_tokens). The Makefile exposes `LLM_MAX_TOKENS` (default 2048):

```makefile
# From Makefile (it-self-service-agent)
LLM_MAX_TOKENS ?= 2048

helm_llama_stack_args = \
    $(if $(LLM),--set global.models.$(LLM).maxTokens=$(LLM_MAX_TOKENS),)
```

### Post-Init Replica Scaling for LlamaStack (from it-self-service-agent)

LlamaStack starts with 1 replica to avoid contention during init job asset registration. After the init job completes, a post-install Helm hook Job scales the deployment to the target replica count. This is controlled by `llamastack.postInitScaling`:

```yaml
# From helm/values.yaml (it-self-service-agent)
llamastack:
  postInitScaling:
    enabled: false  # Set to true or use REPLICA_COUNT in Makefile
    targetReplicas: 2
```

The scaler Job (helm hook `post-install,post-upgrade`) waits for the init job to succeed, then runs `kubectl scale deployment llamastack --replicas=$TARGET_REPLICAS`.

### LlamaStack Client with Kubernetes Service Discovery (from it-self-service-agent)

The agent service uses a factory pattern to create both native LlamaStack and OpenAI-compatible clients. Port resolution uses a priority chain: Helm override (`LLAMASTACK_CLIENT_PORT`) > Kubernetes auto-injected (`LLAMASTACK_SERVICE_PORT`) > default (8321). The `LLAMASTACK_PORT` env var is explicitly avoided because Kubernetes sets it to `tcp://host:port` format:

```python
# From agent-service/src/agent_service/utils/llamastack_client.py
port_str = os.environ.get("LLAMASTACK_CLIENT_PORT") or os.environ.get(
    "LLAMASTACK_SERVICE_PORT", "8321"
)
```

Helm values pipe through as env vars in `_env-helpers.tpl`:

```yaml
# From helm/values.yaml (it-self-service-agent)
llamastack:
# port: 8321           # Sets LLAMASTACK_CLIENT_PORT
# apiKey: "dummy-key"  # Sets LLAMASTACK_API_KEY
# openaiBasePath: "/v1/openai/v1"  # Sets LLAMASTACK_OPENAI_BASE_PATH
# timeout: 120         # Sets LLAMASTACK_TIMEOUT
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
  - `deploy/cluster/scripts/install_with_env.sh` - Install script that wires `global.models` to Helm (ai-virtual-agent)
  - `deploy/cluster/scripts/collect_env_vars.sh` - Interactive env var collection for install (ai-virtual-agent)
  - `deploy/helm/rag-values.yaml.example` - Full model catalog with pre-configured tolerations (f5-ai-guardrails)
  - `deploy/helm/Makefile` - Makefile-driven install with `helm_llm_service_args` and interactive HF token validation (f5-ai-guardrails)

- **Additional Helm values (from it-self-service-agent):**
  - `global.models.<name>.maxTokens` - Server-side max output tokens (default 2048 via `LLM_MAX_TOKENS`)
  - `llamastack.postInitScaling.enabled` - Enable post-init replica scaling for LlamaStack
  - `llamastack.postInitScaling.targetReplicas` - Replica count after init job completes
  - `llamastack.port` - Port override (sets `LLAMASTACK_CLIENT_PORT`, avoids K8s `tcp://` format)
  - `llamastack.apiKey` - API key for LlamaStack authentication (default `dummy-key`)
  - `llamastack.openaiBasePath` - Base path for OpenAI-compatible API (default `/v1/openai/v1`)
  - `llamastack.timeout` - Request timeout in seconds (default 120)

- **Additional Helm values (from RAG):**
  - `llm-service.enabled` - Conditional subchart enablement (default `true`); set to `false` for MaaS or remote-only deployments
  - `global.models.<name>.url` - Remote model endpoint URL (skips InferenceService creation)
  - `global.models.<name>.apiToken` - Authentication token for remote model endpoints
  - `global.models.<name>.resources.limits` - Resource limits including `nvidia.com/gpu` count
  - `global.models.<name>.args` - Per-model vLLM CLI args (e.g., `--distributed-executor-backend=mp`, `--dtype=auto`)
  - `llama-stack.skipModelWait` - Skip waiting for local model servers (for MaaS deployments)

- **Makefile variables (from RAG):**
  - `INTERACTIVE` - Enable/disable interactive prompts (default `true`)
  - `LLM_TOLERATION` / `SAFETY_TOLERATION` - Per-model GPU toleration keys
  - `RAW_DEPLOYMENT` - Use raw Deployments instead of KServe InferenceServices (applied to both `llm-service` and `llama-stack`)
  - `EXTRA_HELM_ARGS` - Passthrough for additional Helm arguments

- **Additional Helm values (from f5-ai-guardrails):**
  - `llm-service.secret.enabled` - Enable secret creation for HF token (default `true`)
  - `llm-service.device` - Global device type (`cpu`, `gpu`, `hpu`; default `gpu`)
  - `llm-service.rawDeploymentMode` - Use raw Deployments instead of KServe InferenceServices
  - `global.models.<name>.device` - Per-model device override
  - `global.models.<name>.accelerators` - Number of accelerators (defaults to `1`)
  - `global.models.<name>.registerShield` - Register as LlamaStack shield (for safety/guard models)

## Known Gotchas

- **No explicit `llm-service:` block in values.yaml:** The llm-service subchart is configured entirely through `global.models` at install time. The values.yaml only has a commented-out example. This means you cannot see the model configuration by reading values.yaml alone; you must look at the install script or the `helm get values` output from a running deployment.

- **Model name vs config key distinction:** The Makefile exposes `LLM` (a YAML-safe config key like `llama-3-1-8b-instruct`) and `LLM_ID` (the actual model identifier like `meta-llama/Llama-3.1-8B-Instruct`). When only `LLM` is set, `LLM_ID` defaults to the same value. This is from `install_with_env.sh`: `cmd_args+=("--set" "global.models.$LLM.id=${LLM_ID:-$LLM}")`.

- **CrewAI model name requires LiteLLM provider prefix:** CrewAI uses LiteLLM routing, so model names must be provider-qualified (e.g., `openai/llama-4-scout-17b-16e-w4a16`). The install script automatically prepends `openai/` for CrewAI: `cmd_args+=("--set" "runners.crewai.default_model=openai/$MAAS_MODEL_NAME")`. The backend runner code also enforces this with `_to_litellm_model()`.

- **LangGraph falls back to LlamaStack's OpenAI-compat layer:** When `LANGGRAPH_LLM_API_BASE` is not set, the LangGraph runner falls back to `LLAMA_STACK_URL + "/v1"`, using LlamaStack's OpenAI-compatible API. This is from `langgraph_runner.py`: `if not base_url and settings.LLAMA_STACK_URL: base_url = f"{settings.LLAMA_STACK_URL}/v1"`.

- **Local dev auto-fallback for unavailable models:** In local dev mode, the LlamaStack runner checks if the requested model is actually available and silently falls back to the first available model. This prevents errors when templates reference production models not present locally.

- **Init container waits for LlamaStack, not llm-service:** The deployment has a `wait-for-llamastack` init container that polls LlamaStack readiness, but LlamaStack itself depends on the llm-service InferenceService being ready. This means total startup time depends on model download speed (10-30 minutes for large models).

- **Safety models share the same llm-service pattern:** Safety/shield models (e.g., `llama-guard-3-8b`) are deployed via the same `global.models` mechanism with a separate `SAFETY` parameter. They get their own InferenceService and GPU allocation.

- **rawDeploymentMode for non-KServe clusters (from f5-ai-guardrails):** The `rawDeploymentMode` flag can be set on both `llm-service` and `llama-stack` subcharts via `RAW_DEPLOYMENT` Make variable. This is passed as `--set llm-service.rawDeploymentMode=$(RAW_DEPLOYMENT)` and `--set llama-stack.rawDeploymentMode=$(RAW_DEPLOYMENT)` simultaneously, ensuring both subcharts use the same deployment method.

- **HPU models need different args than GPU (from f5-ai-guardrails):** Intel Gaudi HPU models require HPU-specific vLLM args (e.g., `--max-num-seqs 32`) and have different `--max-model-len` values than their GPU counterparts. The values.yaml commented examples show the same model (`Llama-3.2-3B-Instruct`) configured differently for GPU vs HPU, including different max model lengths (`30444` for GPU vs `14336` for HPU).

- **Explicit llm-service block for secrets (from f5-ai-guardrails):** Unlike ai-virtual-agent where the `llm-service:` block is absent from values.yaml, f5-ai-guardrails has an explicit block with `secret.hf_token` and `secret.enabled: true`. The Makefile validation parses `hf_token` from this block with `grep -A 40 "^llm-service:" $(VALUES_FILE) | grep "hf_token:"` and prompts interactively if empty.

- **Xeon device requires explicit memory limits (from f5-api-security):** Unlike GPU deployments where vLLM can auto-detect available memory, Xeon (`device: "xeon"`) deployments need explicit `--max-model-len` and `--max-num-seqs` args. The same model (`Llama-3.2-3B-Instruct`) uses `--max-model-len 14336 --max-num-seqs 32` on Xeon, matching HPU defaults but differing from GPU where `30444` is used.

- **Avoid LLAMASTACK_PORT env var (from it-self-service-agent):** Kubernetes auto-injects `LLAMASTACK_PORT` in `tcp://host:port` format (not a plain port number). The client factory explicitly uses `LLAMASTACK_CLIENT_PORT` (Helm override) or `LLAMASTACK_SERVICE_PORT` (K8s auto-injected numeric port) instead. From `llamastack_client.py`: `port_str = os.environ.get("LLAMASTACK_CLIENT_PORT") or os.environ.get("LLAMASTACK_SERVICE_PORT", "8321")`.

- **Post-init scaling requires RBAC for kubectl scale (from it-self-service-agent):** The post-init scaler Job uses `bitnami/kubectl:latest` and needs a dedicated ServiceAccount with Role/RoleBinding granting `get`, `list`, `watch` on Jobs and `get`, `update`, `patch` on Deployments. This is deployed via `llama-stack-post-init-scaler-rbac.yaml` as a Helm hook.

- **maxTokens is server-side only (from it-self-service-agent):** The `global.models.<name>.maxTokens` setting controls server-side max output tokens because the LlamaStack Responses API does not support per-request `max_tokens`. Set via `LLM_MAX_TOKENS` Makefile variable (default 2048). Must fit within model context window (e.g., 14k for some models).

- **Chart.yaml vs Chart.lock version drift (from f5-api-security):** Chart.yaml declares `llm-service` version `0.5.10` but Chart.lock pins `0.5.2`. This happens when `helm dependency update` has not been re-run after a Chart.yaml version bump. Running `make depend` (which calls `helm dependency update`) resolves the drift.

- **`llm-service.enabled` must be explicitly set for MaaS/remote-only (from RAG):** When using external models via MaaS or `LLM=remotellm`, the llm-service subchart should be disabled with `llm-service.enabled: false`. If left enabled (the default), Helm will render KServe InferenceService resources that require KServe CRDs and GPU nodes even when no local models are configured. The e2e tests demonstrate this pattern in `tests/e2e/values-e2e.yaml`.

- **`skipModelWait` and empty `initContainers` for MaaS (from RAG):** When using external MaaS models, LlamaStack must be configured with `skipModelWait: true` and `initContainers: []` to prevent init containers from waiting for local model servers that will never start. From `tests/e2e/values-e2e.yaml`: these two settings together bypass the model-readiness checks.

- **Predictor pod readiness: 2/2 vs 3/3 containers (from RAG):** KServe model server pods show as `component=predictor`. They should show `2/2` Ready when `RAW_DEPLOYMENT` is used (default), or `3/3` when `RAW_DEPLOYMENT=false` (full KServe with queue-proxy sidecar). From README: `Look for 2/2 (or 3/3 when RAW_DEPLOYMENT=false) under the Ready column`.

- **Interactive vs non-interactive Makefile mode (from RAG):** The Makefile `INTERACTIVE ?= true` variable controls whether the install process pauses for user input (HF token, TAVILY key, values file review). Set `INTERACTIVE=false` for CI/unattended deployments. Non-interactive mode skips prompts and logs warnings for missing values instead.

## Testing Notes

- Use `make list-models` to verify available model definitions before installation
- After deployment, check model availability via the LlamaStack API: `GET /api/v1/llama-stack/llms`
- The backend filters out shield models from the LLM list to avoid exposing safety models as inference options
- Monitor model server startup with `make install-status NAMESPACE=<ns>` - llm-service pods need GPU scheduling
- For local dev, confirm Ollama has pulled the model: the compose healthcheck waits for `ollama list | grep llama3.2:1b`
- In f5-ai-guardrails, `make validate` runs `helm lint` and `helm template --dry-run` on the RAG chart, and `make validate-infra` checks KServe CRDs, webhook endpoints, and GPU availability before install
- Use `make logs-llm` (f5-ai-guardrails) to tail llm-service pod logs: `oc logs -n $(NAMESPACE) -l app=llm-service --tail=100`
- `make health` checks pods, services, routes, huggingface-secret, and PVCs in one pass

- In it-self-service-agent, `make helm-list-models` enumerates available models: `helm template dummy-release helm --set llm-service._debugListModels=true | grep ^model:`
- The init job waits for LlamaStack readiness then runs `python3 -m agent_service.scripts.register_assets` to register agents and knowledge bases
- In RAG, verify KServe model servers via `oc get pods -l component=predictor` and wait for 2/2 (raw mode) or 3/3 (full KServe) Ready containers
- RAG e2e tests on Kind disable llm-service entirely and use MaaS models injected via GitHub Actions `helm --set`, with stub KServe CRDs installed to satisfy Helm template rendering
- Use `make validate-config` to check HF token and TAVILY key configuration without installing; `make configure-keys` prompts interactively for both keys

## Related Patterns

- LlamaStack orchestration layer (architecture pattern)
- Helm subchart wiring via `global.models` (deployment pattern)
- Multi-runner inference routing: LlamaStack vs LangGraph vs CrewAI (architecture pattern)
