---
name: helm-initcontainer-db-wait-alembic-migration-chain
description: API Deployment with pg_isready initContainer wait followed by Alembic migration initContainer before main container starts
summary: "Ensures PostgreSQL is ready and Alembic schema migrations are applied before a FastAPI container starts in a Helm-deployed OpenShift API Deployment using a sequential two-step initContainer chain. Use when deploying a Python monorepo application with a co-deployed PostgreSQL StatefulSet requiring automatic migration -- gate both initContainers on database.enabled so external database scenarios skip the chain and assume pre-applied migrations. The postgres:16-alpine initContainer polls pg_isready every 5s against the StatefulSet headless Service DNS, then the application image initContainer runs cd /app/packages/db && alembic upgrade head with PYTHONPATH=/app/packages/db/src:/app/packages/api/src to resolve cross-package model imports in the monorepo layout. The wait loop has no explicit timeout (relies on Kubernetes initContainer deadline), PGPASSWORD must be set as a separate env var from DATABASE_URL to authenticate pg_isready without parsing the connection string, and Alembic must run from the DB package directory because it locates alembic.ini relative to the working directory."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, postgresql, python, fastapi]
  ai_pattern: []
  platform: [openshift]
source_examples:
  - quickstart: "multi-agent-loan-origination"
    repo: "https://github.com/rh-ai-quickstart/multi-agent-loan-origination"
    notes: "Two-step initContainer chain: postgres:16-alpine pg_isready wait then API image Alembic upgrade head, with PYTHONPATH for monorepo package resolution"
    approach: "A"
---

# InitContainer Chain: DB Wait then Alembic Migration

## Overview

This pattern uses a two-step initContainer chain in the API Deployment to ensure the database is ready and migrations are applied before the main application container starts. The first initContainer uses a lightweight PostgreSQL image to poll `pg_isready`, and the second uses the application image to run `alembic upgrade head`, with a custom `PYTHONPATH` to resolve packages from a monorepo layout.

## Pattern Description

Kubernetes initContainers run sequentially before the main container. This pattern chains two: a database readiness check using the official `postgres:16-alpine` image (which includes `pg_isready`), followed by a migration runner using the same application image as the main container. The migration initContainer navigates to the DB package directory within the monorepo structure and runs Alembic with the `PYTHONPATH` set to include both the DB and API source trees. Both initContainers read credentials from the same Secret.

## Implementation

### Database Readiness Wait InitContainer

```yaml
# deploy/helm/mortgage-ai/templates/api-deployment.yaml (excerpt)
initContainers:
  {{- if .Values.database.enabled }}
  - name: wait-for-database
    image: postgres:16-alpine
    command:
      - /bin/sh
      - -c
      - |
        echo "Waiting for database to be ready..."
        until pg_isready -h {{ .Values.database.name }} -U "$POSTGRES_USER" -d "$POSTGRES_DB"; do
          echo "Database not ready, waiting..."
          sleep 5
        done
        echo "Database is ready!"
    env:
      - name: POSTGRES_USER
        valueFrom:
          secretKeyRef:
            name: {{ include "mortgage-ai.fullname" . }}-secret
            key: POSTGRES_USER
      - name: POSTGRES_DB
        valueFrom:
          secretKeyRef:
            name: {{ include "mortgage-ai.fullname" . }}-secret
            key: POSTGRES_DB
      - name: PGPASSWORD
        valueFrom:
          secretKeyRef:
            name: {{ include "mortgage-ai.fullname" . }}-secret
            key: POSTGRES_PASSWORD
```

### Alembic Migration InitContainer

```yaml
# deploy/helm/mortgage-ai/templates/api-deployment.yaml (excerpt)
  - name: run-migrations
    image: {{ include "mortgage-ai.image" (dict "name" .Values.api.image.repository "tag" .Values.api.image.tag "Values" .Values) }}
    imagePullPolicy: {{ .Values.global.imagePullPolicy }}
    command:
      - /bin/sh
      - -c
      - |
        cd /app/packages/db && alembic upgrade head
    env:
      - name: DATABASE_URL
        valueFrom:
          secretKeyRef:
            name: {{ include "mortgage-ai.fullname" . }}-secret
            key: DATABASE_URL
      - name: PYTHONPATH
        value: "/app/packages/db/src:/app/packages/api/src"
  {{- end }}
```

## Configuration

- **Key settings:** Both initContainers are conditional on `database.enabled` -- when the database is externally managed, no wait or migration is needed; the `PYTHONPATH` includes both `db/src` and `api/src` to resolve cross-package imports during migration
- **Defaults:** The wait loop polls every 5 seconds with no timeout (relies on Kubernetes initContainer deadline); the migration runs `alembic upgrade head` which is idempotent
- **Dependencies:** The `postgres:16-alpine` image must be pullable; the API image must contain both Alembic and the migration scripts at `/app/packages/db/`; the Secret must contain `POSTGRES_USER`, `POSTGRES_DB`, `POSTGRES_PASSWORD`, and `DATABASE_URL`

## Gotchas

- The wait initContainer uses `pg_isready` with `-h {{ .Values.database.name }}` which resolves to the StatefulSet's headless service DNS -- this works because the database is deployed as a StatefulSet with a Service in the same namespace (see `deploy/helm/mortgage-ai/templates/api-deployment.yaml` line 52 and `database-deployment.yaml`)
- The `PGPASSWORD` env var is set for `pg_isready` authentication -- this is separate from the `DATABASE_URL` used by Alembic and avoids parsing the connection string (see `deploy/helm/mortgage-ai/templates/api-deployment.yaml` lines 69-72)
- The migration initContainer sets `PYTHONPATH` to include both package source directories because the DB package's Alembic config imports models that cross-reference the API package (see `deploy/helm/mortgage-ai/templates/api-deployment.yaml` lines 88-89)
- The `cd /app/packages/db && alembic upgrade head` command navigates to the DB package directory because Alembic expects to find `alembic.ini` relative to the working directory (see `deploy/helm/mortgage-ai/templates/api-deployment.yaml` line 80)
- The entire initContainers block is wrapped in `{{- if .Values.database.enabled }}` -- when using an external database, the operator is expected to have already applied migrations (see `deploy/helm/mortgage-ai/templates/api-deployment.yaml` line 44)

## Related Patterns

- `helm-init-job-multi-service-wait-chain.md` -- alternative pattern using Jobs instead of initContainers for multi-service waits
- `helm-init-job-llamastack-registration-db-migration.md` -- init Job pattern for combined registration and migration
