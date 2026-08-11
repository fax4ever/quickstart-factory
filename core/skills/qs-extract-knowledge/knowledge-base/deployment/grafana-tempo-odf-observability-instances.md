---
name: grafana-tempo-odf-observability-instances
description: Helm charts deploying Grafana instance with Prometheus/Tempo datasources and TempoStack with ODF storage
summary: "Deploys configured Grafana and TempoStack observability instances via Helm charts on OpenShift, connecting Grafana (grafana.integreatly.org/v1beta1 CRs) to Thanos Querier for Prometheus metrics and Tempo gateway for distributed traces, with an embedded vLLM GrafanaDashboard bound via instanceSelector.matchLabels using namespace/model template variables. Use after OLM observability operators are installed (see observability-olm-operator-helm-install) when you need a Grafana instance with Prometheus/Tempo datasources and ODF-backed trace storage; pairs with otel-sidecar-inject-vllm-model-metrics for trace ingestion and helm-uwm-podmonitor-vllm for metrics collection into the Prometheus datasource Grafana queries. Grafana datasource authenticates to Thanos Querier at openshift-monitoring.svc.cluster.local:9091 via SA bearer token (grafana-sa-token secret, tlsSkipVerify: true); TempoStack uses ODF ObjectBucketClaim (storageClassName: openshift-storage.noobaa.io, 15Gi default) with OpenShift-native multi-tenancy (dev tenant, hardcoded tenant ID); Grafana admin defaults to rhaifn/rhaifn. The grafana.clusterDomain value is environment-specific and controls the Route hostname; the dev tenant name must match both the OTel collector's X-Scope-OrgID header and the Tempo gateway URL path; vLLM dashboard assumes KServe model pods expose metrics under job names ending in -metrics; SA token secret requires correct OpenShift annotation to auto-populate the bearer token."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, grafana, opentelemetry]
  ai_pattern: [model-serving]
  platform: [openshift]
source_examples:
  - quickstart: "aml-rag-nvidia"
    repo: "https://github.com/rh-ai-quickstart/aml-rag-nvidia"
    notes: "Grafana instance with vLLM dashboard, Tempo/Prometheus datasources, and TempoStack using ODF object storage"
    approach: "A"
---

# Grafana and TempoStack Observability Instances via Helm

## Overview

This pattern deploys configured observability instances (Grafana and TempoStack) via separate Helm charts, connecting Grafana to both the cluster Prometheus (Thanos Querier) and a TempoStack trace backend backed by ODF object storage. A pre-built vLLM metrics dashboard is embedded in the chart as a GrafanaDashboard custom resource.

## Pattern Description

After the observability operators are installed (via the OLM pattern), these charts create the actual instances. The Grafana chart deploys a Grafana CR with datasource CRs pointing to Thanos Querier for metrics and Tempo gateway for traces, plus GrafanaDashboard CRs with embedded JSON dashboard definitions. The Tempo chart deploys a TempoStack CR using an ODF ObjectBucketClaim for trace storage. Both charts manage their own RBAC for cross-namespace data access.

## Implementation

### Grafana Datasources

Prometheus and Tempo datasources are created as GrafanaDatasource CRs:

```yaml
# charts/observability/helm/grafana/templates/datasources.yaml (pattern)
spec:
  datasource:
    name: Prometheus
    type: prometheus
    access: proxy
    url: "https://thanos-querier.openshift-monitoring.svc.cluster.local:9091"
    jsonData:
      httpHeaderName1: Authorization
      tlsSkipVerify: true
    secureJsonData:
      httpHeaderValue1: "Bearer ${token}"

  # Tempo datasource
  datasource:
    name: Tempo
    type: tempo
    url: "https://tempo-tempostack-gateway.observability-hub.svc.cluster.local:8081/api/traces/v1/dev/tempo"
```

### Embedded vLLM Dashboard

A GrafanaDashboard CR contains the full dashboard JSON inline:

```yaml
# charts/observability/helm/grafana/templates/vllm-dashboard.yaml (excerpt)
kind: GrafanaDashboard
apiVersion: grafana.integreatly.org/v1beta1
metadata:
  name: vllm-{{ include "grafana.fullname" . }}
spec:
  instanceSelector:
    matchLabels:
      dashboards: grafana
  json: |
    {
      "title": "vLLM Metrics - All Models",
      "templating": {
        "list": [
          {
            "name": "namespace",
            "query": "label_values(up{job=~\".*-metrics\"}, namespace)",
            "type": "query"
          },
          {
            "name": "model",
            "query": "label_values(up{namespace=~\"$namespace\"}, job)",
            "type": "query"
          }
        ]
      }
    }
```

### TempoStack with ODF Storage

The TempoStack uses an ObjectBucketClaim for trace storage:

```yaml
# charts/observability/helm/tempo/values.yaml (excerpt)
tempoStack:
  name: tempostack
  storageSize: 15Gi
  tenants:
    mode: openshift
    authentication:
      - tenantName: dev
        tenantId: "1610b0c3-c509-4592-a256-a1871353dbfa"
  template:
    gateway:
      enabled: true

objectStorage:
  bucketName: tempo-traces
  storageClassName: openshift-storage.noobaa.io
```

### Grafana RBAC for Cross-Namespace Metrics

```yaml
# charts/observability/helm/grafana/templates/rbac.yaml (pattern)
# ClusterRoleBinding granting Grafana SA access to Thanos Querier
# SA token secret provides bearer token for Prometheus datasource auth
```

## Configuration

- **Key settings:** `grafana.clusterDomain` must match the OpenShift cluster's route domain; `datasources.prometheus.url` points to Thanos Querier; `tempoStack.tenants.mode: openshift` enables OpenShift-native multi-tenancy
- **Defaults:** Grafana admin user/password both default to `rhaifn`; vLLM dashboard enabled by default; cluster metrics dashboard disabled; TempoStack storage 15Gi
- **Dependencies:** Grafana Operator and Tempo Operator installed via OLM; ODF for Tempo trace storage; Thanos Querier available at `openshift-monitoring` namespace

## Gotchas

- The `grafana.clusterDomain` value (`apps.launchpad.nvidia.com` in values.yaml) is environment-specific and must be updated per cluster; it determines the Grafana Route hostname
- The Grafana SA token secret (`grafana-sa-token`) is used for bearer token authentication to Thanos Querier; this secret must be annotated correctly for OpenShift to populate it
- The TempoStack tenant mode is `openshift` with a hardcoded tenant ID; the `dev` tenant name must match the OTel collector's `X-Scope-OrgID` header and the Tempo gateway path
- The vLLM dashboard uses Prometheus template variables that query `label_values(up{job=~\".*-metrics\"}, ...)` which assumes KServe model pods expose metrics under job names ending in `-metrics`

## Related Patterns

- `observability-olm-operator-helm-install.md` -- the operator charts that must be installed before these instance charts
- `otel-sidecar-inject-vllm-model-metrics.md` -- the OTel collector that sends traces to this TempoStack
- `helm-uwm-podmonitor-vllm.md` -- the PodMonitors that feed metrics into the Prometheus datasource Grafana queries
