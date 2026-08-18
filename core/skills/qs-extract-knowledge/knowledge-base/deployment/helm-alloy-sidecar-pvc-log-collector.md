---
name: helm-alloy-sidecar-pvc-log-collector
description: Alloy as Deployment with aap-log-collector sidecar sharing PVC, init container waiting for upstream, River pipeline
summary: "Deploys Grafana Alloy (committed alloy-1.4.0.tgz) as a single-replica Deployment instead of DaemonSet with an aap-log-collector sidecar sharing a ReadWriteOnce PVC created via extraObjects, where the sidecar polls an external API (POLL_INTERVAL default 300s) and writes Ansible job logs to /var/log/ansible_logs for Alloy to ingest into Loki. Use when collecting logs from a REST API into Loki via file-based ingestion with startup gating -- the init container uses curl to verify both upstream service health and data availability (count > 0) before the collector and Alloy start. Critical config: controller.type set to deployment with replicas 1, PVC 5Gi via alloy.extraObjects, River pipeline with 16 stages including multiline grouping (firstline regex), four sequential status-extraction regex stages where failed/fatal overrides ok/changed and ignoring overrides all, plus structured metadata promotion before loki.write to http://loki:3100. Gotchas: River regex embedded in YAML requires quadruple backslashes for proper escaping; ReadWriteOnce access mode forces sidecar and Alloy into the same pod; init container must verify data count > 0 not just health to avoid starting collection with empty logs."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, alloy, grafana]
  ai_pattern: []
  platform: [openshift]
source_examples:
  - quickstart: "ansible-log-analysis"
    repo: "https://github.com/rh-ai-quickstart/ansible-log-analysis"
    notes: "Alloy Deployment with sidecar writing to shared PVC, init container, and inline River config for Ansible log parsing"
    approach: "A"
---

# Alloy Deployment with Sidecar Log Collector and Shared PVC

## Overview

This pattern deploys Grafana Alloy as a Kubernetes Deployment (not the default DaemonSet) with a sidecar container that collects logs from an external API and writes them to a shared PersistentVolumeClaim. Alloy reads from the same PVC to ingest logs into Loki. An init container gates startup until the upstream log source is ready and has data loaded.

## Pattern Description

The Alloy Helm chart (committed as `alloy-1.4.0.tgz`) is configured via the parent chart's `values.yaml`. The controller type is overridden from DaemonSet to Deployment since only one pod is needed for static file collection. The pod contains three containers: an init container that waits for the aap-mock service to be healthy and have logs loaded, the aap-log-collector sidecar that polls the aap-mock API and writes job logs to a shared PVC, and the main Alloy container that reads from the same PVC path and pushes to Loki. A PVC is created via Alloy's `extraObjects`.

## Implementation

### Alloy Controller Override to Deployment

The Alloy chart defaults to DaemonSet, overridden here because only one instance is needed:

```yaml
# deploy/helm/ansible-log-monitor/values.yaml (alloy section)
alloy:
  fullnameOverride: alloy
  controller:
    type: deployment  # Changed from the default DaemonSet
    replicas: 1
```

### Init Container Waiting for Upstream Data

The init container uses curl to wait for both the aap-mock healthcheck and for logs to be loaded (verifying count > 0):

```yaml
# deploy/helm/ansible-log-monitor/values.yaml (alloy.controller.initContainers)
initContainers:
  - name: wait-for-aap-mock
    image: registry.access.redhat.com/ubi9/ubi-minimal:latest
    command:
      - sh
      - -c
      - |
        echo "Waiting for AAP Mock to be ready and have logs loaded..."
        until curl -f -s http://alm-aap-mock:8080/healthz > /dev/null 2>&1; do
          echo "Waiting for AAP Mock service..."
          sleep 5
        done
        echo "AAP Mock is healthy, waiting for logs to be loaded..."
        until [ $(curl -f -s http://alm-aap-mock:8080/api/v2/jobs/ | grep -o '"count":[0-9]*' | cut -d':' -f2) -gt 0 ] 2>/dev/null; do
          echo "Waiting for sample logs to load..."
          sleep 5
        done
        echo "Sample logs loaded! Waiting 10 seconds for logs to accumulate..."
        sleep 10
```

### Sidecar Container with Shared PVC

The aap-log-collector sidecar writes to the same PVC that Alloy reads from:

```yaml
# deploy/helm/ansible-log-monitor/values.yaml (alloy.controller section)
volumes:
  extra:
    - name: ansible-logs
      persistentVolumeClaim:
        claimName: ansible-logs-pvc

extraContainers:
  - name: alm-aap-log-collector
    image: quay.io/rh-ai-quickstart/alm-aap-log-collector:latest
    env:
      - name: AAP_API_URL
        value: "http://alm-aap-mock:8080"
      - name: OUTPUT_DIR
        value: "/var/log/ansible_logs"
      - name: POLL_INTERVAL
        value: "300"  # seconds (5 minutes)
    volumeMounts:
      - name: ansible-logs
        mountPath: /var/log/ansible_logs
    resources:
      limits:
        cpu: 200m
        memory: 256Mi
```

### PVC Created via extraObjects

The PVC for shared log storage is created through Alloy's `extraObjects`:

```yaml
# deploy/helm/ansible-log-monitor/values.yaml (alloy.extraObjects)
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

### Alloy River Config for Ansible Log Processing

The Alloy configMap contains a River language pipeline with 16 stages for parsing multiline Ansible logs, extracting status with priority override logic, and promoting fields to structured metadata:

```river
# deploy/helm/ansible-log-monitor/values.yaml (alloy.alloy.configMap.content excerpt)
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

loki.process "ansible_pipeline" {
  forward_to = [loki.write.loki.receiver]

  stage.multiline {
    firstline     = "^(PLAY\\s+\\[|TASK\\s+\\[|RUNNING HANDLER\\s+\\[|PLAY\\s+RECAP\\s+\\*+)"
    max_wait_time = "3s"
    max_lines     = 2000
  }
  // ... 14 more stages for status extraction, label promotion, structured metadata
}

loki.write "loki" {
  endpoint {
    url = "http://loki:3100/loki/api/v1/push"
  }
}
```

## Configuration

- **Key settings:** `POLL_INTERVAL` (sidecar polling frequency, default 300s); PVC size 5Gi; Alloy controller type `deployment` with 1 replica
- **Defaults:** Sidecar writes to `/var/log/ansible_logs`; Alloy reads via glob `/*/*.txt`; expected path convention is `/<cluster_name>/<job_name>.txt`
- **Dependencies:** Requires aap-mock service at `http://alm-aap-mock:8080`; Loki at `http://loki:3100`; PVC storage class must support ReadWriteOnce

## Gotchas

- The Alloy River config uses quadruple backslashes (`\\s+\\[`) because the config is embedded in YAML values which requires escaping the backslashes (see `values.yaml` lines 551-553)
- The status extraction pipeline runs four sequential regex stages (8a-8d) where later stages intentionally override earlier matches -- `failed`/`fatal` overrides `ok`/`changed`, and `ignoring` overrides everything (see `values.yaml` lines 592-610)
- The PVC uses `ReadWriteOnce` which means the sidecar and Alloy must be in the same pod (they are, by design as sidecar and main container)
- The init container checks not just healthiness but also verifies `count > 0` from the aap-mock API to ensure sample logs are actually loaded before starting log collection

## Related Patterns

- `helm-inline-grafana-alerting-loki-webhook.md` -- Grafana alerting rules that consume the Loki data populated by this Alloy pipeline
- `helm-umbrella-mixed-remote-local-committed-deps.md` -- umbrella chart containing the committed alloy tgz
