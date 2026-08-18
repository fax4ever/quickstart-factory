---
name: makefile-delegating-router-cluster-local
description: Root Makefile routing local/* and cluster/* to subdirectory Makefiles with inline credential prompting
summary: "Provides a unified CLI entry point via a root Makefile that routes local/* and cluster/* targets to subdirectory Makefiles (deploy/local/ and deploy/helm/) using $(MAKE) -C pattern rules, solving split cluster/local deployment management for quickstarts with both OpenShift Helm and local compose+native workflows. Use when a quickstart needs both cluster Helm deployment and local compose+native development from one make interface — the root router is a thin dispatcher requiring no tools itself, while subdirectory Makefiles own their dependencies (oc/helm for cluster, compose runtime and uv for local). The Helm Makefile collects LLM credentials via inline read -s prompts, writes a temporary values file to /tmp/rhdp-values.yaml passed alongside global-values.yaml and values.yaml to helm install, defaults NAMESPACE to oc project -q, and loads .env via include/export for dual Make/shell variable access; the local Makefile auto-detects COMPOSE_CMD (docker-compose vs podman-compose) and launches native Python processes (uvicorn backend, Gradio UI/annotation) via uv run after compose services are up. A failed helm install leaves plaintext secrets in /tmp/rhdp-values.yaml on disk, .env loaded with include/export exposes all variables as both Make and shell vars, rag-stack/aap-mock-stack parallelize with &/wait but backend/ui/annotation must start sequentially after compose services, and cross-platform port cleanup switches between lsof (macOS) and fuser (Linux)."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, fastapi]
  ai_pattern: []
  platform: [openshift]
source_examples:
  - quickstart: "ansible-log-analysis"
    repo: "https://github.com/rh-ai-quickstart/ansible-log-analysis"
    notes: "Three-tier Makefile: root router, deploy/helm for cluster, deploy/local for compose+native processes"
    approach: "A"
---

# Delegating Router Makefile with Cluster and Local Targets

## Overview

This pattern uses a three-tier Makefile structure: a root Makefile that routes `local/*` and `cluster/*` targets to subdirectory-specific Makefiles, a Helm Makefile for OpenShift cluster deployment with inline credential prompting, and a local Makefile for compose-based development with hybrid compose+native process management. The root Makefile acts as a thin dispatcher.

## Pattern Description

The root `Makefile` uses pattern rules (`local/%` and `cluster/%`) to delegate to `deploy/local/Makefile` and `deploy/helm/Makefile` respectively via `$(MAKE) -C`. The Helm Makefile provides install/upgrade/uninstall with inline credential collection that generates a temporary values file, passed to `helm install` alongside the main values. The local Makefile orchestrates a mix of compose services (Loki, Grafana, PostgreSQL, MinIO, embedding) and native Python processes (backend, UI, annotation interface run via `uv run`).

## Implementation

### Root Router Makefile

```makefile
# Makefile (root)
local/%: ## Route local targets to deploy/local/Makefile
	@$(MAKE) -C deploy/local $*

cluster/%: ## Route deploy targets to deploy/helm/Makefile
	@$(MAKE) -C deploy/helm $*

# Convenience targets for common local commands
rag-status: local/rag-status
test-rag: local/test-rag
```

### Helm Makefile with Inline Credential Prompting

The cluster Makefile collects LLM API credentials interactively, generates a temporary values file, and passes it to helm:

```makefile
# deploy/helm/Makefile (excerpt)
NAMESPACE ?= $(shell oc project -q 2>/dev/null || echo "default")
MODEL_VALUES_FILE := /tmp/rhdp-values.yaml

define prompt_openai_credentials
	@bash -c '\
	if [ -z "$(OPENAI_API_TOKEN)" ]; then \
		echo -n "Enter LLM API TOKEN: "; \
		read -s OPENAI_API_TOKEN; echo ""; \
	else \
		OPENAI_API_TOKEN="$(OPENAI_API_TOKEN)"; \
	fi; \
	echo "backend:" > $(MODEL_VALUES_FILE); \
	echo "  secret:" >> $(MODEL_VALUES_FILE); \
	echo "    OPENAI_API_TOKEN: \"$$OPENAI_API_TOKEN\"" >> $(MODEL_VALUES_FILE); \
	# ... additional fields ...'
endef

install: namespace
	$(call prompt_openai_credentials)
	helm install $(ANSIBLE_LOG_MONITOR_CHART) ./ansible-log-monitor -n $(NAMESPACE) $(env_args) -f $(MODEL_VALUES_FILE)
	@rm -f $(MODEL_VALUES_FILE)
```

### Local Makefile with Hybrid Compose and Native Processes

The local Makefile starts compose services first, then launches native Python processes in the background:

```makefile
# deploy/local/Makefile (excerpt)
COMPOSE_CMD := $(shell command -v docker-compose 2>/dev/null || command -v podman-compose 2>/dev/null)

start: stop
	@$(MAKE) -s postgres
	@$(MAKE) -s phoenix
	@$(MAKE) -s loki-stack
	@$(MAKE) -s rag-stack & $(MAKE) -s aap-mock-stack & wait
	@$(MAKE) -s backend
	@$(MAKE) -s ui
	@$(MAKE) -s annotation

backend:
	@cd ../.. && uv run uvicorn alm.main_fastapi:app --reload &

ui:
	@cd ../../services/ui && uv run gradio app.py &

annotation:
	@cd ../../services/annotation_interface && uv run gradio app.py &
```

### Port Cleanup and Status Checking

The local Makefile includes cross-platform port killing (macOS `lsof` vs Linux `fuser`) and health checking:

```makefile
# deploy/local/Makefile (excerpt)
kill-ports:
	@if [ "$$(uname)" = "Darwin" ]; then \
		lsof -ti :7860 | xargs kill -9 2>/dev/null || true; \
	else \
		fuser -k 7860/tcp 2>/dev/null || true; \
	fi
```

### Training Pipeline Targets

The local Makefile includes targets for running the RAG initialization and backend training pipelines:

```makefile
# deploy/local/Makefile (excerpt)
run-whole-training-pipeline:
	@( cd ../.. && uv run --index-strategy unsafe-best-match services/rag/rag_init_pipeline.py )
	@( cd ../.. && uv run --index-strategy unsafe-best-match backend_init_pipeline.py )
```

## Configuration

- **Key settings:** `NAMESPACE` defaults to current `oc project` or `"default"`; `COMPOSE_CMD` auto-detects between docker-compose and podman-compose; LLM credentials skip prompts when pre-set via environment or `.env` file
- **Defaults:** Helm release name `alm`; dual values files (`global-values.yaml` + `values.yaml`); temporary credentials file written to `/tmp/rhdp-values.yaml` and deleted after install
- **Dependencies:** Root Makefile requires no tools; Helm Makefile requires `oc`, `helm`; local Makefile requires compose runtime and `uv` for native Python processes

## Gotchas

- The Helm Makefile loads `.env` from `../../.env` (project root) using `include` with `export`, making all `.env` variables available as both Make and shell variables (see `deploy/helm/Makefile` lines 7-9)
- The local Makefile runs `rag-stack` and `aap-mock-stack` in parallel using `&` and `wait`, but backend/ui/annotation must start sequentially after compose services are up (see `deploy/local/Makefile` line 39)
- The credential prompting uses `read -s` for the API token (hidden input) but regular `read` for endpoint and model name (see `deploy/helm/Makefile` lines 40-43)
- The temporary values file at `/tmp/rhdp-values.yaml` contains plaintext secrets and is deleted after install, but a failed install could leave it on disk (see `deploy/helm/Makefile` line 140)

## Related Patterns

- `helm-umbrella-mixed-remote-local-committed-deps.md` -- the Helm chart installed by the cluster Makefile
- `compose-local-dev-loki-grafana-hybrid-services.md` -- the compose stack managed by the local Makefile
