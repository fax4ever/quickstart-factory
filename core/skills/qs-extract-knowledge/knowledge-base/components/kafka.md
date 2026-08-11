---
name: kafka
description: "Strimzi Kafka cluster with KRaft mode for event-driven agent architectures on RHOAI"
summary: "Provides durable event-driven messaging for AI agent architectures on RHOAI by deploying Kafka via Strimzi/AMQ Streams in KRaft mode (no ZooKeeper) with KafkaNodePool dual-role nodes (controller+broker) backing a Knative Kafka Broker that routes CloudEvents between integration dispatcher, request manager, and agent service. Use when production workloads need guaranteed delivery and per-session ordering -- toggle `requestManagement.knative.eventing.enabled` to switch between real Kafka (production) and mock eventing service (dev/CI, constrained to 1 replica for partition-key ordering); `auto.create.topics.enable: false` delegates topic lifecycle to Knative. Bootstrap servers are wired via ConfigMap to Knative Broker with `broker.class: Kafka`, default 6 partitions, P7D retention, retry:10 with exponential backoff (PT0.2S); `BROKER_URL` env var points all services to the broker ingress; network policies restrict access to `kafka-broker-dispatcher` pods only. Must set both `partitionkey` (lowercase) and `partitionKey` (camelCase) plus the `ce-partitionkey` HTTP header on every CloudEvent or session ordering breaks; email Message-IDs require hashing via `_broker_safe_event_id()` to avoid broker failures from special characters; default storage type is `ephemeral` (data lost on restart) -- switch to `persistent-claim` for production."
metadata:
  type: component
tags:
  tech_stack: [kafka, strimzi, knative, cloudevents, python]
  ai_pattern: [agents, event-driven]
  platform: [openshift, rhoai, kubernetes]
source_examples:
  - quickstart: "it-self-service-agent"
    repo: "https://github.com/rh-ai-quickstart/it-self-service-agent"
    notes: "Strimzi Kafka with KRaft and KafkaNodePool backing Knative Kafka Broker for event-driven agent orchestration"
    approach: "A"
---

# Kafka

## Overview

Kafka serves as the durable messaging backbone for event-driven AI agent architectures on RHOAI. Deployed via the Strimzi operator (Red Hat AMQ Streams), it backs a Knative Kafka Broker that routes CloudEvents between microservices (integration dispatcher, request manager, agent service). This enables guaranteed delivery, per-session ordering via partition keys, and horizontal scalability for production workloads.

## Tech Stack & Dependencies

- **Runtime:** Apache Kafka via Strimzi operator (Red Hat AMQ Streams v3.0.0-13)
- **Container image:** Managed by Strimzi operator (no custom image)
- **Key dependencies:** Strimzi/AMQ Streams operator, Knative Eventing with KnativeKafka, OpenShift Serverless Operator
- **Helm subchart:** None -- deployed as a raw `Kafka` CR plus `KafkaNodePool` CR in the parent chart

## Key Patterns

### KRaft Mode with KafkaNodePool

Kafka is deployed in KRaft mode (no ZooKeeper) using Strimzi annotations. A `KafkaNodePool` manages broker storage and resources separately from the Kafka CR. Nodes serve dual roles (controller + broker).

```yaml
# helm/templates/kafka-cluster.yaml
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
      auto.create.topics.enable: false
```

```yaml
# KafkaNodePool -- dual-role nodes
apiVersion: kafka.strimzi.io/v1beta2
kind: KafkaNodePool
metadata:
  name: {{ .Values.requestManagement.kafka.name }}-pool
  labels:
    strimzi.io/cluster: {{ .Values.requestManagement.kafka.name }}
spec:
  replicas: {{ .Values.requestManagement.kafka.replicas }}
  roles:
    - controller
    - broker
  storage:
    type: {{ .Values.requestManagement.kafka.storage.type }}
```

### Conditional Deployment with Feature Gating

Kafka is only deployed when both the request management layer and Knative eventing are enabled. A mock eventing service substitutes Kafka in dev/CI environments.

```yaml
# helm/templates/kafka-cluster.yaml -- guard condition
{{- if and .Values.requestManagement.enabled .Values.requestManagement.knative.eventing.enabled }}
```

```yaml
# helm/values.yaml -- defaults: Kafka enabled but Knative eventing off (mock mode)
requestManagement:
  enabled: true
  knative:
    eventing:
      enabled: false  # Set to true to enable Knative eventing (production mode)
    mockEventing:
      enabled: true   # Default to mock eventing service
  kafka:
    enabled: true
    replicas: 1
    storage:
      type: "ephemeral"  # Use "persistent-claim" for production
      size: "10Gi"
```

### Knative Kafka Broker Wiring

Kafka backs a Knative Broker via a ConfigMap that specifies the bootstrap servers. The broker uses Kafka-class eventing with configurable partition count and retention.

```yaml
# helm/templates/knative-broker.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ .Values.requestManagement.knative.broker.name }}-config
data:
  bootstrap.servers: "{{ .Values.requestManagement.kafka.name }}-kafka-bootstrap.{{ .Release.Namespace }}.svc:9092"
  default.topic.partitions: "{{ .Values.requestManagement.knative.broker.config.numPartitions | default 6 }}"
  default.topic.replication.factor: "{{ .Values.requestManagement.knative.broker.config.replicationFactor | default 1 }}"
---
apiVersion: eventing.knative.dev/v1
kind: Broker
metadata:
  annotations:
    eventing.knative.dev/broker.class: Kafka
spec:
  config:
    apiVersion: v1
    kind: ConfigMap
    name: {{ .Values.requestManagement.knative.broker.name }}-config
  delivery:
    retry: 10
    backoffPolicy: exponential
    backoffDelay: PT0.2S
```

### Partition Key Ordering for Session Consistency

CloudEvents carry both `partitionkey` and `partitionKey` attributes (for broker compatibility). Session ID is the preferred partition key, with user ID as fallback. This ensures per-session FIFO ordering across Kafka partitions.

```python
# shared-models/src/shared_models/events.py
# Partition key for Kafka ordering (session_id preferred; user_id for first request)
# Use both partitionkey and partitionKey for Knative Kafka broker compatibility
partition_key = session_id or user_id
if partition_key:
    pk = str(partition_key)
    attributes["partitionkey"] = pk
    attributes["partitionKey"] = pk  # camelCase for some brokers
```

All Knative Triggers use ordered delivery annotation:

```yaml
# helm/templates/knative-triggers.yaml
annotations:
  kafka.eventing.knative.dev/delivery.order: ordered  # Per-partition FIFO for session ordering
```

### Broker-Safe Event IDs

Email Message-IDs contain special characters (`<`, `>`, `@`, `+`, `=`) that cause issues with Kafka/Knative brokers. The codebase hashes these into safe IDs.

```python
# shared-models/src/shared_models/events.py
def _broker_safe_event_id(request_id: str) -> str:
    """Produce a broker-safe event_id from request_id.

    Email Message-IDs (e.g. <CAPbJ+...@mail.gmail.com>) contain <, >, @, +, =
    that can cause issues with Kafka/Knative brokers. Use a hash-based ID instead.
    """
    if request_id.startswith("<") and "@" in request_id:
        digest = hashlib.sha256(request_id.encode()).hexdigest()[:32]
        return f"email-{digest}"
    return request_id
```

## Configuration

- **Environment variables:**
  - `BROKER_URL` -- Required for all services; points to Knative broker or mock eventing service (e.g., `http://kafka-broker-ingress.knative-eventing.svc.cluster.local`)
  - `EVENT_MAX_RETRIES` -- Max retry attempts for CloudEvent sends (default: 3)
  - `EVENT_BASE_DELAY` -- Base delay between retries in seconds (default: 1.0)
  - `EVENT_MAX_DELAY` -- Max delay cap in seconds (default: 10.0)
  - `EVENT_BACKOFF_MULTIPLIER` -- Exponential backoff multiplier (default: 2.0)
- **Helm values:**
  - `requestManagement.kafka.name` -- Kafka cluster name (default: `self-service-agent-kafka`)
  - `requestManagement.kafka.replicas` -- Broker replicas (default: 1)
  - `requestManagement.kafka.storage.type` -- `ephemeral` for dev, `persistent-claim` for production
  - `requestManagement.kafka.storage.size` -- PVC size when using persistent-claim (default: 10Gi)
  - `requestManagement.kafka.config.*` -- Replication factors and ISR settings (all default to 1)
  - `requestManagement.knative.broker.config.numPartitions` -- Topic partition count (default: 6)
  - `requestManagement.knative.broker.config.retentionDuration` -- Topic retention (default: P7D)

## Known Gotchas

- **Dual partition key attributes required:** The codebase sets both `partitionkey` (lowercase) and `partitionKey` (camelCase) on every CloudEvent because different Knative Kafka broker versions recognize different casing. The `ce-partitionkey` HTTP header is also set explicitly during sends. Omitting any of these can break session ordering. (Source: `shared-models/src/shared_models/events.py`, lines 118-123 and 310-312)
- **auto.create.topics.enable is false:** Topics are not auto-created; the Knative broker manages topic lifecycle. This is deliberate to prevent orphan topics. (Source: `helm/templates/kafka-cluster.yaml`, line 27)
- **Email Message-IDs break brokers:** Raw email Message-IDs (e.g., `<CAPbJ+...@mail.gmail.com>`) contain characters that cause Kafka/Knative broker issues. The `_broker_safe_event_id()` function hashes these into safe IDs. (Source: `shared-models/src/shared_models/events.py`, lines 53-64)
- **Mock eventing stays at 1 replica:** The mock eventing service must run with exactly 1 replica because partition-key ordering requires a single pod. Production Kafka mode has no such constraint. (Source: `helm/values.yaml`, line 357 comment)
- **Ephemeral storage is the default:** The default `storage.type` is `ephemeral`, which loses data on pod restart. Production deployments must switch to `persistent-claim`. (Source: `helm/values.yaml`, line 383)

## Testing Notes

- Dev/CI environments use the mock eventing service instead of real Kafka -- toggle via `requestManagement.knative.eventing.enabled` (false = mock mode)
- The mock eventing service simulates Kafka-like partition-key ordering with per-(subscriber, partition_key) queues
- To verify real Kafka, deploy with `make helm-install-prod` which sets `knative.eventing.enabled: true`
- Network policies restrict Kafka broker dispatcher access: only pods labeled `app: kafka-broker-dispatcher` in the `knative-eventing` namespace can reach application services

## Related Patterns

- `mock-eventing-service.md` -- Dev/CI substitute that simulates Kafka broker behavior
- `shared-models.md` -- CloudEvent builder and sender utilities
- `integration-dispatcher.md` -- Consumes agent response events from the broker
- `request-manager.md` -- Publishes request events and consumes responses
- `agent-service.md` -- Processes request events and publishes agent responses
