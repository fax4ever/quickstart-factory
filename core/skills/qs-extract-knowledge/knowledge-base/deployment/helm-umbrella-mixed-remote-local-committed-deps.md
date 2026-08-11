---
name: helm-umbrella-mixed-remote-local-committed-deps
description: Umbrella Helm chart mixing remote ai-architecture-charts, declared local subcharts, and committed tgz bundles
summary: "Solves structuring a Helm umbrella chart that must combine remote ai-architecture-charts dependencies (pgvector, minio, mcp-servers), conditionally-declared local subcharts (aap-mock, rag), and undeclared charts auto-discovered from the charts/ directory including committed third-party tgz files (Grafana, Loki, Alloy) and local subchart directories (backend, ui, clustering, phoenix, annotation-interface, text-embeddings-inference). Use Approach A (ansible-log-analysis) when third-party charts lack ai-architecture-charts equivalents and need pinned tgz versions committed in charts/ alongside declared remote and local deps with partial Chart.lock tracking (5 of 14); use Approach B (it-self-service-agent) when all deps can be declared in Chart.yaml with `file://` for local subcharts and optional components (nemo-guardrails, zammad-demo-site) deploy as separate `helm upgrade --install` releases with CRD prerequisite checks, achieving complete dependency tracking. Cross-chart configuration splits into a separate global-values.yaml (shared via {{ .Values.global }}) and values.yaml both passed via Makefile -f flags; conditional subcharts toggle via aap-mock.enabled and global.rag.enabled while Approach A's undeclared local charts always install with no condition toggle. Committed tgz files bypass helm dependency update requiring manual tgz replacement for version upgrades, Chart.lock in Approach A tracks only 5 of 14 total subcharts leaving 9 invisible to dependency management, and mcp-servers requires double-nested values keys (mcp-servers.mcp-servers.<server-name>)."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, grafana, loki, alloy]
  ai_pattern: [agents, rag, embeddings]
  platform: [openshift]
  data_layer: [pgvector, minio, faiss]
source_examples:
  - quickstart: "ansible-log-analysis"
    repo: "https://github.com/rh-ai-quickstart/ansible-log-analysis"
    notes: "3 remote deps, 2 declared local deps, 6 undeclared local chart dirs, 3 committed tgz files"
    approach: "A"
  - quickstart: "it-self-service-agent"
    repo: "https://github.com/rh-ai-quickstart/it-self-service-agent"
    notes: "4 remote deps, 1 declared local dep (file://), no committed tgz, separate releases for optional components"
    approach: "B"
---

# Helm Umbrella with Mixed Remote, Local, and Committed Dependencies

## Overview

This pattern uses an umbrella Helm chart that combines three different dependency sourcing strategies: remote subcharts from the ai-architecture-charts repository (declared in Chart.yaml), local subcharts declared in Chart.yaml with conditional enablement, and undeclared charts placed directly in the `charts/` directory as both directories and pre-packaged `.tgz` files. This hybrid approach accommodates components that have no ai-architecture-charts equivalent.

## Pattern Description

The umbrella chart at `deploy/helm/ansible-log-monitor/` declares five dependencies in `Chart.yaml` (three remote, two local with conditions), but the `charts/` directory also contains six additional local subchart directories and three committed `.tgz` files that are not declared as Chart.yaml dependencies. Helm discovers these undeclared charts automatically by scanning the `charts/` directory. The committed `.tgz` files are third-party charts (Grafana, Loki, Alloy) pinned to specific versions.

## Implementation

### Chart.yaml with Declared Dependencies

Only five of the fourteen total subcharts are declared in Chart.yaml:

```yaml
# deploy/helm/ansible-log-monitor/Chart.yaml
dependencies:
  # External dependencies from remote repositories
  - name: pgvector
    version: 0.1.0
    repository: https://rh-ai-quickstart.github.io/ai-architecture-charts
  - name: minio
    version: 0.1.0
    repository: https://rh-ai-quickstart.github.io/ai-architecture-charts
  - name: mcp-servers
    version: 0.5.7
    repository: https://rh-ai-quickstart.github.io/ai-architecture-charts
  
  # Local sub-charts (aap-mock is optional for testing/demos)
  - name: aap-mock
    version: 0.1.0
    condition: aap-mock.enabled
  - name: rag
    version: 0.1.0
    condition: global.rag.enabled
```

### Charts Directory Contents

The `charts/` directory contains all dependency types side by side:

```
charts/
  # Committed pre-packaged third-party charts (not in Chart.yaml)
  alloy-1.4.0.tgz
  grafana-10.1.4.tgz
  loki-6.45.2.tgz
  # Downloaded remote charts (from Chart.yaml)
  mcp-servers-0.5.7.tgz
  minio-0.1.0.tgz
  pgvector-0.1.0.tgz
  # Local subchart directories (some in Chart.yaml, some not)
  aap-mock/          # declared in Chart.yaml
  rag/               # declared in Chart.yaml
  annotation-interface/  # undeclared
  backend/               # undeclared
  clustering/            # undeclared
  phoenix/               # undeclared
  text-embeddings-inference/  # undeclared
  ui/                    # undeclared
```

### Global Values for Cross-Chart Configuration

A separate `global-values.yaml` provides shared configuration that subcharts can reference via `{{ .Values.global }}`:

```yaml
# deploy/helm/ansible-log-monitor/global-values.yaml
global:
  ingress:
    enabled: true
    className: "nginx"
    domain: "ansible-logs.local"
  servicesNames:
    backend: "alm-backend"
    annotationInterface: "alm-annotation-interface"
    clustering: "alm-clustering"
    ui: "alm-ui"
    embedding: "alm-embedding"
    rag: "alm-rag"
  rag:
    enabled: true
    serviceUrl: "http://alm-rag:8002"
    embedding:
      apiUrl: "http://alm-embedding:8080"
```

### Helm Install with Dual Values Files

The Helm Makefile passes both global and main values files:

```makefile
# deploy/helm/Makefile (excerpt)
env_args = \
    -f ansible-log-monitor/global-values.yaml \
    -f ansible-log-monitor/values.yaml

install: namespace
    $(call prompt_openai_credentials)
    helm install $(ANSIBLE_LOG_MONITOR_CHART) ./ansible-log-monitor -n $(NAMESPACE) $(env_args) -f $(MODEL_VALUES_FILE)
```

## Configuration

- **Key settings:** `aap-mock.enabled` and `global.rag.enabled` toggle the two conditionally-declared local subcharts; committed tgz versions are pinned by the filename
- **Defaults:** `aap-mock.enabled: true` (see `values.yaml` line 719); `global.rag.enabled: true` (see `global-values.yaml`)
- **Dependencies:** Remote deps require `helm dependency update` (or `helm dep build`); committed tgz and local directories do not

## Gotchas

- The `mcp-servers` subchart requires double-nested keys in values (`mcp-servers.mcp-servers.<server-name>`) because the chart's internal values structure expects server definitions under its own `mcp-servers` key (visible in `deploy/helm/ansible-log-monitor/values.yaml` lines 36-49)
- Grafana, Loki, and Alloy are committed as `.tgz` files rather than declared in Chart.yaml, meaning `helm dependency update` does not manage their versions -- version upgrades require manually replacing the tgz files
- The Chart.lock only tracks the five declared dependencies; the three committed tgz charts and six undeclared local directories are invisible to `helm dependency update`
- The undeclared local subcharts (backend, ui, annotation-interface, clustering, phoenix, text-embeddings-inference) have no `condition` toggle and are always installed

---

## Approach B: Clean Remote + Local Without Committed Deps (from it-self-service-agent)

### When to Use

When all remote dependencies are declared in Chart.yaml with conditions and the only local subchart uses `file://` syntax -- no committed tgz files and no undeclared charts in the `charts/` directory. Optional components that need independent lifecycle management are deployed as separate Helm releases rather than subcharts.

### Differences from Approach A

- No committed `.tgz` files -- all remote deps managed by `helm dependency update`
- No undeclared charts auto-discovered from `charts/` directory
- Uses `file://` syntax for local subcharts (`repository: "file://./zammad"`)
- Optional components (nemo-guardrails, zammad-demo-site) deployed as separate `helm upgrade --install` releases rather than subcharts
- All 5 dependencies are declared and tracked by Chart.lock

### Chart.yaml with Conditional Dependencies

```yaml
# helm/Chart.yaml
dependencies:
  - name: pgvector
    version: 0.1.0
    repository: https://rh-ai-quickstart.github.io/ai-architecture-charts
  - name: llm-service
    version: 0.5.6
    repository: https://rh-ai-quickstart.github.io/ai-architecture-charts
    condition: llm-service.enabled
  - name: llama-stack
    version: 0.8.5
    repository: https://rh-ai-quickstart.github.io/ai-architecture-charts
  - name: mcp-servers
    version: 0.5.17
    repository: https://rh-ai-quickstart.github.io/ai-architecture-charts
    condition: mcp-servers.enabled
  - name: ticketingZammad
    version: 0.1.0
    repository: "file://./zammad"
    condition: ticketingZammad.enabled
```

### Separate Helm Releases for Optional Components

NeMo Guardrails is deployed as an independent Helm release via a dedicated Makefile target:

```makefile
# Makefile (excerpt)
deploy-nemo-guardrails: namespace
	@if ! oc get crd nemoguardrails.trustyai.opendatahub.io &>/dev/null; then \
		echo "NemoGuardrails CRD not found. Ensure RHOAI 3.3+ is installed."; \
		exit 1; \
	fi
	@helm upgrade --install nemo-guardrails $(NEMO_GUARDRAILS_CHART) \
		-n $(NAMESPACE) \
		--set llm.url=http://llamastack:8321/v1 \
		--set llm.modelId=$(LLM_ID)
```

---

## Choosing Between Approaches

| Criteria | Approach A | Approach B |
|----------|-----------|-----------|
| Third-party charts | Committed as tgz files | Not used |
| Dependency tracking | Partial (5 of 14 in Chart.lock) | Complete (all 5 in Chart.lock) |
| Undeclared charts | 9 auto-discovered from charts/ | None |
| Local subchart syntax | Directory in charts/ | `file://` in Chart.yaml |
| Optional components | Subchart conditions | Separate Helm releases |
| Version management | Manual tgz replacement for committed charts | All via `helm dependency update` |

## Related Patterns

- `helm-inline-grafana-alerting-loki-webhook.md` -- values configuration for the committed Grafana and Loki tgz charts (Approach A)
- `helm-alloy-sidecar-pvc-log-collector.md` -- values configuration for the committed Alloy tgz chart (Approach A)
- `helm-knative-kafka-cloudevents-triggers.md` -- eventing templates within the Approach B umbrella chart
- `makefile-multi-profile-helm-install.md` -- Makefile targets that install the Approach B umbrella chart
