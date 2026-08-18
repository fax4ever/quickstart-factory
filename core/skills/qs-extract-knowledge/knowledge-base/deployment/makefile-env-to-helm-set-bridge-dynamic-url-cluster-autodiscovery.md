---
name: makefile-env-to-helm-set-bridge-dynamic-url-cluster-autodiscovery
description: Makefile sourcing .env.production with define blocks mapping 30+ env vars to --set flags, dynamic URL generation from oc cluster domain, and OpenShift internal registry autodetect
summary: "Bridges 30+ environment variables from .env.production to Helm --set flags via three Makefile define blocks (HELM_SECRET_PARAMS, HELM_LLAMASTACK_PARAMS, HELM_LLM_SERVICE_PARAMS), enabling single-command OpenShift deployment with dynamic URL generation and registry autodiscovery. Use when deploying Helm charts requiring many conditional --set flags sourced from env files with cluster-specific URL computation -- prefer over shell script variants when Makefile targets already orchestrate helm-dep-update across multiple sub-charts in order. Cluster domain is extracted via `oc whoami --show-server | sed` to derive the apps domain, Keycloak and app URLs follow `<app>-<namespace>.<cluster-domain>`, an `ifeq/findstring` block guarded by `$(origin REPOSITORY)` autodetects OpenShift internal registry to set REPOSITORY to namespace, `--set-json` handles complex structures like tolerations arrays, and LLM_PROVIDER toggles both llama-stack.enabled and llm-service.enabled. Comma-containing values (CORS origins, redirect URIs) require `${VAR//,/\\,}` escaping since Helm --set treats commas as list separators; Keycloak hostname extraction via four chained sed commands is duplicated across deploy/deploy-dev/deploy-with-ml-dspa targets; deploy-dev still sources .env.production despite its name; and `set -a; source; set +a` auto-exports all env file variables before explicit export overrides dynamic URLs."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  ai_pattern: []
  platform: [openshift]
source_examples:
  - quickstart: "spending-transaction-monitor"
    repo: "https://github.com/rh-ai-quickstart/spending-transaction-monitor"
    notes: "Three define blocks (HELM_SECRET_PARAMS, HELM_LLAMASTACK_PARAMS, HELM_LLM_SERVICE_PARAMS) mapping 30+ env vars to --set flags, dynamic URL generation from CLUSTER_DOMAIN, OpenShift internal registry autodetect"
    approach: "A"
---

# Makefile Env-to-Helm-Set Bridge with Dynamic URL and Registry Autodiscovery

## Overview

This pattern uses Makefile `define` blocks to bridge environment files (`.env.production`) to Helm `--set` flags, dynamically generating Keycloak and application URLs from the OpenShift cluster domain, and auto-detecting whether the target registry is OpenShift's internal registry to adjust the image repository path accordingly. This enables a single `make deploy` command to configure 30+ Helm values from environment variables.

## Pattern Description

Three Makefile `define` blocks (`HELM_SECRET_PARAMS`, `HELM_LLAMASTACK_PARAMS`, `HELM_LLM_SERVICE_PARAMS`) each generate conditional `--set` flags. The deploy target sources `.env.production`, overrides URL variables with dynamically computed values based on the cluster domain (discovered via `oc whoami --show-server`), and passes all parameters to `helm upgrade --install`. An `ifeq`/`findstring` block detects OpenShift's internal image registry and adjusts `REPOSITORY` to match the namespace-based path convention.

## Implementation

### Cluster Domain and Dynamic URL Generation

```makefile
CLUSTER_DOMAIN ?= $(shell oc whoami --show-server 2>/dev/null | sed -E 's|https://api\.([^:]+).*|apps.\1|')

KEYCLOAK_URL_DYNAMIC := http://$(PROJECT_NAME)-keycloak:8080
KEYCLOAK_FRONTEND_URL_DYNAMIC := https://$(PROJECT_NAME)-keycloak-$(NAMESPACE).$(CLUSTER_DOMAIN)
APP_URL_DYNAMIC := https://$(PROJECT_NAME)-$(NAMESPACE).$(CLUSTER_DOMAIN)
KEYCLOAK_REDIRECT_URIS_DYNAMIC := $(APP_URL_DYNAMIC)/*,$(APP_URL_DYNAMIC)
```

Source: `Makefile` lines 9, 32-41. Internal Keycloak URL uses cluster DNS; external URLs follow OpenShift's `<app>-<namespace>.<cluster-domain>` pattern.

### OpenShift Internal Registry Autodetect

```makefile
ifeq ($(origin REPOSITORY), default)
  ifneq (,$(findstring openshift-image-registry,$(REGISTRY_URL)))
    REPOSITORY := $(NAMESPACE)
  endif
  ifneq (,$(findstring image-registry.openshift-image-registry,$(REGISTRY_URL)))
    REPOSITORY := $(NAMESPACE)
  endif
endif
```

Source: `Makefile` lines 18-25. OpenShift's internal registry uses `<registry>/<namespace>/<image>` vs Quay's `<registry>/<org>/<image>`.

### Env-to-Helm-Set Define Block (excerpt)

```makefile
define HELM_SECRET_PARAMS
$$(if [ -n "$$POSTGRES_DB" ]; then echo "--set secrets.POSTGRES_DB=$$POSTGRES_DB"; fi) \
$$(if [ -n "$$API_KEY" ]; then echo "--set secrets.API_KEY=$$API_KEY"; fi) \
$$(if [ -n "$$CORS_ALLOWED_ORIGINS" ]; then echo "--set secrets.CORS_ALLOWED_ORIGINS=$${CORS_ALLOWED_ORIGINS//,/\\,}"; fi) \
$$(if [ -n "$$KEYCLOAK_FRONTEND_URL" ]; then echo "--set keycloak.config.hostname=$$(echo "$$KEYCLOAK_FRONTEND_URL" | sed 's|http://||' | sed 's|https://||' | sed 's|/.*||' | sed 's|:[0-9]*$$||')"; fi)
endef
```

Source: `Makefile` lines 63-109 (abridged). Comma-containing values use `${VAR//,/\\,}` to escape for Helm. Keycloak hostname is extracted from URL via `sed` pipeline.

### Deploy Target with Environment Override

```makefile
deploy: create-project helm-dep-update check-keycloak-vars
	@set -a; source $(ENV_FILE_PROD); set +a; \
	export KEYCLOAK_URL="$(KEYCLOAK_URL_DYNAMIC)"; \
	export KEYCLOAK_FRONTEND_URL="$(KEYCLOAK_FRONTEND_URL_DYNAMIC)"; \
	export CORS_ALLOWED_ORIGINS="$(CORS_ALLOWED_ORIGINS_DYNAMIC)"; \
	helm upgrade --install $(PROJECT_NAME) ./deploy/helm/spending-monitor \
		--namespace $(NAMESPACE) \
		--timeout 15m \
		--set routes.sharedHost="$(PROJECT_NAME)-$(NAMESPACE).$(CLUSTER_DOMAIN)" \
		$(HELM_SECRET_PARAMS) \
		$(HELM_LLAMASTACK_PARAMS) \
		$(HELM_LLM_SERVICE_PARAMS)
```

Source: `Makefile` lines 522-550 (abridged). Dynamic URLs override env file values.

### LlamaStack and LLM Service Parameter Blocks

```makefile
define HELM_LLAMASTACK_PARAMS
$$(if [ -n "$$LLM_PROVIDER_ID" ]; then echo "--set global.models.$$LLM_PROVIDER_ID.enabled=true"; fi) \
$$(if [ -n "$$LLAMA_STACK_ENV" ]; then echo "--set-json llama-stack.secrets=$$LLAMA_STACK_ENV"; fi) \
$$(if [ "$$LLM_PROVIDER" = "llamastack" ]; then echo "--set llama-stack.enabled=true"; \
    else echo "--set llama-stack.enabled=false"; fi)
endef

define HELM_LLM_SERVICE_PARAMS
$$(if [ -n "$$LLM_TOLERATION" ]; then echo "--set-json global.models.$$LLM_PROVIDER_ID.tolerations=[{\"key\":\"$$LLM_TOLERATION\",\"effect\":\"NoSchedule\",\"operator\":\"Exists\"}]"; fi) \
$$(if [ "$$LLM_PROVIDER" = "llamastack" ]; then echo "--set llm-service.enabled=true"; \
    else echo "--set llm-service.enabled=false"; fi)
endef
```

Source: `Makefile` lines 112-125 (abridged). Uses `--set-json` for complex structures like tolerations arrays. LLM_PROVIDER drives both llama-stack and llm-service toggle.

## Configuration

- **ENV_FILE_PROD:** `.env.production` for cluster deployments
- **ENV_FILE_DEV:** `.env.development` for local Podman Compose
- **NAMESPACE:** `spending-transaction-monitor` (default)
- **REGISTRY_URL:** `quay.io` (default) or OpenShift internal registry
- **Prerequisite targets:** `create-project` (oc new-project), `helm-dep-update`, `check-keycloak-vars`
- **Deploy variants:** `deploy` (production), `deploy-dev` (reduced replicas/no persistence), `deploy-with-ml-dspa` (enables ML pipeline + DSPA)

## Gotchas

- `set -a; source $(ENV_FILE_PROD); set +a` auto-exports all variables from the env file; this is combined with explicit `export` of variables that need dynamic override
- Comma-containing values (CORS origins, redirect URIs) require `${VAR//,/\\,}` escaping because Helm's `--set` treats commas as list separators
- The `KEYCLOAK_FRONTEND_URL` to hostname extraction uses four chained `sed` commands to strip protocol, port, and path -- this is duplicated across deploy/deploy-dev/deploy-with-ml-dspa targets
- `deploy-dev` differs from `deploy` only in setting `database.persistence.enabled=false` and explicit `replicas=1` -- it still sources `.env.production`
- The `helm-dep-update` target chains updates across three charts in order: keycloak, alert-recommender-pipeline, then spending-monitor (parent)

## Related Patterns

- `makefile-split-cluster-local-interactive-env.md` - Split cluster/local Makefile approach
- `deploy-script-conditional-env-helm-set-cluster-autodiscovery.md` - Shell script variant
- `makefile-runtime-secret-bridge-multi-chart-oc-discovery.md` - Multi-chart oc discovery
