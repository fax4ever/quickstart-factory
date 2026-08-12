---
name: keycloak-db
description: PostgreSQL StatefulSet backing Keycloak via Helm subchart with lookup-based secret idempotency
summary: "Deploys a dedicated PostgreSQL 15 StatefulSet as a Helm subchart (charts/keycloak/, condition: keycloak.enabled) to back the Red Hat Build of Keycloak Operator (k8s.keycloak.org/v2alpha1 CR) on RHOAI, isolated from the application's pgvector database despite sharing the postgresql-15-pgvector-c9s image. Choose this raw StatefulSet with volumeClaimTemplates over CNPG operator (keycloak.md Approach A) or embedded H2 (Approach B) when you need direct persistent storage control without operator dependency; credentials use Helm pre-install/pre-upgrade hook secrets with lookup in _helpers.tpl for password reuse, and a pre-delete cleanup Job with scoped RBAC removes hook-managed secrets and KeycloakRealmImport CRs. Keycloak CR wires db.host to the ClusterIP service name with usernameSecret/passwordSecret referencing the hook-created secret, postgres.password must be supplied via --set (no default, enforced by required; generate with openssl rand -base64 24), pg_isready probes verify connectivity (liveness initialDelay 30s, readiness 5s), and defaults are 10Gi PVC with 512Mi-2Gi memory / 250m-1000m CPU. The volumeMount path /data differs from PGDATA /var/lib/pgsql/data (image entrypoint handles redirection), hook-delete-policy: before-hook-creation creates a brief secret absence window during helm upgrade despite lookup-based password continuity, and the cleanup hook's quay.io/openshift/origin-cli:latest image must be mirrored for air-gapped clusters."
metadata:
  type: component
tags:
  tech_stack: [postgresql, keycloak, helm]
  ai_pattern: []
  platform: [openshift, kubernetes]
  data_layer: [postgresql]
source_examples:
  - quickstart: "peoplemesh"
    repo: "https://github.com/rh-ai-quickstart/peoplemesh"
    notes: "Dedicated PostgreSQL 15 StatefulSet backing Keycloak operator CR, with Helm hook secrets and volumeClaimTemplates"
    approach: "A"
---

# Keycloak DB

## Overview

A dedicated PostgreSQL instance deployed as a Kubernetes StatefulSet to back a Keycloak identity provider in AI quickstarts on RHOAI. Unlike the CNPG operator approach (see `keycloak.md` Approach A) or embedded H2 dev mode (Approach B), this pattern uses a raw StatefulSet with volumeClaimTemplates for persistent storage, managed as a Helm subchart alongside the Keycloak operator CR. The database is separate from the application's primary data store (pgvector), providing isolation between authentication infrastructure and application data.

## Tech Stack & Dependencies

- **Runtime:** PostgreSQL 15 (Red Hat build)
- **Container image:** `quay.io/rh-aiservices-bu/postgresql-15-pgvector-c9s:latest` (same image used by pgvector subcharts)
- **Key dependencies:** Red Hat Build of Keycloak Operator (consumes the DB via `k8s.keycloak.org/v2alpha1` Keycloak CR)
- **Helm subchart:** Custom subchart at `charts/keycloak/` (v0.1.0), deployed as umbrella chart dependency with `condition: keycloak.enabled`

## Key Patterns

### StatefulSet with volumeClaimTemplates

The database is deployed as a StatefulSet (not a Deployment) with a volumeClaimTemplate that provisions storage per pod replica. This ensures the PVC survives pod restarts and reschedules without requiring a separate PVC resource.

```yaml
# charts/keycloak/templates/postgres-statefulset.yaml
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: {{ .Values.applicationName }}-postgres-db
spec:
  serviceName: {{ .Values.postgres.service.name }}
  replicas: 1
  template:
    spec:
      containers:
        - name: postgresql-db
          image: {{ .Values.postgres.image.repository }}:{{ .Values.postgres.image.tag }}
          env:
            - name: PGDATA
              value: /var/lib/pgsql/data
          volumeMounts:
            - name: postgres-data
              mountPath: /data
  volumeClaimTemplates:
    - metadata:
        name: postgres-data
      spec:
        accessModes: [ReadWriteOnce]
        resources:
          requests:
            storage: {{ .Values.postgres.persistence.size }}
```

### Helm Hook Secrets with Lookup Idempotency

Database credentials are created as a Helm pre-install/pre-upgrade hook. The `_helpers.tpl` uses the Helm `lookup` function to check if the secret already exists -- if so, the existing password is reused, preventing credential rotation on upgrades that would break the running database.

```yaml
# charts/keycloak/templates/postgres-secret.yaml
apiVersion: v1
kind: Secret
metadata:
  name: {{ .Values.applicationName }}-db-secret
  annotations:
    "helm.sh/hook": pre-install,pre-upgrade
    "helm.sh/hook-weight": "-10"
    "helm.sh/hook-delete-policy": before-hook-creation
stringData:
  username: {{ .Values.postgres.user | quote }}
  password: {{ include "keycloak.postgresPassword" . | quote }}
```

```go
{{/* charts/keycloak/templates/_helpers.tpl */}}
{{- define "keycloak.postgresPassword" -}}
{{- $secret := lookup "v1" "Secret" .Release.Namespace "keycloak-db-secret" -}}
{{- if $secret -}}
  {{- index $secret.data "password" | b64dec -}}
{{- else -}}
  {{- required "keycloak.postgres.password is required. Generate with: openssl rand -base64 24" .Values.postgres.password -}}
{{- end -}}
{{- end }}
```

### Keycloak CR Database Wiring

The Keycloak operator CR references the PostgreSQL service and secret directly, with no intermediate ConfigMap or connection string assembly. The `db.host` points to the ClusterIP service name.

```yaml
# charts/keycloak/templates/keycloak-cr.yaml
spec:
  db:
    vendor: postgres
    host: {{ .Values.postgres.service.name }}
    usernameSecret:
      name: {{ .Values.applicationName }}-db-secret
      key: username
    passwordSecret:
      name: {{ .Values.applicationName }}-db-secret
      key: password
```

### Cleanup Hook with RBAC

A pre-delete Job cleans up secrets and realm imports that Helm cannot track (due to the hook lifecycle). The Job uses a dedicated ServiceAccount with a scoped Role limited to secrets and keycloakrealmimports.

```yaml
# charts/keycloak/templates/cleanup-secrets-hook.yaml
annotations:
  "helm.sh/hook": pre-delete
  "helm.sh/hook-weight": "-5"
  "helm.sh/hook-delete-policy": hook-succeeded,hook-failed
spec:
  containers:
  - name: cleanup
    image: quay.io/openshift/origin-cli:latest
    command: ["/bin/bash", "-c"]
    args:
    - |
      oc delete secret keycloak-client-secret keycloak-db-secret -n {{ include "keycloak.namespace" . }} --ignore-not-found
      oc delete keycloakrealmimport peoplemesh-realm -n {{ include "keycloak.namespace" . }} --ignore-not-found
```

### Health Probes Using pg_isready

Both liveness and readiness probes use `pg_isready` with credentials from environment variables. The liveness probe has a longer initial delay (30s) to allow PostgreSQL startup, while readiness starts checking after 5s.

```yaml
# charts/keycloak/templates/postgres-statefulset.yaml
livenessProbe:
  exec:
    command: ["/bin/sh", "-c", "pg_isready -U $POSTGRESQL_USER -d $POSTGRESQL_DATABASE"]
  initialDelaySeconds: 30
  periodSeconds: 10
  failureThreshold: 6
readinessProbe:
  exec:
    command: ["/bin/sh", "-c", "pg_isready -U $POSTGRESQL_USER -d $POSTGRESQL_DATABASE"]
  initialDelaySeconds: 5
  periodSeconds: 5
  failureThreshold: 3
```

## Configuration

- **Environment variables:**
  - `POSTGRESQL_USER` -- database user, injected from `keycloak-db-secret` via `secretKeyRef`
  - `POSTGRESQL_PASSWORD` -- database password, injected from `keycloak-db-secret` via `secretKeyRef`
  - `POSTGRESQL_DATABASE` -- database name, set directly from `.Values.postgres.database` (default: `keycloak`)
  - `PGDATA` -- data directory path, set to `/var/lib/pgsql/data`
- **Helm values:**
  - `postgres.user` -- PostgreSQL username (default: `keycloak`)
  - `postgres.password` -- PostgreSQL password (REQUIRED, no default)
  - `postgres.database` -- database name (default: `keycloak`)
  - `postgres.image.repository` / `postgres.image.tag` -- container image (default: `quay.io/rh-aiservices-bu/postgresql-15-pgvector-c9s:latest`)
  - `postgres.service.name` -- ClusterIP service name (default: `keycloak-postgres-db`)
  - `postgres.service.port` -- service port (default: `5432`)
  - `postgres.resources` -- resource requests/limits (512Mi-2Gi memory, 250m-1000m CPU)
  - `postgres.persistence.size` -- PVC size (default: `10Gi`)
  - `postgres.persistence.storageClass` -- optional storage class override (empty = cluster default)

## Known Gotchas

- The `postgres.password` value has no default and is enforced via Helm `required` function. Installation fails without providing it via `--set keycloak.postgres.password="$(openssl rand -base64 24)"` as noted in the values.yaml comment.
- The volumeMount path (`/data`) does not match the PGDATA path (`/var/lib/pgsql/data`). The Red Hat `postgresql-15-pgvector-c9s` image uses `/var/lib/pgsql/data` as its internal data directory; the PVC mount at `/data` is a separate mount point. The image's entrypoint is responsible for directing data to the correct location.
- The `helm.sh/hook-delete-policy: before-hook-creation` on the postgres-secret means the Secret is deleted and recreated on every `helm upgrade`. The `lookup` function in `_helpers.tpl` reads the existing secret's password before deletion to maintain continuity, but there is a brief window during upgrade where the secret does not exist.
- The cleanup hook uses `quay.io/openshift/origin-cli:latest` which requires the image to be accessible from the cluster. Air-gapped environments need to mirror this image.
- The Keycloak database is completely separate from the application's pgvector database. Both use the same container image (`postgresql-15-pgvector-c9s`) but serve different purposes -- changing one does not affect the other.

## Testing Notes

- Verify the StatefulSet pod reaches Running state and passes readiness checks: `oc get statefulset keycloak-postgres-db`
- Confirm the Keycloak CR reaches `Ready` status, which depends on successful database connectivity
- Check the `keycloak-db-secret` exists and contains valid credentials: `oc get secret keycloak-db-secret -o jsonpath='{.data.username}' | base64 -d`
- After uninstall, verify the cleanup hook removed `keycloak-client-secret`, `keycloak-db-secret`, and the `peoplemesh-realm` KeycloakRealmImport

## Related Patterns

- See `keycloak.md` for the full Keycloak deployment patterns (Approach A: CNPG operator, Approach B: raw container with H2)
- See `pgvector.md` for the application-level PostgreSQL database using the same base image
- See `postgresql.md` for an alternative PostgreSQL deployment using Deployment (not StatefulSet) with a separate PVC
