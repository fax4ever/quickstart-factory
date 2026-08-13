---
name: helm-initcontainer-db-wait-alembic-migration-chain
description: API Deployment with pg_isready initContainer wait followed by Alembic migration initContainer before main container starts
summary: "Ensures PostgreSQL is ready and schema migrations are applied before a FastAPI container starts in a Helm-deployed OpenShift API Deployment using a sequential two-step initContainer chain (pg_isready wait followed by migration verification). Approach A runs `alembic upgrade head` directly in the second initContainer using the application image with `PYTHONPATH=/app/packages/db/src:/app/packages/api/src` for monorepo cross-package imports (idempotent via Alembic version tracking); Approach B polls table existence via `psql SELECT 1 FROM users LIMIT 1` using only postgres:16-alpine when a separate Helm hook Job handles migrations -- gate both on `database.enabled` to skip the chain for external databases. The first initContainer uses postgres:16-alpine to poll `pg_isready -h {{ .Values.database.name }}` every 5s against the StatefulSet headless Service DNS, credentials come from a shared Secret (POSTGRES_USER, POSTGRES_DB, POSTGRES_PASSWORD, DATABASE_URL), and Approach A runs `cd /app/packages/db && alembic upgrade head` to locate alembic.ini relative to the working directory. The wait loop has no explicit timeout (relies on Kubernetes initContainer deadline), PGPASSWORD must be set as a separate env var from DATABASE_URL for pg_isready authentication, and Approach B's table existence check can pass before all tables are created if migration order differs."
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
  - quickstart: "spending-transaction-monitor"
    repo: "https://github.com/rh-ai-quickstart/spending-transaction-monitor"
    notes: "Two-step initContainer chain on API Deployment: pg_isready wait then wait-for-migration polling users table existence via psql SELECT to confirm hook Job migration completed"
    approach: "B"
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

---

## Approach B: DB Wait + Migration Table Existence Poll (from spending-transaction-monitor)

### When to Use

When migrations run as a separate Helm hook Job (not as an initContainer on the API Deployment) and the API needs to confirm the migration Job completed before starting. Instead of running Alembic directly, the second initContainer polls for a specific table's existence.

### Differences from Approach A

- Migrations are handled by a separate Helm hook Job (`helm-hook-job-migration-keycloak-data-orchestrator.md`), not by an initContainer on the API Deployment
- The second initContainer polls for table existence via `psql SELECT` rather than running `alembic upgrade head`
- No `PYTHONPATH` needed since this initContainer only checks database state, not running Python code
- Both initContainers use `postgres:16-alpine` (not the application image)

### Wait-for-Migration InitContainer

```yaml
# deploy/helm/spending-monitor/templates/api-deployment.yaml (excerpt)
- name: wait-for-migration
  image: postgres:16-alpine
  command:
    - /bin/sh
    - -c
    - |
      echo "Waiting for database migration to complete..."
      until psql -h {{ .Values.database.name }} -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
        -c "SELECT 1 FROM users LIMIT 1" > /dev/null 2>&1; do
        echo "Migration not complete (users table not ready), waiting..."
        sleep 5
      done
      echo "Migration complete - users table exists!"
  env:
    - name: PGPASSWORD
      valueFrom:
        secretKeyRef:
          name: {{ include "spending-monitor.fullname" . }}-secret
          key: POSTGRES_PASSWORD
    - name: POSTGRES_USER
      valueFrom:
        secretKeyRef:
          name: {{ include "spending-monitor.fullname" . }}-secret
          key: POSTGRES_USER
    - name: POSTGRES_DB
      valueFrom:
        secretKeyRef:
          name: {{ include "spending-monitor.fullname" . }}-secret
          key: POSTGRES_DB
```

### Gotchas (Approach B)

- The `SELECT 1 FROM users LIMIT 1` check assumes the `users` table is created during migration; if migrations create tables in a different order, this check could pass before all tables exist
- Both initContainers use `postgres:16-alpine` which includes both `pg_isready` and `psql` -- no application image needed
- The wait-for-migration has no timeout and depends entirely on the Kubernetes initContainer deadline

---

## Choosing Between Approaches

| Criteria | Approach A | Approach B |
|----------|-----------|-----------|
| Migration runner | InitContainer on API Deployment | Separate Helm hook Job |
| Second initContainer | Runs `alembic upgrade head` | Polls table existence via `psql SELECT` |
| Application image needed | Yes (for Alembic) | No (uses postgres:16-alpine) |
| PYTHONPATH required | Yes (cross-package imports) | No |
| Idempotent | Yes (Alembic tracks versions) | N/A (only checks, does not migrate) |

## Related Patterns

- `helm-init-job-multi-service-wait-chain.md` -- alternative pattern using Jobs instead of initContainers for multi-service waits
- `helm-init-job-llamastack-registration-db-migration.md` -- init Job pattern for combined registration and migration
- `helm-hook-job-migration-keycloak-data-orchestrator.md` -- the migration hook Job that Approach B waits for
