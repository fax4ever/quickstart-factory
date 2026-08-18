---
name: helm-otel-collector-kafka-exporter-filter-healthcheck
description: OTel Collector deployed via third-party Helm chart configured to export logs/traces to Kafka with healthcheck span filtering
summary: "Deploys the OTel Collector contrib image via the open-telemetry/opentelemetry-collector Helm chart as a telemetry ingestion layer that receives OTLP logs and traces and exports them to Kafka topics (otlp_logs, otlp_spans) in otlp_json encoding for downstream Camel consumer correlation and analysis. Use when building an OTLP-to-Kafka observability pipeline with span noise reduction -- requires the contrib image because the kafka exporter is absent from the core distribution; installed as a standalone helm install release (mode: deployment, single replica, not DaemonSet) via shell script with serviceAccount camel-otel-collector, not as a subchart dependency. Critical configuration: dual OTLP receivers on :4317 (gRPC) and :4318 (HTTP), kafka exporter targeting cluster-internal kafka:9092 with auto-created topics, filter/healthcheck processor using OTTL expression name == \"GET /actuator/health\" with error_mode: ignore applied to the traces pipeline only (logs pipeline has no filter), and a debug exporter enabled alongside kafka for troubleshooting. The healthcheck filter only matches Spring-style /actuator/health spans so other health paths pass through unfiltered; image.tag is empty string meaning the collector version is controlled by the Helm chart appVersion not the values file; Kafka must be deployed as a raw manifest and available before collector startup, ensured by shell script phased step ordering."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [opentelemetry, kafka, helm]
  ai_pattern: [data-pipeline]
  platform: [openshift]
source_examples:
  - quickstart: "smart-telemetry-pipeline"
    repo: "https://github.com/rh-ai-quickstart/smart-telemetry-pipeline"
    notes: "OTel Collector contrib image installed via open-telemetry Helm chart with Kafka exporter for OTLP JSON logs/traces and filter processor dropping healthcheck spans"
    approach: "A"
---

# OTel Collector with Kafka Exporter and Healthcheck Filter

## Overview

A deployment pattern using the official OpenTelemetry Helm chart to deploy the OTel Collector contrib image, configured to receive OTLP telemetry (gRPC and HTTP) and export both logs and traces to Kafka topics in OTLP JSON encoding. A filter processor drops healthcheck spans to reduce noise. This serves as the telemetry ingestion layer in a pipeline where downstream Camel applications consume from Kafka for correlation and analysis.

## Pattern Description

The OTel Collector is deployed as a Deployment (not DaemonSet) using the upstream Helm chart from the `open-telemetry` repo. The collector receives telemetry from instrumented applications via OTLP gRPC (port 4317) and HTTP (port 4318), processes traces through a filter that drops healthcheck spans, and exports both logs and traces to Kafka using the `kafka` exporter with `otlp_json` encoding. The Kafka broker is a cluster-internal single-node deployment. The Collector is installed via `helm install` in the orchestrator shell script, not as a subchart dependency.

## Implementation

### Helm Installation in Shell Script

The OTel Collector is installed as a standalone Helm release separate from the application chart:

```bash
# create.sh - Step 3: Deploy OTel Collector
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts 2>/dev/null || true
helm repo update
helm install camel-otel-collector open-telemetry/opentelemetry-collector \
  -f deploy/resources/otel-infra/otel-collector/values-sandbox.yaml \
  -n "${NS}" --wait --timeout 300s
```

### Values Configuration

The collector is configured as a Deployment with dual OTLP receivers, a Kafka exporter, and a healthcheck filter:

```yaml
# deploy/resources/otel-infra/otel-collector/values-sandbox.yaml
mode: deployment
replicaCount: 1

image:
  repository: ghcr.io/open-telemetry/opentelemetry-collector-releases/opentelemetry-collector-contrib

serviceAccount:
  create: true
  name: camel-otel-collector

config:
  receivers:
    otlp:
      protocols:
        grpc:
          endpoint: 0.0.0.0:4317
        http:
          endpoint: 0.0.0.0:4318

  processors:
    filter/healthcheck:
      error_mode: ignore
      traces:
        span:
          - 'name == "GET /actuator/health"'

  exporters:
    debug: {}
    kafka:
      brokers:
        - kafka:9092
      logs:
        encoding: otlp_json
      traces:
        encoding: otlp_json

  service:
    pipelines:
      logs:
        receivers: [otlp]
        exporters: [debug, kafka]
      traces:
        receivers: [otlp]
        processors: [filter/healthcheck]
        exporters: [debug, kafka]
```

### Kafka Infrastructure Dependency

The Kafka broker that the exporter targets is deployed separately as a raw manifest:

```yaml
# deploy/resources/otel-infra/kafka/kafka-sandbox.yaml (key config)
env:
  - name: KAFKA_PROCESS_ROLES
    value: "broker,controller"
  - name: KAFKA_LISTENERS
    value: "PLAINTEXT://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093"
  - name: KAFKA_AUTO_CREATE_TOPICS_ENABLE
    value: "true"
```

## Configuration

- **Key settings:** Kafka broker address `kafka:9092` (cluster-internal DNS); OTLP ports 4317 (gRPC) and 4318 (HTTP); uses the contrib image (includes Kafka exporter which is not in the core distribution)
- **Defaults:** `mode: deployment` (not DaemonSet); single replica; both logs and traces exported to Kafka; debug exporter also enabled for troubleshooting; Kafka auto-creates topics (`otlp_logs`, `otlp_spans`)
- **Dependencies:** Kafka must be deployed and available at `kafka:9092` before the OTel Collector starts (ensured by the shell script step ordering); the collector uses the `contrib` image variant because the Kafka exporter is not included in the core distribution

## Gotchas

- The healthcheck filter uses the OTTL expression `name == "GET /actuator/health"` to drop Spring-style health check spans -- this assumes the monitored applications use the `/actuator/health` endpoint pattern; other healthcheck paths would not be filtered
- The `error_mode: ignore` in the filter processor means malformed span names are silently ignored rather than causing the collector to error -- this is a safety measure for production stability
- The `image.tag` is empty string (`""`), meaning the Helm chart's default tag (matching the chart's appVersion) is used -- the specific OTel Collector version is controlled by the Helm chart version, not by this values file
- The Kafka exporter uses `otlp_json` encoding (not Protobuf) -- downstream Camel consumers parse these as JSON messages from the `otlp_logs` and `otlp_spans` topics

## Related Patterns

- `shell-script-phased-infra-helm-tekton-deploy-chain.md` -- the orchestrator that installs this as Step 3
