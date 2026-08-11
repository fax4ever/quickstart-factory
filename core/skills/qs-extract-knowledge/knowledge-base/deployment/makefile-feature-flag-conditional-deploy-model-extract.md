---
name: makefile-feature-flag-conditional-deploy-model-extract
description: Makefile with boolean feature flags, model/provider mode selection, and runtime KServe config extraction
summary: "Solves conditional multi-component deployment orchestration for AI quickstarts using a single Makefile with 6 boolean `?=` feature flags (DEPLOY_MODEL, DEPLOY_MINIO, BUILD_COPILOT_UI, etc.) and 2 mode selectors (MODEL=qwen3/nemotron, PROVIDER_MODE=mcp_direct/llama_stack) that guard 9 `helm upgrade --install` calls via `ifeq` — orchestrates the independent subchart architecture from helm-independent-subcharts-no-umbrella. Use when deploying a multi-chart quickstart that needs deploy-then-discover model config propagation: the Makefile starts model deployment non-blocking, waits for KServe InferenceService readiness, then extracts route URL, model name, and SA token from the `default-name-<model-name>-sa` secret to inject as `--set` flags (dotted notation like `llm.baseUrl`, `llm.apiKey`) into downstream charts like copilot-backend. Critical patterns: model-provider compatibility check blocks nemotron+llama_stack (custom TOOLCALL format unsupported), PROVIDER_MODE=llama_stack switches pg-airman-mcp MCP transport from `streamable-http` to `sse`, and CORS is auto-configured by extracting copilot-ui route via `oc set env` on the backend deployment. Gotchas: `oc set env` CORS injection bypasses Helm values and resets on next `helm upgrade` without explicit `--set cors.allowedOrigins`, the label selector `release=qwen3-model` is baked into chart templates not values.yaml, NAMESPACE validation uses `$(error)` at parse time so all targets except `help` fail immediately if unset, and the SA token secret naming convention `default-name-<model-name>-sa` is chart-template-dependent (see token-secret.yaml)."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, fastapi]
  ai_pattern: [agents, model-serving]
  platform: [kserve, vllm, rhoai, openshift]
  data_layer: [pgvector]
source_examples:
  - quickstart: "data-governance-co-pilot"
    repo: "https://github.com/rh-ai-quickstart/data-governance-co-pilot"
    notes: "Single Makefile with 6 boolean flags, 2 mode selectors, and dynamic model config extraction from KServe"
    approach: "A"
---

# Makefile with Feature Flags and Model Config Extraction

## Overview

This pattern uses a single Makefile with boolean feature flags and mode selectors to control which components are deployed and how they are configured. The most distinctive aspect is runtime extraction of LLM configuration (endpoint URL, model name, API key) from deployed KServe InferenceServices, enabling a deploy-then-discover workflow where model details propagate to downstream services automatically.

## Pattern Description

The Makefile defines six `?=` boolean flags (`DEPLOY_MODEL`, `DEPLOY_MINIO`, `DEPLOY_PGADMIN`, `BUILD_COPILOT_UI`, `BUILD_PG_AIRMAN_MCP`, `BUILD_COPILOT_BACKEND`, `BUILD_DATA_LOADER`) and two mode selectors (`MODEL` for nemotron/qwen3, `PROVIDER_MODE` for mcp_direct/llama_stack). The `install` target sequences 9 `helm upgrade --install` calls with `ifeq` guards on these flags. When `DEPLOY_MODEL=true`, the Makefile deploys the selected model chart first (non-blocking), then later waits for the InferenceService to become ready and extracts its route URL, model name, and SA token secret to pass as `--set` flags to downstream charts.

## Implementation

### Feature Flag Declarations

```makefile
# helm/Makefile (lines 30-56)
DEPLOY_MODEL ?= false
DEPLOY_MINIO ?= false
DEPLOY_PGADMIN ?= false
BUILD_COPILOT_UI ?= false
BUILD_PG_AIRMAN_MCP ?= false
BUILD_COPILOT_BACKEND ?= false
BUILD_DATA_LOADER ?= false
MODEL ?= qwen3
PROVIDER_MODE ?= mcp_direct
```

### Model Config Extraction from KServe

When `DEPLOY_MODEL=true`, the backend install target waits for the model, then extracts three values from the live cluster:

```makefile
# helm/Makefile (copilot-backend-install, DEPLOY_MODEL=true branch)
@MODEL_NAME=$$(oc get inferenceservice -n $(NAMESPACE) \
    -l release=qwen3-model \
    -o jsonpath='{.items[0].metadata.name}'); \
MODEL_URL="https://$$(oc get route $$MODEL_NAME \
    -o jsonpath='{.spec.host}' -n $(NAMESPACE))/v1"; \
MODEL_API_KEY=$$(oc get secret default-name-$$MODEL_NAME-sa \
    -n $(NAMESPACE) -o jsonpath='{.data.token}' | base64 -d); \
helm -n $(NAMESPACE) upgrade --install copilot-backend $(COPILOT_BACKEND_CHART) \
    --set llm.baseUrl=$$MODEL_URL \
    --set llm.model=$$MODEL_NAME \
    --set llm.apiKey=$$MODEL_API_KEY \
    --timeout 5m
```

### Model-Provider Compatibility Check

The Makefile validates that the selected model is compatible with the chosen provider mode before proceeding:

```makefile
# helm/Makefile (check-model-provider-compatibility target)
check-model-provider-compatibility:
	@if [ "$(MODEL)" = "nemotron" ] && [ "$(PROVIDER_MODE)" = "llama_stack" ]; then \
		echo "Error: Nemotron model is not compatible with Llama Stack mode."; \
		echo "Nemotron uses custom <TOOLCALL> format which Llama Stack does not support."; \
		exit 1; \
	fi
```

### Non-Blocking Model Deploy with Deferred Wait

Model deployment is started early (non-blocking), and the wait happens later when downstream services need the model config:

```makefile
# helm/Makefile (install target, lines 259-270)
ifeq ($(DEPLOY_MODEL),true)
	@echo "DEPLOY_MODEL=true: Starting $(MODEL) model deployment..."
ifeq ($(MODEL),qwen3)
	@$(MAKE) qwen3-model-deploy NAMESPACE=$(NAMESPACE)
endif
	@echo "Model is deploying in the background. Continuing with remaining deployments..."
endif
```

### CORS Auto-Configuration

After copilot-ui is deployed, the Makefile extracts the UI route and injects it as the backend's CORS origin:

```makefile
# helm/Makefile (copilot-ui-install target, lines 815-818)
@UI_ORIGIN="https://$$(oc get route copilot-ui \
    -o jsonpath='{.spec.host}' -n $(NAMESPACE))"; \
oc set env deployment/copilot-backend COPILOT_UI_ORIGIN="$$UI_ORIGIN" -n $(NAMESPACE)
```

## Configuration

- **Key settings:** `NAMESPACE` is required for all targets except `help`; credential parameters use dotted notation (`postgres.userId`, `llm.apiKey`) passed as make arguments
- **Defaults:** `MODEL=qwen3`, `PROVIDER_MODE=mcp_direct`, all `DEPLOY_*` and `BUILD_*` flags default to `false`
- **Dependencies:** Requires `oc` (minimum version 4.17.0 enforced by `check-oc-version`), `helm`, and `jq`

## Gotchas

- The token secret name follows the convention `default-name-<model-name>-sa` which is created by the model chart's `token-secret.yaml` template -- if the secret naming convention changes, the extraction breaks (see `helm/nemotron-model/templates/token-secret.yaml`)
- The label selector `release=qwen3-model` used to find the InferenceService is set by the model chart's Helm labels, not by a values.yaml config (see `helm/qwen3-model/templates/inferenceservice.yaml`)
- `PROVIDER_MODE=llama_stack` changes the MCP transport from `streamable-http` to `sse` in the pg-airman-mcp install (see `helm/Makefile` lines 390-416)
- The `copilot-ui-install` target uses `oc set env` to inject CORS origin directly into the deployment, bypassing Helm values -- subsequent `helm upgrade` calls without `--set cors.allowedOrigins` will reset this (see `helm/Makefile` lines 815-818)
- NAMESPACE validation happens at Makefile parse time via `$(error)`, not as a target prerequisite, so all targets (except help) fail immediately if NAMESPACE is unset (see `helm/Makefile` lines 2-6)

## Related Patterns

- `helm-independent-subcharts-no-umbrella.md` -- the chart architecture this Makefile orchestrates
- `kserve-oauth-proxy-timeout-patch-job.md` -- post-install Job used by the model charts this Makefile deploys
