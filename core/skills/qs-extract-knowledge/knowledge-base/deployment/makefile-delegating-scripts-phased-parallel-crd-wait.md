---
name: makefile-delegating-scripts-phased-parallel-crd-wait
description: Makefile delegates to bash scripts that install 18 Helm charts in 6 phases with parallel operators and CRD waits
summary: "Solves orchestrated multi-phase deployment of 18 independent Helm charts across 3 namespaces (observability-hub, llama-serve, openshift-user-workload-monitoring) by delegating Makefile targets to bash scripts that handle parallel operator installation via background PIDs, CRD readiness polling, and sequenced AI service rollout -- sourced from the lls-observability quickstart. Use when deploying complex multi-operator stacks (5+ operators) requiring CRD availability before instance creation, idempotent re-runnability via `helm list -q` release-exists guards, and a DEVICE env var (gpu/xeon) controlling AI service variants; also provides generic install-chart/template-chart/lint-chart targets searching numbered directories (01-operators through 04-mcp-servers). Six-phase orchestration: namespace creation, parallel operator install, CRD polling loops (12 retries x 5s) plus `oc wait --for=condition=Ready`, ordered observability (tempo->otel-collector->grafana, then UWM via `helm template | oc apply` for pre-existing platform ConfigMaps, then UI plugin), parallel MCP servers, and sequenced AI services with inter-component waits. Operator readiness checks use version-specific pod labels (e.g., `app.kubernetes.io/name=cluster-observability-operator`, `control-plane=controller-manager`) that may change between releases, AI workloads use a hardcoded `sleep 60` instead of readiness probes between model and llama-stack-instance, and the clean target's interactive `read -p` prompt breaks non-interactive CI pipelines."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, opentelemetry, grafana]
  ai_pattern: [agents, model-serving]
  platform: [openshift, vllm]
source_examples:
  - quickstart: "lls-observability"
    repo: "https://github.com/rh-ai-kickstart/llama-stack-observability"
    notes: "Makefile with 6 targets delegating to bash scripts that install 18 independent Helm charts across 3 namespaces with parallel operator install and CRD readiness polling"
    approach: "A"
---

# Makefile Delegating to Phased Bash Scripts with Parallel Install and CRD Waits

## Overview

This pattern uses a Makefile that delegates to dedicated bash scripts for multi-phase deployment of 18 independent Helm charts across three namespaces. The scripts implement parallel operator installation, CRD readiness polling loops, ordered observability infrastructure deployment, and idempotent release-exists checks before each install.

## Pattern Description

The Makefile provides six top-level targets (`setup`, `install-operators`, `deploy-observability`, `deploy-ai`, `install-all`, `validate`, `clean`) plus three generic targets (`install-chart`, `uninstall-chart`, `template-chart`, `lint-chart`) for individual chart operations. The `install-all` target delegates to `scripts/install-full-stack.sh`, which orchestrates a 6-phase deployment: namespace creation, parallel operator install, operator readiness waits with CRD polling, ordered observability deployment, parallel MCP server install, and sequenced AI service installation. Each phase has its own script that can also be run independently via individual Makefile targets.

## Implementation

### Makefile Structure

The Makefile delegates to scripts rather than running helm commands directly:

```makefile
# Makefile (top-level)
install-operators: setup
	@chmod +x scripts/install-operators.sh
	@./scripts/install-operators.sh

deploy-observability:
	@chmod +x scripts/deploy-observability.sh
	@./scripts/deploy-observability.sh

deploy-ai:
	@chmod +x scripts/deploy-ai-workloads.sh
	@./scripts/deploy-ai-workloads.sh

install-all: setup
	@chmod +x scripts/install-full-stack.sh
	@./scripts/install-full-stack.sh
```

### Parallel Operator Installation

The operator install script launches all 5 operator Helm installs in parallel using background processes:

```bash
# scripts/install-operators.sh
pids=()
for chart_dir in "$HELM_DIR/01-operators"/*; do
    if [ -d "$chart_dir" ] && [ -f "$chart_dir/Chart.yaml" ]; then
        chart_name=$(basename "$chart_dir")
        if release_exists "$chart_name"; then
            print_status "$chart_name already installed, skipping..."
            continue
        fi
        helm install "$chart_name" "$chart_dir" &
        pids+=($!)
    fi
done
for pid in "${pids[@]}"; do
    wait $pid
done
```

### CRD Readiness Polling Loop

After operator installation, scripts poll for CRD availability before deploying instances:

```bash
# scripts/deploy-observability.sh
retries=0
while ! oc get crd uiplugins.observability.openshift.io >/dev/null 2>&1; do
    if [ $retries -ge 12 ]; then
        print_error "UIPlugin CRD not available after 60 seconds"
        break
    fi
    print_status "Waiting for UIPlugin CRD... (attempt $((retries + 1))/12)"
    sleep 5
    retries=$((retries + 1))
done
```

### Idempotent Release Checks

Every install is guarded by a release existence check:

```bash
# scripts/install-full-stack.sh
release_exists() {
    local release_name=$1
    local namespace=${2:-$DEFAULT_NAMESPACE}
    helm list -q -n "$namespace" | grep -q "^${release_name}$"
}
```

### Six-Phase Full Stack Install

```bash
# scripts/install-full-stack.sh (main function structure)
# Phase 1: Create namespaces (observability-hub, openshift-user-workload-monitoring, llama-serve)
# Phase 2: Install operators (parallel via install_charts_in_directory "01-operators" "true")
# Phase 3: Wait for operators (oc wait --for=condition=Ready + CRD polling)
# Phase 4: Deploy observability (ordered: tempo -> otel-collector -> grafana, then UWM, then UI plugin)
# Phase 5: Deploy MCP servers (parallel via install_charts_in_directory "04-mcp-servers" "true")
# Phase 6: Deploy AI services (sequenced: llama3-2-3b -> wait -> llama-stack-instance -> playground -> guard)
```

### Generic Chart Operations

The Makefile also provides generic targets that search all four chart directories:

```makefile
# Makefile (install-chart target)
install-chart:
	@if [ -z "$(CHART)" ]; then echo "Usage: make install-chart CHART=chart-name"; exit 1; fi
	@if [ -d "helm/01-operators/$(CHART)" ]; then \
		helm install $(CHART) helm/01-operators/$(CHART); \
	elif [ -d "helm/02-observability/$(CHART)" ]; then \
		helm install $(CHART) helm/02-observability/$(CHART) -n $$NAMESPACE; \
	elif [ -d "helm/03-ai-services/$(CHART)" ]; then \
		helm install $(CHART) helm/03-ai-services/$(CHART); \
	elif [ -d "helm/04-mcp-servers/$(CHART)" ]; then \
		helm install $(CHART) helm/04-mcp-servers/$(CHART); \
	fi
```

## Configuration

- **Key settings:** `DEVICE` env var (gpu or xeon) controls AI service deployment; `OBSERVABILITY_NAMESPACE` (default observability-hub), `AI_SERVICES_NAMESPACE` (default llama-serve), `OPERATOR_RELEASE_NAMESPACE` (default lls-observability) control namespace placement
- **Defaults:** Operators install in parallel; observability deploys sequentially in order (tempo, otel-collector, grafana); AI services deploy with 60s sleep between model and llama-stack-instance
- **Dependencies:** Requires `oc` CLI and `helm` CLI; OpenShift cluster with OLM; scripts must be run from the repository root

## Gotchas

- The UWM (User Workload Monitoring) chart is deployed via `helm template | oc apply -f-` rather than `helm install` because it manages ConfigMaps in platform namespaces (openshift-monitoring, openshift-user-workload-monitoring) that may already exist (see `scripts/deploy-observability.sh`)
- Operator readiness checks use specific pod labels per operator (e.g., `app.kubernetes.io/name=cluster-observability-operator`, `control-plane=controller-manager` for Grafana) which are operator-specific and may change between versions (see `scripts/install-full-stack.sh` wait_for_operators function)
- The `clean` target uses an interactive `read -p` confirmation prompt, making it unsuitable for non-interactive CI environments (see Makefile clean target)
- AI workloads deploy with a hardcoded `sleep 60` between the model and llama-stack-instance to allow model initialization, rather than using a readiness check (see `scripts/deploy-ai-workloads.sh`)

## Related Patterns

- `observability-olm-operator-helm-install.md` -- the individual operator charts installed in Phase 2
- `helm-independent-subcharts-no-umbrella.md` -- the independent chart pattern used here with numbered directory organization
