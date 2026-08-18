---
name: pgadmin
description: "pgAdmin 4 web UI for PostgreSQL database administration, deployed as optional Helm subchart on OpenShift"
summary: "pgAdmin 4 (dpage/pgadmin4:latest) provides an optional web UI for inspecting pgvector/PostgreSQL databases in quickstart architectures, deployed as a standalone Helm subchart with a TLS-terminated OpenShift Route (edge termination, insecure redirect). Use when developers need to browse pgvector data during development and debugging — gated behind DEPLOY_PGADMIN=false Makefile flag to exclude from production; requires privileged SCC pre-granted to a dedicated service account because the container needs allowPrivilegeEscalation: true, runAsUser: 5050, fsGroup: 5050. Critical config: servers.json ConfigMap auto-configures the pgvector connection via StatefulSet headless DNS (pgvector-0.pgvector-postgres-service), PGADMIN_CONFIG_SERVER_MODE and PGADMIN_CONFIG_MASTER_PASSWORD_REQUIRED set to \"False\" to bypass multi-user login, credentials from Secrets validated by check-pgadmin-credentials Makefile target before Helm install. Pod fails to start without the privileged SCC grant, postgres.host default couples to the pgvector chart's StatefulSet naming convention, pgadmin-data PVC (1Gi RWO at /var/lib/pgadmin) must be explicitly deleted on uninstall to avoid orphaned storage, and health checks use /misc/ping with 30s liveness initial delay."
metadata:
  type: component
tags:
  tech_stack: [pgadmin, postgresql]
  ai_pattern: []
  platform: [openshift, helm]
  data_layer: [pgvector, postgresql]
source_examples:
  - quickstart: "data-governance-co-pilot"
    repo: "https://github.com/rh-ai-quickstart/data-governance-co-pilot"
    notes: "Optional pgAdmin 4 deployment for inspecting pgvector database, requires anyuid/privileged SCC"
    approach: "A"
---

# pgAdmin

## Overview

pgAdmin 4 is a web-based administration tool for PostgreSQL databases. In quickstart architectures it serves as an optional monitoring/inspection component that provides a UI for examining the underlying pgvector or PostgreSQL database. It is deployed as a standalone Helm subchart with an OpenShift Route for browser access.

## Tech Stack & Dependencies

- **Runtime:** pgAdmin 4 (Python-based web application)
- **Container image:** `dpage/pgadmin4:latest`
- **Key dependencies:** PostgreSQL-compatible database (pgvector StatefulSet), OpenShift Route for external access
- **Helm subchart:** Standalone chart at `helm/pgadmin/` (Chart.yaml v1.0.0, appVersion 8.0)

## Key Patterns

### Optional Deployment via Makefile Flag

pgAdmin is gated behind a `DEPLOY_PGADMIN` flag (default `false`) in the Makefile. This keeps it out of production deployments while available for development and debugging.

```makefile
# Flag to control whether to deploy pgAdmin (default: false)
DEPLOY_PGADMIN ?= false

# Conditional installation during main install target
ifeq ($(DEPLOY_PGADMIN),true)
	@$(MAKE) check-pgadmin-credentials
endif
ifeq ($(DEPLOY_PGADMIN),true)
	@$(MAKE) pgadmin-install NAMESPACE=$(NAMESPACE)
else
	@echo "Skipping pgAdmin installation (DEPLOY_PGADMIN=$(DEPLOY_PGADMIN))"
endif
```

### Pre-created Service Account with Privileged SCC

The Makefile pre-creates a dedicated service account and grants the `privileged` SCC before Helm install, because the pgAdmin container requires `allowPrivilegeEscalation: true` and `runAsUser: 5050`.

```makefile
pgadmin-install:
	@echo "Pre-creating pgadmin service account and granting privileged SCC..."
	@oc create serviceaccount pgadmin -n $(NAMESPACE) 2>/dev/null || echo "ServiceAccount already exists"
	@oc adm policy add-scc-to-user privileged -z pgadmin -n $(NAMESPACE) 2>/dev/null || echo "SCC already granted"
```

The deployment references this service account and sets the required security context:

```yaml
spec:
  template:
    spec:
      serviceAccountName: pgadmin
      securityContext:
        fsGroup: 5050
      containers:
        - name: pgadmin
          securityContext:
            allowPrivilegeEscalation: true
            runAsUser: 5050
```

### Pre-configured Server Connection via ConfigMap

A `servers.json` file is mounted into pgAdmin via ConfigMap, so the pgvector database appears automatically in the UI without manual setup. The host is constructed as a fully-qualified in-cluster DNS name.

```yaml
servers.json: |
  {
    "Servers": {
      "1": {
        "Name": "PGVector Database",
        "Group": "Servers",
        "Host": "{{ .Values.postgres.host }}.{{ .Release.Namespace }}.svc.cluster.local",
        "Port": {{ .Values.postgres.port }},
        "MaintenanceDB": "postgres",
        "Username": "{{ .Values.postgres.user }}",
        "SSLMode": "prefer"
      }
    }
  }
```

### Server Mode Disabled for Simplified Login

The deployment sets `PGADMIN_CONFIG_SERVER_MODE` to `"False"` and `PGADMIN_CONFIG_MASTER_PASSWORD_REQUIRED` to `"False"`, which bypasses the multi-user login screen and master password prompt. This simplifies the quickstart experience at the cost of multi-user support.

```yaml
env:
  - name: PGADMIN_CONFIG_SERVER_MODE
    value: "False"
  - name: PGADMIN_CONFIG_MASTER_PASSWORD_REQUIRED
    value: "False"
```

### TLS-terminated OpenShift Route

Access is exposed via an OpenShift Route with edge TLS termination and redirect for insecure traffic.

```yaml
apiVersion: route.openshift.io/v1
kind: Route
spec:
  to:
    kind: Service
    name: pgadmin-service
  port:
    targetPort: http
  tls:
    termination: edge
    insecureEdgeTerminationPolicy: Redirect
```

## Configuration

- **Environment variables:**
  - `PGADMIN_DEFAULT_EMAIL` -- Login email, sourced from Secret (set via `pgadmin.email` Helm value)
  - `PGADMIN_DEFAULT_PASSWORD` -- Login password, sourced from Secret (set via `pgadmin.password` Helm value)
  - `PGADMIN_CONFIG_SERVER_MODE` -- Set to `"False"` to disable multi-user mode
  - `PGADMIN_CONFIG_MASTER_PASSWORD_REQUIRED` -- Set to `"False"` to skip master password prompt
- **Config files:** `servers.json` mounted at `/pgadmin4/servers.json` via ConfigMap (auto-configures database connection)
- **Helm values:**
  - `pgadmin.email` / `pgadmin.password` -- pgAdmin login credentials (required)
  - `postgres.host` / `postgres.port` / `postgres.user` / `postgres.password` / `postgres.database` -- PostgreSQL connection details, passed from Makefile
  - `storage.size` -- PVC size for pgAdmin data (default `1Gi`)

## Known Gotchas

- **Privileged SCC required:** pgAdmin's container requires `allowPrivilegeEscalation: true` and `runAsUser: 5050` with `fsGroup: 5050`. The Makefile pre-creates a service account and grants the `privileged` SCC before Helm install. Without this, the pod will fail to start on OpenShift due to restricted SCC policies.
- **Credential validation in Makefile:** The `check-pgadmin-credentials` target validates that `pgadmin.email` and `pgadmin.password` are set before installation proceeds, preventing cryptic Helm errors from missing values.
- **Persistent storage for settings:** pgAdmin data is stored on a PVC (`pgadmin-data`, 1Gi RWO) mounted at `/var/lib/pgadmin`. The uninstall target explicitly cleans up this PVC to avoid orphaned storage.
- **postgres.host points to StatefulSet pod DNS:** The default host `pgvector-0.pgvector-postgres-service` is the headless service DNS for a StatefulSet pod. This couples the pgAdmin config to the pgvector chart's naming convention.

## Testing Notes

- After deployment, the Makefile waits for rollout status and route admission before printing the access URL
- Health checks use `/misc/ping` endpoint (liveness at 30s initial delay, readiness at 10s)
- Login credentials are the `pgadmin.email` and `pgadmin.password` values passed during install
- The pre-configured pgvector server should appear automatically in the left panel without manual setup

## Related Patterns

- `components/pgvector.md` -- The PostgreSQL/pgvector database that pgAdmin connects to
- `components/minio.md` -- Another optional infrastructure component in the same quickstart
