---
name: grafana
description: "Grafana instance via Grafana Operator CRDs with Prometheus and Tempo datasources on OpenShift"
summary: "Grafana provides AI workload observability dashboarding on OpenShift, deployed as a Grafana Operator v5 CR (grafana.integreatly.org/v1beta1) with companion GrafanaDatasource and GrafanaDashboard CRDs that bind to the instance via instanceSelector.matchLabels (label: dashboards: grafana). Use this CRD-based approach when the Grafana Operator from community-operators catalog is available — it manages the full instance lifecycle, RBAC, and datasource wiring declaratively via Helm chart at helm/02-observability/grafana/, avoiding standalone container management. Datasources connect to Prometheus (Thanos Querier at thanos-querier.openshift-monitoring.svc.cluster.local:9091) and Tempo using service account token authentication injected via valuesFrom.secretKeyRef from a kubernetes.io/service-account-token secret; RBAC requires three ClusterRoleBindings (cluster-monitoring-view, openshift-cluster-monitoring-view, tempostack-traces-reader) plus a namespace edit RoleBinding targeting grafana-sa in observability-hub. Both dashboards (vLLM and cluster metrics) are disabled by default, grafana-sa name is hardcoded in RBAC templates and not overridable via Helm values, tlsSkipVerify: true is set on both datasources, default admin credentials are rhel/rhel in plain text, and the operator namespace (openshift-grafana-operator) and instance namespace (observability-hub) require two separate ordered Helm releases."
metadata:
  type: component
tags:
  tech_stack: [grafana, grafana-operator, helm]
  ai_pattern: [model-serving]
  platform: [openshift, kubernetes]
  observability: [prometheus, tempo, distributed-tracing, dashboards, vllm-metrics]
source_examples:
  - quickstart: "lls-observability"
    repo: "https://github.com/rh-ai-quickstart/lls-observability"
    notes: "Grafana instance with Prometheus and Tempo datasources, vLLM and cluster-metrics dashboards, deployed via Grafana Operator CRDs"
    approach: "A"
---

# Grafana

## Overview

Grafana provides visualization and dashboarding for AI workload observability on OpenShift. In this quickstart it is deployed as a Grafana Operator custom resource (`grafana.integreatly.org/v1beta1`), not as a standalone container or Helm community chart. The operator manages the Grafana instance lifecycle, while companion CRDs (`GrafanaDatasource`, `GrafanaDashboard`) wire up Prometheus and Tempo datasources and pre-built dashboards for vLLM metrics and cluster health.

## Tech Stack & Dependencies

- **Runtime:** Grafana (managed by Grafana Operator v5)
- **Operator:** `grafana-operator` from `community-operators` catalog, channel `v5`
- **Container image:** Managed by the operator (no explicit image reference in the chart)
- **Key dependencies:** Grafana Operator installed in `openshift-grafana-operator` namespace; Thanos Querier (OpenShift built-in monitoring); Tempo for distributed tracing
- **Helm subchart:** Standalone chart at `helm/02-observability/grafana/` (not a subchart dependency)

## Key Patterns

### Grafana Operator CRD-Based Deployment

The Grafana instance is declared as a `Grafana` CR rather than a Deployment. The operator watches for this CR and reconciles the actual Grafana pod, service, and configuration. The `dashboards: grafana` label on the instance is the selector that datasources and dashboards use to bind to this specific instance.

```yaml
apiVersion: grafana.integreatly.org/v1beta1
kind: Grafana
metadata:
  name: {{ include "grafana.fullname" . }}
  namespace: {{ .Values.grafana.namespace }}
  labels:
    dashboards: grafana
spec:
  config:
    log:
      level: {{ .Values.grafana.logLevel }}
      mode: console
    security:
      admin_password: {{ .Values.grafana.adminPassword | quote }}
      admin_user: {{ .Values.grafana.adminUser | quote }}
```

### Service Account Token Authentication for Datasources

Both Prometheus and Tempo datasources authenticate to cluster-internal endpoints using a service account token injected from a Kubernetes secret. The secret is created with the `kubernetes.io/service-account-token` type and annotated to auto-populate from the `grafana-sa` service account.

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: {{ .Values.serviceAccount.tokenSecretName }}
  annotations:
    kubernetes.io/service-account.name: grafana-sa
type: kubernetes.io/service-account-token
```

The datasource then references this token via `valuesFrom`:

```yaml
valuesFrom:
  - targetPath: secureJsonData.httpHeaderValue1
    valueFrom:
      secretKeyRef:
        name: {{ .Values.serviceAccount.tokenSecretName }}
        key: token
```

### Datasource Instance Selector Pattern

Datasources and dashboards bind to the Grafana instance using `instanceSelector.matchLabels`. This label must match the label on the `Grafana` CR (`dashboards: grafana`).

```yaml
spec:
  instanceSelector:
    matchLabels:
      dashboards: grafana
  datasource:
    name: prometheus
    type: prometheus
    access: proxy
    url: {{ .Values.datasources.prometheus.url | quote }}
    jsonData:
      httpHeaderName1: "Authorization"
      timeInterval: "5s"
      tlsSkipVerify: true
```

### URL-Based Dashboard Provisioning

Dashboards are loaded from external URLs rather than embedded JSON, keeping the Helm chart lightweight. The `GrafanaDashboard` CR fetches dashboard JSON at reconciliation time.

```yaml
apiVersion: grafana.integreatly.org/v1beta1
kind: GrafanaDashboard
metadata:
  name: vllm-{{ include "grafana.fullname" . }}
spec:
  instanceSelector:
    matchLabels:
      dashboards: grafana
  url: https://raw.githubusercontent.com/opendatahub-io/llama-stack-demos/refs/heads/main/kubernetes/observability/grafana/vllm-dashboard/vllm-grafana-openshift.json
```

Two dashboards are available (both disabled by default via `values.yaml`):
- **vLLM dashboard** -- sourced from `opendatahub-io/llama-stack-demos`
- **Cluster metrics dashboard** -- sourced from `redhat-et/edge-ocp-observability`

### RBAC for Cross-Namespace Monitoring Access

The Grafana service account requires three ClusterRoleBindings and one RoleBinding to read metrics and traces across the cluster:

```yaml
# ClusterRoleBindings (cluster-scoped read access)
- cluster-monitoring-view         # Read Prometheus metrics
- openshift-cluster-monitoring-view  # Read OpenShift monitoring metrics
- tempostack-traces-reader        # Read distributed traces from Tempo

# RoleBinding (namespace-scoped)
- edit                            # Edit access in the observability-hub namespace
```

All bindings target the `grafana-sa` service account in the `observability-hub` namespace.

### OpenShift Route with TLS Edge Termination

Grafana is exposed externally via an OpenShift Route with TLS edge termination, pointing to the operator-created `grafana-service`:

```yaml
apiVersion: route.openshift.io/v1
kind: Route
spec:
  to:
    kind: Service
    name: grafana-service
  port:
    targetPort: grafana
  tls:
    termination: edge
```

## Configuration

- **Environment variables:** None -- all configuration is done through the `Grafana` CR spec
- **Config files:** None at the application level; the operator manages Grafana's `grafana.ini` from the CR spec
- **Helm values:**

| Value | Purpose | Default |
|-------|---------|---------|
| `grafana.adminUser` | Grafana admin username | `rhel` |
| `grafana.adminPassword` | Grafana admin password | `rhel` |
| `grafana.logLevel` | Grafana log level | `warn` |
| `grafana.namespace` | Target namespace for all resources | `observability-hub` |
| `datasources.prometheus.enabled` | Enable Prometheus datasource | `true` |
| `datasources.prometheus.url` | Thanos Querier URL | `https://thanos-querier.openshift-monitoring.svc.cluster.local:9091` |
| `datasources.tempo.enabled` | Enable Tempo datasource | `true` |
| `datasources.tempo.url` | Tempo gateway URL | `https://tempo-tempostack-gateway.observability-hub.svc.cluster.local:8081/api/traces/v1/dev/tempo` |
| `dashboards.clusterMetrics.enabled` | Deploy cluster metrics dashboard | `false` |
| `dashboards.vllm.enabled` | Deploy vLLM metrics dashboard | `false` |
| `serviceAccount.tokenSecretName` | SA token secret name | `grafana-sa-token` |

## Known Gotchas

- **Dashboards disabled by default:** Both `dashboards.clusterMetrics.enabled` and `dashboards.vllm.enabled` default to `false` in `values.yaml`. They must be explicitly enabled to deploy any dashboards.
- **Hardcoded service account name:** The RBAC templates reference `grafana-sa` as a literal string rather than a templated value, so the service account name cannot be overridden through Helm values. The operator creates this SA automatically when it reconciles the `Grafana` CR.
- **TLS skip verify on datasources:** Both Prometheus and Tempo datasources set `tlsSkipVerify: true` in `jsonData`. This bypasses certificate validation for the cluster-internal connections.
- **Hardcoded admin credentials in values.yaml:** The default admin username/password (`rhel`/`rhel`) are set in plain text in `values.yaml`. These should be overridden for any non-development deployment.
- **Operator namespace vs instance namespace:** The Grafana Operator installs into `openshift-grafana-operator` (via the separate `helm/01-operators/grafana-operator/` chart), but the Grafana instance and all its resources deploy into `observability-hub`. These are two separate Helm releases that must be installed in order.

## Testing Notes

- Verify the Grafana Operator is running in `openshift-grafana-operator` before installing this chart
- After deployment, check the `Grafana` CR status: `oc get grafana -n observability-hub`
- Confirm datasources are connected: `oc get grafanadatasource -n observability-hub`
- Confirm dashboards are created (if enabled): `oc get grafanadashboard -n observability-hub`
- Access Grafana via the OpenShift Route and verify Prometheus and Tempo datasources show as "connected"

## Related Patterns

- Prometheus / Thanos Querier (OpenShift built-in user workload monitoring)
- Tempo distributed tracing backend (`helm/02-observability/tempo/`)
- OpenTelemetry Collector (`helm/02-observability/otel-collector/`)
- User Workload Monitoring (`helm/02-observability/uwm/`)
