---
name: kafka
description: "Strimzi Kafka cluster with KRaft mode for event-driven agent architectures on RHOAI"
summary: "Provides durable event-driven messaging for AI agent architectures on RHOAI via two approaches: Approach A (active) deploys Kafka via Strimzi/AMQ Streams in KRaft mode with KafkaNodePool dual-role nodes (controller+broker) backing a Knative Kafka Broker that routes CloudEvents between integration dispatcher, request manager, and agent service; Approach B (deprecated) used Strimzi as a Helm subchart (`createGlobalResources=false`) with separate broker/controller pools and Kafka Connect JDBC sink to stream interactions to PostgreSQL via kafka-python KafkaProducer with schema-enabled JSON, later removed for direct DB writes. Use Approach A when production workloads need guaranteed delivery and per-session ordering -- toggle `requestManagement.knative.eventing.enabled` to switch between real Kafka (production) and mock eventing service (dev/CI, constrained to 1 replica for partition-key ordering); Approach B is a cautionary reference demonstrating when Kafka adds unnecessary complexity over direct database writes for simple ETL pipelines. Bootstrap servers wire via ConfigMap to Knative Broker with `broker.class: Kafka`, default 6 partitions, P7D retention, retry:10 with exponential backoff (PT0.2S); `auto.create.topics.enable: false` delegates topic lifecycle to Knative; `BROKER_URL` env var points all services to the broker ingress; network policies restrict access to `kafka-broker-dispatcher` pods only. Must set both `partitionkey` (lowercase) and `partitionKey` (camelCase) plus the `ce-partitionkey` HTTP header on every CloudEvent or session ordering breaks; email Message-IDs require hashing via `_broker_safe_event_id()` to avoid broker failures from special characters; default storage type is `ephemeral` (data lost on restart) -- switch to `persistent-claim` for production; Approach B requires `STRIMZI_USE_FINALIZERS=false` to prevent uninstall hangs."
metadata:
  type: component
tags:
  tech_stack: [kafka, strimzi, knative, cloudevents, python, kafka-connect, kafka-python]
  ai_pattern: [agents, event-driven, data-pipeline]
  platform: [openshift, rhoai, kubernetes]
source_examples:
  - quickstart: "it-self-service-agent"
    repo: "https://github.com/rh-ai-quickstart/it-self-service-agent"
    notes: "Strimzi Kafka with KRaft and KafkaNodePool backing Knative Kafka Broker for event-driven agent orchestration"
    approach: "A"
  - quickstart: "product-recommender-system"
    repo: "https://github.com/rh-ai-quickstart/product-recommender-system"
    notes: "Strimzi Kafka with KRaft, Kafka Connect JDBC sink for streaming user interactions to PostgreSQL -- later removed in favor of direct database writes"
    approach: "B"
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

---

## Approach B: Kafka Connect JDBC Sink for Interaction Streaming -- Deprecated (from product-recommender-system)

### When to Use

Use this pattern when you need to stream user interaction events (views, cart additions, purchases, registrations) from a FastAPI backend into PostgreSQL via Kafka Connect, decoupling the application from direct database writes. This approach was ultimately removed from the product-recommender-system in favor of direct database writes (commit b17587c, PR #92), making it a reference for when Kafka adds unnecessary complexity.

### Differences from Approach A

- **Purpose:** ETL/event ingestion pipeline (user interactions to database) vs. agent orchestration (CloudEvents routing between microservices)
- **Integration method:** Strimzi Kafka as a Helm subchart dependency (`strimzi-kafka-operator` v0.46.0 from `strimzi.io/charts/`) vs. raw Kafka CR in the parent chart
- **Consumer:** Kafka Connect with JDBC sink connector (auto-writes to PostgreSQL) vs. Knative Kafka Broker with Triggers
- **Producer:** `kafka-python` library with `KafkaProducer` vs. HTTP CloudEvent sends to broker ingress
- **Node pools:** Separate broker and controller pools vs. dual-role (controller+broker) single pool
- **Outcome:** Removed in favor of direct DB writes -- demonstrates when Kafka is overengineered for the use case

### Key Patterns

#### Strimzi Kafka Subchart Dependency

Kafka was deployed as a Helm subchart dependency from the Strimzi charts repository, with `createGlobalResources=false` to avoid cluster-wide CRDs clashing.

```yaml
# helm/product-recommender-system/Chart.yaml (before removal)
dependencies:
  - name: strimzi-kafka-operator
    repository: https://strimzi.io/charts/
    version: 0.46.0
```

```bash
# helm/Makefile -- install with global resources disabled
helm upgrade --install product-recommender-system product-recommender-system \
  --set strimzi-kafka-operator.createGlobalResources=false --timeout 300m
```

#### KRaft Mode with Separate Node Pools

Kafka v4.0.0 deployed in KRaft mode with separate broker and controller node pools (unlike Approach A's dual-role pool). Each pool had 3 replicas with ephemeral JBOD storage.

```yaml
# helm/product-recommender-system/templates/kafka-config.yaml (before removal)
apiVersion: kafka.strimzi.io/v1beta2
kind: Kafka
metadata:
  name: {{ .Values.kafka.cluster.name }}
  annotations:
    strimzi.io/node-pools: enabled
    strimzi.io/kraft: enabled
spec:
  kafka:
    version: 4.0.0
    metadataVersion: 4.0-IV3
    listeners:
      - name: plain
        port: 9092
        type: internal
        tls: false
```

```yaml
# KafkaNodePool -- separate pools for broker and controller roles
# helm/product-recommender-system/values.yaml (before removal)
kafka:
  cluster:
    name: recommendation-cluster
  nodepools:
    - name: broker
      roles: ["broker"]
    - name: controller
      roles: ["controller"]
```

#### Kafka Connect JDBC Sink Pipeline

Kafka Connect with JDBC sink connector auto-created PostgreSQL tables from topic messages. Topics (`interactions`, `new-users`) mapped to database tables (`stream_interaction`, `new_users`) with schema-enabled JSON conversion.

```yaml
# helm/product-recommender-system/templates/kafka-config.yaml (before removal)
apiVersion: kafka.strimzi.io/v1beta2
kind: KafkaConnector
metadata:
  labels:
    strimzi.io/cluster: connect-cluster
  name: {{ .name }}
spec:
  class: io.aiven.connect.jdbc.JdbcSinkConnector
  config:
    value.converter: org.apache.kafka.connect.json.JsonConverter
    value.converter.schemas.enable: true
    insert.mode: insert
    auto.create: true
    auto.evolve: true
    table.name.format: {{ .tableNameFormat }}
```

#### KafkaProducer with Schema-Based Messages

The backend used `kafka-python` library with a singleton `KafkaService`. Messages included explicit JSON schemas alongside payloads to support the JDBC sink connector's schema-aware deserialization.

```python
# backend/src/services/kafka_service.py (before removal)
from kafka import KafkaProducer

class KafkaService:
    def _initialize(self):
        kafka_service = os.getenv(
            "KAFKA_SERVICE_ADDR",
            "recommendation-cluster-kafka-bootstrap.recommendation.svc.cluster.local:9092",
        )
        self.producer = KafkaProducer(
            bootstrap_servers=kafka_service,
            value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        )

    def send_interaction(self, user_id, item_id, interaction_type, ...):
        message = {"schema": schema, "payload": interaction}
        self.producer.send("interactions", message)
        self.producer.flush()
```

#### Replacement: Direct Database Writes

After removal, a `DatabaseService` singleton replaced `KafkaService`, writing interactions directly to the same `stream_interaction` table that Kafka Connect previously populated.

```python
# backend/src/services/database_service.py
class DatabaseService:
    """Service to handle direct database writes (replaces Kafka)"""

    async def log_interaction(self, db: AsyncSession, user_id, item_id, interaction_type, ...):
        interaction = StreamInteraction(
            user_id=str(user_id), item_id=item_id,
            timestamp=datetime.now(),
            interaction_type=interaction_type,
            interaction_id=f"{user_id}-{item_id}-{datetime.now(timezone.utc).timestamp()}",
        )
        db.add(interaction)
        await db.commit()
```

### Configuration

- **Environment variables:**
  - `KAFKA_SERVICE_ADDR` -- Bootstrap server address (default: `recommendation-cluster-kafka-bootstrap.recommendation.svc.cluster.local:9092`) -- removed in commit b17587c
- **Helm values (before removal):**
  - `kafka.cluster.name` -- Cluster name (default: `recommendation-cluster`)
  - `kafka.replicas` -- 3 replicas
  - `kafka.storage.type` -- `ephemeral`
  - `kafka.dbSecretName` -- Secret for JDBC connection (default: `pgvector`)
  - `kafka.topics` -- List of topics: `new-users`, `interactions`
  - `kafka.connectors` -- JDBC sink connector configs mapping topics to table names
  - `strimzi-kafka-operator.createGlobalResources` -- Set to `false` during install to avoid cluster-wide CRD conflicts
- **Residual config still in codebase:**
  - `strimzi-kafka-operator.extraEnvs[].STRIMZI_USE_FINALIZERS: "false"` -- in `helm/product-recommender-system/values.yaml`
  - `rbac-strimzi.yaml` -- wide RBAC Role/RoleBinding for strimzi-cluster-operator still present in templates

### Known Gotchas

- **Strimzi finalizers must be disabled:** Without setting `STRIMZI_USE_FINALIZERS=false`, uninstalling the Helm chart hangs because Strimzi finalizers block Kafka CR deletion. This was fixed in commit 8bdc427 ("Disable strimzi finalizers"). (Source: `helm/product-recommender-system/values.yaml`, lines 265-268)
- **Residual Strimzi artifacts after removal:** The `rbac-strimzi.yaml` template and `strimzi-kafka-operator` values block remain in the codebase even after Kafka was removed. The RBAC grants wildcard permissions (`apiGroups: ["*"], resources: ["*"], verbs: ["*"]`) to the `strimzi-cluster-operator` service account, which is overly permissive. (Source: `helm/product-recommender-system/templates/rbac-strimzi.yaml`)
- **JDBC sink connector requires schema-enabled JSON:** The `kafka-python` producer must include a `schema` field alongside `payload` in every message for the JDBC sink connector's `JsonConverter` with `schemas.enable: true` to deserialize correctly. Without the schema, connector writes fail silently. (Source: `backend/src/services/kafka_service.py`, `send_interaction` method)
- **Kafka Connect image build uses internal registry:** The `KafkaConnect` CR builds a custom image with the JDBC connector plugin and pushes to OpenShift's internal image registry (`image-registry.openshift-image-registry.svc:5000`), which requires the internal registry to be enabled and accessible. (Source: `helm/product-recommender-system/templates/kafka-config.yaml`, KafkaConnect spec)
- **Kafka dependency removed from pyproject.toml last:** The `kafka-python>=2.2.11` dependency remains in `backend/pyproject.toml` even after `kafka_service.py` was deleted. (Source: `backend/pyproject.toml`, line 14)

### Testing Notes

- The Makefile originally had a `delete-topics` target to clean up Kafka topics (`interactions`, `new-users`) during uninstall, removed in the same commit as Kafka
- After migration, interaction logging correctness can be verified by querying the `stream_interaction` table directly

---

## Choosing Between Approaches

| Criteria | Approach A (Knative Kafka Broker) | Approach B (Kafka Connect JDBC Sink) |
|----------|----------------------------------|--------------------------------------|
| Use case | Agent orchestration with CloudEvents routing | Event ingestion / ETL from app to database |
| Consumer | Knative Triggers with per-service subscriptions | JDBC sink connector auto-writing to PostgreSQL |
| Producer | HTTP CloudEvent POST to broker ingress | `kafka-python` KafkaProducer with schema+payload messages |
| Ordering | Partition key (session ID) for per-session FIFO | No explicit ordering guarantees |
| Dev/CI mode | Mock eventing service substitutes Kafka | No dev-mode substitute (full Kafka required) |
| Deployment | Raw Kafka CR in parent chart | Strimzi operator as Helm subchart dependency |
| Node pools | Dual-role (controller+broker) single pool | Separate broker and controller pools |
| Status | Active | Deprecated -- removed in favor of direct DB writes |
| When to prefer | Multi-service event routing with guaranteed delivery | Consider direct DB writes instead (lesson from this quickstart) |
