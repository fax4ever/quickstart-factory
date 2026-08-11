---
name: makefile-multi-profile-helm-install
description: Single helm_install_common function with 4 install profiles (test/demo/prod/ticketing) composed via values overlays
summary: "Centralizes Helm installation logic in a single helm_install_common Makefile function that assembles 12+ conditional argument groups via $(eval)/$(if) and runs helm upgrade --install --timeout 15m with composed values overlays, eliminating duplication across four deployment profiles for an AI agent quickstart. Use when a quickstart needs multiple deployment modes -- test (values-test.yaml, mock eventing, integration tests), demo (values-test.yaml + values-demo.yaml, email server), prod (values-production.yaml, Knative Kafka eventing with retry), or ticketing (Zammad pre-setup + ConfigMaps) -- each layering profile-specific values files atop a shared base; all targets require namespace (auto-created) and helm-depend (helm dependency update) prerequisites. Critical configuration: NAMESPACE is required (guarded by ifeq), model serving toggles via LLM/LLM_URL/LLM_API_TOKEN/HF_TOKEN, observability via ENABLE_LANGFUSE/ENABLE_MLFLOW, image.tag=$(VERSION) for versioning, and PROMPT_OVERRIDES auto-converts LG_PROMPT_* env vars into --set requestManagement.agentService.promptOverrides Helm flags for runtime prompt injection. The prod target retries 3 times because Knative Trigger creation races with Kafka broker readiness (validates 10 triggers reach Ready); ticketing is the most complex profile because Zammad nginx resolves upstream hostnames at config load time requiring pre-created ConfigMaps and credentials secrets; the common function uses kubectl create secret --dry-run=client -o yaml | kubectl apply -f - for idempotent secret creation and kubectl delete job -l app.kubernetes.io/instance for pre-install job cleanup."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, fastapi]
  ai_pattern: [agents]
  platform: [openshift, kubernetes]
source_examples:
  - quickstart: "it-self-service-agent"
    repo: "https://github.com/rh-ai-quickstart/it-self-service-agent"
    notes: "4 helm-install profiles sharing a common function with values-test/demo/production/ticketing overlays"
    approach: "A"
---

# Makefile Multi-Profile Helm Install

## Overview

This pattern centralizes Helm installation logic in a single `helm_install_common` Makefile function, then exposes four install profiles (test, demo, prod, ticketing) that compose different values overlay files and flags. Each profile adds its own values files (`values-test.yaml`, `values-demo.yaml`, `values-production.yaml`, `values-ticketing.yaml`) on top of the base `values.yaml`, sharing common argument assembly for pgvector, LLM service, LlamaStack, request management, and image versioning.

## Pattern Description

The `helm_install_common` function assembles 12+ conditional argument groups (`helm_pgvector_args`, `helm_llm_service_args`, `helm_llama_stack_args`, etc.) using Makefile `$(eval)` and `$(if)` constructs, then runs `helm upgrade --install` with the composed arguments. Each profile target calls this function with its own values overlays and mode-specific flags. The function also handles pre-install steps: creating ServiceNow credentials secrets via `kubectl create secret --dry-run=client -o yaml | kubectl apply -f -` and cleaning up old jobs.

## Implementation

### Common Install Function

```makefile
# Makefile (excerpt)
define helm_install_common
	@$(eval PGVECTOR_ARGS := $(helm_pgvector_args))
	@$(eval LLM_SERVICE_ARGS := $(helm_llm_service_args))
	@$(eval LLAMA_STACK_ARGS := $(helm_llama_stack_args))
	@$(eval REQUEST_MANAGEMENT_ARGS := $(helm_request_management_args))
	@$(eval REPLICA_COUNT_ARGS := $(helm_replica_count_args))
	@$(eval LANGFUSE_ARGS := $(if $(filter true,$(ENABLE_LANGFUSE)),--set langfuse.enabled=true,))

	@kubectl create secret generic $(MAIN_CHART_NAME)-servicenow-credentials \
		--from-literal=servicenow-instance-url="$${SERVICENOW_INSTANCE_URL:-}" \
		--from-literal=servicenow-api-key="$${SERVICENOW_API_KEY:-}" \
		-n $(NAMESPACE) --dry-run=client -o yaml | kubectl apply -f -

	@kubectl delete job -l app.kubernetes.io/instance=$(MAIN_CHART_NAME) \
		-n $(NAMESPACE) --ignore-not-found || true

	@helm upgrade --install $(MAIN_CHART_NAME) helm -n $(NAMESPACE) --timeout 15m \
		--set image.tag=$(VERSION) $(PGVECTOR_ARGS) $(LLM_SERVICE_ARGS) \
		$(LLAMA_STACK_ARGS) $(REQUEST_MANAGEMENT_ARGS) $(REPLICA_COUNT_ARGS) \
		$(2) $(EXTRA_HELM_ARGS)
endef
```

### Profile Targets

```makefile
# Makefile (excerpt)
helm-install-test: namespace helm-depend
	$(call helm_install_common,"testing/CI",\
		-f helm/values-test.yaml \
		--set requestManagement.knative.mockEventing.enabled=true \
		--set testIntegrationEnabled=true $(PROMPT_OVERRIDES),true)

helm-install-demo: namespace helm-depend deploy-email-server
	$(call helm_install_common,"demo config",\
		-f helm/values-test.yaml -f helm/values-demo.yaml \
		$(helm_demo_email_args) $(PROMPT_OVERRIDES),true)

_helm-install-prod-single:
	$(call helm_install_common,"production",\
		-f helm/values-production.yaml \
		--set requestManagement.knative.eventing.enabled=true,false)

helm-install-ticketing: namespace helm-depend
	# Multi-step: create ConfigMaps, credentials secret, demo-site, then helm install
```

### Conditional Argument Assembly

Arguments use `$(if)` to include flags only when the corresponding variable is set:

```makefile
# Makefile (excerpt)
helm_llm_service_args = \
    $(if $(HF_TOKEN),--set llm-service.secret.hf_token=$(HF_TOKEN),) \
    $(if $(LLM),--set global.models.$(LLM).enabled=true,) \
    $(if $(LLM_URL),--set llm-service.enabled=false,)

helm_llama_stack_args = \
    $(if $(LLM),--set global.models.$(LLM).enabled=true,) \
    $(if $(LLM_URL),--set global.models.$(LLM).url='$(LLM_URL)',) \
    $(if $(LLM_API_TOKEN),--set global.models.$(LLM).apiToken='$(LLM_API_TOKEN)',)
```

## Configuration

- **Key settings:** `NAMESPACE` is required for all install targets (enforced by an `ifeq` guard at the top of the Makefile); `LLM`, `LLM_URL`, `LLM_API_TOKEN`, `HF_TOKEN` control model serving; `ENABLE_LANGFUSE`, `ENABLE_MLFLOW` toggle observability; `EXTRA_HELM_ARGS` injects arbitrary additional Helm flags
- **Defaults:** `values-test.yaml` enables mock eventing; `values-production.yaml` enables Knative eventing with Kafka; LLM defaults require either `HF_TOKEN` (for self-hosted vLLM) or `LLM_URL` (for external inference)
- **Dependencies:** All targets depend on `namespace` (creates namespace if missing) and `helm-depend` (runs `helm dependency update`)

## Gotchas

- The `helm-install-prod` target wraps `_helm-install-prod-single` in a retry loop (3 attempts) because Knative Trigger creation can race with Kafka broker readiness -- it validates that all 10 triggers reach Ready condition before succeeding (see `Makefile` `helm-install-prod`)
- The `PROMPT_OVERRIDES` variable dynamically converts environment variables matching `LG_PROMPT_*` into `--set requestManagement.agentService.promptOverrides.lg-prompt-*` Helm flags, enabling runtime prompt injection for testing (see `Makefile`)
- The ticketing profile (`helm-install-ticketing`) is significantly more complex than other profiles -- it pre-creates ConfigMaps, credentials secrets, and installs the Zammad demo site chart before the main chart, because Zammad's nginx resolves upstream hostnames at config load time (see `Makefile` `helm-install-ticketing`)
- The function uses `kubectl create secret --dry-run=client -o yaml | kubectl apply -f -` for idempotent secret creation that works on both fresh installs and upgrades (see `helm_install_common`)

## Related Patterns

- `makefile-git-branch-version-autodetect.md` -- version detection consumed by these install targets
- `helm-knative-kafka-cloudevents-triggers.md` -- eventing layer enabled by the production profile
