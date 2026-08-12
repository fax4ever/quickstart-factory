---
name: helm-hook-initcontainer-psql-table-existence-poll
description: Helm post-install hook Job with initContainer polling PostgreSQL for table existence before running app init
summary: "Sequences application initialization after an asynchronous external process (e.g., Kubeflow training pipeline) by implementing a two-level Helm hook wait chain that polls PostgreSQL for table existence before running app init in a post-install/post-upgrade hook Job. Use when app init depends on database schema created by an async pipeline with PostgreSQL/pgvector as the data layer — the hook Job (weight 1, delete-policy before-hook-creation) runs a postgres:15-alpine initContainer polling for the table, then the main Deployment's ose-cli initContainer polls for hook Job completion via jsonpath. Critical implementation: initContainer runs `until PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -U $DB_USER -d $DB_NAME -c \"SELECT 1 FROM <table> LIMIT 1\"; do sleep 10; done` with DB credentials from pgvector Secret via secretKeyRef; Deployment polls `oc get job <name> -o jsonpath='{.status.conditions[?(@.type==\"Complete\")].status}'` every 20s. Neither polling loop has a timeout so both block indefinitely if the pipeline fails, the oc get job approach requires a job-viewer ServiceAccount with RBAC Role/RoleBinding, and before-hook-creation deletes old hook Jobs leaving no init run history."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, postgresql]
  ai_pattern: [data-pipeline]
  platform: [openshift]
  data_layer: [pgvector]
source_examples:
  - quickstart: "product-recommender-system"
    repo: "https://github.com/rh-ai-quickstart/product-recommender-system"
    notes: "db-init hook Job initContainer polls PostgreSQL for model_version table created by Kubeflow pipeline before running Python init script"
    approach: "A"
---

# Helm Hook InitContainer Polling PostgreSQL Table Existence

## Overview

A Helm post-install/post-upgrade hook Job uses an initContainer to poll PostgreSQL for the existence of a specific table before the main container runs application initialization. This creates a dependency chain where the app init waits for an external process (e.g., a Kubeflow training pipeline) to complete its database schema setup.

## Pattern Description

The db-init Job is annotated as a Helm `post-install,post-upgrade` hook at weight `1`. Its initContainer runs a `psql` query in a loop, checking whether a table (`model_version`) exists in the database. This table is created by a Kubeflow training pipeline that runs asynchronously after deployment. Only after the table is found does the main container execute the Python initialization script (`init_backend.py`), which depends on the training results.

## Implementation

### Hook Job with PostgreSQL Polling InitContainer

```yaml
# helm/product-recommender-system/templates/backend.yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ include "product-recommender-system.fullname" . }}-db-init
  annotations:
    "helm.sh/hook": "post-install,post-upgrade"
    "helm.sh/hook-weight": "1"
    "helm.sh/hook-delete-policy": "before-hook-creation"
spec:
  template:
    spec:
      initContainers:
        - name: wait-until-model-training-workflow
          image: postgres:15-alpine
          command:
            - /bin/sh
            - -c
            - |
              until PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -U $DB_USER -d $DB_NAME -c "SELECT 1 FROM model_version LIMIT 1" > /dev/null 2>&1; do
                echo "Waiting for model_version table..."
                sleep 10
              done
              echo "model_version table is ready!"
          env:
            {{- if .Values.env }}
            {{- toYaml .Values.env | nindent 12 }}
            {{- end }}
      containers:
      - name: db-init
        image: "{{ .Values.frontendBackendImage }}"
        command: ["/bin/sh", "-c", "cd /app/backend && PYTHONPATH=/app/backend python src/init_backend.py"]
```

### Deployment InitContainer Waiting for Hook Job

The main Deployment also uses an initContainer that waits for this db-init Job to complete, using `oc get job` to poll for the Job's completion status:

```yaml
# Same file: backend Deployment spec
initContainers:
  - name: wait-for-db-init
    image: registry.redhat.io/openshift4/ose-cli:latest
    command:
      - /bin/sh
      - -c
      - |
        until oc get job product-recommender-system-db-init -o jsonpath='{.status.conditions[?(@.type=="Complete")].status}' | grep "True"; do
          echo "Waiting for db-init job to complete..."
          sleep 20
        done
        echo "db-init job completed successfully!"
```

## Configuration

- **Key settings:** Database credentials (`DB_HOST`, `DB_PORT`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`) sourced from `pgvector` Secret via `secretKeyRef`
- **Defaults:** Poll interval is 10 seconds for psql check, 20 seconds for Job completion check
- **Dependencies:** PostgreSQL must be running (provided by pgvector subchart), and the Kubeflow training pipeline must eventually create the `model_version` table

## Gotchas

- The `postgres:15-alpine` image is used for the initContainer rather than the application image, introducing a separate image dependency solely for the `psql` client.
- The wait loop has no timeout -- if the training pipeline never runs or fails, the initContainer will poll indefinitely.
- The Deployment's initContainer uses `oc get job` which requires the `job-viewer` ServiceAccount and Role/RoleBinding (also defined in the same template file) to have RBAC access to watch Jobs.
- `helm.sh/hook-delete-policy: before-hook-creation` means old hook Jobs are deleted before new ones are created, so there is no history of previous init runs.

## Related Patterns

- `helm-lookup-guard-job-cronjob-shared-define-template.md` — the KFP runner Job in the same quickstart that also uses initContainer wait chains
- `helm-feast-crd-git-featurerepo-registry-wait-apply.md` — similar initContainer wait pattern for Feast registry readiness
