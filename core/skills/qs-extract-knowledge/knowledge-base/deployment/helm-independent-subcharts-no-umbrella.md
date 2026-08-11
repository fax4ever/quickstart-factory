---
name: helm-independent-subcharts-no-umbrella
description: Nine independent Helm application charts deployed separately via Makefile without an umbrella chart
summary: "Deploys multi-component AI quickstarts (pgvector StatefulSet, KServe InferenceServices, FastAPI backend, SvelteKit frontend, optional MinIO/pgAdmin) using independent Helm application charts (`apiVersion: v2`, `type: application`, no `dependencies:` section) under `helm/` without an umbrella chart or ai-architecture-charts. Approach A deploys 9 flat charts in a single namespace via Makefile-sequenced `helm upgrade --install` with `--set` flags and runtime `oc get route` URL extraction (install order: model -> database -> MCP server -> conditional llama-stack -> backend -> UI); Approach B deploys 18 charts in numbered directories (`01-operators/` through `04-mcp-servers/`) across 3 namespaces via bash scripts with parallel install within phases -- choose A for smaller single-namespace deployments and B for larger multi-namespace phased rollouts. All custom images default to `quay.io/rh-ai-quickstart/<name>:latest` with `pullPolicy: Always`; Approach A wires cross-chart values at deploy time via Makefile `--set` flags while Approach B embeds cross-namespace service DNS defaults (e.g., `mcp-weather.llama-serve.svc.cluster.local`) directly in values.yaml. Cross-chart service references are hardcoded strings (e.g., `pgvector-0.pgvector-postgres-service`), so renaming any chart's service requires manually updating all consumer values.yaml files; no `Chart.lock` or `helm dependency update` step exists since all charts are independent and versioned at `0.1.0`; and the Makefile must run from `helm/` since chart paths are relative."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, fastapi, sveltekit, postgresql, vllm]
  ai_pattern: [agents, model-serving]
  platform: [kserve, vllm, rhoai, openshift]
  data_layer: [pgvector]
source_examples:
  - quickstart: "data-governance-co-pilot"
    repo: "https://github.com/rh-ai-quickstart/data-governance-co-pilot"
    notes: "9 independent charts under helm/ with no umbrella Chart.yaml; Makefile sequences installs"
    approach: "A"
  - quickstart: "lls-observability"
    repo: "https://github.com/rh-ai-kickstart/llama-stack-observability"
    notes: "18 independent charts in numbered directories (01-operators/, 02-observability/, 03-ai-services/, 04-mcp-servers/) orchestrated by bash scripts across 3 namespaces"
    approach: "B"
---

# Independent Helm Subcharts without Umbrella Chart

## Overview

This pattern deploys a multi-component quickstart using independent Helm application charts, each installed separately via `helm upgrade --install` calls orchestrated by a Makefile. Unlike the umbrella chart pattern (where a parent Chart.yaml declares dependencies), each chart is self-contained with its own Chart.yaml, values.yaml, and templates -- there is no parent chart and no `helm dependency update` step.

## Pattern Description

All charts live under `helm/` as sibling directories. Each has `apiVersion: v2` and `type: application` with no `dependencies:` section. The Makefile replaces the umbrella chart's dependency management by controlling install order, passing cross-chart values via `--set` flags, and coordinating waits between components. No ai-architecture-charts are used; all charts are local and custom.

## Implementation

### Chart Directory Layout

```
helm/
  Makefile              # Orchestrates all installs
  pgvector/             # PostgreSQL + pgvector (StatefulSet)
  minio/                # MinIO object storage (optional)
  pgadmin/              # pgAdmin UI (optional)
  pg-airman-mcp/        # PostgreSQL MCP server
  nemotron-model/       # KServe InferenceService (Nemotron)
  qwen3-model/          # KServe InferenceService (Qwen3)
  copilot-backend/      # FastAPI backend (Deployment)
  copilot-ui/           # SvelteKit frontend (Deployment)
  copilot-llama-stack/  # Llama Stack distribution (CRD)
```

### Chart.yaml Pattern (No Dependencies)

Each chart is a standalone application chart with no declared dependencies:

```yaml
# helm/copilot-backend/Chart.yaml
apiVersion: v2
name: copilot-backend
description: Data Governance Copilot Backend Service
type: application
version: 0.1.0
appVersion: "0.1.0"
```

### Cross-Chart Value Wiring via Makefile

Since there is no umbrella `values.yaml`, the Makefile passes cross-chart references via `--set` flags. For example, the copilot-ui install extracts the backend route URL at deploy time:

```makefile
# helm/Makefile (copilot-ui-install target)
@BACKEND_URL=$$(oc get route copilot-backend -o jsonpath='https://{.spec.host}' \
  -n $(NAMESPACE) 2>/dev/null || echo "http://copilot-backend:8080"); \
helm -n $(NAMESPACE) upgrade --install copilot-ui $(COPILOT_UI_CHART) \
    --set backend.url=$$BACKEND_URL \
    --timeout 5m
```

### Hardcoded Service References

Charts reference each other via hardcoded Kubernetes service names rather than Helm template variables:

```yaml
# helm/copilot-backend/values.yaml
mcp:
  serviceUrl: "http://pg-airman-mcp-service:8000"
```

```yaml
# helm/pg-airman-mcp/values.yaml
postgres:
  host: pgvector-0.pgvector-postgres-service
```

## Configuration

- **Key settings:** Each chart independently defines its own `image.repository`, `service.port`, `resources`, and probe configurations
- **Defaults:** All custom application images default to `quay.io/rh-ai-quickstart/<name>:latest` with `pullPolicy: Always`
- **Dependencies:** Install order is managed entirely by the Makefile's `install` target, which sequences: model (optional, background) -> minio (optional) -> database -> pgadmin (optional) -> pg-airman-mcp -> llama-stack (conditional) -> copilot-backend -> copilot-ui

## Gotchas

- Cross-chart service references are hardcoded strings (e.g., `pgvector-0.pgvector-postgres-service`), so changing a chart's service name requires updating all consumers manually (see `helm/copilot-backend/values.yaml` and `helm/pg-airman-mcp/values.yaml`)
- There is no `helm dependency update` or `Chart.lock` -- each chart is fully independent and versioned at `0.1.0`
- The Makefile must be run from the `helm/` directory since chart paths are relative (e.g., `helm -n $(NAMESPACE) upgrade --install postgres $(POSTGRES_CHART)` references `pgvector/`)

## Related Patterns

- `helm-umbrella-all-remote-ai-arch-deps.md` -- alternative approach using an umbrella chart with remote dependencies
- `makefile-feature-flag-conditional-deploy-model-extract.md` -- the Makefile orchestration pattern used with these independent charts

---

## Approach B: Numbered Directory Organization with Bash Script Orchestration (from lls-observability)

### When to Use

When deploying a larger number of independent charts (18+) that span multiple deployment phases (operators, observability infrastructure, AI services, tooling) across multiple namespaces, requiring phased ordering with parallel installation within phases.

### Differences from Approach A

- Charts organized in numbered directories (`helm/01-operators/`, `helm/02-observability/`, `helm/03-ai-services/`, `helm/04-mcp-servers/`) instead of flat siblings under `helm/`
- Orchestrated by 4 bash scripts under `scripts/` instead of a Makefile with individual helm targets
- Deploys across 3 namespaces (observability-hub, llama-serve, default for operators) vs a single namespace
- Parallel installation within phases (operators installed concurrently via background processes)
- Cross-chart references via values.yaml defaults with hardcoded service DNS names instead of Makefile `--set` runtime extraction

### Numbered Directory Layout

```
helm/
  01-operators/
    cluster-observability-operator/
    grafana-operator/
    llama-stack-operator/
    otel-operator/
    tempo-operator/
  02-observability/
    distributed-tracing-ui-plugin/
    grafana/
    otel-collector/
    tempo/
    uwm/
  03-ai-services/
    llama3.2-3b/
    llama-guard/
    llama-stack/
    llama-stack-instance/
    llama-stack-playground/
  04-mcp-servers/
    hr-api/
    mcp-weather/
    openshift-mcp/
```

### Cross-Chart References via Values Defaults

Instead of Makefile `--set` flags, charts embed default cross-namespace service references:

```yaml
# helm/03-ai-services/llama-stack-instance/values.yaml
mcpServers:
  - name: "weather"
    uri: "http://mcp-weather.llama-serve.svc.cluster.local:80"
  - name: "openshift"
    uri: "http://ocp-mcp-server.llama-serve.svc.cluster.local:8000"

# helm/02-observability/otel-collector/values.yaml
tempo:
  gateway:
    endpoint: "tempo-tempostack-gateway"
    namespace: "observability-hub"
```

---

## Choosing Between Approaches

| Criteria | Approach A | Approach B |
|----------|-----------|-----------|
| Chart count | 9 charts | 18 charts |
| Directory structure | Flat under helm/ | Numbered phase directories (01-04) |
| Namespace scope | Single namespace | 3 namespaces (observability-hub, llama-serve, default) |
| Orchestration | Makefile with sequential helm targets | Bash scripts with parallel install support |
| Cross-chart wiring | Makefile `--set` with runtime `oc get route` | Values.yaml defaults with hardcoded service DNS |
| Install parallelism | Sequential only | Parallel within phases (background processes) |
