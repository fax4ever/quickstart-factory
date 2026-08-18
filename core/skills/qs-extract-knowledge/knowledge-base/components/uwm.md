---
name: uwm
description: "OpenShift User Workload Monitoring Helm chart deploying PodMonitors and ConfigMaps for vLLM/LLaMA metrics"
summary: "UWM is a Helm chart (helm/02-observability/uwm/) that enables OpenShift User Workload Monitoring for vLLM and LLaMA Stack model-serving pods -- the foundational monitoring prerequisite that must be deployed before any Grafana dashboards or alerting rules can observe model metrics on RHOAI. Deploy first when setting up observability for AI model-serving on OpenShift; provides two PodMonitor patterns -- matchExpressions with In operator for multi-model scraping (safety, llama32-3b, granite-8b, llama31-70b at 30s interval) and matchLabels for single KServe predictor targeting via isvc. prefix convention (h2c port, 15s interval). Two-layer ConfigMap enablement deploys to openshift-monitoring (enableUserWorkload: true) and openshift-user-workload-monitoring (Prometheus retention 15d, Alertmanager enabled); PodMonitor target namespace resolves via global.targetNamespace or defaults to release namespace; bearerTokenSecret conditionally rendered when name is non-empty for secured endpoints. Requires cluster-admin privileges for cross-namespace ConfigMap deployment to system namespaces, Cluster Observability Operator must be installed first (oc wait --for=condition=Established crd/podmonitors.monitoring.coreos.com), openshift-user-workload-monitoring namespace must pre-exist, and KServe isvc. label prefix will not match non-KServe model deployments."
metadata:
  type: component
tags:
  tech_stack: [helm, prometheus, openshift]
  ai_pattern: [model-serving]
  platform: [openshift, vllm, kserve]
source_examples:
  - quickstart: "lls-observability"
    repo: "https://github.com/rh-ai-quickstart/lls-observability"
    notes: "UWM chart enabling OpenShift User Workload Monitoring with PodMonitors for vLLM and LLaMA Stack model-serving pods"
    approach: "A"
---

# User Workload Monitoring (UWM)

## Overview

UWM is a Helm chart that enables OpenShift User Workload Monitoring for AI model-serving workloads. It deploys two ConfigMaps (cluster-level and user-workload-level) to activate Prometheus scraping of user namespaces, plus PodMonitor resources that target vLLM and LLaMA Stack pods exposing `/metrics` endpoints. This is the foundational monitoring component that must be deployed before any Grafana dashboards or alerting rules can observe model-serving metrics on RHOAI.

## Tech Stack & Dependencies

- **Runtime:** Helm chart (no application runtime -- pure Kubernetes resource definitions)
- **Container image:** None (chart deploys ConfigMaps and PodMonitor CRDs only)
- **Key dependencies:**
  - Cluster Observability Operator (provides `PodMonitor` CRD from `monitoring.coreos.com/v1`)
  - OpenShift 4.12+ with User Workload Monitoring support
  - vLLM/LLaMA Stack pods with `/metrics` endpoints
- **Helm subchart:** Standalone chart at `helm/02-observability/uwm/`, version 0.1.0

## Key Patterns

### Two-Layer ConfigMap Enablement

The chart deploys ConfigMaps to two distinct OpenShift namespaces. The cluster-level ConfigMap in `openshift-monitoring` enables user workload monitoring globally, while the user-workload ConfigMap in `openshift-user-workload-monitoring` configures Prometheus settings for user workloads.

From `templates/cluster-monitoring-config.yaml`:

```yaml
{{- if .Values.clusterMonitoring.enabled }}
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ .Values.clusterMonitoring.configMapName }}
  namespace: {{ .Values.clusterMonitoring.namespace }}
data:
  config.yaml: |
    enableUserWorkload: {{ .Values.clusterMonitoring.enableUserWorkload }}
{{- end }}
```

From `templates/user-workload-monitoring-config.yaml`:

```yaml
data:
  config.yaml: |
    prometheus:
      logLevel: {{ .Values.userWorkloadMonitoring.prometheus.logLevel }}
      retention: {{ .Values.userWorkloadMonitoring.prometheus.retention }}
    alertmanager:
      enabled: {{ .Values.userWorkloadMonitoring.alertmanager.enabled }}
      enableAlertmanagerConfig: {{ .Values.userWorkloadMonitoring.alertmanager.enableAlertmanagerConfig }}
```

### PodMonitor with matchExpressions for Multi-Model Scraping

The `vllm-llama-serve-monitor` PodMonitor uses `matchExpressions` with the `In` operator to monitor multiple model-serving pods via a single PodMonitor. This avoids creating a separate monitor for each model.

From `values.yaml`:

```yaml
vllmLlamaServeMonitor:
  enabled: true
  name: vllm-llama-serve-monitor
  podMetricsEndpoints:
    - interval: 30s
      path: /metrics
      bearerTokenSecret:
        name: ""
        key: ""
  selector:
    matchExpressions:
      - key: app
        operator: In
        values:
          - safety
          - llama32-3b
          - granite-8b
          - llama31-70b
```

### PodMonitor with matchLabels for Single-Model Targeting

The `vllm-metrics` PodMonitor uses `matchLabels` to target a specific KServe predictor pod by its `app` label with the `isvc.` prefix convention, scraping at a faster 15s interval on the `h2c` port.

From `values.yaml`:

```yaml
vllmMetricsMonitor:
  enabled: true
  name: vllm-metrics
  podMetricsEndpoints:
    - interval: 15s
      path: /metrics
      port: h2c
  selector:
    matchLabels:
      app: isvc.llama3-2-3b-predictor
  labels:
    release: prometheus
```

### Target Namespace Resolution via Helper

The chart uses a Helm helper to resolve which namespace PodMonitors are deployed to, defaulting to the Helm release namespace but overridable via `global.targetNamespace`.

From `templates/_helpers.tpl`:

```yaml
{{- define "uwm.targetNamespace" -}}
{{- if .Values.global.targetNamespace }}
{{- .Values.global.targetNamespace }}
{{- else }}
{{- .Release.Namespace }}
{{- end }}
{{- end }}
```

## Configuration

- **Environment variables:** None (chart deploys only Kubernetes resources)
- **Config files:**
  - `values.yaml` -- all chart configuration including ConfigMap settings, PodMonitor selectors, and scrape intervals
- **Helm values:**
  - `clusterMonitoring.enabled` / `clusterMonitoring.namespace` -- controls the cluster-level ConfigMap in `openshift-monitoring`
  - `userWorkloadMonitoring.enabled` / `.namespace` -- controls the user-workload ConfigMap in `openshift-user-workload-monitoring`
  - `userWorkloadMonitoring.prometheus.logLevel` -- Prometheus log level (default: `debug`)
  - `userWorkloadMonitoring.prometheus.retention` -- data retention period (default: `15d`)
  - `userWorkloadMonitoring.alertmanager.enabled` -- enables Alertmanager (default: `true`)
  - `vllmLlamaServeMonitor.selector.matchExpressions` -- list of model app labels to scrape
  - `vllmMetricsMonitor.selector.matchLabels` -- label selector for the KServe predictor pod
  - `global.targetNamespace` -- override namespace for PodMonitor deployment (defaults to release namespace)

## Known Gotchas

- **Cross-namespace ConfigMap deployment requires cluster-admin:** The chart deploys ConfigMaps to `openshift-monitoring` and `openshift-user-workload-monitoring`, which are system namespaces. The Helm install must run with cluster-admin privileges, not just namespace-admin. This is noted in the README under "System Requirements" as requiring "Cluster Admin privileges for operator installation."
- **Namespace must pre-exist:** The `openshift-user-workload-monitoring` namespace must be created manually before chart installation. The chart does not create it. From README: "The `openshift-user-workload-monitoring` namespace must exist before deployment."
- **PodMonitor CRD dependency:** If the Cluster Observability Operator is not installed before this chart, Helm will fail with `no matches for kind "PodMonitor"`. The README documents this: install `cluster-observability-operator` chart first, then wait for the CRD with `oc wait --for=condition=Established crd/podmonitors.monitoring.coreos.com`.
- **KServe label convention:** The vllm-metrics PodMonitor targets pods labeled `app: isvc.llama3-2-3b-predictor` -- the `isvc.` prefix is a KServe InferenceService convention. If models are deployed differently, this selector will not match.
- **Bearer token secret left empty by default:** The `vllmLlamaServeMonitor` includes `bearerTokenSecret` fields with empty name/key. The template conditionally renders this only when `bearerTokenSecret.name` is non-empty, so it is a no-op by default but ready for secured endpoints.

## Testing Notes

- Verify ConfigMaps exist in their target namespaces: `oc get configmap cluster-monitoring-config -n openshift-monitoring` and `oc get configmap user-workload-monitoring-config -n openshift-user-workload-monitoring`
- Verify PodMonitors are created: `oc get podmonitors -n <target-namespace>`
- Confirm target pods match PodMonitor selectors: `oc get pods --show-labels | grep -E "app=(safety|llama32-3b|granite-8b|llama31-70b|isvc.llama3-2-3b-predictor)"`
- Test metrics endpoint accessibility: `oc port-forward pod/<pod-name> 8080:8080 && curl http://localhost:8080/metrics`
- Check Prometheus targets in the OpenShift console under Observe > Targets

## Related Patterns

- See `observability-stack.md` for the broader observability architecture including Grafana dashboards and Alloy
- See `alloy.md` for the metrics collection agent that complements UWM
