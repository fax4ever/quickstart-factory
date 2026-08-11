---
name: otel-collector
description: OpenTelemetry Collector deployed via OTel Operator CRD with central deployment and sidecar injection for LLM observability
summary: "Provides centralized telemetry for LLM serving on RHOAI via the OTel Operator's OpenTelemetryCollector CRD (mode: deployment, upgradeStrategy: automatic) in a hub-and-spoke architecture -- a central collector in observability-hub receives OTLP from auto-injected sidecar collectors, routing traces to Tempo dev tenant (X-Scope-OrgID header) and exposing metrics. Use vLLM sidecars when the model server exposes a Prometheus metrics endpoint (scrapes localhost:8000 alongside OTLP traces) and LlamaStack sidecars for trace-only OTLP forwarding -- each toggled via sidecars.*.enabled Helm values and matched by sidecar.opentelemetry.io/inject annotation on pod templates. Helm _helpers.tpl constructs centralCollectorEndpoint and tempoGatewayEndpoint dynamically; bearertokenauth extension authenticates to Tempo gateway using SA token with ca_file: service-ca.crt and insecure: false (OpenShift service CA); namespace-prefixed ClusterRoles grant tempo.grafana.com/dev trace writes and pod/namespace/replicaset access for k8sattributes processor (requires KUBE_NODE_NAME env var via fieldRef spec.nodeName). OTel Operator appends \"-collector\" to CR name creating a doubled \"otel-collector-collector\" service name that sidecars must target, sidecar CR metadata.name must exactly match the injection annotation value, k8sattributes processor exists only in Helm-templated config (not base manifests), and kustomization.yaml omits sidecar resources suggesting separate deployment path."
metadata:
  type: component
tags:
  tech_stack: [opentelemetry, helm, opentelemetry-operator]
  ai_pattern: [model-serving]
  platform: [openshift, rhoai, kserve, vllm]
  data_layer: []
source_examples:
  - quickstart: "lls-observability"
    repo: "https://github.com/rh-ai-quickstart/lls-observability"
    notes: "Central OTel Collector deployment with vLLM and LlamaStack sidecar injection, Tempo trace export, Prometheus scraping"
    approach: "A"
---

# OpenTelemetry Collector

## Overview

The OpenTelemetry Collector is deployed using the OpenTelemetry Operator's `OpenTelemetryCollector` CRD, providing a hub-and-spoke telemetry architecture for LLM serving workloads on RHOAI. A central collector runs as a Deployment in the `observability-hub` namespace, receiving metrics and traces from model-serving pods via per-workload sidecar collectors that are auto-injected by the OTel Operator. This pattern avoids manual instrumentation plumbing and centralizes export configuration for backends like Tempo and Prometheus.

## Tech Stack & Dependencies

- **Runtime:** OpenTelemetry Collector v0.115.0 (managed by the OTel Operator)
- **Container image:** Managed by the OpenTelemetry Operator (no explicit image reference in the chart)
- **Key dependencies:** Red Hat Build of OpenTelemetry Operator, Tempo TempoStack (trace backend), Kubernetes service-account token auth
- **Helm subchart:** Standalone chart at `helm/02-observability/otel-collector/` (Chart.yaml `apiVersion: v2`, `version: 0.1.0`)

## Key Patterns

### Hub-and-Spoke Collector Architecture

A central collector runs as a `Deployment` and receives OTLP data from sidecar collectors injected into model-serving pods. The sidecars forward everything to the central collector over HTTP, which then routes traces to Tempo and exposes metrics.

```yaml
# Central collector - deployment mode
apiVersion: opentelemetry.io/v1beta1
kind: OpenTelemetryCollector
metadata:
  name: otel-collector
spec:
  mode: deployment
  serviceAccount: otel-collector
  upgradeStrategy: automatic
  managementState: managed
```

### Sidecar Injection via OTel Operator

Sidecar collectors are defined as `OpenTelemetryCollector` CRs with `mode: sidecar`. The OTel Operator injects them into any pod carrying the matching annotation. Each AI service type gets its own sidecar definition.

```yaml
# Sidecar definition - OTel Operator auto-injects into annotated pods
apiVersion: opentelemetry.io/v1beta1
kind: OpenTelemetryCollector
metadata:
  name: vllm-otelsidecar
spec:
  mode: sidecar
  config:
    exporters:
      otlphttp:
        endpoint: 'http://otel-collector-collector.observability-hub.svc.cluster.local:4318'
        tls:
          insecure: true
```

Pods opt in via annotation on the pod template:

```yaml
# In the workload Deployment template
metadata:
  annotations:
    sidecar.opentelemetry.io/inject: llamastack-otelsidecar
```

### vLLM Sidecar with Prometheus Scraping

The vLLM sidecar differs from the LlamaStack sidecar: it includes a `prometheus` receiver that scrapes vLLM's built-in metrics endpoint on `localhost:8000`, in addition to receiving OTLP traces. This creates both a metrics and traces pipeline in a single sidecar.

```yaml
# vLLM sidecar receivers - scrapes vLLM metrics locally
receivers:
  otlp:
    protocols:
      grpc: {}
      http: {}
  prometheus:
    config:
      scrape_configs:
        - job_name: vllm-sidecar
          scrape_interval: 15s
          static_configs:
            - targets: ['localhost:8000']
```

### LlamaStack Sidecar (Traces Only)

The LlamaStack sidecar is simpler -- it only receives OTLP traces (no Prometheus scraping) and forwards them to the central collector. LlamaStack's built-in OpenTelemetry instrumentation sends traces directly via OTLP.

```yaml
# LlamaStack sidecar - traces only, no Prometheus receiver
service:
  pipelines:
    traces:
      exporters: [debug, otlphttp]
      receivers: [otlp]
```

### Bearer Token Auth to Tempo Gateway

The central collector authenticates to the Tempo gateway using the Kubernetes service-account token, mounted at the standard path. The `bearertokenauth` extension is wired into the OTLP HTTP exporter.

```yaml
extensions:
  bearertokenauth:
    filename: "/var/run/secrets/kubernetes.io/serviceaccount/token"
exporters:
  otlphttp/dev:
    endpoint: "https://tempo-tempostack-gateway.observability-hub.svc.cluster.local:8080/api/traces/v1/dev"
    headers:
      X-Scope-OrgID: dev
    tls:
      insecure: false
      ca_file: /var/run/secrets/kubernetes.io/serviceaccount/service-ca.crt
    auth:
      authenticator: bearertokenauth
```

### Templated Endpoint Construction

The Helm chart constructs the Tempo gateway and central collector endpoints using helper templates, making the namespace and service names configurable:

```go
// _helpers.tpl - Tempo gateway endpoint
{{- define "otel-collector.tempoGatewayEndpoint" -}}
{{- with .Values.tempo.gateway }}
{{- printf "%s://%s.%s.svc.cluster.local:%s%s" .protocol .endpoint .namespace .port .path }}
{{- end }}
{{- end }}

// _helpers.tpl - Central collector endpoint for sidecars
{{- define "otel-collector.centralCollectorEndpoint" -}}
{{- printf "http://%s-collector.%s.svc.cluster.local:4318" .Values.collector.name .Values.global.namespace }}
{{- end }}
```

### Cluster-Scoped RBAC for Tempo and K8s Attributes

The collector requires a ClusterRole to write traces to the Tempo `dev` tenant and to list/watch pods, namespaces, and replicasets for the `k8sattributes` processor. The ClusterRole name includes the namespace to avoid conflicts across releases.

```yaml
rules:
  - apiGroups: ['tempo.grafana.com']
    resources: [dev]
    resourceNames: [traces]
    verbs: ['create']
  - apiGroups: ['']
    resources: ['pods', 'namespaces']
    verbs: ['get', 'watch', 'list']
  - apiGroups: ['apps']
    resources: ['replicasets']
    verbs: ['get', 'watch', 'list']
```

## Configuration

- **Environment variables:**
  - `KUBE_NODE_NAME` (via fieldRef `spec.nodeName`) -- used by the `k8sattributes` processor to filter by node
- **Config files:** Collector config is embedded in the `OpenTelemetryCollector` CR spec, not a separate ConfigMap
- **Helm values:**
  - `global.namespace` -- target namespace (default: `observability-hub`)
  - `collector.enabled` -- toggle main collector (default: `true`)
  - `collector.mode` -- deployment mode: `deployment`, `daemonset`, `sidecar`, `statefulset` (default: `deployment`)
  - `sidecars.llamastack.enabled` / `sidecars.vllm.enabled` -- toggle per-workload sidecars
  - `sidecars.*.injectAnnotation` -- annotation value pods use to opt-in to injection
  - `tempo.gateway.*` -- Tempo gateway endpoint components (protocol, endpoint, port, path, namespace)
  - `tempo.auth.orgID` -- Tempo tenant org ID (default: `dev`)
  - `prometheus.scrapeConfigs` -- map of Prometheus scrape targets for the central collector
  - `rbac.create` -- toggle ClusterRole/ClusterRoleBinding creation

## Known Gotchas

- **Sidecar collector name must match injection annotation:** The `metadata.name` of the sidecar `OpenTelemetryCollector` CR must match the value used in `sidecar.opentelemetry.io/inject` on the pod template. The chart uses `sidecars.*.injectAnnotation` for this, but the raw manifest and the Helm template must stay in sync.
- **Central collector service name follows OTel Operator convention:** The OTel Operator appends `-collector` to the CR name when creating the Service, so the sidecar endpoint is `otel-collector-collector.observability-hub.svc.cluster.local:4318` (note the doubled "collector"). This is encoded in the `otel-collector.centralCollectorEndpoint` helper template.
- **ClusterRole name includes namespace to avoid conflicts:** The `otel-collector.clusterResourceName` helper prepends the namespace to the fullname, preventing collisions when multiple Helm releases exist in different namespaces (see `_helpers.tpl`).
- **TLS to Tempo uses OpenShift service-ca:** The exporter sets `ca_file: /var/run/secrets/kubernetes.io/serviceaccount/service-ca.crt` rather than disabling TLS, relying on OpenShift's service CA certificate injection. The `insecure: false` setting is explicit.
- **Kustomization only includes base manifests, not sidecars:** The `kustomization.yaml` only references `sa.yaml`, `clusterrole.yaml`, and `otel-collector.yaml` -- the sidecar manifests are not in the kustomization resource list, suggesting they are deployed separately or only via Helm.
- **k8sattributes processor in Helm values but not in base manifest:** The `values.yaml` includes `k8sattributes` in the processors config and pipelines, but the raw `otel-collector.yaml` base manifest omits it. The Helm-templated version is the authoritative one.

## Testing Notes

- Verify collector is running: `kubectl get opentelemetrycollector otel-collector -n observability-hub`
- Check collector logs: `kubectl logs -n observability-hub deployment/otel-collector-collector`
- OTLP endpoints: gRPC at `:4317`, HTTP at `:4318`, metrics at `:8888`
- Test trace ingestion with curl: `curl -X POST otel-collector-collector.observability-hub.svc.cluster.local:4318/v1/traces -H "Content-Type: application/json" -d '{"resourceSpans": []}'`
- Verify RBAC: `kubectl auth can-i create dev --as=system:serviceaccount:observability-hub:otel-collector`
- Verify sidecar injection: check that pods with the `sidecar.opentelemetry.io/inject` annotation have an extra container

## Related Patterns

- `observability-stack.md` -- broader observability stack including Tempo, Grafana, and operator setup
- `tracing-config.md` -- application-level tracing configuration patterns
- `llamastack.md` -- LlamaStack deployment with OTel sidecar integration
