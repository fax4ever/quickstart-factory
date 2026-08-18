---
name: infinispan
description: Infinispan Data Grid as distributed cache for event correlation and prompt storage in Camel-based pipelines
summary: "Infinispan Server 16.0 (quay.io/infinispan/server:16.0) provides distributed in-memory caching for OpenTelemetry event correlation and AI prompt storage in Camel/Quarkus pipelines, deployed as a standalone single-replica Deployment (no Operator/Helm) with Hot Rod on port 11222 using DIGEST-MD5 SASL from infra-accounts Secret. Use when Camel routes need shared event aggregation with time-based deferred processing -- three SYNC distributed caches are defined: events (600s TTL, traces keyed by otel-{traceId}), events-to-process (20s TTL triggering CLIENT_CACHE_ENTRY_EXPIRED listener for deferred LLM analysis via JMS without polling), and ai-messages (no TTL, per-trace prompts with fallback to default). Critical config requires dual property blocks (camel.component.infinispan.* with security-realm=default/security-server-name=infinispan AND quarkus.infinispan-client.*) with INFINISPAN_HOSTS from infra-endpoints ConfigMap; caches are created post-startup via REST API curl after polling 30 attempts at 2s intervals. Caches must exist before clients deploy or runtime errors occur; all caches use text/plain encoding storing JSON as strings; PUTIFABSENT on events-to-process prevents duplicate analyses; 256Mi/512Mi memory limits are sandbox-only."
metadata:
  type: component
tags:
  tech_stack: [infinispan, camel, quarkus, hotrod]
  ai_pattern: [data-pipeline]
  platform: [openshift]
  data_layer: [infinispan]
source_examples:
  - quickstart: "smart-telemetry-pipeline"
    repo: "https://github.com/rh-ai-quickstart/smart-telemetry-pipeline"
    notes: "Infinispan as distributed cache for OpenTelemetry event correlation and AI prompt storage via Camel routes"
    approach: "A"
---

# Infinispan

## Overview

Infinispan (Red Hat Data Grid) serves as a distributed in-memory cache for grouping and temporarily storing correlated telemetry events before AI analysis. In the smart-telemetry-pipeline quickstart, it holds OpenTelemetry logs and traces keyed by traceId, uses TTL-based expiration to trigger deferred processing, and stores per-trace AI prompts for the LLM analyzer.

## Tech Stack & Dependencies

- **Runtime:** Infinispan Server 16.0
- **Container image:** `quay.io/infinispan/server:16.0`
- **Protocol:** Hot Rod (port 11222)
- **Authentication:** DIGEST-MD5 SASL via `infra-accounts` secret (`DATAGRID_USERNAME` / `DATAGRID_PASSWORD`)
- **Client integration:** Camel Infinispan component + Quarkus Infinispan Client extension
- **Helm subchart:** None -- deployed as a standalone Kubernetes Deployment via raw YAML manifest

## Key Patterns

### Standalone Deployment via Raw YAML

Infinispan is deployed as a single-replica Deployment with a Service exposing the Hot Rod port. No Operator or Helm subchart is used. Credentials are injected from a shared `infra-accounts` Secret.

```yaml
# deploy/resources/infinispan/infinispan-sandbox.yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: infinispan
  labels:
    app: infinispan
    app.kubernetes.io/part-of: smart-log-analyzer
    app.openshift.io/runtime: infinispan
spec:
  replicas: 1
  selector:
    matchLabels:
      app: infinispan
  template:
    spec:
      containers:
        - name: infinispan
          image: quay.io/infinispan/server:16.0
          ports:
            - containerPort: 11222
          env:
            - name: USER
              valueFrom:
                secretKeyRef:
                  name: infra-accounts
                  key: DATAGRID_USERNAME
            - name: PASS
              valueFrom:
                secretKeyRef:
                  name: infra-accounts
                  key: DATAGRID_PASSWORD
```

### Cache Creation via REST API

Caches are not auto-created. The deployment script creates them post-startup by `oc exec`-ing `curl` commands against the Infinispan REST API inside the pod. Each cache is defined as a JSON file in `deploy/resources/infinispan/caches/`.

```bash
# create.sh -- cache creation loop
ISPN_POD=$(oc get pod -l app=infinispan -o jsonpath='{.items[0].metadata.name}')

for CACHE_FILE in deploy/resources/infinispan/caches/*.json; do
  CACHE_NAME=$(basename "${CACHE_FILE}" .json)
  oc exec "${ISPN_POD}" -- curl -sf \
    -u admin:password --digest \
    -X POST "http://localhost:11222/rest/v2/caches/${CACHE_NAME}" \
    -H 'Content-Type: application/json' \
    -d "$(cat "${CACHE_FILE}")"
done
```

### Distributed Cache Definitions with TTL Expiration

Three caches are defined, all using SYNC mode with `text/plain` encoding. Two use TTL-based expiration to control deferred processing.

```json
// deploy/resources/infinispan/caches/events.json
{
  "events": {
    "distributed-cache": {
      "mode": "SYNC",
      "statistics": true,
      "encoding": { "media-type": "text/plain" },
      "expiration": { "lifespan": "600000" }
    }
  }
}
```

```json
// deploy/resources/infinispan/caches/events-to-process.json -- 20s TTL triggers analysis
{
  "events-to-process": {
    "distributed-cache": {
      "mode": "SYNC",
      "statistics": true,
      "encoding": { "media-type": "text/plain" },
      "expiration": { "lifespan": "20000" }
    }
  }
}
```

The `ai-messages` cache has no expiration (prompts persist indefinitely).

### Camel Infinispan Component for Event Correlation

The correlator stores telemetry events in the `events` cache keyed by `otel-{traceId}`, appending new records to an existing JSON array. Error events are also written to `events-to-process` with PUTIFABSENT.

```yaml
# src/correlator/infinispan.camel.yaml -- store pattern
- setHeader:
    name: CamelInfinispanKey
    simple: otel-${variable.traceId}
- to:
    uri: infinispan:events
    parameters:
      operation: GET
# ... append to array, then PUT back ...
- to:
    uri: infinispan:events
    parameters:
      operation: PUT
```

### TTL-Driven Event Processing via Cache Expiration Listener

The correlator listens for `CLIENT_CACHE_ENTRY_EXPIRED` events on the `events-to-process` cache. When a traceId entry expires (after the 20-second TTL), the expired key is forwarded to a JMS queue for LLM analysis -- implementing a deferred-processing pattern without polling.

```yaml
# src/correlator/infinispan.camel.yaml -- expiration listener
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

### Prompt Storage in ai-messages Cache

The `ai-messages` cache stores system prompts, default prompts, and per-trace custom prompts. The analyzer reads per-trace prompts with a fallback to the default prompt.

```yaml
# src/analyzer/error-analyzer.camel.yaml -- prompt read with fallback
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

## Configuration

- **Environment variables:**
  - `INFINISPAN_HOSTS` -- server address, set via `infra-endpoints` ConfigMap (e.g., `infinispan.${NS}.svc:11222`)
  - `DATAGRID_USERNAME` / `DATAGRID_PASSWORD` -- credentials from `infra-accounts` Secret
- **Quarkus properties (both correlator and analyzer):**
  ```properties
  quarkus.infinispan-client.hosts=${INFINISPAN_HOSTS:infinispan:11222}
  quarkus.infinispan-client.username=${DATAGRID_USERNAME}
  quarkus.infinispan-client.password=${DATAGRID_PASSWORD}
  quarkus.infinispan-client.sasl-mechanism=DIGEST-MD5
  ```
- **Camel component properties (both correlator and analyzer):**
  ```properties
  camel.component.infinispan.hosts=${INFINISPAN_HOSTS:infinispan:11222}
  camel.component.infinispan.username=${DATAGRID_USERNAME}
  camel.component.infinispan.password=${DATAGRID_PASSWORD}
  camel.component.infinispan.sasl-mechanism=DIGEST-MD5
  camel.component.infinispan.security-realm=default
  camel.component.infinispan.security-server-name=infinispan
  camel.component.infinispan.secure=true
  ```

## Known Gotchas

- **Caches must be created after pod startup:** The Infinispan server starts with no caches. The `create.sh` script waits for the REST API to become available (polling up to 30 attempts with 2-second intervals) before creating caches via `curl`. Deploying clients before caches exist will cause runtime errors.
- **Dual client configuration required:** Both `camel.component.infinispan.*` and `quarkus.infinispan-client.*` properties must be set in the Quarkus properties files. The Camel component properties configure the Camel route operations while the Quarkus extension properties configure the Hot Rod client used for cache event listeners (e.g., `CLIENT_CACHE_ENTRY_EXPIRED`).
- **text/plain encoding for all caches:** All caches use `text/plain` media type encoding. The Camel routes store JSON as plain strings (`CamelInfinispanValue` set via `simple` expressions), not as typed objects.
- **PUTIFABSENT for deduplication:** Error events use `PUTIFABSENT` on the `events-to-process` cache to avoid triggering duplicate analyses for the same traceId.
- **Resource limits:** The Deployment sets 256Mi request / 512Mi limit for memory, suitable for sandbox. Production workloads with large trace volumes would require tuning.

## Testing Notes

- After deployment, verify caches exist via: `oc exec <pod> -- curl -u admin:password --digest http://localhost:11222/rest/v2/caches`
- Confirm the three caches (`events`, `events-to-process`, `ai-messages`) are listed
- Monitor cache statistics via the Infinispan REST API or the Camel Micrometer metrics (`correlator.events.stored`, `correlator.events.expired`)

## Related Patterns

- Kafka (telemetry ingestion upstream of Infinispan)
- Camel routes (primary client for Infinispan operations)
- Artemis JMS (downstream of cache expiration events)
