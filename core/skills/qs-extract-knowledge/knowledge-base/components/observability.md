---
name: observability
description: Multi-layer observability stack for MaaS quickstarts — cluster monitoring, Istio telemetry, and Kuadrant TelemetryPolicy
summary: "Three-layer Helm-templated observability stack for RHOAI MaaS quickstarts wiring OpenShift cluster monitoring (platform/user-workload Prometheus ConfigMaps with 168h/72h retention, 40Gi PVC, `helm.sh/resource-policy: keep`), Istio Telemetry CRD in `openshift-ingress` adding `subscription` dimension to REQUEST_DURATION from `x-maas-subscription` header targeting `maas-default-gateway` via label selector, and Kuadrant TelemetryPolicy extracting billing labels (`model` via `responseBodyJSON(\"/model\")`, user/subscription/organization_id/cost_center from Authorino JWT) for per-user/model chargeback attribution. Use when MaaS quickstarts need multi-tenant usage attribution and chargeback -- requires DSCInitialization metrics (90d/5Gi), Red Hat Connectivity Link (Kuadrant) v1.3.4 with `observability.enable: true`, Red Hat OpenTelemetry Operator, and OdhDashboardConfig `observabilityDashboard: true` for Perses dashboards in the OpenShift AI console. Cluster monitoring ConfigMaps gated by `clusterMonitoring.enabled` with install-script auto-detection of existing configs to avoid conflicts; Istio Telemetry targets only the MaaS gateway via `gateway.networking.k8s.io/gateway-name` label, not all sidecars; templates live in parent chart with no subchart. Pin Cluster Observability Operator to v1.4.0 with Manual install plan (v1.5.0 incompatible), do not enable DSCI traces without additional prerequisites, and TelemetryPolicy billing labels will be empty if Authorino auth is misconfigured -- verify JWT claims are populated before expecting chargeback metrics."
metadata:
  type: component
tags:
  tech_stack: [prometheus, istio, kuadrant, opentelemetry, helm]
  ai_pattern: [model-serving]
  platform: [rhoai, openshift, kserve]
source_examples:
  - quickstart: "maas-code-assistant"
    repo: "https://github.com/rh-ai-quickstart/maas-code-assistant"
    notes: "Three-tier observability: OpenShift cluster monitoring ConfigMaps, Istio Telemetry for per-subscription latency, Kuadrant TelemetryPolicy for per-user/model usage attribution"
    approach: "A"
---

# Observability

## Overview

Observability in this quickstart is a three-layer stack deployed via Helm templates into an OpenShift cluster running RHOAI with Models-as-a-Service (MaaS). It wires together OpenShift's built-in Prometheus-based cluster monitoring, Istio's Telemetry CRD for per-subscription latency metrics, and Kuadrant's TelemetryPolicy CRD for per-user and per-model usage attribution with billing metadata. The OpenShift Cluster Observability Operator surfaces these metrics in Perses Dashboards embedded in the OpenShift AI console.

## Tech Stack & Dependencies

- **Runtime:** Kubernetes-native CRDs (no application code)
- **Container image:** N/A (uses OpenShift platform operators)
- **Key dependencies:**
  - Prometheus Operator (OpenShift built-in cluster monitoring)
  - OpenShift Cluster Observability Operator v1.4.0 (pinned; v1.5.0 has incompatibilities per README)
  - Red Hat OpenTelemetry Operator (opentelemetry-product subscription)
  - Red Hat Connectivity Link (Kuadrant) v1.3.4 with `observability.enable: true`
  - Istio (via OpenShift Service Mesh / Gateway API)
  - DSCInitialization with metrics enabled
- **Helm subchart:** None -- templates live directly in the parent `maas-code-assistant` chart

## Key Patterns

### Cluster Monitoring ConfigMaps

Two ConfigMaps configure OpenShift's Prometheus stack -- one for platform-level monitoring and one for user-workload monitoring. Both are gated by `.Values.clusterMonitoring.enabled` and are skipped when an existing `cluster-monitoring-config` ConfigMap is detected (to avoid overwriting shared cluster config).

```yaml
# charts/maas-code-assistant/templates/cluster-monitoring-config.yaml
{{- if .Values.clusterMonitoring.enabled }}
{{- with .Values.clusterMonitoring.config }}
apiVersion: v1
kind: ConfigMap
metadata:
  name: cluster-monitoring-config
  namespace: openshift-monitoring
  annotations:
    helm.sh/resource-policy: keep
data:
  config.yaml: |
    {{- toYaml . | nindent 4 }}
{{- end }}
```

The `helm.sh/resource-policy: keep` annotation prevents Helm from deleting the ConfigMap on uninstall, since it is a cluster-wide resource shared with other workloads.

Default values set 168h retention for platform Prometheus and 72h for user-workload Prometheus, each with 40Gi PVC:

```yaml
# charts/maas-code-assistant/values.yaml (excerpt)
clusterMonitoring:
  enabled: false
  config:
    enableUserWorkload: true
    prometheusK8s:
      retention: 168h
      volumeClaimTemplate:
        spec:
          resources:
            requests:
              storage: 40Gi
  userConfig:
    prometheus:
      retention: 72h
```

### Auto-detection of Existing Monitoring Config

The all-in-one install script detects whether a `cluster-monitoring-config` ConfigMap already exists and disables the Helm-managed one to avoid conflicts:

```bash
# all-in-one.sh (excerpt)
MONITORING_CONFIG=true
if oc get configmap -n openshift-monitoring cluster-monitoring-config >/dev/null 2>&1; then
  echo "WARNING: Detected an existing cluster monitoring config. ..." >&2
  MONITORING_CONFIG=false
fi
export MONITORING_CONFIG
```

This value flows into `environment.yaml.tpl` as `clusterMonitoring.enabled: ${MONITORING_CONFIG}`.

### Istio Telemetry for Per-Subscription Latency

An Istio `Telemetry` CRD in `openshift-ingress` adds a custom `subscription` dimension to the `REQUEST_DURATION` metric by extracting the `x-maas-subscription` header:

```yaml
# charts/maas-code-assistant/templates/telemetry.yaml
apiVersion: telemetry.istio.io/v1
kind: Telemetry
metadata:
  name: latency-per-subscription
  namespace: openshift-ingress
spec:
  selector:
    matchLabels:
      gateway.networking.k8s.io/gateway-name: maas-default-gateway
  metrics:
  - providers:
    - name: prometheus
    overrides:
    - match:
        metric: REQUEST_DURATION
        mode: CLIENT_AND_SERVER
      tagOverrides:
        subscription:
          operation: UPSERT
          value: request.headers["x-maas-subscription"]
```

This targets only the `maas-default-gateway` Gateway pods via label selector, not all Istio sidecars.

### Kuadrant TelemetryPolicy for Usage Attribution

A Kuadrant `TelemetryPolicy` CRD attaches billing-relevant labels to metrics for every request passing through the gateway:

```yaml
# charts/maas-code-assistant/templates/telemetrypolicy.yaml
apiVersion: extensions.kuadrant.io/v1alpha1
kind: TelemetryPolicy
metadata:
  name: maas-telemetry
  namespace: openshift-ingress
  labels:
    app.kubernetes.io/part-of: maas-observability
spec:
  metrics:
    default:
      labels:
        model: responseBodyJSON("/model")
        user: auth.identity.userid
        subscription: auth.identity.selected_subscription
        organization_id: auth.identity.subscription_info.organizationId
        cost_center: auth.identity.subscription_info.costCenter
  targetRef:
    group: gateway.networking.k8s.io
    kind: Gateway
    name: maas-default-gateway
```

Labels are extracted from the auth identity (Authorino JWT claims) and response body (model name from the LLM response JSON), enabling per-user, per-subscription, per-org, and per-model metric breakdowns for chargeback.

### DSCInitialization Metrics Configuration

The DSCInitialization resource enables the RHOAI observability stack with configurable retention and storage:

```yaml
# charts/dependency-operators/values.yaml (excerpt)
dataScienceClusterInitialization:
  monitoring:
    metrics:
      replicas: 1
      storage:
        retention: 90d
        size: 5Gi
```

### ODH Dashboard Config for Observability Dashboard

The `observabilityDashboard` flag is patched into the `OdhDashboardConfig` via a post-install/post-upgrade Helm hook Job:

```yaml
# charts/maas-code-assistant/values.yaml (excerpt)
dashboardConfig:
  observabilityDashboard: true
```

This enables Perses dashboards in the OpenShift AI console UI.

### Kuadrant Observability Enable

The Kuadrant CR itself is deployed with observability turned on:

```yaml
# charts/dependency-operators/files/rhcl/kuadrant.yaml
apiVersion: kuadrant.io/v1beta1
kind: Kuadrant
metadata:
  name: kuadrant
spec:
  observability:
    enable: true
```

## Configuration

- **Environment variables:** `MONITORING_CONFIG` -- set by `all-in-one.sh` to `true`/`false` based on detection of existing cluster monitoring config
- **Helm values:**
  - `clusterMonitoring.enabled` -- toggle cluster/user-workload monitoring ConfigMaps (default `false`, auto-detected)
  - `clusterMonitoring.config.prometheusK8s.retention` -- platform Prometheus retention (default `168h`)
  - `clusterMonitoring.userConfig.prometheus.retention` -- user-workload Prometheus retention (default `72h`)
  - `dashboardConfig.observabilityDashboard` -- enable Perses dashboards in RHOAI console (default `true`)
  - `dataScienceClusterInitialization.monitoring.metrics.replicas` -- RHOAI metrics replicas (default `1`)
  - `dataScienceClusterInitialization.monitoring.metrics.storage.retention` -- RHOAI metrics retention (default `90d`)

## Known Gotchas

- **Cluster Observability Operator must be pinned to v1.4.0:** The README explicitly warns that v1.5.0 has incompatibilities. The operator subscription in `dependency-operators/values.yaml` enforces `startingCSV: cluster-observability-operator.v1.4.0` with `Manual` install plan approval.
- **Do not enable DSCI traces without additional prerequisites:** Per commit `6903b20`, only the `metrics` section of the DSCInitialization observability stack should be modified. Enabling `traces` requires additional prerequisites not covered by this quickstart.
- **Existing cluster-monitoring-config can cause conflicts:** The install script auto-detects an existing ConfigMap and warns the user to ensure user-workload monitoring is enabled manually. The Helm template uses `helm.sh/resource-policy: keep` to avoid deleting shared cluster config on uninstall.
- **Kuadrant TelemetryPolicy requires auth identity claims:** The `user`, `subscription`, `organization_id`, and `cost_center` labels depend on Authorino JWT claims being populated. If auth is misconfigured, these labels will be empty in metrics.
- **Telemetry CRD targets Gateway by label:** The Istio Telemetry resource uses `gateway.networking.k8s.io/gateway-name: maas-default-gateway` label selector, so it only affects the MaaS gateway -- not other Istio workloads on the cluster.

## Testing Notes

- Verify cluster monitoring is running: check that `cluster-monitoring-config` and `user-workload-monitoring-config` ConfigMaps exist in their respective namespaces
- Confirm the Kuadrant CR has `observability.enable: true`
- Verify DSCInitialization has metrics enabled with `oc get dsci default-dsci -o yaml`
- Check that the `observabilityDashboard` flag is set in the OdhDashboardConfig
- Validate that Perses dashboards appear in the OpenShift AI console

## Related Patterns

- `cluster-observability-operator.md` -- operator installation and subscription details
- `uwm.md` -- user-workload monitoring patterns
- `otel-operator.md` -- OpenTelemetry operator patterns
- `grafana.md` / `grafana-operator.md` -- alternative visualization approaches
