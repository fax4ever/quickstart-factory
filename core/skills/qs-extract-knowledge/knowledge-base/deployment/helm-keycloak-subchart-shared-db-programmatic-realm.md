---
name: helm-keycloak-subchart-shared-db-programmatic-realm
description: Keycloak local subchart in production mode sharing parent PostgreSQL via init ConfigMap, with programmatic realm/user setup via auth CLI
summary: "Deploys Keycloak 26.x as a local Helm subchart (file://../keycloak dependency, condition: keycloak.enabled) sharing the parent app's PostgreSQL via a ConfigMap init script that creates a separate keycloak database, with programmatic realm/client/user setup via a Python keycloak.cli package instead of static realm JSON import. Use when Keycloak must run in production mode (start, not start-dev) alongside an existing PostgreSQL-backed parent chart and realm configuration needs to sync users from the application database — prefer helm-keycloak-realm-files-get-configmap-dev-mode for dev-mode with static realm JSON or RHBK CRD-based approaches for operator-managed deployments. Critical config: 01-create-keycloak-db.sh init script mounts into /docker-entrypoint-initdb.d/ with full schema public grants, Keycloak reads DB credentials via secretKeyRef from the parent Secret with KC_PROXY=edge, KC_PROXY_HEADERS=xforwarded, KC_HOSTNAME_STRICT=false, KC_HTTP_ENABLED=true, health probes on management port 9000 (initialDelaySeconds 120 liveness / 60 readiness), and the migration Job runs keycloak.cli wait --max-attempts 60 then setup --sync-users. Gotchas: init script only executes on first PostgreSQL startup (empty PVC — redeploying without clearing PVC skips keycloak DB creation), production mode adds ~30s startup for config auto-build, KC_HOSTNAME is sed-extracted from KEYCLOAK_FRONTEND_URL in the Makefile, admin password must be passed via --set (not values.yaml), checksum/config annotation forces pod restart on Secret changes, and the wait-for-keycloak-db initContainer is commented out in favor of Keycloak's own retry logic."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  ai_pattern: []
  platform: [openshift]
source_examples:
  - quickstart: "spending-transaction-monitor"
    repo: "https://github.com/rh-ai-quickstart/spending-transaction-monitor"
    notes: "Keycloak 26.0.7 local subchart with start (production mode), shared PostgreSQL via init ConfigMap that creates keycloak DB, credentials from parent Secret, programmatic realm setup via Python auth CLI"
    approach: "A"
---

# Keycloak Local Subchart with Shared DB and Programmatic Realm Setup

## Overview

This pattern deploys Keycloak as a local Helm subchart (referenced via `file://../keycloak`) that shares the parent application's PostgreSQL instance rather than deploying its own database. A ConfigMap init script creates the `keycloak` database on first PostgreSQL startup, and realm/user configuration is handled programmatically by a Python auth CLI package (not via static realm JSON import). Keycloak runs in production mode (`start`, not `start-dev`).

## Pattern Description

The parent chart's umbrella `Chart.yaml` declares a dependency on the local Keycloak chart. Keycloak connects to the same PostgreSQL instance as the main application using credentials from the parent's Secret, but targets a separate database (`keycloak`) created by an init script mounted into PostgreSQL's `/docker-entrypoint-initdb.d/`. Unlike patterns that embed realm JSON via `.Files.Get`, this approach uses a Python `keycloak.cli` package that programmatically creates the realm, clients, and syncs users from the application database at migration time.

## Implementation

### Parent Chart Dependency Declaration

```yaml
# deploy/helm/spending-monitor/Chart.yaml
dependencies:
  - name: keycloak
    version: "1.0.0"
    repository: "file://../keycloak"
    condition: keycloak.enabled
```

Source: `deploy/helm/spending-monitor/Chart.yaml`

### Database Init Script ConfigMap

A ConfigMap creates the `keycloak` database during PostgreSQL's first startup, granting full privileges to the shared user:

```yaml
data:
  01-create-keycloak-db.sh: |
    #!/bin/bash
    set -e
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
        CREATE DATABASE keycloak;
        GRANT ALL PRIVILEGES ON DATABASE keycloak TO "$POSTGRES_USER";
    EOSQL
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "keycloak" <<-EOSQL
        GRANT ALL ON SCHEMA public TO "$POSTGRES_USER";
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO "$POSTGRES_USER";
        ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON SEQUENCES TO "$POSTGRES_USER";
    EOSQL
```

Source: `deploy/helm/spending-monitor/templates/database-init-configmap.yaml`

### Keycloak Deployment Using Parent Secret

Keycloak reads database credentials from the parent chart's Secret rather than having its own:

```yaml
env:
  - name: KC_DB
    value: {{ .Values.database.vendor }}
  - name: KC_DB_URL_HOST
    valueFrom:
      secretKeyRef:
        name: {{ .Values.database.secretName | quote }}  # spending-monitor-secret
        key: POSTGRES_DB_HOST
  - name: KC_DB_URL_DATABASE
    value: {{ .Values.database.dbname }}  # "keycloak"
  - name: KC_DB_USERNAME
    valueFrom:
      secretKeyRef:
        name: {{ .Values.database.secretName | quote }}
        key: POSTGRES_USER
```

Source: `deploy/helm/keycloak/templates/deployment.yaml`

### Production Mode Configuration

Keycloak uses `start` (not `start-dev`), with proxy headers for OpenShift Routes:

```yaml
args:
  - start
env:
  - name: KC_PROXY
    value: {{ .Values.config.proxy }}  # "edge"
  - name: KC_PROXY_HEADERS
    value: {{ .Values.config.proxyHeaders }}  # "xforwarded"
  - name: KC_HOSTNAME_STRICT
    value: {{ .Values.config.hostnameStrict | quote }}  # "false"
  - name: KC_HTTP_ENABLED
    value: "true"
```

Source: `deploy/helm/keycloak/templates/deployment.yaml`. Health probes target port 9000 (`/health/live`, `/health/ready`).

### Programmatic Realm Setup

Realm and user configuration is done by a Python auth CLI package at migration time (in the migration Job), not via Keycloak realm JSON:

```bash
# From startup.sh (migration Job)
cd /app/packages/auth/src
/app/venv/bin/python3 -m keycloak.cli wait --max-attempts 60 --interval 2
/app/venv/bin/python3 -m keycloak.cli setup --sync-users
```

Source: `packages/db/startup.sh`

## Configuration

- **database.secretName:** `spending-monitor-secret` -- shared Secret with parent app for DB credentials
- **database.dbname:** `keycloak` -- separate DB within shared PostgreSQL
- **config.proxy:** `edge` -- TLS terminated at OpenShift Route
- **config.proxyHeaders:** `xforwarded` -- trust X-Forwarded headers from OpenShift HAProxy
- **Health probes:** Port 9000 (Keycloak 26.x management port), `initialDelaySeconds: 120` for liveness, 60 for readiness
- **admin.password:** Passed via `--set keycloak.admin.password` from Makefile (not stored in values.yaml)

## Gotchas

- The `01-create-keycloak-db.sh` init script only runs on first PostgreSQL startup (when data volume is empty); redeploying without clearing the PVC will not recreate the keycloak database
- Keycloak's hostname (`KC_HOSTNAME`) is dynamically computed by the Makefile from `KEYCLOAK_FRONTEND_URL` using `sed` to strip protocol and port: `sed 's|http://||' | sed 's|https://||' | sed 's|/.*||' | sed 's|:[0-9]*$||'`
- The deployment has a commented-out `wait-for-keycloak-db` initContainer (visible in the template), suggesting the team considered but disabled it in favor of Keycloak's own retry logic
- Using `start` (production mode) adds ~30 seconds to startup vs `start-dev` because Keycloak auto-builds its configuration; a comment in the template explains this tradeoff
- The `checksum/config` annotation (`{{ include (print $.Template.BasePath "/secret.yaml") . | sha256sum }}`) forces pod restart when the Secret changes

## Related Patterns

- `helm-keycloak-realm-files-get-configmap-dev-mode.md` - Keycloak in start-dev with .Files.Get realm JSON
- `helm-keycloak-openshift-oauth-patch-realmimport.md` - RHBK operator with KeycloakRealmImport CRD
- `helm-keycloak-rhbk-crd-subchart-oidc-autoconfig.md` - RHBK CRD-based approach
