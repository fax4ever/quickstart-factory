---
name: makefile-multi-component-observability-stack-orchestrator
description: Makefile orchestrating 10+ Helm charts across 4 namespaces with component toggles, idempotent install, and RBAC cleanup
summary: "Orchestrates deployment of 10+ Helm charts (MinIO, TempoStack, LokiStack, OTel Collector, Korrel8r, MCP server, Console Plugin/React UI, RAG, alerting) across 4 OpenShift namespaces (observability-hub, openshift-logging, openshift-cluster-observability-operator, user) via a 55+-target Makefile with component toggles RAG_ENABLED, ALERTING_ENABLED, and DEV_MODE. Use when deploying a multi-component observability stack requiring ordered installation (verify-operators-ready then infrastructure then application), idempotent helm list pre-checks, cross-component Helm argument templates (helm_llm_service_args, helm_minio_args with --set-json and $(call TOLERATIONS_TEMPLATE,...) for GPU tolerations), and configuration drift detection via check-observability-drift. Critical pattern: RBAC cleanup checks meta.helm.sh/release-name annotations on ClusterRoleBindings before deletion and only removes ClusterRoles when zero remaining bindings reference them; NAMESPACE validation uses $(MAKECMDGOALS) filter to exempt non-deployment targets (build, test, help) from requiring cluster connectivity. Gotchas: stale Loki Helm releases in failed state must be force-deleted by removing Helm secrets before reinstall; collector SA existence check (check_collector_sa_and_get_flag) prevents conflicts with cluster-logging operator's pre-created ServiceAccount; MinIO install must delete broken upstream routes (minio-api, minio-webui) referencing a non-existent service name; the NAMESPACE validation filter must enumerate ALL non-deployment targets or local-only commands will error."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, python, react]
  ai_pattern: [rag]
  platform: [openshift, rhoai, kserve, vllm]
  data_layer: [pgvector, minio]
source_examples:
  - quickstart: "openshift-ai-observability-summarizer"
    repo: "https://github.com/rh-ai-quickstart/openshift-ai-observability-summarizer"
    notes: "55+ Makefile targets orchestrating 10 Helm charts across observability-hub, openshift-logging, openshift-cluster-observability-operator, and user namespace with idempotent install, RBAC ownership tracking, and observability drift checks"
    approach: "A"
---

# Makefile Multi-Component Observability Stack Orchestrator

## Overview

This pattern uses a Makefile with 55+ targets to orchestrate the deployment of 10+ Helm charts across 4 OpenShift namespaces, managing component toggles (RAG_ENABLED, ALERTING_ENABLED, DEV_MODE), idempotent installation with existing-release checks, Helm RBAC ownership tracking for clean uninstalls, and observability configuration drift detection.

## Pattern Description

The Makefile serves as the deployment orchestrator for the entire observability stack, including operators, infrastructure components (MinIO, TempoStack, LokiStack, OTel Collector, Korrel8r), application components (MCP server, Console Plugin or React UI, RAG, Alerting), and supporting operations (user workload monitoring, tracing instrumentation, console plugin registration). Each component is a separate `helm upgrade --install` call with extensive `--set` flag computation. The install chain ensures correct ordering: operators first, then infrastructure, then application components.

## Implementation

### Main Install Chain

```makefile
# Makefile
.PHONY: install
install: namespace pre-install-checks enable-user-workload-monitoring depend \
         validate-llm install-operators install-observability-stack \
         install-mcp-server delete-jobs
	@if [ "$(DEV_MODE)" = "true" ]; then \
		$(MAKE) install-react-ui NAMESPACE=$(NAMESPACE); \
	else \
		$(MAKE) install-console-plugin NAMESPACE=$(NAMESPACE); \
	fi
	@if [ "$(RAG_ENABLED)" != "false" ]; then \
		$(MAKE) install-rag NAMESPACE=$(NAMESPACE); \
	fi
	@if [ "$(ALERTING_ENABLED)" = "true" ]; then \
		$(MAKE) install-alerts NAMESPACE=$(NAMESPACE); \
	fi
```

### Observability Stack Sequencing

```makefile
# Makefile
.PHONY: install-observability-stack
install-observability-stack: verify-operators-ready
	@$(MAKE) install-minio
	@$(MAKE) setup-tracing
	@$(MAKE) install-observability
	@$(MAKE) check-observability-drift
	@$(MAKE) enable-tracing-ui
	@$(MAKE) install-korrel8r
```

### Idempotent Install with Existing-Release Checks

Each component checks if it is already installed before deploying:

```makefile
# Makefile
install-minio:
	@if helm list -n $(MINIO_NAMESPACE) 2>/dev/null | grep -q "^$(MINIO_CHART)\s"; then \
		echo "$(MINIO_CHART) already installed, skipping..."; \
	else \
		cd deploy/helm && helm -n $(MINIO_NAMESPACE) upgrade --install $(MINIO_CHART) ... ; \
	fi
	# Clean up broken upstream routes
	- @oc delete route minio-api minio-webui -n $(MINIO_NAMESPACE) --ignore-not-found ||:
```

### Helm Argument Templates for Cross-Component Wiring

```makefile
# Makefile
helm_llm_service_args = \
    $(if $(LLM_URL),,--set llm-service.secret.hf_token=$(HF_TOKEN)) \
    $(if $(DEVICE),--set llm-service.device='$(DEVICE)',) \
    $(if $(LLM),--set global.models.$(LLM).enabled=true,) \
    $(if $(LLM_TOLERATION),--set-json global.models.$(LLM).tolerations='$(call TOLERATIONS_TEMPLATE,$(LLM_TOLERATION))',)

helm_minio_args = \
    --set minio.secret.user=$(MINIO_USER) \
    --set minio.secret.password=$(MINIO_PASSWORD) \
    --set-json minio.buckets='[$(shell echo "$(MINIO_BUCKETS)" | sed 's/,/","/g' | ...)]'
```

### RBAC Ownership Tracking for Clean Uninstall

The uninstall process checks Helm release ownership annotations before deleting cluster-scoped resources:

```makefile
# Makefile
uninstall:
	# Check ClusterRoleBinding ownership before deletion
	@MCP_CRB="grafana-prometheus-reader-binding-$(NAMESPACE)-mcp"; \
	OWNER=$$(oc get clusterrolebinding $$MCP_CRB \
	  -o jsonpath='{.metadata.annotations.meta\.helm\.sh/release-name}' 2>/dev/null); \
	if [ "$$OWNER" = "$(MCP_SERVER_RELEASE_NAME)" ] || [ -z "$$OWNER" ]; then \
		oc delete clusterrolebinding $$MCP_CRB --ignore-not-found; \
	else \
		echo "Skipping (owned by '$$OWNER', not $(MCP_SERVER_RELEASE_NAME))"; \
	fi
	# Only delete ClusterRole if no remaining bindings reference it
	@REMAINING=$$(oc get clusterrolebindings -o json | \
	  jq -r '.items[] | select(.roleRef.name=="grafana-prometheus-reader") | .metadata.name' | wc -l); \
	if [ "$$REMAINING" -eq 0 ]; then \
		oc delete clusterrole grafana-prometheus-reader --ignore-not-found; \
	fi
```

### Loki Collector SA Existence Check

```makefile
# Makefile
# Returns "false" if SA exists, "true" if it doesn't
check_collector_sa_and_get_flag = \
	if oc get serviceaccount collector -n $(LOKI_NAMESPACE) >/dev/null 2>&1; then \
		echo "false"; \
	else \
		echo "true"; \
	fi
```

### Conditional NAMESPACE Validation

The NAMESPACE variable is only required for deployment targets, not for build/test/help:

```makefile
# Makefile
ifeq ($(NAMESPACE),)
ifeq (,$(filter install-local depend install-ingestion-pipeline list-models% \
  generate-model-config help build build-alerting build-mcp-server ... test ..., \
  $(MAKECMDGOALS)))
$(error NAMESPACE is not set)
endif
endif
```

## Configuration

- **Key settings:** `NAMESPACE` (required for deploy), `RAG_ENABLED` (default: true), `ALERTING_ENABLED` (default: false), `DEV_MODE` (default: false selects Console Plugin vs React UI), `OBSERVABILITY_NAMESPACE` (default: observability-hub)
- **Defaults:** Infrastructure deploys to fixed namespaces; application deploys to user-specified NAMESPACE; build tool auto-detects podman vs docker
- **Dependencies:** `oc` CLI for cluster operations, `helm` for chart installs, `jq` and `yq` for config manipulation

## Gotchas

- The NAMESPACE validation filter list must include ALL non-deployment targets to avoid requiring cluster connectivity for local operations like `make test` or `make build`
- Stale Loki Helm releases in `failed` state are detected via `helm list --all` and force-deleted by removing Helm secrets before reinstall
- The `check_collector_sa_and_get_flag` shell snippet determines whether the collector ServiceAccount needs creation -- if the cluster-logging operator already created it, the Helm chart must skip creation to avoid conflicts
- MinIO install cleans up "broken upstream routes" (`minio-api`, `minio-webui`) that reference a non-existent `minio` service name -- these routes come from the upstream minio chart but don't match the renamed service
- The `TOLERATIONS_TEMPLATE` macro uses `$(call ...)` to generate JSON for `--set-json` flags, enabling GPU node tolerations per model

## Related Patterns

- `makefile-rhoai-autodetect-llamastack-operator-toggle.md` -- the RHOAI/LlamaStack auto-detection used within this orchestrator
- `makefile-split-cluster-local-interactive-env.md` -- alternative Makefile organization pattern
