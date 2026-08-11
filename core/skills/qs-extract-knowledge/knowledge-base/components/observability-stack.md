---
name: observability-stack
description: Multi-layer observability stack for RHOAI with Grafana, Tempo, OpenTelemetry, and User Workload Monitoring
summary: "Provides end-to-end observability for vLLM/NIM model serving on RHOAI combining Prometheus metrics via User Workload Monitoring with dual PodMonitors (different NIM label selectors and scrape intervals), distributed tracing via TempoStack with ODF/NooBaa ObjectBucketClaim S3 storage and multi-tenant OpenShift mode (dev tenant), custom Grafana dashboards for vLLM metrics (TTFT p95, generation tokens/sec, request rates) and NVIDIA DCGM GPU metrics (console-embedded via console.openshift.io/dashboard label), plus OpenTelemetry collectors in deployment and sidecar modes with a UIPlugin CR for console trace viewing. Requires four OLM operators (Cluster Observability, Grafana v5 from community-operators channel v5, OpenTelemetry and Tempo from redhat-operators stable channel) deployed via 8 Helm subcharts in a strict two-phase pattern -- install-operators.sh installs operators from openshift-marketplace and waits for CRDs (tempostacks, opentelemetrycollectors, grafanas, uiplugins) before deploy.sh creates resources in the observability-hub namespace. Central OTEL collector authenticates to Tempo gateway via bearertokenauth extension with service-ca.crt TLS and X-Scope-OrgID dev tenant header, sidecar collectors auto-inject into vLLM pods via sidecar.opentelemetry.io/inject annotation to scrape localhost:8000 over insecure HTTP, and Grafana connects to Thanos Querier and Tempo gateway using SA token auth with cluster-monitoring-view, openshift-cluster-monitoring-view, and tempostack-traces-reader ClusterRoleBindings. Grafana Operator is community-operators (unsupported by Red Hat), Tempo storage and Grafana SA token Secrets require Helm post-install Jobs with retry loops for async OBC provisioning and SA creation, grafana/values.yaml has hardcoded clusterDomain (apps.launchpad.nvidia.com) and plain-text admin credentials that must be overridden, uwm chart uses environment-specific nfs-client storageClass for Prometheus PVCs (168h retention, 40Gi), and dual PodMonitors use different NIM label selectors (app.kubernetes.io/name vs app) with different scrape intervals (30s vs 15s on port h2c)."
metadata:
  type: component
tags:
  tech_stack: [grafana, opentelemetry, tempo, prometheus, helm]
  ai_pattern: [model-serving, metrics, tracing]
  platform: [openshift, rhoai, vllm, kserve]
  data_layer: [minio, noobaa]
source_examples:
  - quickstart: "aml-rag-nvidia"
    repo: "https://github.com/rh-ai-quickstart/aml-rag-nvidia"
    notes: "Full observability stack with vLLM/NIM metrics, GPU dashboards, distributed tracing via Tempo, and OTel sidecar injection"
    approach: "A"
---

# Observability Stack

## Overview

A comprehensive observability stack for monitoring AI model serving workloads on OpenShift AI (RHOAI). It combines OpenShift User Workload Monitoring (Prometheus-based metrics), Grafana Operator with custom dashboards for vLLM and GPU metrics, Tempo for distributed tracing with S3-backed storage, and OpenTelemetry collectors (both centralized and sidecar-injected) to capture metrics and traces from model inference endpoints.

## Tech Stack & Dependencies

- **Runtime:** OpenShift operators (OLM-managed) + Helm subcharts
- **Operators required:** Cluster Observability Operator (redhat-operators), Grafana Operator v5 (community-operators), OpenTelemetry Operator (redhat-operators, package `opentelemetry-product`), Tempo Operator (redhat-operators, package `tempo-product`)
- **Key components:** Grafana v5.x, TempoStack (v1alpha1), OpenTelemetryCollector (v1beta1), PodMonitors
- **Helm subcharts:** 8 independent subcharts under `charts/observability/helm/` -- `uwm`, `grafana`, `grafana-operator`, `otel-collector`, `otel-operator`, `tempo`, `tempo-operator`, `cluster-observability-operator`, `distributed-tracing-ui-plugin`
- **Storage:** ODF/NooBaa ObjectBucketClaim for Tempo trace storage (storageClass `openshift-storage.noobaa.io`)
- **Namespace:** `observability-hub` for deployed resources; operators install into their own `openshift-*` namespaces

## Key Patterns

### Two-Phase Deployment (Operators First, Then Resources)

The stack uses a strict two-phase install: `install-operators.sh` installs the four OLM operators via Helm and waits for their CRDs to become available, then `deploy.sh` installs the actual resources (TempoStack, OTEL collectors, Grafana instance, PodMonitors). This is necessary because the custom resources cannot be created before the CRDs exist.

```bash
# install-operators.sh - Phase 1: waits for CRDs
helm upgrade --install cluster-obs helm/cluster-observability-operator/
helm upgrade --install grafana-op helm/grafana-operator/
helm upgrade --install otel-op helm/otel-operator/
helm upgrade --install tempo-op helm/tempo-operator/
# Waits for tempostacks.tempo.grafana.com, opentelemetrycollectors.opentelemetry.io,
# grafanas.grafana.integreatly.org, uiplugins.observability.openshift.io
```

```bash
# deploy.sh - Phase 2: installs resources into observability-hub
helm upgrade --install tempo helm/tempo/ -n observability-hub
helm upgrade --install otel-collector helm/otel-collector/ -n observability-hub
helm upgrade --install uwm helm/uwm/
helm upgrade --install grafana helm/grafana/ -n observability-hub
helm upgrade --install tracing-ui helm/distributed-tracing-ui-plugin/
```

### OLM Operator Subscription Pattern

Each operator uses the same Helm chart pattern: create a namespace, OperatorGroup, and Subscription. All target `openshift-marketplace` as the source namespace. Channel selection differs: `stable` for cluster-observability-operator, otel-operator, and tempo-operator; `v5` for grafana-operator.

```yaml
# From cluster-observability-operator/values.yaml
subscription:
  name: cluster-observability-operator
  packageName: cluster-observability-operator
  channel: stable
  source: redhat-operators
  sourceNamespace: openshift-marketplace
  installPlanApproval: Automatic
```

```yaml
# From grafana-operator/values.yaml - note: community-operators, not redhat-operators
subscription:
  name: grafana
  packageName: grafana-operator
  channel: v5
  source: community-operators
  sourceNamespace: openshift-marketplace
```

### User Workload Monitoring with PodMonitors for vLLM

The `uwm` subchart configures OpenShift's built-in monitoring by creating `cluster-monitoring-config` and `user-workload-monitoring-config` ConfigMaps. It enables user workload monitoring (required for PodMonitors to work) and deploys two PodMonitors to scrape vLLM/NIM model serving metrics.

```yaml
# From uwm/values.yaml - enables user workload monitoring
clusterMonitoringConfig:
  enableUserWorkload: true
  prometheusK8s:
    retention: 168h  # 7 days
    volumeClaimTemplate:
      spec:
        storageClassName: nfs-client
        resources:
          requests:
            storage: 40Gi
```

```yaml
# PodMonitor for NIM/LLaMA serve endpoint
vllmLlamaServeMonitor:
  enabled: true
  name: vllm-llama-serve-monitor
  podMetricsEndpoints:
    - interval: 30s
      path: /metrics
  selector:
    matchLabels:
      app.kubernetes.io/name: nim-llm
```

```yaml
# PodMonitor for vLLM metrics on h2c port
vllmMetricsMonitor:
  enabled: true
  name: vllm-metrics
  podMetricsEndpoints:
    - interval: 15s
      path: /metrics
      port: h2c
  selector:
    matchLabels:
      app: nim-llm
```

### OpenTelemetry Collector with Sidecar Injection

The OTEL collector deploys two OpenTelemetryCollector CRs: a centralized deployment-mode collector that receives OTLP and Prometheus metrics and exports traces to Tempo, and a sidecar-mode collector that gets auto-injected into vLLM pods. Sidecars scrape `localhost:8000` for vLLM metrics and forward everything to the central collector via OTLP HTTP.

```yaml
# Central collector: deployment mode, exports to Tempo
spec:
  mode: deployment
  config:
    exporters:
      otlphttp/dev:
        endpoint: "https://tempo-tempostack-gateway.observability-hub.svc.cluster.local:8080/api/traces/v1/dev"
        headers:
          X-Scope-OrgID: dev
        tls:
          ca_file: /var/run/secrets/kubernetes.io/serviceaccount/service-ca.crt
        auth:
          authenticator: bearertokenauth
    extensions:
      bearertokenauth:
        filename: "/var/run/secrets/kubernetes.io/serviceaccount/token"
```

```yaml
# Sidecar collector: injected into pods with annotation
# sidecar.opentelemetry.io/inject: vllm-otelsidecar
spec:
  mode: sidecar
  config:
    receivers:
      prometheus:
        config:
          scrape_configs:
            - job_name: vllm-sidecar
              scrape_interval: 15s
              static_configs:
                - targets: ['localhost:8000']
    exporters:
      otlphttp:
        endpoint: 'http://otel-collector-collector.observability-hub.svc.cluster.local:4318'
        tls:
          insecure: true
```

### TempoStack with ODF/NooBaa Object Storage

Tempo uses a TempoStack CR with S3-compatible storage backed by an ObjectBucketClaim (OBC) from OpenShift Data Foundation (NooBaa). A Helm post-install Job extracts credentials from the OBC-created Secret and ConfigMap, then creates a `tempo-storage` Secret in the format TempoStack expects. Multi-tenancy uses OpenShift mode with a `dev` tenant.

```yaml
# From tempo/values.yaml
tempoStack:
  name: tempostack
  storageSize: 15Gi
  resources:
    total:
      limits:
        memory: 10Gi
        cpu: 5
  tenants:
    mode: openshift
    authentication:
      - tenantName: dev
        tenantId: "1610b0c3-c509-4592-a256-a1871353dbfa"

objectStorage:
  bucketName: tempo-traces
  storageClassName: openshift-storage.noobaa.io
```

### Grafana with Thanos Querier and Tempo Datasources

Grafana connects to OpenShift's Thanos Querier for Prometheus data and to the Tempo gateway for traces. Authentication uses a ServiceAccount token injected from a Secret. A Helm post-install Job waits for the Grafana operator to create the `grafana-sa` ServiceAccount, then creates the token Secret. The Grafana SA gets three ClusterRoleBindings: `cluster-monitoring-view`, `openshift-cluster-monitoring-view`, and `tempostack-traces-reader`.

```yaml
# From grafana/values.yaml
datasources:
  prometheus:
    enabled: true
    url: "https://thanos-querier.openshift-monitoring.svc.cluster.local:9091"
    isDefault: true
  tempo:
    enabled: true
    url: "https://tempo-tempostack-gateway.observability-hub.svc.cluster.local:8081/api/traces/v1/dev/tempo"
```

```yaml
# Datasource template - uses SA token for auth
spec:
  datasource:
    type: prometheus
    url: "https://thanos-querier.openshift-monitoring.svc.cluster.local:9091"
    secureJsonData:
      httpHeaderValue1: "Bearer ${token}"
    jsonData:
      httpHeaderName1: "Authorization"
      tlsSkipVerify: true
  valuesFrom:
    - targetPath: secureJsonData.httpHeaderValue1
      valueFrom:
        secretKeyRef:
          name: grafana-sa-token
          key: token
```

### vLLM Grafana Dashboard with LLM-Specific Metrics

A GrafanaDashboard CR provides a custom dashboard tracking vLLM-specific performance metrics: time to first token (TTFT) at p95, generation tokens per second, request rates, and input vs output token throughput. The dashboard uses Prometheus queries with template variables for namespace and model filtering.

```json
// Key vLLM metrics tracked in the dashboard:
// - histogram_quantile(0.95, sum(rate(vllm:time_to_first_token_seconds_bucket[5m])) by (le)) * 1000
// - sum(rate(vllm:generation_tokens_total[$__rate_interval]))
// - rate(vllm:num_requests_running[5m])
// - sum(rate(vllm:e2e_request_latency_seconds_count[5m])) by (job, namespace)
// - vllm:prompt_tokens_total (input) vs vllm:generation_tokens_total (output)
```

### NVIDIA DCGM GPU Console Dashboard

A standalone ConfigMap (not deployed via Helm) provides an OpenShift console-embedded GPU dashboard using NVIDIA DCGM Exporter metrics. It tracks GPU temperature, power usage, SM clocks, GPU utilization, tensor core utilization, and framebuffer memory usage. The ConfigMap uses `console.openshift.io/dashboard: "true"` labels for automatic console integration.

```yaml
# gpu-console-dashboard.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: nvidia-dcgm-exporter-dashboard
  namespace: openshift-config-managed
  labels:
    console.openshift.io/dashboard: "true"
    console.openshift.io/odc-dashboard: "true"
```

### Distributed Tracing UI Plugin

A UIPlugin CR of type `DistributedTracing` integrates trace viewing into the OpenShift console. This requires the Cluster Observability Operator to be installed first, as it provides the `UIPlugin` CRD.

```yaml
apiVersion: observability.openshift.io/v1alpha1
kind: UIPlugin
metadata:
  name: distributed-tracing
spec:
  type: DistributedTracing
```

## Configuration

- **Environment variables:** None directly -- all configuration is via Helm values and Kubernetes resources
- **Config files:** `cluster-monitoring-config` ConfigMap in `openshift-monitoring`, `user-workload-monitoring-config` ConfigMap in `openshift-user-workload-monitoring`
- **Helm values:** Each of the 8 subcharts has its own `values.yaml`. Key tuning points:
  - `uwm/values.yaml`: `clusterMonitoringConfig.enableUserWorkload` (must be `true`), PodMonitor selectors, scrape intervals
  - `grafana/values.yaml`: `clusterDomain` (must match cluster), admin credentials, datasource URLs
  - `otel-collector/values.yaml`: Tempo gateway endpoint, Prometheus scrape targets, sidecar injection annotation
  - `tempo/values.yaml`: `storageSize`, `objectStorage.storageClassName`, tenant configuration

## Known Gotchas

- The Grafana Operator comes from `community-operators` (not `redhat-operators`), which means it is not Red Hat supported. All other operators use `redhat-operators`.
- The Tempo storage secret must be created after the ObjectBucketClaim is provisioned. The chart uses a Helm post-install Job (`tempo-storage-secret-creator`) that polls until the OBC secret exists, then reformats the credentials into the `tempo-storage` Secret format that TempoStack expects.
- The Grafana SA token Secret must be created after the Grafana operator creates the `grafana-sa` ServiceAccount. Another Helm post-install Job (`grafana-sa-token-creator`) handles this with a 30-iteration retry loop.
- The `grafana/values.yaml` contains hardcoded `clusterDomain: "apps.launchpad.nvidia.com"` -- this must be overridden for each cluster. A comment in values.yaml suggests: `oc get route -A | grep apps | head -1 | awk '{print $3}' | cut -d. -f2-`.
- Grafana admin credentials (`rhaifn`/`rhaifn`) are stored in plain text in `grafana/values.yaml` -- these should be overridden or externalized for production.
- The vLLM sidecar OTEL collector exports to the central collector over unencrypted HTTP (`tls.insecure: true`) because it is cluster-internal traffic.
- The `uwm` chart uses `storageClassName: nfs-client` for Prometheus PVCs, which is specific to the NVIDIA launchpad environment and must be changed for other clusters.
- Two separate PodMonitors target NIM pods with different label selectors (`app.kubernetes.io/name: nim-llm` vs `app: nim-llm`) and different scrape intervals (30s vs 15s with port `h2c`), suggesting the NIM pods expose metrics on multiple ports/labels.

## Testing Notes

- After deploying operators, verify CRDs are available: `oc get crd tempostacks.tempo.grafana.com`, `oc get crd opentelemetrycollectors.opentelemetry.io`, `oc get crd grafanas.grafana.integreatly.org`, `oc get crd uiplugins.observability.openshift.io`
- Check pods are running: `oc get pods -n observability-hub`
- Verify TempoStack is ready: `oc get tempostack -n observability-hub`
- Verify Grafana is ready: `oc get grafana -n observability-hub`
- Confirm PodMonitors are picking up targets: `oc get podmonitor -A`
- Test Grafana route: access the route created in `observability-hub` namespace

## Related Patterns

- vLLM/NIM model serving (the workload being monitored)
- Helm subchart deployment pattern (each operator and resource is its own chart)
- OpenShift OLM operator lifecycle management
- ODF/NooBaa object storage for trace persistence
