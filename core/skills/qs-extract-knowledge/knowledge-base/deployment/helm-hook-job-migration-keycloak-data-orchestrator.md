---
name: helm-hook-job-migration-keycloak-data-orchestrator
description: Helm post-install/post-upgrade hook Job with DB+Keycloak initContainer waits running startup.sh for Alembic migration, CSV data load, and Keycloak realm sync
summary: "Orchestrates multi-step initialization -- PostgreSQL readiness wait via pg_isready initContainer, conditional Keycloak health-check initContainer, Alembic schema migration, CSV sample-data loading, and Keycloak realm/user sync -- as a Helm post-install,post-upgrade hook Job (hook-weight \"1\") that completes before the application Deployment starts. Use over initContainer-on-Deployment (see helm-initcontainer-db-wait-alembic-migration-chain) when initialization requires a separate image with ML dependencies (torch, sentence-transformers for embeddings during data load), monorepo cross-package PYTHONPATH, and conditional auth setup gated by BYPASS_AUTH; single approach (A) from spending-transaction-monitor. Critical config: backoffLimit: 1 (config issues won't self-resolve), hook-delete-policy: before-hook-creation,hook-succeeded cleans up successful Jobs, 2Gi memory limit for torch/sentence-transformers imports, and startup.sh chains alembic upgrade head, CSV load via load_csv_data, then keycloak.cli setup --sync-users with set +e so sync failures are non-critical. Keycloak wait initContainer exits 0 on timeout (soft dependency), so startup.sh includes a second CLI-based wait via keycloak.cli wait --max-attempts 60; migration image (spending-monitor-db) differs from API image requiring separate build; KEYCLOAK_DEFAULT_PASSWORD is hardcoded password123 in the Job spec for demo users."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, postgresql, python, fastapi]
  ai_pattern: []
  platform: [openshift]
source_examples:
  - quickstart: "spending-transaction-monitor"
    repo: "https://github.com/rh-ai-quickstart/spending-transaction-monitor"
    notes: "Hook Job with pg_isready + conditional Keycloak health initContainers, startup.sh runs Alembic + CSV data load + Keycloak realm setup with user sync"
    approach: "A"
---

# Helm Hook Job: Migration + Data Load + Keycloak Orchestrator

## Overview

This pattern uses a Helm `post-install,post-upgrade` hook Job to orchestrate multi-step initialization: database readiness wait, optional Keycloak readiness wait, Alembic schema migration, CSV sample data loading, and Keycloak realm setup with user synchronization. Unlike initContainers on the application Deployment, this runs as a standalone Job that completes before the application starts via hook ordering.

## Pattern Description

The Job uses two initContainers (database wait via `pg_isready`, conditional Keycloak wait via `curl` health check) followed by a main container that runs a `startup.sh` shell script. The startup script orchestrates Alembic migrations, detects and loads CSV data files, and conditionally sets up a Keycloak realm with user sync when `BYPASS_AUTH=false`. The Job is annotated with `helm.sh/hook-delete-policy: before-hook-creation,hook-succeeded` to clean up on re-deploy, and uses `hook-weight: "1"` for ordering.

## Implementation

### Hook Job with InitContainers

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ .Values.migration.name }}
  annotations:
    "helm.sh/hook": post-install,post-upgrade
    "helm.sh/hook-weight": "1"
    "helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded
spec:
  backoffLimit: {{ .Values.migration.backoffLimit }}
  template:
    spec:
      restartPolicy: {{ .Values.migration.restartPolicy }}
      initContainers:
        - name: wait-for-database
          image: postgres:16-alpine
          command:
            - /bin/sh
            - -c
            - |
              until pg_isready -h {{ .Values.database.name }} -p 5432; do
                sleep 3
              done
```

Source: `deploy/helm/spending-monitor/templates/migration-job.yaml`

### Conditional Keycloak Wait InitContainer

The Keycloak wait is conditionally included only when auth is enabled (`BYPASS_AUTH != true`) and Keycloak subchart is enabled:

```yaml
      {{- if and (not (eq (.Values.secrets.BYPASS_AUTH | toString) "true")) .Values.keycloak.enabled }}
        - name: wait-for-keycloak
          image: curlimages/curl:latest
          command:
            - /bin/sh
            - -c
            - |
              MAX_ATTEMPTS=36
              ATTEMPT=1
              while [ $ATTEMPT -le $MAX_ATTEMPTS ]; do
                if curl -s -f "http://{{ .Release.Name }}-keycloak:8080/health/ready" > /dev/null 2>&1; then
                  exit 0
                fi
                sleep 5
                ATTEMPT=$((ATTEMPT + 1))
              done
              echo "Keycloak not ready after 3 minutes"
              echo "Continuing anyway - sync script will check availability"
              exit 0
      {{- end }}
```

Source: `deploy/helm/spending-monitor/templates/migration-job.yaml`. The Keycloak wait exits successfully even on timeout, making it a soft dependency.

### Startup Script Orchestration

The main container runs `startup.sh` which chains four steps:

```bash
#!/bin/bash
set -e

# Step 1: Wait for PostgreSQL (belt-and-suspenders after initContainer)
MAX_ATTEMPTS=30
while [ $ATTEMPT -le $MAX_ATTEMPTS ]; do
    if pg_isready -h ${POSTGRES_HOST:-postgres} -U ${POSTGRES_USER:-user} -d ${POSTGRES_DB:-spending-monitor} -q; then
        break
    fi
    sleep 5
done

# Step 2: Run Alembic migrations
cd /app/packages/db
alembic upgrade head

# Step 3: Load CSV data if present
if [ -f "$USERS_CSV" ] && [ -f "$TRANSACTIONS_CSV" ]; then
    export PYTHONPATH="/app/packages/db/src:/app/packages/api/src:$PYTHONPATH"
    python3 -m db.scripts.load_csv_data
fi

# Step 4: Keycloak realm setup (conditional)
if [ "${BYPASS_AUTH:-true}" = "false" ] && [ -n "${KEYCLOAK_URL}" ]; then
    cd /app/packages/auth/src
    /app/venv/bin/python3 -m keycloak.cli wait --max-attempts 60 --interval 2
    set +e
    /app/venv/bin/python3 -m keycloak.cli setup --sync-users
    set -e
fi
```

Source: `packages/db/startup.sh` (abridged). Keycloak sync failures are non-critical -- the script continues.

## Configuration

- **backoffLimit:** 1 (only retry once -- config issues won't resolve with retries)
- **hook-delete-policy:** `before-hook-creation,hook-succeeded` cleans up completed Jobs before re-deploy
- **Migration resources:** requests 1Gi memory, 250m CPU; limits 2Gi memory (accommodates torch/sentence-transformers imports)
- **PYTHONPATH:** `/app/packages/db/src:/app/packages/api/src` for monorepo cross-package imports
- **KEYCLOAK_DEFAULT_PASSWORD:** Hardcoded `password123` in the Job spec for demo user creation

## Gotchas

- The Keycloak wait initContainer exits 0 on timeout, so the Job continues even if Keycloak is not ready; the startup.sh has its own Keycloak wait with the auth CLI's `wait` subcommand as a second check
- Migration resources are set higher than typical (2Gi memory limit) because the startup.sh imports torch and sentence-transformers for embedding generation during CSV data loading
- The startup.sh uses `set +e` around Keycloak sync to prevent non-critical sync failures from failing the entire Job
- The migration image (`spending-monitor-db`) is different from the API image -- it includes the auth package, PostgreSQL client, and venv with ML dependencies for data processing

## Related Patterns

- `helm-initcontainer-db-wait-alembic-migration-chain.md` - initContainer approach on API Deployment (not a hook Job)
- `helm-hook-data-loader-job-readonly-user.md` - Data loading via hook Job
- `helm-keycloak-realm-files-get-configmap-dev-mode.md` - Keycloak realm via .Files.Get (not programmatic CLI)
