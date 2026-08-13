---
name: event-driven-ai-pipeline
description: Event-driven telemetry correlation pipeline using cache-based deferred triggering and LLM root cause analysis
summary: "Solves automated root cause analysis of correlated distributed system telemetry by ingesting OTel logs and traces from Kafka via Apache Camel YAML DSL routes, normalizing with Kaoto DataMapper XSLT, and correlating events in Infinispan as sorted JSON arrays keyed by traceId. Use for event-driven automatic analysis where errors should trigger LLM inference without human intervention -- prefer over agent-based observability-summarization (tool-calling on-demand queries) when you need a fully decoupled pipeline with cache-based deferred triggering and async JMS (Artemis) messaging between stages. Core mechanism is the events-to-process Infinispan cache with 20s TTL and PUTIFABSENT deduplication that fires CLIENT_CACHE_ENTRY_EXPIRED to trigger analysis via Artemis JMS; the analyzer constructs two-level prompts (system + user from ai-messages cache with per-trace override) and calls Granite on KServe/vLLM through Camel's openai component, with error detection via jq checking both severityText==\"error\" and numeric status==\"2\". TLS to KServe requires a custom Java truststore init container importing the OpenShift service CA certificate (-Djavax.net.ssl.trustStore), Netty native transport must be disabled (-Dio.netty.transport.noNative=true), events arriving after the 20s collection window are excluded from initial analysis (though the events cache retains data for 600s for interactive re-analysis via JMS InOnly fire-and-forget), and JMS pool requires maxSessionsPerConnection=500 to prevent connection exhaustion."
metadata:
  type: architecture
tags:
  tech_stack: [apache-camel, quarkus, kafka, infinispan, artemis, opentelemetry, kaoto, java]
  ai_pattern: [data-pipeline, prompt-chaining]
  platform: [openshift, kserve, vllm]
  data_layer: [infinispan]
source_examples:
  - quickstart: "smart-telemetry-pipeline"
    repo: "https://github.com/rh-ai-quickstart/smart-telemetry-pipeline"
    notes: "Event-driven observability pipeline using Apache Camel routes to correlate OTel logs/traces in Infinispan, trigger LLM analysis on cache expiration, and serve root cause analysis results through a web console"
    approach: "A"
---

# Event-Driven AI Pipeline

## Overview

This architecture implements an event-driven data pipeline where streaming telemetry data (logs and traces) is ingested from Kafka, correlated by a shared key (traceId) in an in-memory data grid (Infinispan), and then sent to an LLM for analysis when a deferred trigger fires (cache entry expiration). The pipeline uses Apache Camel YAML DSL routes as the integration framework, with JMS (Artemis) queues for async messaging between pipeline stages. The pattern solves the problem of analyzing correlated distributed system events without requiring synchronous orchestration -- all stages are decoupled through message brokers and cache events.

## Data Flow

1. Instrumented applications emit OTLP logs and traces to the OpenTelemetry Collector (ports 4317/4318)
2. OTel Collector exports logs and traces to Kafka topics (`otlp_logs`, `otlp_spans`) in OTLP JSON encoding
3. Correlator Camel routes consume from Kafka topics, splitting batch payloads into individual records via JSONPath
4. Kaoto DataMapper (XSLT transformations) transforms raw OTel JSON into simplified correlated formats (log entries and span entries)
5. Transformed records are stored in the Infinispan `events` cache, grouped by traceId as sorted JSON arrays
6. If the record has ERROR severity or error status, the traceId is also stored in the `events-to-process` cache (20-second TTL, PUTIFABSENT to avoid duplicates)
7. When the `events-to-process` entry expires (after 20s collection window), the `CLIENT_CACHE_ENTRY_EXPIRED` event fires
8. The expiration handler sends the traceId to the JMS `error-logs` queue
9. Analyzer Camel route consumes the traceId from JMS, retrieves all correlated events from the Infinispan `events` cache
10. Analyzer constructs a prompt (system message from `ai-messages` cache + user prompt with events JSON), calls the OpenAI-compatible LLM via Camel's `openai` component
11. LLM response is published to the JMS `analysis-result` queue
12. UI Console consumes from `analysis-result` queue, persists results as text files on a PVC
13. UI Console serves results through REST API (`/api/traces`) and an embedded HTML/JavaScript web interface

## Component Wiring

| From | To | Protocol | Purpose |
|------|----|----------|---------|
| Instrumented apps | OTel Collector | OTLP gRPC/HTTP (4317/4318) | Emit logs and traces |
| OTel Collector | Kafka (`otlp_logs`, `otlp_spans`) | Kafka producer (OTLP JSON) | Export telemetry to streaming topics |
| Correlator | Kafka | Kafka consumer (port 9092) | Consume logs and traces |
| Correlator | Infinispan (`events` cache) | Hot Rod (port 11222) | Store correlated events by traceId |
| Correlator | Infinispan (`events-to-process` cache) | Hot Rod (port 11222) | Mark error traceIds for deferred processing |
| Infinispan | Correlator | Hot Rod event listener | Notify on cache entry expiration (`CLIENT_CACHE_ENTRY_EXPIRED`) |
| Correlator | Artemis (`error-logs` queue) | JMS/AMQP (port 61616) | Send traceIds for analysis |
| Correlator | Infinispan (`ai-messages` cache) | Hot Rod (port 11222) | Store/retrieve per-trace and default prompts |
| Analyzer | Artemis (`error-logs` queue) | JMS/AMQP (port 61616) | Consume traceIds to analyze |
| Analyzer | Infinispan (`events` cache) | Hot Rod (port 11222) | Retrieve correlated events for a traceId |
| Analyzer | Infinispan (`ai-messages` cache) | Hot Rod (port 11222) | Retrieve system and user prompts |
| Analyzer | Granite LLM (KServe/vLLM) | HTTPS (OpenAI-compatible `/v1` API) | Root cause analysis inference |
| Analyzer | Artemis (`analysis-result` queue) | JMS/AMQP (port 61616) | Publish analysis results |
| UI Console | Artemis (`analysis-result` queue) | JMS/AMQP (port 61616) | Consume and persist analysis results |
| UI Console | File system (PVC) | Local file I/O | Persist analysis results as text files |
| UI Console | Correlator/Analyzer | HTTP (Prometheus scrape at port 9876) | Proxy metrics for infrastructure dashboard |
| UI Console | Infinispan REST API | HTTP (port 11222, Digest auth) | Query cache entry count statistics |
| UI Console | Artemis management | JMS management queue | Query queue message counts |
| Browser | UI Console | HTTP REST (port 8080) | Serve web UI and trace/metrics APIs |

## Key Integration Points

### Kafka to Camel Ingestion with Kaoto DataMapper

The correlator consumes raw OTel JSON from Kafka, splits batch payloads into individual records using JSONPath, and applies Kaoto-generated XSLT transformations to normalize the data into a simplified correlated format suitable for LLM analysis.

```yaml
# src/correlator/logs-mapper.camel.yaml (lines 1-55)
- route:
    id: log-consumer
    description: Consume Kafka logs
    from:
      uri: kafka:{{camel.kafka.topic.logs}}
      parameters:
        autoOffsetReset: earliest
        groupId: correlator
      steps:
        - split:
            expression:
              jsonpath:
                expression: $.resourceLogs[*].scopeLogs[*].logRecords[*]
                writeAsString: true
            steps:
              - step:
                  id: kaoto-datamapper-4a94acc3
                  steps:
                    - to:
                        uri: xslt-saxon:kaoto-datamapper-4a94acc3.xsl
                        parameters:
                          allowStAX: true
              - to:
                  uri: direct
                  parameters:
                    name: store
```

### Cache-Based Deferred Triggering via TTL Expiration

Error events are stored in a short-lived cache (`events-to-process`, 20s TTL) using PUTIFABSENT to deduplicate. When the entry expires, the Infinispan `CLIENT_CACHE_ENTRY_EXPIRED` event triggers analysis. This creates a collection window: all events for a traceId that arrive within 20 seconds of the first error are correlated before analysis begins.

```yaml
# src/correlator/infinispan.camel.yaml (lines 101-146)
# Error detection and marking
- choice:
    description: Check error severity
    when:
      - steps:
          - setHeader:
              name: CamelInfinispanKey
              simple: ${variable.traceId}
          - setHeader:
              name: CamelInfinispanValue
              simple: ${variable.traceId}
          - to:
              description: Mark to process
              uri: infinispan:events-to-process
              parameters:
                operation: PUTIFABSENT
        jq:
          expression: (.severityText // "" | ascii_downcase) == "error" or .status == "2"

# Cache expiration handler
- route:
    id: route-expired-events
    from:
      uri: infinispan:events-to-process
      parameters:
        eventTypes: CLIENT_CACHE_ENTRY_EXPIRED
      steps:
        - setBody:
            simple: ${header.CamelInfinispanKey}
        - to:
            uri: jms:{{camel.jms.queue.error-logs}}
```

The `events-to-process` cache is configured with a 20-second lifespan:

```json
// deploy/resources/infinispan/caches/events-to-process.json
{
  "events-to-process": {
    "distributed-cache": {
      "mode": "SYNC",
      "expiration": {
        "lifespan": "20000"
      }
    }
  }
}
```

### Infinispan Event Correlation with Sorted JSON Arrays

Correlated events are stored as JSON arrays in Infinispan, sorted by `timeUnixNano`. When a new record arrives, the existing array is fetched, the new record is appended using jq, and the combined array is re-sorted and stored back. This ensures the LLM receives events in chronological order.

```yaml
# src/correlator/infinispan.camel.yaml (lines 40-70)
- choice:
    description: Check existing records
    otherwise:
      steps:
        - claimCheck:
            key: currentRecord
            operation: Get
        - setBody:
            jq:
              expression: "[.]"
              resultType: java.lang.String
    when:
      - steps:
          - setVariable:
              name: existingRecords
              simple: ${body}
          - claimCheck:
              key: currentRecord
              operation: Get
          - setBody:
              jq:
                expression: (variable("existingRecords") | fromjson) + [.] |
                  sort_by(.timeUnixNano)
                resultType: java.lang.String
        simple: ${body} != null && ${body} != ''
```

### LLM Prompt Construction with Cached System and User Messages

The analyzer retrieves prompts from the `ai-messages` Infinispan cache, supporting per-trace custom prompts with fallback to a default prompt. The prompt body includes the correlated events JSON, giving the LLM full context of all spans and logs for the trace.

```yaml
# src/analyzer/error-analyzer.camel.yaml (lines 109-188)
- route:
    id: run-analysis
    from:
      uri: direct:run-analysis
      steps:
        - setHeader:
            name: CamelInfinispanKey
            simple: ${variable.traceId}-prompt-msg
        - to:
            description: Get per-trace prompt from cache
            uri: infinispan:ai-messages
            parameters:
              operation: GET
        - choice:
            description: Fallback to default prompt if per-trace not found
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
        - setBody:
            description: Create prompt body
            simple: >-
              ${body}\n\nTrace ID: ${variable.traceId}\n\n
              Events (spans and logs sorted by timestamp):\n${variable.eventsJson}
        - to:
            description: Call OpenAI LLM
            uri: openai:chat-completion
```

### OpenAI-Compatible LLM via Camel Component with Service CA Trust

The analyzer uses Camel's `openai` component to call the LLM. The OpenAI base URL points to a KServe InferenceService (Granite model) using the cluster-internal HTTPS endpoint. An init container builds a custom Java truststore that includes the OpenShift service CA certificate for TLS verification.

```yaml
# deploy/resources/secrets/openai.yaml
apiVersion: v1
kind: Secret
metadata:
  name: openai
stringData:
  OPENAI_API_KEY: "dummy"
  OPENAI_BASE_URL: https://isvc-granite-31-8b-fp8-predictor.sandbox-shared-models.svc.cluster.local:8443/v1
  OPENAI_MODEL: isvc-granite-31-8b-fp8
```

```yaml
# chart/templates/deployment.yaml (lines 31-50) - Truststore init container
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

### Interactive Re-Analysis via JMS Fire-and-Forget

The UI Console supports interactive re-analysis where users provide custom prompts for a trace. The custom prompt is saved to Infinispan via JMS fire-and-forget (`InOnly`), then a separate JMS message triggers re-analysis on a dedicated interactive queue (`error-logs-interactive`). Results are stored with an `-it.txt` suffix and polled by the UI.

```yaml
# src/ui-console/rest-api.camel.yaml (lines 161-243)
# Save custom prompt
- route:
    id: route-post-trace-prompt
    from:
      uri: direct:post-trace-prompt
      steps:
        - setHeader:
            name: traceId
            simple: ${variable.traceId}
        - setBody:
            simple: ${variable.promptBody}
        - to:
            uri: "jms:queue:{{camel.jms.queue.ai-prompts}}?exchangePattern=InOnly"

# Trigger interactive analysis
- route:
    id: route-post-interactive
    from:
      uri: direct:post-interactive-analysis
      steps:
        - setBody:
            simple: ${variable.traceId}
        - to:
            uri: "jms:queue:{{camel.jms.queue.error-logs-interactive}}?exchangePattern=InOnly"
```

## Prompt / Chain Patterns

The architecture uses a two-level prompt structure stored in the Infinispan `ai-messages` cache:

1. **System prompt** (key: `system-msg`): Provides the LLM with instructions for root cause analysis behavior. Set via the `CamelOpenAISystemMessage` header. Cleared (set to empty string) for interactive mode to allow free-form conversation.

2. **User prompt** (key: `prompt-msg` for default, `{traceId}-prompt-msg` for per-trace override): Contains instructions for analyzing the events. The final prompt body appends the trace ID and the full correlated events JSON:

```
{prompt text}

Trace ID: {traceId}

Events (spans and logs sorted by timestamp):
{eventsJson}
```

For interactive re-analysis, the user prompt is prefixed with the original analysis result followed by the user's custom question, creating a conversational context without maintaining chat history. This is assembled in the UI Console JavaScript before saving to the `ai-messages` cache:

```javascript
// src/ui-console/index.html (lines 1140-1141)
const fullPrompt = currentTraceContent + '\n\n' + promptText;
await fetch(`${API_BASE}/${traceId}/prompt`, {
    method: 'POST',
    headers: { 'Content-Type': 'text/plain' },
    body: fullPrompt
});
```

## Gotchas

- The `events-to-process` cache uses a 20-second TTL (`"lifespan": "20000"`) as a collection window. Events arriving for the same traceId within this window are correlated together. If related events arrive after the TTL expires and the analysis has already been triggered, they will not be included in the analysis. The `events` cache itself has a longer 600-second (10-minute) TTL (`"lifespan": "600000"` in `deploy/resources/infinispan/caches/events.json`), so the data remains available in Infinispan for interactive re-analysis even after the initial trigger.
- The correlator uses `PUTIFABSENT` when writing to `events-to-process`, ensuring only the first error event for a given traceId starts the collection window timer. Subsequent error events for the same traceId do not reset the TTL.
- The analyzer's OpenAI connection requires a custom Java truststore that includes the OpenShift service CA certificate. An init container (`build-truststore`) copies the default JDK cacerts and imports the service CA cert via `keytool`. Without this, TLS verification fails when calling the KServe InferenceService endpoint over HTTPS. The JVM flag `-Djavax.net.ssl.trustStore=/tmp/truststore/truststore.jks` is set via the `JAVA_OPTS_APPEND` environment variable in `chart/templates/deployment.yaml`.
- Netty native transport is disabled (`-Dio.netty.transport.noNative=true` via `JAVA_OPTS_APPEND`) as a workaround across all three Camel components (`chart/values.yaml` line 41).
- The `events` cache uses `text/plain` encoding with `distributed-cache` mode in SYNC replication (`deploy/resources/infinispan/caches/events.json`). Even though only a single replica is deployed, the distributed cache mode is used to support potential scaling.
- Interactive analysis deletes any existing interactive result file before triggering re-analysis using Groovy `Files.deleteIfExists` (`src/ui-console/rest-api.camel.yaml` lines 212-216). The UI polls the `GET /api/traces/{id}/interactive` endpoint every 3 seconds up to 200 attempts (10 minutes) waiting for the new result to appear.
- The analyzer tracks its processing state by writing a JSON file (`analyzer-state.json`) to `/tmp/smart-log-analyzer` using Camel's `routeConfiguration` with `interceptFrom` (set active on message arrival) and `onCompletion` (set inactive when processing finishes). This is read by the status API (`/api/analyzer/state`) and proxied by the UI Console to show real-time analyzer activity on the infrastructure dashboard (`src/analyzer/error-analyzer.camel.yaml` lines 1-41, `src/analyzer/status-api.camel.yaml`).
- The Camel JMS connection pool (`JmsPoolConnectionFactory`) is configured with `maxSessionsPerConnection=500` and `connectionIdleTimeout=20000` across all three components to prevent connection exhaustion under load (`src/correlator/application-dev.properties` lines 16-18).
- Error severity detection uses jq to check both `severityText` (case-insensitive comparison to "error") and numeric `status` field (value "2" indicates error in OpenTelemetry span status), covering both log records and span records (`src/correlator/infinispan.camel.yaml` line 126).
- The OpenAI API key is set to `"dummy"` in the secret (`deploy/resources/secrets/openai.yaml`) because the sandbox-shared Granite model does not require authentication -- only the base URL and model name matter.

## Related Architectures

- [observability-summarization](observability-summarization.md) -- An alternative approach to AI-powered observability that uses tool-calling agents to query observability backends on-demand, versus this pipeline's event-driven automatic analysis
- [llm-observability-pipeline](llm-observability-pipeline.md) -- Covers the OpenTelemetry instrumentation side; this architecture consumes OTel data rather than producing it
