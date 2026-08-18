---
name: kafka
description: "Kafka messaging for event-driven agent architectures and telemetry pipelines on RHOAI"
summary: "Provides durable event-driven messaging for AI agent orchestration, ETL pipelines, and telemetry buffering on RHOAI across three approaches: Approach A (Strimzi KRaft + Knative Kafka Broker) for multi-service CloudEvents routing with per-session partition-key FIFO ordering and mock eventing for dev/CI, Approach B (Strimzi subchart + Kafka Connect JDBC sink, deprecated) replaced by direct DatabaseService writes, and Approach C (vanilla Confluent cp-kafka:8.2.1 Deployment) for operator-free OTel-to-Camel telemetry buffering. Choose A for production multi-service agent orchestration needing guaranteed delivery and Knative Trigger subscriptions with ordered delivery annotation; choose C for sandbox telemetry pipelines without Strimzi/AMQ Streams operator access; avoid B and use direct DB writes instead -- Kafka Connect added unnecessary complexity for simple interaction logging. Approach A gates deployment via `requestManagement.knative.eventing.enabled` (false=mock mode) with `auto.create.topics.enable: false` (Knative manages topics) and defaults to ephemeral storage (switch to `persistent-claim` for production); Approach C sets `auto.create.topics.enable: true` for OTel Collector auto-topic creation and uses emptyDir-only volumes; Strimzi subchart installs require `createGlobalResources=false` to avoid CRD conflicts. Dual `partitionkey`/`partitionKey` CloudEvent attributes plus `ce-partitionkey` header are all required for Knative broker compatibility or session ordering breaks; email Message-IDs must be hashed via `_broker_safe_event_id()`; Strimzi finalizers must be disabled (`STRIMZI_USE_FINALIZERS=false`) to prevent Helm uninstall hangs; Confluent image requires an init container for writable `/etc/kafka` plus `KAFKA_PORT=\"\"` to avoid listener port conflicts; and JDBC sink connector requires schema+payload JSON format or writes fail silently."
metadata:
  type: component
tags:
  tech_stack: [kafka, strimzi, knative, cloudevents, python, kafka-connect, kafka-python, confluent-kafka, opentelemetry, camel]
  ai_pattern: [agents, event-driven, data-pipeline, observability]
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
  - quickstart: "smart-telemetry-pipeline"
    repo: "https://github.com/rh-ai-quickstart/smart-telemetry-pipeline"
    notes: "Vanilla Confluent Kafka as plain Kubernetes Deployment for OpenTelemetry-to-Camel telemetry buffering -- no operators, no Strimzi"
    approach: "C"
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

## Approach C: Vanilla Confluent Kafka Deployment for Telemetry Buffering (from smart-telemetry-pipeline)

### When to Use

Use this pattern for sandbox or lightweight environments where Kafka serves as a simple telemetry buffer between an OpenTelemetry Collector and downstream consumers (e.g., Apache Camel routes). No operator (Strimzi/AMQ Streams) is available or warranted -- Kafka is deployed as a plain Kubernetes Deployment using the Confluent community image with KRaft mode.

### Differences from Approach A

- **Operator:** No Strimzi operator -- plain Kubernetes Deployment + Service resources applied via `oc apply`
- **Image:** `confluentinc/cp-kafka:8.2.1` (Confluent community) vs. Strimzi-managed images
- **Topic management:** `auto.create.topics.enable: true` (OTel Collector creates topics on first export) vs. Approach A's `false` (Knative manages topics)
- **Consumer:** Apache Camel Kafka component consuming OTLP JSON vs. Knative Triggers with CloudEvents
- **Producer:** OpenTelemetry Collector Kafka exporter vs. HTTP CloudEvent POST to broker ingress
- **Storage:** emptyDir volumes only (no PVC support) -- data lost on pod restart by design (telemetry is transient)
- **Security:** PLAINTEXT only, no TLS -- suitable for sandbox environments only
- **Deployment method:** Raw YAML via `oc apply -f` in a shell script vs. Helm-templated Kafka CR

### Key Patterns

#### KRaft Single-Node Combined Mode

Kafka runs as a single-node cluster in KRaft mode with combined broker+controller roles. An init container copies the base Kafka config before the main container starts.

```yaml
# deploy/resources/otel-infra/kafka/kafka-sandbox.yaml
spec:
  initContainers:
    - name: init-config
      image: confluentinc/cp-kafka:8.2.1
      command: ['sh', '-c', 'cp -r /etc/kafka/* /kafka-config/']
      volumeMounts:
        - name: kafka-config
          mountPath: /kafka-config
  containers:
    - name: kafka
      image: confluentinc/cp-kafka:8.2.1
      env:
        - name: KAFKA_PROCESS_ROLES
          value: "broker,controller"
        - name: KAFKA_NODE_ID
          value: "1"
        - name: KAFKA_CONTROLLER_QUORUM_VOTERS
          value: "1@localhost:9093"
```

#### Listener Configuration for In-Cluster Access

Two listeners separate client traffic (port 9092) from controller traffic (port 9093). The advertised listener uses the Kubernetes Service DNS name.

```yaml
# deploy/resources/otel-infra/kafka/kafka-sandbox.yaml
env:
  - name: KAFKA_LISTENERS
    value: "PLAINTEXT://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093"
  - name: KAFKA_ADVERTISED_LISTENERS
    value: "PLAINTEXT://kafka:9092"
  - name: KAFKA_CONTROLLER_LISTENER_NAMES
    value: "CONTROLLER"
  - name: KAFKA_INTER_BROKER_LISTENER_NAME
    value: "PLAINTEXT"
```

#### OTel Collector Kafka Exporter

The OpenTelemetry Collector exports both logs and traces to Kafka using the `kafka` exporter with `otlp_json` encoding. Topics are auto-created (`otlp_logs`, `otlp_spans`).

```yaml
# deploy/resources/otel-infra/otel-collector/values-sandbox.yaml
exporters:
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
      exporters: [debug, kafka]
    traces:
      exporters: [debug, kafka]
```

#### Camel Kafka Consumer Routes

Apache Camel routes consume from Kafka topics using the Camel Kafka component. Broker address is resolved via the `KAFKA_BROKERS` environment variable from a ConfigMap.

```yaml
# src/correlator/traces-mapper.camel.yaml
- route:
    id: trace-consumer
    from:
      uri: kafka:{{camel.kafka.topic.spans}}
      parameters:
        autoOffsetReset: earliest
        groupId: correlator
```

```properties
# chart/properties/correlator/application-prod-quarkus.properties
camel.component.kafka.brokers=${KAFKA_BROKERS:kafka:9092}
camel.component.kafka.security-protocol=PLAINTEXT
camel.kafka.topic.logs=otlp_logs
camel.kafka.topic.spans=otlp_spans
```

#### Bootstrap Server Wiring via ConfigMap

The Kafka broker address is shared across components via a dedicated ConfigMap, referenced by Camel consumers.

```yaml
# deploy/resources/configmaps/otel-infra-endpoints.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: otel-infra-endpoints
data:
  KAFKA_BROKERS: kafka:9092
```

### Configuration

- **Environment variables:**
  - `KAFKA_BROKERS` -- Kafka bootstrap server address, injected from `otel-infra-endpoints` ConfigMap (default: `kafka:9092`)
  - `CLUSTER_ID` -- Hardcoded KRaft cluster ID (`MkU3OEVBNTcwNTJENDM2Qk`)
  - `KAFKA_PORT` -- Set to empty string to avoid Confluent image port conflict
- **Resource requests/limits:**
  - Requests: 250m CPU, 512Mi memory
  - Limits: 1Gi memory
- **Kafka broker config (via env vars):**
  - `KAFKA_AUTO_CREATE_TOPICS_ENABLE: true` -- OTel Collector and Camel routes rely on auto-created topics
  - `KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: 1` -- Single-node cluster
  - `KAFKA_LOG_DIRS: /tmp/kraft-combined-logs` -- Uses emptyDir volume

### Known Gotchas

- **Init container required for Confluent image:** The `confluentinc/cp-kafka` image requires its `/etc/kafka` config directory to be writable at startup. An init container copies the base config to an emptyDir volume before the main container starts; without it, Kafka fails to boot with a read-only filesystem error. (Source: `deploy/resources/otel-infra/kafka/kafka-sandbox.yaml`, initContainers section)
- **KAFKA_PORT must be set to empty string:** The Confluent image sets a default `KAFKA_PORT` that conflicts with the listener configuration. Setting it to `""` prevents the image's entrypoint script from overriding the explicit listener ports. (Source: `deploy/resources/otel-infra/kafka/kafka-sandbox.yaml`, env `KAFKA_PORT: ""`)
- **Ephemeral storage only -- data lost on restart:** Both the Kafka config and log data use emptyDir volumes. Pod restarts lose all messages. This is acceptable for transient telemetry data but not for durable messaging. (Source: `deploy/resources/otel-infra/kafka/kafka-sandbox.yaml`, volumes section)
- **Hardcoded CLUSTER_ID:** The KRaft cluster ID is hardcoded in the YAML. Each new deployment reusing the same ID is fine for single-node ephemeral setups, but would conflict if multiple Kafka clusters are deployed in the same namespace. (Source: `deploy/resources/otel-infra/kafka/kafka-sandbox.yaml`, env `CLUSTER_ID`)

### Testing Notes

- Verify Kafka is ready: `oc wait deployment/kafka --for=condition=Available --timeout=180s` (used in `create.sh`)
- Check pod health: `oc get pods -l app=kafka`
- Verify OTel Collector can export: check debug exporter logs for successful sends alongside Kafka exporter
- Verify Camel consumption: check correlator pod logs for `Received trace from Kafka` / `Received log from Kafka` messages

---

## Choosing Between Approaches

| Criteria | Approach A (Knative Kafka Broker) | Approach B (Kafka Connect JDBC Sink) | Approach C (Vanilla Confluent Deployment) |
|----------|----------------------------------|--------------------------------------|-------------------------------------------|
| Use case | Agent orchestration with CloudEvents routing | Event ingestion / ETL from app to database | Telemetry buffering between OTel Collector and Camel |
| Operator | Strimzi / AMQ Streams | Strimzi as Helm subchart | None -- plain Kubernetes Deployment |
| Consumer | Knative Triggers with per-service subscriptions | JDBC sink connector auto-writing to PostgreSQL | Apache Camel Kafka component |
| Producer | HTTP CloudEvent POST to broker ingress | `kafka-python` KafkaProducer with schema+payload messages | OTel Collector Kafka exporter (otlp_json) |
| Ordering | Partition key (session ID) for per-session FIFO | No explicit ordering guarantees | Default partition assignment (no explicit keys) |
| Dev/CI mode | Mock eventing service substitutes Kafka | No dev-mode substitute (full Kafka required) | Sandbox-only -- no separate dev mode needed |
| Deployment | Raw Kafka CR in parent chart | Strimzi operator as Helm subchart dependency | Raw YAML via `oc apply -f` in shell script |
| Storage | Ephemeral or persistent-claim | Ephemeral JBOD | emptyDir only (ephemeral by design) |
| Security | Internal PLAINTEXT or TLS | Internal PLAINTEXT | PLAINTEXT only |
| Status | Active | Deprecated -- removed in favor of direct DB writes | Active (sandbox/demo scope) |
| When to prefer | Multi-service event routing with guaranteed delivery | Consider direct DB writes instead (lesson from this quickstart) | Lightweight telemetry pipeline in sandbox without operator access |
