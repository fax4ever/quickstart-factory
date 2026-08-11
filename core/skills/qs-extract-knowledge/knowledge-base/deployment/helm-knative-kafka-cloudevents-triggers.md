---
name: helm-knative-kafka-cloudevents-triggers
description: Helm-templated Knative Triggers with Kafka broker for CloudEvent-driven microservice routing
summary: "This pattern deploys Helm-templated Knative Eventing Triggers backed by a Strimzi Kafka cluster (KRaft mode, KafkaNodePool CR) to route CloudEvents by type/source attributes between three microservices (integration-dispatcher, request-manager, agent-service) using 10 triggers with per-partition FIFO ordering for session-consistent delivery. Use when building event-driven multi-service architectures on OpenShift requiring ordered message routing — toggled via requestManagement.knative.eventing.enabled (disabled by default, enabled in values-production.yaml), requiring Red Hat AMQ Streams v3.0.0-13 and Knative Eventing with Kafka channel support. All triggers annotated with kafka.eventing.knative.dev/delivery.order: ordered, data-flow triggers use retry: 10 with exponential backoff (PT1S) while notification triggers use retry: 2 for best-effort delivery, broker URL centralized at requestManagement.knative.broker.url with numPartitions: 6. The helm-install-prod Makefile target retries 3 times with 30s backoff because Knative Trigger creation races Kafka broker readiness — it validates all 10 triggers and broker reach Ready; ordered delivery reduces throughput vs unordered; mock eventing (requestManagement.knative.mockEventing.enabled) provides HTTP-based non-Kafka alternative for CI/testing."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, kafka]
  ai_pattern: [agents]
  platform: [openshift, kubernetes]
source_examples:
  - quickstart: "it-self-service-agent"
    repo: "https://github.com/rh-ai-quickstart/it-self-service-agent"
    notes: "10 Knative Triggers routing CloudEvents between 3 microservices via Kafka broker with ordered delivery"
    approach: "A"
---

# Knative Kafka CloudEvents Trigger Routing

## Overview

This pattern uses Helm-templated Knative Eventing Triggers backed by a Strimzi Kafka cluster to implement event-driven routing between microservices. Ten triggers route CloudEvents by `type` and `source` attributes between three services (integration-dispatcher, request-manager, agent-service), with per-partition FIFO ordering enforced via Kafka annotations.

## Pattern Description

The system deploys a Strimzi Kafka cluster (KRaft mode, no ZooKeeper) as the message backbone, a Knative Broker pointing to that Kafka cluster, and ten Trigger resources that route CloudEvents based on `type`/`source` attribute filtering. All triggers use `kafka.eventing.knative.dev/delivery.order: ordered` annotation for per-partition FIFO delivery, ensuring session-consistent message ordering. The entire eventing layer is conditionally deployed via `requestManagement.knative.eventing.enabled`.

## Implementation

### Kafka Cluster (Strimzi KRaft)

A Kafka CR and KafkaNodePool deploy a single-node Kafka cluster using Red Hat AMQ Streams:

```yaml
# helm/templates/kafka-cluster.yaml (excerpt)
apiVersion: kafka.strimzi.io/v1beta2
kind: Kafka
metadata:
  name: {{ .Values.requestManagement.kafka.name }}
  annotations:
    strimzi.io/node-pools: enabled
    strimzi.io/kraft: enabled
spec:
  kafka:
    listeners:
    - name: plain
      port: 9092
      type: internal
      tls: false
    config:
      default.replication.factor: {{ .Values.requestManagement.kafka.config.defaultReplicationFactor }}
      auto.create.topics.enable: false
```

### Trigger Routing by CloudEvent Attributes

Each trigger filters on `type` and optionally `source` attributes to route events to the correct service endpoint:

```yaml
# helm/templates/knative-triggers.yaml (excerpt)
apiVersion: eventing.knative.dev/v1
kind: Trigger
metadata:
  name: {{ include "self-service-agent.fullname" . }}-request-created-trigger
  annotations:
    kafka.eventing.knative.dev/delivery.order: ordered
spec:
  broker: {{ .Values.requestManagement.knative.broker.name }}
  filter:
    attributes:
      type: com.self-service-agent.request.created
      source: request-manager
  subscriber:
    uri: http://{{ include "self-service-agent.fullname" . }}-agent-service.{{ .Release.Namespace }}.svc.cluster.local/api/v1/events/cloudevents
  delivery:
    retry: 10
    backoffPolicy: exponential
    backoffDelay: PT1S
```

### Event Type Catalog

The ten triggers implement this routing topology:

| Event Type | Source | Subscriber | Purpose |
|-----------|--------|-----------|---------|
| `request.created` | integration-dispatcher | request-manager | Inbound user request |
| `request.created` | request-manager | agent-service | Forward to agent |
| `agent.response-ready` | request-manager | integration-dispatcher | Deliver response |
| `agent.response-ready` | agent-service | request-manager | Agent reply |
| `request.created` (requiresrouting=true) | any | agent-service | Routing decision |
| `request.created` | any | integration-dispatcher /notifications | Ack notification |
| `request.processing` | any | integration-dispatcher /notifications | Processing status |
| `request.database-update` | request-manager | agent-service | DB sync |
| `session.create-or-get` | request-manager | request-manager | Session mgmt |
| `session.ready` | request-manager | request-manager | Session ready |

### Knative Broker Configuration

The broker URL is centralized in values for use by services that need to publish events:

```yaml
# helm/values.yaml (excerpt)
requestManagement:
  knative:
    broker:
      name: "self-service-agent-broker"
      url: "http://kafka-broker-ingress.knative-eventing.svc.cluster.local"
      config:
        numPartitions: 6
```

## Configuration

- **Key settings:** `requestManagement.knative.eventing.enabled` toggles the entire eventing layer (Kafka + Broker + all 10 Triggers); `requestManagement.kafka.config.defaultReplicationFactor` and `numPartitions` tune Kafka; broker name is configurable
- **Defaults:** Eventing is disabled by default (`enabled: false`); Kafka uses ephemeral storage with 1 replica for dev; production values (`values-production.yaml`) enable eventing
- **Dependencies:** Requires Strimzi operator (Red Hat AMQ Streams v3.0.0-13) and Knative Eventing with Kafka channel support installed on the cluster

## Gotchas

- The `helm-install-prod` Makefile target includes retry logic (3 attempts with 30s backoff) specifically because Knative Trigger creation can race with Kafka broker readiness -- it validates all 10 triggers and the broker reach Ready condition before succeeding (see `Makefile` `helm-install-prod` target)
- Notification triggers (`request.created` and `request.processing` to `/notifications` endpoint) use `retry: 2` instead of `retry: 10` used by data-flow triggers, reflecting that notifications are best-effort (see `helm/templates/knative-triggers.yaml`)
- All triggers use `kafka.eventing.knative.dev/delivery.order: ordered` for per-partition FIFO -- this is critical for session consistency but reduces throughput compared to unordered delivery
- The mock eventing service (`requestManagement.knative.mockEventing.enabled`) provides a non-Kafka alternative for testing/CI where Strimzi is unavailable -- events flow via HTTP POST between services instead (see `helm/values-test.yaml`)

## Related Patterns

- `helm-umbrella-mixed-remote-local-committed-deps.md` -- umbrella chart containing this eventing layer
