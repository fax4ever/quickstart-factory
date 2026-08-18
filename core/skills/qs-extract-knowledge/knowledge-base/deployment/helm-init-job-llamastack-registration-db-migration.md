---
name: helm-init-job-llamastack-registration-db-migration
description: Two parallel init Jobs (LlamaStack asset registration and Alembic DB migration) with curl-based readiness wait
summary: "Runs two parallel Kubernetes Jobs during Helm install for LlamaStack agent deployments: an init Job that curl-polls LlamaStack readiness then executes register_assets to register KB assets (with optional ConfigMap injection via knowledgeBases.configMaps mounting to EXTRA_KB_PATH=/mnt/knowledge-bases), and an Alembic DB migration Job against pgvector gated by requestManagement.enabled with credentials from the pgvector secret. Use when deploying an agent service requiring both LlamaStack asset registration and database schema migrations at install time — both Jobs reuse the agent-service application image (not utility images) with OpenShift-compatible securityContext (runAsNonRoot, drop ALL capabilities, RuntimeDefault seccomp). The Makefile helm_install_common function must run kubectl delete job -l app.kubernetes.io/instance=<release> before each helm upgrade --install because Kubernetes Jobs are immutable; init Job uses backoffLimit: 6 with ttlSecondsAfterFinished: 86400, migration Job uses backoffLimit: 3 with activeDeadlineSeconds: 300 running shared-models/scripts/migrate.py. Dual curl commands (with and without --fail) handle LlamaStack endpoint version differences where non-200 responses still indicate readiness; the DB migration Job is explicitly not a Helm hook (uses Makefile cleanup instead) to avoid hook execution ordering issues; database.expectedMigrationVersion can override the Alembic version check."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, fastapi]
  ai_pattern: [agents, model-serving]
  platform: [openshift, kubernetes]
  data_layer: [pgvector]
source_examples:
  - quickstart: "it-self-service-agent"
    repo: "https://github.com/rh-ai-quickstart/it-self-service-agent"
    notes: "Init Job waits for LlamaStack via curl then registers KB assets; DB migration Job runs Alembic against pgvector"
    approach: "A"
---

# Init Job with LlamaStack Registration and DB Migration

## Overview

This pattern uses two Kubernetes Jobs that run during Helm install: an init Job that waits for LlamaStack readiness via curl probing then registers knowledge base assets, and a DB migration Job that runs Alembic migrations against pgvector. Both Jobs use the application's own container image (agent-service) rather than utility images, keeping initialization logic in the application codebase.

## Pattern Description

The init Job uses a bash script in its container command to poll the LlamaStack endpoint with `curl`, then runs a Python registration script (`register_assets`). The DB migration Job runs `shared-models/scripts/migrate.py` using database credentials from the pgvector secret. Both Jobs are conditionally deployed and cleaned up by the Makefile before each `helm upgrade --install` to avoid conflicts with previous Job runs.

## Implementation

### Init Job with LlamaStack Wait

```yaml
# helm/templates/init-job.yaml (excerpt)
spec:
  backoffLimit: 6
  ttlSecondsAfterFinished: 86400
  template:
    spec:
      restartPolicy: OnFailure
      securityContext:
        runAsNonRoot: true
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: init-and-complete
          image: "{{ .Values.image.registry }}/{{ .Values.image.agentService }}:{{ .Values.image.tag }}"
          securityContext:
            allowPrivilegeEscalation: false
            capabilities:
              drop:
              - ALL
          command:
            - /bin/bash
            - -c
            - |
              set -e
              echo "Waiting for LlamaStack at $LLAMA_STACK_URL..."
              until curl -ks "$LLAMA_STACK_URL/" --max-time 5 --silent --fail || \
                    curl -ks "$LLAMA_STACK_URL" --max-time 5 --silent; do
                echo "Still waiting for LlamaStack..."
                sleep 10
              done
              echo "LlamaStack is ready"
              cd /app/agent-service
              python3 -m agent_service.scripts.register_assets
```

### ConfigMap-Based Knowledge Base Injection

The init Job optionally mounts extra knowledge bases from ConfigMaps:

```yaml
# helm/templates/init-job.yaml (excerpt)
          {{- if and (hasKey .Values "knowledgeBases") .Values.knowledgeBases.configMaps }}
          env:
            - name: EXTRA_KB_PATH
              value: /mnt/knowledge-bases
          volumeMounts:
            {{- range .Values.knowledgeBases.configMaps }}
            - name: kb-cm-{{ .kbName | default .name | lower }}
              mountPath: /mnt/knowledge-bases/{{ .kbName | default .name }}
              readOnly: true
            {{- end }}
          {{- end }}
```

### DB Migration Job

```yaml
# helm/templates/db-migration-job.yaml (excerpt)
{{- if .Values.requestManagement.enabled }}
spec:
  backoffLimit: 3
  activeDeadlineSeconds: 300
  template:
    spec:
      restartPolicy: OnFailure
      containers:
      - name: db-migration
        image: "{{ .Values.image.registry }}/{{ .Values.image.agentService }}:{{ .Values.image.tag }}"
        command: ["python3", "shared-models/scripts/migrate.py"]
        env:
        - name: POSTGRES_HOST
          valueFrom:
            secretKeyRef:
              name: pgvector
              key: host
{{- end }}
```

### Makefile Job Cleanup

The `helm_install_common` function cleans up old Jobs before each install:

```makefile
# Makefile (excerpt)
@kubectl delete job -l app.kubernetes.io/instance=$(MAIN_CHART_NAME) \
    -n $(NAMESPACE) --ignore-not-found || true
```

## Configuration

- **Key settings:** `knowledgeBases.configMaps` allows injecting additional knowledge bases from ConfigMaps; `requestManagement.enabled` gates the DB migration Job; `database.expectedMigrationVersion` can override the Alembic version check
- **Defaults:** Init Job has `backoffLimit: 6` and `ttlSecondsAfterFinished: 86400` (24h for debugging); DB migration Job has `backoffLimit: 3` and `activeDeadlineSeconds: 300`
- **Dependencies:** Init Job requires LlamaStack to be running; DB migration Job requires pgvector to be ready (both subcharts of the umbrella chart)

## Gotchas

- The init Job uses dual `curl` commands (`--fail` and without) because LlamaStack's root endpoint behavior differs between versions -- the second curl catches cases where the endpoint returns a non-200 status but is actually ready (see `helm/templates/init-job.yaml`)
- The Makefile deletes all Jobs matching the Helm release label before each install because Kubernetes Jobs are immutable -- `helm upgrade` cannot modify completed Jobs, causing upgrade failures (see `helm_install_common` function)
- The init Job uses the agent-service image (same as the app) rather than a utility image, keeping the registration script (`register_assets`) versioned alongside the application code
- The DB migration Job is explicitly NOT a Helm hook (comment says "Remove Helm hooks - let jobs run naturally with Makefile cleanup") to avoid ordering issues with Helm hook execution (see `helm/templates/db-migration-job.yaml`)

## Related Patterns

- `helm-post-init-scaler-job-hook.md` -- scaler Job that waits for the init Job to complete before scaling LlamaStack
- `helm-init-job-multi-service-wait-chain.md` -- similar init Job pattern but with chained init containers
