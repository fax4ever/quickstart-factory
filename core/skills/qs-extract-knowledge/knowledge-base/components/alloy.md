---
name: alloy
description: "Grafana Alloy log collector configured as a Deployment with inline River config for Ansible log ingestion into Loki"
summary: "Grafana Alloy (v1.11.3, Helm subchart v1.4.0) collects Ansible playbook logs from a shared PVC via a sidecar-written file path and forwards structured entries to Loki at http://loki:3100/loki/api/v1/push using an inline River configuration pipeline. Deploy as a single-replica Deployment (override controller.type from the upstream chart's DaemonSet default, set fullnameOverride: alloy) when collecting from a specific PVC path rather than node-level logs -- a sidecar (alm-aap-log-collector, POLL_INTERVAL=300s) polls a source API and writes logs to a 5Gi ReadWriteOnce PVC created via extraObjects, while an init container gates startup on upstream service health. The inline River config (alloy.alloy.configMap.content) implements a 16-stage pipeline: local.file_match discovers /var/log/ansible_logs/*/*.txt, stage.multiline aggregates PLAY/TASK/RECAP blocks (max_lines=2000), chained regex stages extract cluster_name/task_name/play_name/status with priority override ordering, and stage.label_keep restricts forwarded labels to filename/cluster_name/status for cardinality control. The upstream chart defaults to DaemonSet so controller.type: deployment must be explicitly set, status regex stages 8a-8d must maintain their order because failed/fatal overrides ok/changed and ignoring overrides everything, the backend init-job depends on Alloy readiness via oc rollout status (including its own init container for AAP Mock), and the custom Containerfile layering seed data must be built from project root."
metadata:
  type: component
tags:
  tech_stack: [grafana-alloy, loki, river-config]
  ai_pattern: [data-pipeline]
  platform: [openshift, kubernetes]
  data_layer: [loki]
source_examples:
  - quickstart: "ansible-log-analysis"
    repo: "https://github.com/rh-ai-quickstart/ansible-log-analysis"
    notes: "Alloy deployed as single-replica Deployment with inline River config for Ansible log file collection, multiline aggregation, and Loki forwarding"
    approach: "A"
---

# Alloy

## Overview

Grafana Alloy is an open-source log collection agent used in quickstart architectures to ingest log files and forward them to Loki for storage and querying. In the ansible-log-analysis quickstart, Alloy reads Ansible playbook log files from a shared PVC, applies a multi-stage processing pipeline (multiline aggregation, regex extraction, label promotion), and pushes structured log entries to Loki. It replaces Promtail as the preferred collection agent and is deployed via the upstream Grafana Alloy Helm chart (v1.4.0, appVersion v1.11.3).

## Tech Stack & Dependencies

- **Runtime:** Grafana Alloy v1.11.3 (Go-based agent)
- **Container image:** `docker.io/grafana/alloy:latest` (custom Containerfile layers sample logs on top)
- **Key dependencies:** Loki (write endpoint at `http://loki:3100/loki/api/v1/push`), shared PVC (`ansible-logs-pvc`, 5Gi ReadWriteOnce), AAP Mock service (init container waits for it)
- **Helm subchart:** Upstream `alloy` chart v1.4.0 bundled as `.tgz` in `deploy/helm/ansible-log-monitor/charts/`

## Key Patterns

### Deployment Instead of DaemonSet

The upstream Alloy chart defaults to DaemonSet mode (one pod per node for cluster-wide log collection). This quickstart overrides it to a single-replica Deployment because it collects from a specific PVC path rather than node-level log directories.

```yaml
# From values.yaml
alloy:
  fullnameOverride: alloy
  controller:
    type: deployment  # Changed from the default DaemonSet to Deployment (only need 1 pod for static file collection)
    replicas: 1
```

### Init Container for Dependency Ordering

The Alloy pod includes an init container that waits for the AAP Mock service to be healthy and have logs loaded before Alloy starts collecting. This prevents Alloy from starting with an empty log directory.

```yaml
# From values.yaml — alloy.controller.initContainers
- name: wait-for-aap-mock
  image: registry.access.redhat.com/ubi9/ubi-minimal:latest
  command:
    - sh
    - -c
    - |
      until curl -f -s http://alm-aap-mock:8080/healthz > /dev/null 2>&1; do
        echo "Waiting for AAP Mock service..."
        sleep 5
      done
      # Also waits for log count > 0 before proceeding
```

### Sidecar Log Collector Pattern

A sidecar container (`alm-aap-log-collector`) runs alongside Alloy in the same pod, polling the AAP Mock API and writing job logs to the shared PVC. Alloy then discovers and ingests these files.

```yaml
# From values.yaml — alloy.controller.extraContainers
- name: alm-aap-log-collector
  image: quay.io/rh-ai-quickstart/alm-aap-log-collector:latest
  env:
    - name: AAP_API_URL
      value: "http://alm-aap-mock:8080"
    - name: OUTPUT_DIR
      value: "/var/log/ansible_logs"
    - name: POLL_INTERVAL
      value: "300"  # seconds (5 minutes)
```

### Inline River Configuration for Log Processing

The Alloy configuration is embedded directly in `values.yaml` via `alloy.alloy.configMap.content`, using Grafana Alloy's River configuration language. The pipeline consists of 16 stages covering file discovery, multiline aggregation, regex extraction, label promotion, and Loki forwarding.

```river
// From values.yaml — alloy.alloy.configMap.content
local.file_match "ansible_logs" {
  path_targets = [{
    __address__ = "localhost",
    __path__    = "/var/log/ansible_logs/*/*.txt",
  }]
}

loki.source.file "ansible_logs" {
  targets    = local.file_match.ansible_logs.targets
  forward_to = [loki.process.ansible_pipeline.receiver]
}
```

### Multiline Log Aggregation

Ansible logs span multiple lines per entry (PLAY, TASK, RECAP blocks). The pipeline uses `stage.multiline` with a regex matching Ansible-specific line starters to aggregate them into single log entries.

```river
// From values.yaml — stage 1 of ansible_pipeline
stage.multiline {
  firstline     = "^(PLAY\\s+\\[|TASK\\s+\\[|RUNNING HANDLER\\s+\\[|PLAY\\s+RECAP\\s+\\*+|NO MORE HOSTS LEFT\\s+\\*+|Vault password)"
  max_wait_time = "3s"
  max_lines     = 2000
}
```

### Structured Metadata Extraction

The pipeline extracts `cluster_name` from the file path, `task_name`, `play_name`, `status` (ok/changed/failed/fatal/skipping/ignoring), and `log_type` (task/recap/play/other) using chained regex stages with override priority logic.

```river
// From values.yaml — status extraction with priority override
// 8b: Extract standard status
stage.regex {
  expression = "(?P<status>ok|changed|failed|fatal|skipping):\\s+\\[(?P<host>[^\\]]+)\\]"
}
// 8c: Override to ensure failed/fatal takes priority
stage.regex {
  expression = "(?P<status>failed|fatal):\\s+\\[(?P<host>[^\\]]+)\\]"
}
// 8d: Override if "...ignoring" appears at line end
stage.regex {
  expression = "\\.\\.\\.(?P<status>ignoring)\\s*$"
}
```

### PVC via extraObjects

The PVC for log storage is created through the Alloy chart's `extraObjects` mechanism rather than a separate Helm template, keeping the storage definition co-located with the Alloy values.

```yaml
# From values.yaml — alloy.extraObjects
extraObjects:
  - apiVersion: v1
    kind: PersistentVolumeClaim
    metadata:
      name: ansible-logs-pvc
    spec:
      accessModes:
        - ReadWriteOnce
      resources:
        requests:
          storage: 5Gi
```

## Configuration

- **Environment variables:** The Alloy container itself has no custom env vars; the sidecar log collector uses `AAP_API_URL`, `OUTPUT_DIR`, `POLL_INTERVAL`, `CLUSTER_NAME`, `LOG_LEVEL`
- **Config files:** River config is inline in `values.yaml` under `alloy.alloy.configMap.content` (no separate config file)
- **Helm values:** `alloy.fullnameOverride` (set to `alloy`), `alloy.controller.type` (`deployment`), `alloy.controller.replicas` (`1`), `alloy.rbac.create` (`true`)
- **Shared volume:** Both Alloy and the sidecar mount `ansible-logs-pvc` at `/var/log/ansible_logs`

## Known Gotchas

- **DaemonSet vs Deployment override required:** The upstream Alloy chart defaults to DaemonSet. For file-based collection from a PVC (not node logs), you must set `controller.type: deployment` -- the comment in values.yaml explicitly calls this out: "Changed from the default DaemonSet to Deployment (only need 1 pod for static file collection)"
- **Status regex ordering matters:** The pipeline runs four sequential regex stages (8a-8d) for status extraction with intentional override behavior -- `failed`/`fatal` overrides `ok`/`changed`, and `ignoring` overrides everything. The comment notes: "This runs after 8b to guarantee failed/fatal overrides other statuses even if they appear later in the log line"
- **Init container dependency chain:** The backend init-job has a `wait-for-alloy` init container that checks `oc rollout status deployment/alloy` -- Alloy must be fully ready (with its own init container for AAP Mock completed) before the backend initialization pipeline runs
- **Custom Containerfile layers sample data:** The `services/alloy/Containerfile` copies `data/logs/` into `/var/log/ansible_logs/` on top of the upstream `grafana/alloy:latest` image, providing seed data. Build must run from project root: `podman build -f services/alloy/Containerfile -t quay.io/rh-ai-quickstart/alm-alloy:latest ../../`
- **Label cardinality control:** Stage 16 uses `stage.label_keep` to restrict forwarded labels to only `filename`, `cluster_name`, and `status` -- preventing high-cardinality labels like `task_name_marker` from reaching Loki

## Testing Notes

- Verify Alloy deployment is running: `oc rollout status deployment/alloy`
- Confirm logs are being collected by checking Loki: `curl http://loki:3100/loki/api/v1/query?query={job="ansible_logs"}`
- Check that the sidecar log collector is writing files: inspect `/var/log/ansible_logs/` inside the Alloy pod
- The backend init-job depends on Alloy being ready -- if the init-job fails at `wait-for-alloy`, check the Alloy pod's init container logs for AAP Mock connectivity issues

## Related Patterns

- Loki (log storage backend that Alloy forwards to)
- Grafana (alerting layer that queries Loki for error patterns)
- AAP Mock (log source that Alloy's sidecar polls)
