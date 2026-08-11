---
name: helm-umbrella-mixed-remote-local-committed-deps
description: Umbrella Helm chart mixing remote ai-architecture-charts, declared local subcharts, and committed tgz bundles
summary: "Solves structuring a Helm umbrella chart that must combine remote ai-architecture-charts dependencies (pgvector, minio, mcp-servers), conditionally-declared local subcharts (aap-mock, rag), and undeclared charts auto-discovered from the charts/ directory including committed third-party tgz files (Grafana 10.1.4, Loki 6.45.2, Alloy 1.4.0) and local subchart directories (backend, ui, clustering, phoenix, annotation-interface, text-embeddings-inference). Use when some components lack ai-architecture-charts equivalents and need pinned third-party chart versions committed as tgz files alongside declared remote and local dependencies in a single umbrella chart -- only Approach A exists covering this mixed-sourcing strategy. Cross-chart configuration splits into a separate global-values.yaml (shared via {{ .Values.global }}) and values.yaml both passed via Makefile -f flags; conditional subcharts toggle via aap-mock.enabled and global.rag.enabled while undeclared local charts always install with no condition toggle. Committed tgz files bypass helm dependency update requiring manual tgz replacement for version upgrades, Chart.lock tracks only 5 of 14 total subcharts leaving 9 invisible to dependency management, and mcp-servers requires double-nested values keys (mcp-servers.mcp-servers.<server-name>)."
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

## Related Patterns

- `helm-inline-grafana-alerting-loki-webhook.md` -- values configuration for the committed Grafana and Loki tgz charts
- `helm-alloy-sidecar-pvc-log-collector.md` -- values configuration for the committed Alloy tgz chart
