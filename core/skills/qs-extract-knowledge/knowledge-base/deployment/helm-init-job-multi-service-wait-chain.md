---
name: helm-init-job-multi-service-wait-chain
description: Backend init Job with chained init containers waiting for 4 services, deployment blocked on job completion
summary: "Orchestrates ordered multi-service startup using a Kubernetes init Job with five sequential init containers (PostgreSQL via pg_isready, Phoenix/Alloy via oc rollout status, Loki via HTTP curl, fixed log-accumulation delay) before executing backend_init_pipeline.py, with downstream workloads blocking on Job completion via oc wait --for=condition=complete. Use when multiple upstream services must be confirmed ready before a one-shot initialization pipeline runs and multiple downstream Deployments (backend, annotation-interface) need fan-out blocking on that same Job -- single-approach pattern suited to complex dependency graphs where simple readiness probes are insufficient. Job uses restartPolicy: Never with backoffLimit: 3, initResources with 8Gi memory for HuggingFace downloads, quay.io/openshift/origin-cli:4.15 for oc commands requiring RBAC via role.yaml/rolebinding.yaml, service names from global.servicesNames, pgvector secret for DATABASE_URL, and postgresql.waitForReady toggle on the Deployment. Alloy wait hardcodes deployment/alloy (needs fullnameOverride: alloy) while Phoenix uses templated {{ .Release.Name }}-phoenix; duplicate wait-for-postgres containers use different sleep intervals (5s in Job vs 2s in Deployment); annotation-interface uses a single 600s timeout while backend polls with 10s loop timeouts -- inconsistent strategies for the same dependency."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, fastapi]
  ai_pattern: [agents, embeddings]
  platform: [openshift]
  data_layer: [pgvector]
source_examples:
  - quickstart: "ansible-log-analysis"
    repo: "https://github.com/rh-ai-quickstart/ansible-log-analysis"
    notes: "Init Job with 5 init containers, deployment blocks on job via oc wait, annotation-interface also waits"
    approach: "A"
---

# Init Job with Multi-Service Wait Chain

## Overview

This pattern uses a Kubernetes Job with multiple sequential init containers to ensure all upstream services are ready before running an initialization pipeline. The main backend Deployment then blocks startup until this Job completes, using an init container with `oc wait --for=condition=complete`. Other services (annotation-interface) also wait for the same Job, creating a fan-out dependency graph.

## Pattern Description

The backend chart defines two workloads: an init Job (`backend-init`) and a Deployment (`backend`). The init Job runs five init containers in sequence -- waiting for PostgreSQL (via `pg_isready`), Phoenix (via `oc rollout status`), Loki (via HTTP readiness probe), Alloy (via `oc rollout status`), and a fixed delay for log accumulation -- before running the `backend_init_pipeline.py` script. The Deployment's own init container uses `oc wait --for=condition=complete` to block until the Job finishes. The annotation-interface subchart similarly waits for the same Job.

## Implementation

### Init Job with Chained Init Containers

Five init containers execute sequentially, each using the appropriate tool to verify readiness:

```yaml
# deploy/helm/ansible-log-monitor/charts/backend/templates/init-job.yaml
spec:
  template:
    spec:
      restartPolicy: Never
      initContainers:
        - name: wait-for-postgres
          image: postgres:15-alpine
          command:
            - sh
            - -c
            - |
              until pg_isready -d "$DATABASE_URL"; do
                echo "Waiting for PostgreSQL to be ready..."
                sleep 5
              done
          env:
            - name: DATABASE_URL
              valueFrom:
                secretKeyRef:
                  name: pgvector
                  key: uri
        - name: wait-for-phoenix
          image: quay.io/openshift/origin-cli:4.15
          command:
            - sh
            - -c
            - |
              until oc rollout status deployment/{{ .Release.Name }}-phoenix -n {{ .Release.Namespace }} --timeout=10s; do
                echo "Still waiting..."
                sleep 3
              done
        - name: wait-for-loki
          image: registry.access.redhat.com/ubi9/ubi-minimal:latest
          command:
            - sh
            - -c
            - |
              until curl -f -s http://loki:3100/ready > /dev/null 2>&1; do
                sleep 5
              done
        - name: wait-for-alloy
          image: quay.io/openshift/origin-cli:4.15
          command:
            - sh
            - -c
            - |
              until oc rollout status deployment/alloy --timeout=10s; do
                sleep 5
              done
        - name: wait-for-log-accumulation
          image: registry.access.redhat.com/ubi9/ubi-minimal:latest
          command:
            - sh
            - -c
            - |
              echo "Waiting 10 seconds for logs to accumulate..."
              sleep 10
      containers:
        - name: init-pipeline
          image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
          command:
            - sh
            - -c
            - python backend_init_pipeline.py
  backoffLimit: 3
```

### Deployment Blocked on Job Completion

The backend Deployment uses an init container with `oc wait` to block until the Job completes:

```yaml
# deploy/helm/ansible-log-monitor/charts/backend/templates/deployment.yaml (excerpt)
initContainers:
  - name: wait-for-postgres
    image: postgres:15-alpine
    command:
      - sh
      - -c
      - |
        until pg_isready -d "$DATABASE_URL"; do
          echo "Waiting for PostgreSQL to be ready..."
          sleep 2
        done
  - name: wait-for-init-job
    image: quay.io/openshift/origin-cli:4.15
    command:
      - sh
      - -c
      - |
        echo "Waiting for init job to complete..."
        until oc wait --for=condition=complete job/{{ include "backend.fullname" . }}-init -n {{ .Release.Namespace }} --timeout=10s; do
          echo "Still waiting..."
          sleep 3
        done
```

### Annotation Interface Also Waits for Init Job

The annotation-interface subchart has its own init container that waits for the same backend init job:

```yaml
# deploy/helm/ansible-log-monitor/charts/annotation-interface/templates/deployment.yaml (excerpt)
initContainers:
  - name: wait-for-{{ .Values.global.servicesNames.backend }}-init
    image: quay.io/openshift/origin-cli:latest
    command:
      - sh
      - -c
      - |
        oc wait --for=condition=complete --timeout=600s job/{{ .Values.global.servicesNames.backend }}-init -n {{ .Release.Namespace }}
  - name: init-annotation-data
    image: "{{ .Values.image.repository }}:{{ .Values.image.tag }}"
    command:
      - sh
      - -c
      - |
        if [ -f /mnt/data/feedback/annotation.json ]; then
          echo "annotation.json already exists on persistent volume, skipping copy."
        else
          mkdir -p /mnt/data/feedback
          cp /app/data/feedback/annotation.json /mnt/data/feedback/annotation.json
        fi
```

## Configuration

- **Key settings:** Init job `backoffLimit: 3`; init resources set separately from main container resources (`initResources` in values.yaml with 8Gi memory limit for HuggingFace model downloads); `postgresql.waitForReady: true` toggles the postgres init container in the deployment
- **Defaults:** The init job always runs (no toggle); annotation-interface always waits for backend init (no toggle)
- **Dependencies:** Requires `oc` CLI in the wait containers (`quay.io/openshift/origin-cli:4.15`); PostgreSQL secret `pgvector` with key `uri`; services named via `global.servicesNames` values

## Gotchas

- The init job uses `quay.io/openshift/origin-cli:4.15` for `oc rollout status` and `oc wait` commands, meaning the init containers need RBAC permissions to query deployments and jobs in the namespace (see `charts/backend/templates/role.yaml` and `rolebinding.yaml`)
- The `wait-for-alloy` container references `deployment/alloy` without the release name prefix (hardcoded), while `wait-for-phoenix` uses `deployment/{{ .Release.Name }}-phoenix` (templated) -- this inconsistency means the Alloy chart must use `fullnameOverride: alloy`
- The init Job and the Deployment both have a `wait-for-postgres` init container, but with different sleep intervals (5s in the Job, 2s in the Deployment)
- The annotation-interface uses a 600s timeout for the init job wait while the backend deployment polls with 10s timeouts in a loop -- different wait strategies for the same dependency

## Related Patterns

- `helm-alloy-sidecar-pvc-log-collector.md` -- Alloy deployment that the init job waits for
- `helm-umbrella-mixed-remote-local-committed-deps.md` -- umbrella chart containing the backend subchart
