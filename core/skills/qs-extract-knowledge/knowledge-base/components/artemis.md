---
name: artemis
description: "ActiveMQ Artemis message broker deployed as a Kubernetes Deployment for JMS-based inter-component messaging"
summary: "ActiveMQ Artemis 2.38.0 provides JMS-based inter-component messaging for event-driven AI pipelines, decoupling Camel/Quarkus services (correlator, analyzer, ui-console) via five queues (error-logs, error-logs-interactive, analysis-result, ai-prompts, ai-prompts-read) on OpenShift. Deploy as a single-replica Kubernetes Deployment from quay.io/artemiscloud (not the AMQ Broker Operator) when lightweight, non-persistent JMS brokering is sufficient for sandbox/demo workloads with Camel route integration. Clients use artemis-jakarta-client-all:2.44.0 with quarkus-pooled-jms:2.12.0 (maxSessionsPerConnection=500) configured via Camel bean properties, broker URL dynamically injected through an infra-endpoints ConfigMap, and queue names externalized as Camel properties referenced in routes as `jms:{{camel.jms.queue.<name>}}`. No PVC means all messages are in-memory and lost on restart; broker expects `AMQ_USER` but the infra-accounts Secret stores credentials under `AMQ_USERNAME` (mapped via secretKeyRef); broker URL in infra-endpoints ConfigMap is namespace-scoped requiring regeneration on namespace change; 512Mi memory limit and 500-session pool need tuning when scaling consumers."
metadata:
  type: component
tags:
  tech_stack: [activemq-artemis, jms, amqp, camel, quarkus]
  ai_pattern: [data-pipeline]
  platform: [openshift, kubernetes]
source_examples:
  - quickstart: "smart-telemetry-pipeline"
    repo: "https://github.com/rh-ai-quickstart/smart-telemetry-pipeline"
    notes: "Artemis broker as JMS backbone connecting correlator, analyzer, and ui-console Camel apps"
    approach: "A"
---

# Artemis

## Overview

ActiveMQ Artemis is used as a lightweight JMS message broker to decouple application components in event-driven AI pipelines. In quickstart architectures, it acts as the glue between telemetry correlation, LLM-based analysis, and UI presentation layers. It is deployed as a plain Kubernetes Deployment (not via the AMQ Broker Operator) using the community container image from `quay.io/artemiscloud`.

## Tech Stack & Dependencies

- **Runtime:** ActiveMQ Artemis 2.38.0
- **Container image:** `quay.io/artemiscloud/activemq-artemis-broker:artemis.2.38.0`
- **Protocols exposed:** Core (port 61616), AMQP (port 5672), Web Console (port 8161)
- **Client library:** `org.apache.activemq:artemis-jakarta-client-all:2.44.0`
- **Connection pooling:** `io.quarkiverse.messaginghub:quarkus-pooled-jms:2.12.0`
- **Helm subchart:** None -- deployed as a standalone raw Kubernetes manifest

## Key Patterns

### Standalone Deployment Manifest (No Operator)

Artemis is deployed as a single-replica Kubernetes Deployment with a companion Service, using raw YAML rather than the AMQ Broker Operator or a Helm subchart. Credentials are injected from a shared `infra-accounts` Secret.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: artemis
  labels:
    app.kubernetes.io/part-of: smart-log-analyzer
    app.openshift.io/runtime: amq
spec:
  replicas: 1
  template:
    spec:
      containers:
        - name: artemis
          image: quay.io/artemiscloud/activemq-artemis-broker:artemis.2.38.0
          env:
            - name: AMQ_USER
              valueFrom:
                secretKeyRef:
                  name: infra-accounts
                  key: AMQ_USERNAME
            - name: AMQ_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: infra-accounts
                  key: AMQ_PASSWORD
            - name: AMQ_REQUIRE_LOGIN
              value: "true"
```

Source: `deploy/resources/amq-broker/artemis-sandbox.yaml`

### Pooled JMS Connection Factory via Camel Properties

All consuming applications (correlator, analyzer, ui-console) share the same Camel-based JMS configuration pattern. The connection factory is defined using Camel bean properties, wrapped in a pooled connection factory, and wired to the JMS component.

```properties
# Artemis JMS configuration for OpenShift
camel.beans.artemisCF = #class:org.apache.activemq.artemis.jms.client.ActiveMQConnectionFactory
camel.beans.artemisCF.brokerURL = ${ARTEMIS_BROKER_URL:tcp://artemis:61616}
camel.beans.artemisCF.user = ${AMQ_USERNAME}
camel.beans.artemisCF.password = ${AMQ_PASSWORD}
camel.beans.poolCF = #class:org.messaginghub.pooled.jms.JmsPoolConnectionFactory
camel.beans.poolCF.connectionFactory = #bean:artemisCF
camel.beans.poolCF.maxSessionsPerConnection = 500
camel.beans.poolCF.connectionIdleTimeout = 20000
camel.component.jms.connection-factory = #bean:poolCF
```

Source: `chart/properties/analyzer/application-prod-quarkus.properties` (identical block in correlator and ui-console)

### Queue Naming via Camel Properties

Queue names are externalized as Camel properties rather than hardcoded in routes. This allows each component to declare only the queues it uses.

```properties
# Correlator queues
camel.jms.queue.error-logs=error-logs
camel.jms.queue.ai-prompts=ai-prompts
camel.jms.queue.ai-prompts-read=ai-prompts-read

# Analyzer queues
camel.jms.queue.error-logs=error-logs
camel.jms.queue.error-logs-interactive=error-logs-interactive
camel.jms.queue.analysis-result=analysis-result
```

Referenced in Camel routes as `jms:{{camel.jms.queue.error-logs}}`.

Source: `chart/properties/correlator/application-prod-quarkus.properties`, `chart/properties/analyzer/application-prod-quarkus.properties`

### Artemis Management Queue for Stats

The ui-console queries broker queue statistics via the built-in `activemq.management` queue using JMS message headers `_AMQ_ResourceName` and `_AMQ_Attribute` for InOut request/reply.

```yaml
- setHeader:
    name: _AMQ_ResourceName
    constant: "queue.error-logs"
- setHeader:
    name: _AMQ_Attribute
    constant: "messageCount"
- to:
    uri: "jms:queue:activemq.management?exchangePattern=InOut&requestTimeout=3000"
- convertBodyTo:
    type: String
- setVariable:
    name: errorLogsCount
    jq:
      expression: "try (.[0] | tonumber) catch -1"
```

Source: `src/ui-console/infra-api.camel.yaml` (route `route-queue-stats`, lines 228-276)

## Configuration

- **Environment variables:**
  - `AMQ_USER` / `AMQ_PASSWORD` -- broker authentication credentials (injected from `infra-accounts` Secret)
  - `AMQ_REQUIRE_LOGIN` -- set to `"true"` to enforce authentication
  - `ARTEMIS_BROKER_URL` -- connection URL for clients (e.g., `tcp://artemis.<namespace>.svc:61616`), created dynamically in the `infra-endpoints` ConfigMap
  - `AMQ_USERNAME` / `AMQ_PASSWORD` -- client-side credential keys from the same `infra-accounts` Secret
- **Config files:** Application properties at `chart/properties/<component>/application-prod-quarkus.properties`
- **Queues used:**
  - `error-logs` -- traceIds forwarded from correlator to analyzer
  - `error-logs-interactive` -- user-triggered re-analysis requests from ui-console to analyzer
  - `analysis-result` -- LLM analysis results from analyzer to ui-console
  - `ai-prompts` -- prompt storage (correlator to ui-console)
  - `ai-prompts-read` -- prompt retrieval (correlator to ui-console)

## Known Gotchas

- **Broker URL is namespace-scoped:** The `infra-endpoints` ConfigMap is created dynamically by `create.sh` with the namespace interpolated into the URL (`tcp://artemis.${NS}.svc:61616`). This is not a static manifest -- it must be regenerated if the namespace changes.
- **Shared credentials Secret:** Both the broker itself (`AMQ_USER`/`AMQ_PASSWORD`) and the client applications (`AMQ_USERNAME`/`AMQ_PASSWORD`) reference the same `infra-accounts` Secret, but with slightly different key names. The broker image expects `AMQ_USER` while the Secret stores the value under `AMQ_USERNAME`. This works because the Deployment maps `AMQ_USER` via `secretKeyRef` to the `AMQ_USERNAME` key.
- **No persistence configured:** The Deployment has no PVC -- all messages are stored in-memory. Broker restart loses unprocessed messages. This is acceptable for the sandbox/demo use case.
- **Resource constraints:** Memory is capped at 512Mi (limit) / 256Mi (request) with 250m CPU request. The `maxSessionsPerConnection = 500` pool setting should be tuned if scaling the number of consuming components.

## Testing Notes

- Verify broker is ready: `oc wait deployment/artemis --for=condition=Available --timeout=180s`
- Check Service ports: Core (61616), AMQP (5672), Console (8161)
- Queue stats can be checked via the ui-console REST endpoint at `/api/queue-stats` which queries the `activemq.management` queue
- Confirm client connectivity by checking Camel route health endpoints at `/observe/health/ready` on each consuming component

## Related Patterns

- Camel-based event-driven architectures using JMS for inter-service messaging
- Infrastructure endpoint injection via dynamically created ConfigMaps
- Shared credential management via Kubernetes Secrets with `envFrom`
