---
name: analyzer
description: "Apache Camel YAML DSL component that retrieves OTel events from Infinispan and sends them to an LLM for root cause analysis"
summary: "Apache Camel YAML DSL analyzer (zero Java code) consumes trace IDs from Artemis JMS, retrieves correlated OTel events from Infinispan, assembles prompts with per-trace override fallback (`${traceId}-prompt-msg` -> default `prompt-msg`), and calls a KServe-served Granite LLM via `camel-openai` with micrometer timer instrumentation (`analyzer.llm.duration`). Use for event-driven root cause analysis pipelines needing Camel YAML DSL routes with JMS/Infinispan/LLM integration; built via Tekton `camel export --runtime=quarkus` into a Quarkus JVM container on ubi10/openjdk-21-runtime, deployed alongside correlator and ui-console from a shared Helm chart. Tracks processing state through routeConfiguration interceptFrom/onCompletion writing JSON to /tmp served via REST status API; supports interactive re-analysis on a separate JMS queue (error-logs-interactive) that skips system prompts and proceeds with empty event sets. Key gotchas: Netty native transport fails in restricted containers (requires -Dio.netty.transport.noNative=true), dual Infinispan client config needed for both Camel and Quarkus extensions, JMS pooling via quarkus-pooled-jms with maxSessionsPerConnection=500 is critical, standalone Camel metrics must be disabled (camel.metrics.enabled=false) in favor of Quarkus metrics, and an init container must build a Java truststore with the OpenShift service CA for TLS to KServe."
metadata:
  type: component
tags:
  tech_stack: [apache-camel, quarkus, java, infinispan, artemis-jms, openai-api, micrometer]
  ai_pattern: [model-serving, data-pipeline]
  platform: [openshift, rhoai, kserve]
  data_layer: [infinispan]
source_examples:
  - quickstart: "smart-telemetry-pipeline"
    repo: "https://github.com/rh-ai-quickstart/smart-telemetry-pipeline"
    notes: "Camel YAML DSL analyzer that retrieves correlated OTel events from Infinispan by traceId and sends them to a Granite LLM for root cause analysis via OpenAI-compatible API"
    approach: "A"
---

# Analyzer

## Overview

The analyzer is an Apache Camel application written entirely in YAML DSL that consumes trace IDs from JMS queues, retrieves correlated OpenTelemetry events from Infinispan (Red Hat Data Grid), constructs prompts from cached system/user messages, and sends them to an LLM via the Camel OpenAI component for root cause analysis. It publishes results back to a JMS queue and exposes a REST status API and Prometheus metrics. On OpenShift, it is built from Camel JBang source using `camel export --runtime=quarkus` in a Tekton pipeline and deployed as a standard Quarkus JVM container.

## Tech Stack & Dependencies

- **Runtime:** Apache Camel 4.18.x on Quarkus 3.33.x (Red Hat productized builds)
- **Container image:** `registry.access.redhat.com/ubi10/openjdk-21-runtime:latest` (Quarkus fast-jar layout)
- **Key dependencies:** `camel-openai`, `camel-jms`, `camel-infinispan`, `camel-platform-http`, `camel-rest`, `camel-file`, `camel-observability-services`, `artemis-jakarta-client-all`, `quarkus-pooled-jms`
- **Helm subchart:** None -- deployed via a shared Helm chart (`chart/`) that templates all three app components (correlator, analyzer, ui-console) from `values.yaml`

## Key Patterns

### Camel YAML DSL Routes (No Java Code)

The entire analyzer is defined in two YAML files with no compiled Java source. Camel JBang interprets them locally; the Tekton pipeline runs `camel export --runtime=quarkus` to generate a full Maven/Quarkus project for production deployment.

```yaml
# src/analyzer/error-analyzer.camel.yaml (route definition)
- route:
    id: error-log-analyzer
    routeConfigurationId: state-configuration
    description: Analyze error logs
    from:
      uri: jms:{{camel.jms.queue.error-logs}}
      steps:
        - setHeader:
            name: CamelInfinispanKey
            simple: otel-${variable.traceId}
        - to:
            uri: infinispan:events
            parameters:
              operation: GET
```

### Multi-Source Prompt Assembly from Infinispan Cache

The analyzer assembles LLM prompts from multiple Infinispan cache entries. It supports per-trace prompt overrides (keyed as `${traceId}-prompt-msg`) with a fallback to a default prompt (keyed as `prompt-msg`). System prompts are loaded from a separate cache key (`system-msg`) and conditionally omitted for interactive requests.

```yaml
# Prompt cache lookup with per-trace override fallback
- setHeader:
    name: CamelInfinispanKey
    simple: ${variable.traceId}-prompt-msg
- to:
    uri: infinispan:ai-messages
    parameters:
      operation: GET
- choice:
    when:
      - simple: "${body} == null || ${body} == ''"
        steps:
          - setHeader:
              name: CamelInfinispanKey
              constant: prompt-msg
          - to:
              uri: infinispan:ai-messages
              parameters:
                operation: GET
```

### OpenAI-Compatible LLM Integration via Camel Component

The analyzer calls the LLM using the `camel-openai` component with `CamelOpenAISystemMessage` header for system prompts. The body contains the assembled user prompt with trace events appended. The OpenAI endpoint is configured to point at a KServe InferenceService (Granite model) via cluster-internal HTTPS.

```yaml
# LLM call with metrics instrumentation
- to:
    uri: "micrometer:timer:analyzer.llm.duration?action=start"
- to:
    uri: openai:chat-completion
- to:
    uri: "micrometer:timer:analyzer.llm.duration?action=stop"
```

```yaml
# OpenAI secret pointing to KServe InferenceService (deploy/resources/secrets/openai.yaml)
stringData:
  OPENAI_API_KEY: "dummy"
  OPENAI_BASE_URL: https://isvc-granite-31-8b-fp8-predictor.sandbox-shared-models.svc.cluster.local:8443/v1
  OPENAI_MODEL: isvc-granite-31-8b-fp8
```

### Route Configuration for Processing State Tracking

A `routeConfiguration` block uses `interceptFrom` and `onCompletion` callbacks to write a JSON state file to `/tmp/smart-log-analyzer/analyzer-state.json`. This file is served by a separate REST route (`status-api.camel.yaml`) at `/api/analyzer/state` so the UI can show whether an analysis is in progress.

```yaml
- routeConfiguration:
    id: state-configuration
    interceptFrom:
      - interceptFrom:
          steps:
            - setBody:
                simple: >-
                  {"active":true,"traceId":"${variable.traceId}","startedAtEpochMs":${messageTimestamp},...}
            - to:
                uri: "file:/tmp/smart-log-analyzer"
    onCompletion:
      - onCompletion:
          steps:
            - setBody:
                simple: >-
                  {"active":false,"traceId":"${variable.traceId}",...}
            - to:
                uri: "file:/tmp/smart-log-analyzer"
```

### Interactive Re-Analysis via Separate JMS Queue

The analyzer exposes a second route (`interactive-log-analyzer`) on a separate JMS queue (`error-logs-interactive`) that allows the UI to trigger re-analysis of a specific trace. Interactive requests skip the system prompt and proceed even when no events are found in Infinispan (using an empty array), enabling free-form prompt-based queries.

```yaml
- route:
    id: interactive-log-analyzer
    from:
      uri: jms:{{camel.jms.queue.error-logs-interactive}}
      steps:
        - setVariable:
            name: opHeader
            constant: interactive
        # Proceeds with empty events if not found in cache
```

### OpenShift Service CA Trust for TLS to KServe

The analyzer deployment uses an init container to build a Java truststore that includes the OpenShift service CA certificate. This is required because the KServe InferenceService endpoint uses cluster-internal TLS signed by the OpenShift service CA, which is not in the default JDK truststore.

```yaml
# chart/values.yaml -- analyzer-specific config
analyzer:
  serviceCa:
    enabled: true
    configMap: service-ca-bundle
```

```yaml
# chart/templates/deployment.yaml -- init container builds truststore
initContainers:
  - name: build-truststore
    command: ['sh', '-c']
    args:
      - |
        cat "$JAVA_HOME/lib/security/cacerts" > /tmp/truststore/truststore.jks
        chmod 664 /tmp/truststore/truststore.jks
        if [ -f /service-ca/service-ca.crt ]; then
          keytool -import -trustcacerts -alias openshift-service-ca \
            -file /service-ca/service-ca.crt \
            -keystore /tmp/truststore/truststore.jks \
            -storepass changeit -noprompt
        fi
```

## Configuration

- **Environment variables:**
  - `OPENAI_API_KEY` -- API key for the LLM endpoint (dummy value when using KServe)
  - `OPENAI_BASE_URL` -- Full URL to the OpenAI-compatible endpoint (e.g., KServe InferenceService `/v1`)
  - `OPENAI_MODEL` -- Model name matching the KServe InferenceService name
  - `INFINISPAN_HOSTS` -- Infinispan/Data Grid host:port (default: `infinispan:11222`)
  - `DATAGRID_USERNAME` / `DATAGRID_PASSWORD` -- Infinispan credentials
  - `ARTEMIS_BROKER_URL` -- ActiveMQ Artemis broker URL (default: `tcp://artemis:61616`)
  - `AMQ_USERNAME` / `AMQ_PASSWORD` -- Artemis credentials
  - `JAVA_OPTS_APPEND` -- Injected by Helm; includes Netty native transport workaround and truststore path
- **Config files:**
  - `src/analyzer/application-dev.properties` -- Local dev config with `camel.jbang.dependencies` for JBang mode
  - `chart/properties/analyzer/application-prod-quarkus.properties` -- Production config mounted as ConfigMap; disables standalone Camel metrics (uses Quarkus metrics instead)
- **Helm values:** `components.analyzer.enabled`, `components.analyzer.replicas`, `components.analyzer.memoryLimit` (default 512Mi), `components.analyzer.secrets` (list of Secret names), `components.analyzer.serviceCa.enabled`
- **JMS queues:** `error-logs` (input), `error-logs-interactive` (interactive input), `analysis-result` (output)
- **Infinispan caches:** `events` (OTel event storage), `ai-messages` (prompt/system message storage)

## Known Gotchas

- **Netty native transport fails on OpenShift:** The Helm chart sets `JAVA_OPTS_APPEND="-Dio.netty.transport.noNative=true"` globally via `nettyWorkaround: true` in `values.yaml`. Without this, Netty attempts to load native epoll transport which fails in the restricted container environment.
- **Quarkus disables standalone Camel metrics:** The production properties file (`application-prod-quarkus.properties`) explicitly sets `camel.metrics.enabled=false` and `camel.management.enabled=false` because standalone Camel metrics conflict with Quarkus's own metrics subsystem. The dev properties file enables them for local JBang use.
- **Dual Infinispan client configuration in production:** The production properties file configures both `camel.component.infinispan.*` (for Camel routes) and `quarkus.infinispan-client.*` (for the Quarkus extension). Both must be set with the same credentials for the exported Quarkus application to function correctly.
- **JMS connection pooling is critical:** The config uses `JmsPoolConnectionFactory` with `maxSessionsPerConnection=500` and `connectionIdleTimeout=20000`. The pooled-jms library (`quarkus-pooled-jms`) is added as an explicit dependency in the Tekton build pipeline.
- **State file-based status API:** The analyzer writes processing state to a temporary file (`/tmp/smart-log-analyzer/analyzer-state.json`) rather than using in-memory state. The status API route uses `pollEnrich` with a 250ms timeout and `noop=true&idempotent=false` to read it without consuming it. If the file is missing or unreadable, the API returns a default inactive state.

## Testing Notes

- Verify the analyzer pod is running: `oc get pods -l app=analyzer`
- Check the status API endpoint: `curl http://analyzer:8089/api/analyzer/state` (should return `{"active":false,...}` when idle)
- Metrics are scraped by Prometheus via ServiceMonitor on port 9876 at `/observe/metrics`
- The PrometheusRule defines `AnalysisCompleted` alert that fires on `increase(analyzer_analyses_completed_total[1m]) > 0`
- Monitor the `analyzer.llm.duration` timer metric for LLM response latency
- Verify the truststore init container completed: `oc logs <pod> -c build-truststore`
- Check that the `openai` secret has the correct `OPENAI_BASE_URL` pointing to the KServe InferenceService

## Related Patterns

- Correlator component (event correlation and cache population that feeds the analyzer)
- UI Console component (consumes analysis results from the output JMS queue)
- Infinispan/Data Grid (event cache and prompt storage)
- ActiveMQ Artemis (JMS message broker for inter-component communication)
- Tekton build pipeline with `camel export --runtime=quarkus` for Camel JBang-to-Quarkus conversion
