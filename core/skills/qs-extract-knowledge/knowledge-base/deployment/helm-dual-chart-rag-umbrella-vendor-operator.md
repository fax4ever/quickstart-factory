---
name: helm-dual-chart-rag-umbrella-vendor-operator
description: Two independent Helm charts -- RAG umbrella with ai-architecture-charts deps and vendor operator chart -- sequenced by Makefile
summary: "Splits a quickstart into two independent Helm charts under deploy/helm/: a RAG umbrella (deploy/helm/rag/ with pgvector, llm-service, llama-stack from ai-architecture-charts plus Streamlit frontend) and a standalone vendor operator chart (deploy/helm/f5-ai-security/ managing OLM Subscription, CRs, SCC anyuid bindings, Moderator routes, and Prefect RBAC across four namespaces: f5-ai-sec, cai-moderator, prefect, f5-ai-sec-inference). Use when pairing a RAG stack with a third-party operator needing independent lifecycle, separate namespaces, optional skip via SKIP_F5_GUARDRAILS, and per-chart values files (rag-values.yaml, f5-ai-security-values.yaml); model config is shared between llm-service and llama-stack via global.models. Makefile sequences deployment: depend target runs helm dependency update, RAG chart installs first with `oc rollout status deploy/llamastack --timeout=900s`, then conditionally chains to standalone install-f5-ai-security target with MODERATOR_HOST_AUTO/MODERATOR_HOST_PREFIX for auto-derived Moderator URL. Independent Helm releases require separate `helm uninstall` per chart (Makefile uninstall target handles both), Streamlit guardrails state in emptyDir volume (/data/guardrails_state.json) is lost on pod replacement, and LlamaStack rollout must complete before F5 chart installs because operator inference models connect to model endpoints."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, streamlit, llamastack, vllm, postgresql]
  ai_pattern: [rag, guardrails]
  platform: [kserve, vllm, rhoai, openshift]
  data_layer: [pgvector]
source_examples:
  - quickstart: "f5-ai-guardrails"
    repo: "https://github.com/rh-ai-quickstart/f5-ai-guardrails"
    notes: "RAG umbrella chart (pgvector, llm-service, llama-stack) + standalone f5-ai-security operator chart, sequenced by Makefile install target"
    approach: "A"
---

# Dual Helm Chart: RAG Umbrella plus Vendor Operator

## Overview

This pattern splits a quickstart into two independent Helm charts with different lifecycles: an umbrella chart for the RAG application stack (using ai-architecture-charts remote dependencies) and a separate standalone chart for a vendor-provided operator (managing OLM Subscription, custom CRs, RBAC, and routes). A Makefile sequences the two installs and handles cross-chart coordination.

## Pattern Description

The RAG chart (`deploy/helm/rag/`) is a standard umbrella chart with three remote ai-architecture-charts dependencies (pgvector, llm-service, llama-stack) plus application-specific templates for the Streamlit frontend deployment, service, route, and configmap. The F5 AI Security chart (`deploy/helm/f5-ai-security/`) is a standalone chart with no subchart dependencies -- it manages the operator lifecycle declaratively. The Makefile's `install` target deploys the RAG chart first (with rollout wait), then conditionally deploys the F5 chart via `install-f5-ai-security`. The `SKIP_F5_GUARDRAILS` flag allows installing only the RAG stack.

## Implementation

### RAG Umbrella Chart Dependencies

```yaml
# deploy/helm/rag/Chart.yaml
apiVersion: v2
name: f5-ai-guardrails
type: application
version: 1.0.0

dependencies:
  - name: pgvector
    version: 0.1.0
    repository: https://rh-ai-quickstart.github.io/ai-architecture-charts
  - name: llm-service
    version: 0.5.2
    repository: https://rh-ai-quickstart.github.io/ai-architecture-charts
  - name: llama-stack
    version: 0.8.6
    repository: https://rh-ai-quickstart.github.io/ai-architecture-charts
```

### Vendor Operator Chart (No Subchart Dependencies)

```yaml
# deploy/helm/f5-ai-security/Chart.yaml
apiVersion: v2
name: f5-ai-security
description: >-
  OpenShift manifests for F5 AI Security Operator (OLM), SecurityOperator CR,
  SCC anyuid bindings, Moderator routes, and Prefect worker cluster RBAC.
type: application
version: 0.1.0
appVersion: "0.8.1"
```

### Makefile Sequencing

The `install` target deploys the RAG chart first with rollout wait, then chains to the F5 chart unless `SKIP_F5_GUARDRAILS` is set:

```makefile
# deploy/helm/Makefile (install target, lines 519-590)
install:
	@$(MAKE) namespace
	@$(MAKE) depend
	@$(MAKE) delete-jobs
	@$(call check_values_file)
	@helm -n $(NAMESPACE) upgrade --install $(RAG_CHART) $(RAG_CHART) -n $(NAMESPACE) $$HELM_ARGS
	@oc rollout status deploy/llamastack -n $(NAMESPACE) --timeout=900s
	@if [ -n "$(SKIP_F5_GUARDRAILS)" ]; then \
		echo "SKIP_F5_GUARDRAILS is set; skipping F5 AI Security chart."; \
	else \
		$(MAKE) install-f5-ai-security; \
	fi
```

### Separate Namespaces per Chart

The RAG chart deploys into a user-specified `NAMESPACE`, while the F5 chart manages four dedicated namespaces (`f5-ai-sec`, `cai-moderator`, `prefect`, `f5-ai-sec-inference`):

```makefile
# deploy/helm/Makefile (namespace config)
F5_AI_SECURITY_NAMESPACE ?= f5-ai-sec
F5_MODERATOR_NS ?= cai-moderator
F5_PREFECT_NS ?= prefect
F5_INFERENCE_NS ?= f5-ai-sec-inference
```

### Separate Values Files

Each chart has its own values file: `rag-values.yaml` for the RAG chart and `f5-ai-security-values.yaml` for the vendor operator chart, each initialized from its own `.yaml.example`:

```makefile
VALUES_FILE := rag-values.yaml
F5_AI_SECURITY_VALUES ?= f5-ai-security-values.yaml
```

## Configuration

- **Key settings:** `SKIP_F5_GUARDRAILS` (non-empty to skip F5 chart); `NAMESPACE` for RAG stack; `F5_AI_SECURITY_NAMESPACE` for operator; `MODERATOR_HOST_AUTO`/`MODERATOR_HOST_PREFIX` for auto-derived Moderator URL
- **Defaults:** RAG namespace is user-specified; F5 namespaces default to product-standard names; model configuration uses `global.models` shared between `llm-service` and `llama-stack` subcharts
- **Dependencies:** RAG chart requires `helm dependency update` (Makefile `depend` target); F5 chart has no external chart dependencies

## Gotchas

- The RAG chart and F5 chart have independent Helm releases in different namespaces -- `helm uninstall` must be run separately for each, and the Makefile's `uninstall` target handles both (see `deploy/helm/Makefile` lines 733-755)
- The F5 chart's `install-f5-ai-security` target is called by `install` but also available as a standalone target for re-installing only the operator chart
- The Streamlit frontend's guardrails state is stored in an emptyDir volume (`/data/guardrails_state.json`) -- the F5 Moderator URL and API token configured in the UI are lost if the pod is replaced (see `deploy/helm/rag/values.yaml` lines 38-39)
- LlamaStack rollout must complete before the F5 chart can be installed because the F5 operator's inference models need to connect to the model endpoints (see `deploy/helm/Makefile` line 584: `oc rollout status deploy/llamastack --timeout=900s`)

## Related Patterns

- `helm-umbrella-all-remote-ai-arch-deps.md` -- the RAG chart follows this pattern with 3 remote deps
- `helm-olm-subscription-crd-lookup-securityoperator.md` -- what the F5 chart deploys internally
- `makefile-two-phase-helm-crd-wait-scc-preapply.md` -- how the F5 chart installation is orchestrated
