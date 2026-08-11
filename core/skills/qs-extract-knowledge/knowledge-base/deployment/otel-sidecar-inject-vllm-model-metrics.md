---
name: otel-sidecar-inject-vllm-model-metrics
description: OpenTelemetry Collector sidecar mode auto-injecting into vLLM pods for metrics and traces collection
summary: "Solves observability for vLLM model serving by deploying an OpenTelemetryCollector CR in sidecar mode (`charts/observability/helm/otel-collector/`) so the OTel Operator auto-injects a collector into any pod annotated with `sidecar.opentelemetry.io/inject: vllm-otelsidecar`, avoiding Helm chart modifications to model serving deployments. Use when you need per-pod metrics and traces from vLLM without altering model serving charts -- the sidecar is toggled via `sidecars.vllm.enabled` and complements PodMonitor-based collection (`helm-uwm-podmonitor-vllm`); requires OTel Operator installed and central OTel collector deployment in the `observability-hub` namespace. The sidecar scrapes vLLM's Prometheus `/metrics` at `localhost:8000` every 15s, accepts OTLP traces on grpc/http, and forwards all telemetry via OTLP HTTP to the central collector, which exports traces to Tempo gateway using `bearertokenauth` with the SA token. Critical gotcha: vLLM metrics port is 8000, not 8080 (serving port); sidecar-to-collector uses `insecure: true` TLS (in-cluster only); `targetAllocator` with `consistent-hashing` is configured in values but inactive for sidecar mode."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, opentelemetry]
  ai_pattern: [model-serving]
  platform: [openshift]
source_examples:
  - quickstart: "aml-rag-nvidia"
    repo: "https://github.com/rh-ai-quickstart/aml-rag-nvidia"
    notes: "OTel sidecar collector auto-injected into vLLM model server pods, scraping localhost:8000 metrics and forwarding to central OTel collector"
    approach: "A"
---

# OpenTelemetry Sidecar Injection for vLLM Model Metrics

## Overview

This pattern deploys an OpenTelemetryCollector custom resource in `sidecar` mode, which auto-injects an OTel collector container into any pod annotated with the matching sidecar annotation. The injected sidecar scrapes vLLM's Prometheus metrics endpoint on `localhost:8000`, collects OTLP traces, and forwards everything to a central OTel collector deployment in the observability namespace.

## Pattern Description

The OpenTelemetry Operator watches for OpenTelemetryCollector resources with `mode: sidecar`. When a pod is created with the annotation `sidecar.opentelemetry.io/inject: <sidecar-name>`, the operator mutates the pod spec to inject the collector as an additional container. This avoids modifying model serving Helm charts to add monitoring containers. The sidecar scrapes vLLM's built-in `/metrics` endpoint on localhost and forwards metrics and traces to the central collector via OTLP HTTP.

## Implementation

### Sidecar Collector Custom Resource

```yaml
# charts/observability/helm/otel-collector/templates/otel-collector-vllm-sidecar.yaml
{{- if .Values.sidecars.vllm.enabled -}}
apiVersion: opentelemetry.io/v1beta1
kind: OpenTelemetryCollector
metadata:
  name: {{ .Values.sidecars.vllm.name }}
  namespace: {{ include "otel-collector.namespace" . }}
spec:
  mode: sidecar
  managementState: managed
  upgradeStrategy: automatic
  config:
    exporters:
      debug: {}
      otlphttp:
        endpoint: {{ include "otel-collector.centralCollectorEndpoint" . }}
        tls:
          insecure: true
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
                - targets:
                    - 'localhost:8000'
    service:
      pipelines:
        traces:
          exporters: [debug, otlphttp]
          receivers: [otlp]
        metrics:
          exporters: [debug, otlphttp]
          receivers: [prometheus, otlp]
{{- end }}
```

### Central Collector with Tempo Export

The central OTel collector receives data from sidecars and exports traces to Tempo and metrics via Prometheus pull:

```yaml
# charts/observability/helm/otel-collector/values.yaml (excerpt)
collector:
  mode: deployment
  config:
    exporters:
      otlphttp/dev:
        endpoint: "https://tempo-tempostack-gateway.{{ .Values.global.namespace }}.svc.cluster.local:8080/api/traces/v1/dev"
        auth:
          authenticator: bearertokenauth
    extensions:
      bearertokenauth:
        filename: "/var/run/secrets/kubernetes.io/serviceaccount/token"
    service:
      pipelines:
        traces:
          exporters: [debug, otlphttp/dev]
```

### Sidecar Values Configuration

```yaml
# charts/observability/helm/otel-collector/values.yaml (excerpt)
sidecars:
  vllm:
    enabled: true
    name: "vllm-otelsidecar"
    injectAnnotation: "vllm-otelsidecar"
    targetAllocator:
      allocationStrategy: consistent-hashing
      filterStrategy: relabel-config
```

## Configuration

- **Key settings:** `sidecars.vllm.name` and `injectAnnotation` define the sidecar name and the annotation value pods must carry; `global.namespace: observability-hub` determines where the central collector and Tempo gateway live
- **Defaults:** Sidecar enabled by default; scrapes vLLM at `localhost:8000` every 15 seconds; exports to central collector with insecure TLS (within-cluster communication)
- **Dependencies:** OpenTelemetry Operator installed (via `otel-operator` Helm chart); model serving pods annotated with `sidecar.opentelemetry.io/inject: vllm-otelsidecar`; central OTel collector deployment running

## Gotchas

- The sidecar targets `localhost:8000` (vLLM's default metrics port), not port 8080 (the vLLM serving port exposed via KServe); these are different ports
- The central collector uses `bearertokenauth` with the ServiceAccount token for authenticating to Tempo gateway, while the sidecar-to-collector link uses `insecure: true` TLS since both are in-cluster
- The sidecar CR template comment notes that pods need the annotation `sidecar.opentelemetry.io/inject: vllm-otelsidecar` to receive the sidecar injection
- The `targetAllocator` with `consistent-hashing` strategy is configured in values but may not be active for sidecar mode (target allocator is primarily for StatefulSet/DaemonSet modes)

## Related Patterns

- `kserve-multi-model-mig-gpu-slicing.md` -- the vLLM model pods that receive the OTel sidecar injection
- `observability-olm-operator-helm-install.md` -- the OTel Operator installation that enables sidecar injection
- `helm-uwm-podmonitor-vllm.md` -- complementary PodMonitor-based metrics collection for vLLM
