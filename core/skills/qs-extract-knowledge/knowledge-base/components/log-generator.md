---
name: log-generator
description: Camel-based telemetry data generator with bundled OTel Java agent, built and deployed via Tekton Pipelines
summary: "Apache Camel YAML DSL application simulating order processing (~30 orders/min, 30% failure rate across three error types) with a health-checker route to produce realistic logs and traces for testing observability pipelines on OpenShift. Use when you need a synthetic telemetry source that bundles the OTel Java agent directly in the container (built on camel-launcher:4.18.1.redhat-00016 with camel-opentelemetry2) — eliminates the OTel Operator/Instrumentation CR dependency; deployed via Tekton Pipeline with Buildah and oc CLI, not Helm. All source files (Camel routes, agent.properties disabling metrics export, Dockerfile downloading the OTel agent) are generated inline in the Tekton pipeline YAML; deployment creates at zero replicas, sets OTEL_EXPORTER_OTLP_ENDPOINT (grpc) and agent env vars, then scales to 1. OTel agent latest-tag download from GitHub breaks in air-gapped environments, namespace sed substitution in run.sh fails if the namespace contains the literal string \"NAMESPACE\", and all application edits must be made inside pipeline.yaml since no separate source files exist."
metadata:
  type: component
tags:
  tech_stack: [apache-camel, opentelemetry, tekton, buildah, java]
  ai_pattern: [data-pipeline, observability]
  platform: [openshift]
  data_layer: []
source_examples:
  - quickstart: "smart-telemetry-pipeline"
    repo: "https://github.com/rh-ai-quickstart/smart-telemetry-pipeline"
    notes: "Camel log generator simulating order processing failures for telemetry pipeline testing"
    approach: "A"
---

# Log Generator

## Overview

The log generator is an Apache Camel application that simulates order processing with random failures to produce realistic telemetry data for testing observability pipelines on OpenShift. It bundles the OpenTelemetry Java agent directly in its container image, removing the need for an external OTel Operator or Instrumentation CR. Logs and traces are exported via OTLP to an OTel Collector, which forwards them through Kafka for downstream correlation and AI-powered analysis.

## Tech Stack & Dependencies

- **Runtime:** Apache Camel (via `camel-launcher` image, version `4.18.1.redhat-00016`) with `camel-opentelemetry2` dependency
- **Container image:** Built from `camel-launcher` base in the OpenShift internal registry (`image-registry.openshift-image-registry.svc:5000/<namespace>/camel-launcher:<version>`)
- **Key dependencies:** OpenTelemetry Java agent (downloaded at build time from GitHub releases), OTel Collector endpoint for OTLP export, Tekton Pipelines for build and deploy
- **Helm subchart:** None -- deployed via Tekton Pipeline with Buildah image build and `oc` CLI deployment

## Key Patterns

### Camel Route-Based Log Simulation

The generator uses Camel YAML DSL routes to produce structured log output. Two routes run concurrently: an order-processor that fires every 2 seconds with a 30% failure rate across three error types, and a health-checker that emits DEBUG logs every 5 seconds.

```yaml
# 30% failure rate with three error categories
- route:
    id: order-processor
    from:
      uri: timer:orderProcessor
      parameters:
        period: "{{timer.order.period:2000}}"
        fixedRate: true
      steps:
        - setVariable:
            name: orderId
            simple: "ORD-${random(10000,99999)}"
        - choice:
            when:
              - simple: "${random(0,100)} < 30"
                steps:
                  - choice:
                      when:
                        - simple: "${random(0,100)} < 33"
                          steps:
                            - throwException:
                                message: "Database connection failed: Connection refused to postgres:5432 ..."
                                exceptionType: java.lang.RuntimeException
```

### Bundled OTel Java Agent (No Operator Required)

The OpenTelemetry Java agent is downloaded and embedded directly in the container image at build time. This eliminates the dependency on the OTel Operator or an `Instrumentation` CR for auto-instrumentation.

```dockerfile
FROM ${CAMEL_IMAGE}
USER root
RUN curl -fsSL -o /opt/opentelemetry-javaagent.jar \
    https://github.com/open-telemetry/opentelemetry-java-instrumentation/releases/latest/download/opentelemetry-javaagent.jar
COPY agent.properties /opt/agent.properties
ENV JAVA_OPTS="-javaagent:/opt/opentelemetry-javaagent.jar"
ENV OTEL_JAVAAGENT_CONFIGURATION_FILE=/opt/agent.properties
```

The agent properties file disables metrics export and Apache HTTP client instrumentation to reduce noise:

```properties
otel.service.name=log-generator
otel.traces.exporter=otlp
otel.metrics.exporter=none
otel.logs.exporter=otlp
otel.instrumentation.apache-httpclient.enabled=false
```

### Tekton Pipeline Build and Deploy

The entire build-deploy lifecycle is managed by a Tekton Pipeline with four tasks: workspace initialization, source preparation (inline task that generates all files), Buildah image build, and `oc`-based deployment.

```yaml
# Deploy task uses oc CLI to create and configure the Deployment
oc create deployment ${APP} \
  --image="${IMAGE}" \
  --replicas=0 \
  -n "${NS}" --dry-run=client -o yaml | oc apply -f -

oc set env deployment/${APP} -n "${NS}" \
  OTEL_EXPORTER_OTLP_ENDPOINT="${OTEL_ENDPOINT}" \
  OTEL_EXPORTER_OTLP_PROTOCOL=grpc

oc scale deployment/${APP} -n "${NS}" --replicas=1
```

### Inline Source Generation in Tekton Task

All source files (Camel route YAML, application properties, OTel agent properties, Dockerfile) are generated inline within the `prepare-sources` Tekton task step rather than cloned from a Git repository. The entire application definition lives inside the pipeline YAML.

```yaml
# Camel OpenTelemetry integration config
camel.opentelemetry2.enabled = true
camel.opentelemetry2.traceProcessors = true
camel.jbang.dependencies=org.apache.camel:camel-opentelemetry2
```

### Shell Script Wrapper with Namespace Auto-Detection

The `run.sh` script auto-detects the current OpenShift namespace via `oc project -q` and substitutes it into the PipelineRun manifest using `sed`, avoiding hardcoded namespace values.

```bash
NS=$(oc project -q)
sed "s/NAMESPACE/${NS}/g" log-generator/pipelinerun.yaml | oc apply -f -
tkn pipelinerun logs deploy-log-generator-run -f
```

## Configuration

- **Environment variables:**
  - `OTEL_EXPORTER_OTLP_ENDPOINT` -- OTLP collector endpoint, set on the Deployment at deploy time (e.g., `http://camel-otel-collector-opentelemetry-collector.<namespace>.svc:4317`)
  - `OTEL_EXPORTER_OTLP_PROTOCOL` -- set to `grpc` for the collector connection
  - `JAVA_OPTS` -- set to `-javaagent:/opt/opentelemetry-javaagent.jar` in the Dockerfile
  - `OTEL_JAVAAGENT_CONFIGURATION_FILE` -- points to `/opt/agent.properties`
- **Config files:**
  - `agent.properties` -- OTel Java agent configuration (service name, exporter settings)
  - `application-dev.properties` -- Camel OpenTelemetry2 integration settings
  - `log-generator.camel.yaml` -- Camel route definitions
- **Helm values:** Not applicable -- deployed via Tekton Pipeline, not Helm
- **Pipeline parameters:**
  - `namespace` -- target OpenShift namespace (default: `slog-analyzer`)
  - `otel-collector-endpoint` -- OTLP collector endpoint (default: `http://camel-otel-collector-opentelemetry-collector.slog-analyzer.svc:4317`)
  - `camel-launcher-version` -- tag of the `camel-launcher` base image (default: `4.18.1.redhat-00016`)
  - `camel-image` -- override for the full base image reference (empty by default; auto-constructed from namespace and version)

## Known Gotchas

- **All source files are inline in the pipeline YAML:** The Camel route, properties files, and Dockerfile are all generated inside the `prepare-sources` Tekton task step. Editing the application requires modifying `pipeline.yaml`, not separate source files.
- **Deployment starts at zero replicas:** The deploy task creates the Deployment with `--replicas=0`, then sets environment variables, then scales to 1. This prevents the pod from starting before the OTLP endpoint is configured.
- **Namespace placeholder uses simple sed substitution:** The PipelineRun YAML contains the literal string `NAMESPACE` which `run.sh` replaces via `sed "s/NAMESPACE/${NS}/g"`. If the namespace itself contains the string "NAMESPACE", this would cause issues.
- **OTel agent downloaded at build time from GitHub:** The Dockerfile downloads `opentelemetry-javaagent.jar` from GitHub releases using the `latest` tag. In air-gapped or restricted environments, this URL would need to be replaced with an internal mirror.
- **Pipeline cleanup after run:** The `run.sh` script deletes the PipelineRun and associated TaskRuns after completion. The `delete.sh` script separately handles deleting the Deployment, ImageStream, Pipeline, and orphaned ReplicaSets.
- **camel-image parameter override:** The pipeline supports overriding the base image via `camel-image` parameter. When empty (default), it constructs the image reference from the namespace and `camel-launcher-version`. This allows using a pre-built image from a different registry.

## Testing Notes

- Verify the pod is running: `oc get pods -l app=log-generator`
- Check logs for order processing output: `oc logs deployment/log-generator`
- Expect a mix of INFO-level order success/failure logs and DEBUG-level health checks
- Confirm OTLP export by checking the OTel Collector logs for received telemetry
- The generator produces roughly 30 orders/minute (one every 2 seconds) with ~9 failures/minute

## Related Patterns

- `otel-collector.md` -- OTel Collector that receives the generated telemetry
- `kafka.md` -- Kafka broker where the collector forwards telemetry events
