---
name: kafka-kraft-single-node-initcontainer-config-copy
description: KRaft-mode Kafka single-node deployment with initContainer copying config dir to writable volume for OpenShift compatibility
summary: "Deploys single-node Kafka in KRaft combined mode (broker+controller, no ZooKeeper) on OpenShift using Confluent cp-kafka:8.2.1 as a plain Deployment, solving the read-only filesystem problem where the Confluent distribution writes runtime state to /etc/kafka at startup but OpenShift restricted SCC blocks writes. Use for sandbox/dev environments where persistence and HA are unnecessary — prefer Strimzi operator or AMQ Streams for production; single approach uses an initContainer config copy with emptyDir volumes for both config and data. InitContainer runs `cp -r /etc/kafka/* /kafka-config/` to writable emptyDir; KRaft uses hardcoded base64 CLUSTER_ID, controller quorum voters at `1@localhost:9093`, PLAINTEXT listeners on 9092/9093, `KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: \"1\"`, auto topic creation, advertised listener via Service DNS `kafka:9092`, and 512Mi-1Gi memory limits. `KAFKA_PORT` must be set to empty string to prevent the Confluent image from binding a conflicting default listener; all messages and topic metadata are lost on pod restart (emptyDir is ephemeral); the `CLUSTER_ID` must be a valid base64 string shared by all cluster nodes."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [kafka]
  ai_pattern: [data-pipeline]
  platform: [openshift]
source_examples:
  - quickstart: "smart-telemetry-pipeline"
    repo: "https://github.com/rh-ai-quickstart/smart-telemetry-pipeline"
    notes: "Confluent cp-kafka 8.2.1 in KRaft combined mode (broker+controller), initContainer copying /etc/kafka to writable emptyDir, ephemeral data volume, auto topic creation enabled"
    approach: "A"
---

# Kafka KRaft Single-Node with InitContainer Config Copy

## Overview

A deployment pattern for running a single-node Apache Kafka instance in KRaft mode (no ZooKeeper) on OpenShift, using the Confluent cp-kafka image. An initContainer copies the read-only `/etc/kafka` configuration directory to a writable emptyDir volume, working around the fact that Kafka writes to its config directory at startup but the container's filesystem may be read-only under OpenShift's restricted SCC.

## Pattern Description

Instead of using the Strimzi operator or AMQ Streams, this pattern deploys Kafka as a simple Deployment with the Confluent image in KRaft combined mode (both broker and controller roles in a single process). The node handles its own controller quorum via localhost. An initContainer copies the default Kafka configuration from the image to a writable volume, and data is stored in an emptyDir (ephemeral). This is designed for sandbox/development use where persistence and high availability are not required.

## Implementation

### InitContainer for Config Directory

The initContainer copies Kafka's config directory to a writable volume:

```yaml
# deploy/resources/otel-infra/kafka/kafka-sandbox.yaml
initContainers:
  - name: init-config
    image: confluentinc/cp-kafka:8.2.1
    command: ['sh', '-c', 'cp -r /etc/kafka/* /kafka-config/']
    volumeMounts:
      - name: kafka-config
        mountPath: /kafka-config
```

### KRaft Combined Mode Configuration

The Kafka container runs in combined broker+controller mode via environment variables:

```yaml
# deploy/resources/otel-infra/kafka/kafka-sandbox.yaml
env:
  - name: CLUSTER_ID
    value: "MkU3OEVBNTcwNTJENDM2Qk"
  - name: KAFKA_NODE_ID
    value: "1"
  - name: KAFKA_PROCESS_ROLES
    value: "broker,controller"
  - name: KAFKA_LISTENERS
    value: "PLAINTEXT://0.0.0.0:9092,CONTROLLER://0.0.0.0:9093"
  - name: KAFKA_ADVERTISED_LISTENERS
    value: "PLAINTEXT://kafka:9092"
  - name: KAFKA_CONTROLLER_QUORUM_VOTERS
    value: "1@localhost:9093"
  - name: KAFKA_CONTROLLER_LISTENER_NAMES
    value: "CONTROLLER"
  - name: KAFKA_AUTO_CREATE_TOPICS_ENABLE
    value: "true"
  - name: KAFKA_LOG_DIRS
    value: "/tmp/kraft-combined-logs"
```

### Ephemeral Volumes

Both config and data use emptyDir volumes (no persistence):

```yaml
# deploy/resources/otel-infra/kafka/kafka-sandbox.yaml
volumes:
  - name: kafka-config
    emptyDir: {}
  - name: data
    emptyDir: {}
```

### Resource Limits

```yaml
resources:
  requests:
    memory: 512Mi
    cpu: 250m
  limits:
    memory: 1Gi
```

## Configuration

- **Key settings:** `CLUSTER_ID` is a fixed base64 string; `KAFKA_PORT` is set to empty string to prevent the Confluent image from starting an extra listener; `KAFKA_OFFSETS_TOPIC_REPLICATION_FACTOR: "1"` for single-node operation
- **Defaults:** PLAINTEXT listeners (no TLS); auto topic creation enabled; advertised listener uses the Service DNS name (`kafka:9092`); data in `/tmp/kraft-combined-logs`
- **Dependencies:** A Kubernetes Service named `kafka` exposing port 9092 must exist (included in the same manifest file)

## Gotchas

- The `KAFKA_PORT: ""` (empty string) environment variable is set to prevent the Confluent cp-kafka image from opening an additional listener on the default port -- without this, the image may try to bind a conflicting port
- Data is entirely ephemeral -- pod restarts lose all messages and topic metadata; this is intentional for sandbox/demo use
- The `CLUSTER_ID` is hardcoded (`MkU3OEVBNTcwNTJENDM2Qk`) -- in KRaft mode, the cluster ID must be a valid base64 string and all nodes in a cluster must share the same ID
- The initContainer config copy pattern (`cp -r /etc/kafka/* /kafka-config/`) is necessary because Kafka (specifically the `confluent-platform` distribution) writes runtime state into `/etc/kafka` at startup, and OpenShift's restricted SCC prevents writing to the image's filesystem

## Related Patterns

- `helm-otel-collector-kafka-exporter-filter-healthcheck.md` -- the OTel Collector that exports telemetry to this Kafka instance
- `shell-script-phased-infra-helm-tekton-deploy-chain.md` -- the orchestrator that deploys this as Step 2
