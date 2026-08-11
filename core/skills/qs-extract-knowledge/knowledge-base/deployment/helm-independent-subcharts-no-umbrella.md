---
name: helm-independent-subcharts-no-umbrella
description: Nine independent Helm application charts deployed separately via Makefile without an umbrella chart
summary: "Deploys multi-component quickstarts (pgvector StatefulSet, KServe InferenceServices, FastAPI backend, SvelteKit frontend, optional MinIO/pgAdmin) using nine independent Helm application charts (`apiVersion: v2`, `type: application`, no `dependencies:` section) under `helm/` without an umbrella chart or ai-architecture-charts. Use when each component needs independent versioning and Makefile-sequenced `helm upgrade --install` rather than umbrella chart dependency management -- no `Chart.lock` or `helm dependency update` step exists; all charts are local and custom. The Makefile sequences installs (model -> database -> MCP server -> conditional llama-stack -> backend -> UI), wires cross-chart values via `--set` flags with runtime `oc get route` URL extraction, and defaults all images to `quay.io/rh-ai-quickstart/<name>:latest` with `pullPolicy: Always`. Charts reference each other via hardcoded Kubernetes service names (e.g., `pgvector-0.pgvector-postgres-service`), so renaming any chart's service requires manually updating all consumer values.yaml files, and the Makefile must run from `helm/` since chart paths are relative."
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
