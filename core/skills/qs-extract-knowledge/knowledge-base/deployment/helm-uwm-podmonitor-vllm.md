---
name: helm-uwm-podmonitor-vllm
description: Helm chart enabling OpenShift User Workload Monitoring with PodMonitors targeting vLLM model server pods
summary: "Helm chart (charts/observability/helm/uwm/) enables OpenShift User Workload Monitoring and deploys PodMonitors to scrape vLLM model server metrics by managing cluster-monitoring-config (enableUserWorkload: true) and user-workload-monitoring-config ConfigMaps across openshift-monitoring namespaces. Approach A uses two matchLabels PodMonitors (30s/15s intervals, selectors app.kubernetes.io/name: nim-llm and app: nim-llm) with nfs-client PVC (40Gi), 168h/72h retention, alertmanager via helm install; Approach B uses matchExpressions IN operator for multi-model scraping (safety, llama32-3b, granite-8b, llama31-70b), KServe isvc-prefixed selectors (app: isvc.llama3-2-3b-predictor), no PVC, 15d retention, and helm template | oc apply for idempotent deployment when platform ConfigMaps already exist. Two PodMonitors cover different KServe deployment label formats with the second specifying port h2c for gRPC HTTP/2 cleartext; pattern complements OTel sidecar injection for distributed traces alongside Prometheus scraping. Requires cluster-admin privileges for ConfigMap deployment to openshift-monitoring and openshift-user-workload-monitoring namespaces; storageClassName nfs-client is environment-specific and must match the target cluster's available StorageClass."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, prometheus]
  ai_pattern: [model-serving]
  platform: [openshift]
source_examples:
  - quickstart: "aml-rag-nvidia"
    repo: "https://github.com/rh-ai-quickstart/aml-rag-nvidia"
    notes: "UWM chart manages cluster-monitoring-config and user-workload-monitoring-config ConfigMaps plus two PodMonitors for vLLM metrics"
    approach: "A"
  - quickstart: "lls-observability"
    repo: "https://github.com/rh-ai-kickstart/llama-stack-observability"
    notes: "UWM chart with no PVC storage config, matchExpressions IN selector for multi-model scraping, and deploy via helm template | oc apply"
    approach: "B"
---

# User Workload Monitoring with vLLM PodMonitors

## Overview

This pattern uses a dedicated Helm chart to configure OpenShift's User Workload Monitoring (UWM) subsystem and deploy PodMonitor resources that scrape vLLM model server metrics. The chart manages two platform ConfigMaps (`cluster-monitoring-config` in `openshift-monitoring` and `user-workload-monitoring-config` in `openshift-user-workload-monitoring`) and creates PodMonitors that select vLLM pods by label.

## Pattern Description

OpenShift's built-in Prometheus stack requires explicit enablement of user workload monitoring via a ConfigMap in the `openshift-monitoring` namespace. This chart manages that ConfigMap plus the user workload monitoring configuration, then creates PodMonitor resources that tell Prometheus where to scrape vLLM metrics. Two PodMonitors target vLLM pods using different label selectors to ensure comprehensive coverage.

## Implementation

### Cluster Monitoring ConfigMap

Enables user workload monitoring at the platform level:

```yaml
# charts/observability/helm/uwm/templates/ (cluster-monitoring-config)
apiVersion: v1
kind: ConfigMap
metadata:
  name: cluster-monitoring-config
  namespace: openshift-monitoring
data:
  config.yaml: |
    enableUserWorkload: true
    prometheusK8s:
      retention: 168h
      volumeClaimTemplate:
        spec:
          storageClassName: nfs-client
          resources:
            requests:
              storage: 40Gi
```

### User Workload Monitoring ConfigMap

Configures the user workload Prometheus instance:

```yaml
# charts/observability/helm/uwm/templates/ (user-workload-monitoring-config)
apiVersion: v1
kind: ConfigMap
metadata:
  name: user-workload-monitoring-config
  namespace: openshift-user-workload-monitoring
data:
  config.yaml: |
    prometheus:
      logLevel: debug
      retention: 72h
      volumeClaimTemplate:
        spec:
          storageClassName: nfs-client
          resources:
            requests:
              storage: 40Gi
    alertmanager:
      enabled: true
      enableAlertmanagerConfig: true
```

### PodMonitor for vLLM Models

Two PodMonitors target vLLM pods using different label selectors:

```yaml
# charts/observability/helm/uwm/templates/ (PodMonitor)
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: {{ .Values.vllmLlamaServeMonitor.name }}
spec:
  podMetricsEndpoints:
  - interval: 30s
    path: /metrics
  selector:
    matchLabels:
      app.kubernetes.io/name: nim-llm

---
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: {{ .Values.vllmMetricsMonitor.name }}
spec:
  podMetricsEndpoints:
  - interval: 15s
    path: /metrics
    port: h2c
  selector:
    matchLabels:
      app: nim-llm
```

### Values for Monitor Configuration

```yaml
# charts/observability/helm/uwm/values.yaml (excerpt)
vllmLlamaServeMonitor:
  enabled: true
  name: vllm-llama-serve-monitor
  selector:
    matchLabels:
      app.kubernetes.io/name: nim-llm

vllmMetricsMonitor:
  enabled: true
  name: vllm-metrics
  selector:
    matchLabels:
      app: nim-llm
```

## Configuration

- **Key settings:** `clusterMonitoringConfig.enableUserWorkload: true` is the platform-level toggle; `storageClassName: nfs-client` for persistent storage; retention set to 168h (cluster) and 72h (user workload)
- **Defaults:** Both PodMonitors enabled by default; scrape intervals are 30s and 15s respectively; alertmanager enabled with alertmanager config support
- **Dependencies:** OpenShift cluster monitoring stack; storage class `nfs-client` must exist; vLLM model pods must carry labels `app.kubernetes.io/name: nim-llm` or `app: nim-llm`

## Gotchas

- The chart deploys ConfigMaps to `openshift-monitoring` and `openshift-user-workload-monitoring` namespaces, which require cluster-admin privileges to manage
- Two PodMonitors use different label selectors (`app.kubernetes.io/name` vs `app`) because KServe InferenceService pods may carry different label formats depending on the deployment mode
- The `storageClassName: nfs-client` is environment-specific and must match the available StorageClass on the target cluster
- The second PodMonitor specifies `port: h2c` for the metrics endpoint, targeting the gRPC HTTP/2 cleartext port used by some vLLM configurations

## Related Patterns

- `otel-sidecar-inject-vllm-model-metrics.md` -- complementary OTel-based metrics and traces collection for the same vLLM pods
- `observability-olm-operator-helm-install.md` -- the Cluster Observability Operator that may interact with these monitoring configurations
- `kserve-multi-model-mig-gpu-slicing.md` -- the vLLM model pods whose metrics are scraped by these PodMonitors

---

## Approach B: Lightweight UWM with matchExpressions Multi-Model Selector (from lls-observability)

### When to Use

When UWM needs to scrape multiple model types using a single PodMonitor with `matchExpressions` IN operator, and when the cluster monitoring stack should use default storage (no PVC) rather than dedicated persistent volumes.

### Differences from Approach A

- Cluster monitoring ConfigMap enables `enableUserWorkload: true` without PVC volumeClaimTemplate or retention settings -- relies on cluster defaults
- User workload monitoring ConfigMap sets `retention: 15d` and `logLevel: debug` without a PVC
- First PodMonitor uses `matchExpressions` with `IN` operator to target multiple model app labels in a single resource instead of `matchLabels` for a single label value
- Second PodMonitor targets KServe InferenceService pod labels (`app: isvc.llama3-2-3b-predictor`) instead of generic `app: nim-llm`
- Deployed via `helm template uwm ... | oc apply -f-` instead of `helm install` because platform ConfigMaps may already exist

### PodMonitor with matchExpressions

```yaml
# helm/02-observability/uwm/templates/vllm-llama-serve-monitor.yaml
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: vllm-llama-serve-monitor
spec:
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

### KServe InferenceService Label Selector

```yaml
# helm/02-observability/uwm/templates/vllm-metrics-monitor.yaml
apiVersion: monitoring.coreos.com/v1
kind: PodMonitor
metadata:
  name: vllm-metrics
  labels:
    release: prometheus
spec:
  podMetricsEndpoints:
  - interval: 15s
    path: /metrics
    port: h2c
  selector:
    matchLabels:
      app: isvc.llama3-2-3b-predictor
```

### Lightweight ConfigMap (No PVC)

```yaml
# helm/02-observability/uwm/values.yaml (Approach B)
clusterMonitoring:
  enabled: true
  enableUserWorkload: true
  # No prometheusK8s volumeClaimTemplate -- uses cluster defaults

userWorkloadMonitoring:
  enabled: true
  prometheus:
    logLevel: debug
    retention: 15d
  alertmanager:
    enabled: true
    enableAlertmanagerConfig: true
```

---

## Choosing Between Approaches

| Criteria | Approach A | Approach B |
|----------|-----------|-----------|
| Storage configuration | PVC with nfs-client StorageClass (40Gi) | No PVC; cluster defaults |
| Retention | 168h cluster / 72h user workload | Not configured (cluster default) / 15d user workload |
| Multi-model selector | Two PodMonitors with matchLabels for single label | matchExpressions IN operator for 4+ model labels in one PodMonitor |
| Pod label targeting | `app.kubernetes.io/name: nim-llm` / `app: nim-llm` | `app: safety/llama32-3b/granite-8b/llama31-70b` / `app: isvc.llama3-2-3b-predictor` |
| Install method | `helm install` | `helm template | oc apply -f-` (idempotent for existing ConfigMaps) |
