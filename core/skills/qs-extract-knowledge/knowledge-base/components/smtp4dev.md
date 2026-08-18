---
name: smtp4dev
description: "smtp4dev test SMTP server for email notification development and E2E testing in AI Quickstarts"
summary: "smtp4dev (`rnwood/smtp4dev:v3`, .NET-based) provides a fake SMTP server that captures outgoing emails without delivery for development and E2E testing of notification features in RHOAI quickstarts, with a web UI for inspecting messages and health checks on the `/` path at 10-second intervals. Deploy when building email notification flows needing local/CI email capture without a real mail server — toggle on via Helm `smtp4dev.enabled` flag for dev/test (gating deployment, service, and TLS-edge-terminated Route templates) and off for production; locally use podman-compose with the web UI on port 3002; in CI it starts alongside postgres and keycloak in GitHub Actions E2E runs. The container runs SMTP on port 2525 and web UI on 8080 (avoiding privileged ports under OpenShift restricted SCCs) while the Service maps these to 25/80; the FastAPI backend connects via `SMTP_HOST=smtp4dev`, `SMTP_PORT=25`, empty credentials to skip `smtplib` auth, and `SMTP_USE_TLS=false`. Port-forwarding requires container ports 2525/8080 not Service ports 25/80; `emptyDir` storage loses captured emails on pod restart; `config.py` defaults `SMTP_PORT` to 8025 but Helm overrides to 25 causing confusion in bare local dev; IMAP/POP3 are disabled via empty `--imapport=`/`--pop3port=` args; `ServerOptions__HostName` must be set in the deployment template."
metadata:
  type: component
tags:
  tech_stack: [smtp4dev, smtp, email]
  platform: [openshift, kubernetes]
source_examples:
  - quickstart: "spending-transaction-monitor"
    repo: "https://github.com/rh-ai-quickstart/spending-transaction-monitor"
    notes: "smtp4dev as a toggleable test SMTP server with Helm deployment, OpenShift Route, and podman-compose for local dev"
    approach: "A"
---

# smtp4dev

## Overview

smtp4dev is a lightweight fake SMTP server used as a drop-in email testing tool in AI Quickstarts. It captures outgoing emails without delivering them, providing a web UI to inspect messages during development and E2E testing. In RHOAI quickstarts, it is deployed as a toggleable component via Helm with an OpenShift Route for web UI access.

## Tech Stack & Dependencies
- **Runtime:** .NET-based container (`rnwood/smtp4dev`)
- **Container image:** `rnwood/smtp4dev:v3` (Helm), `docker.io/rnwood/smtp4dev:latest` (podman-compose)
- **Key dependencies:** None (standalone service); consumed by the FastAPI backend via Python `smtplib`
- **Helm subchart:** Standalone templates within the parent chart (not a separate subchart)

## Key Patterns

### Toggleable Deployment via Helm Flag

smtp4dev is gated behind an `enabled` flag so it can be included for testing and disabled in production. The deployment, service, and route templates all check this flag.

```yaml
# deploy/helm/spending-monitor/values.yaml
smtp4dev:
  enabled: true  # Set to true to deploy smtp4dev for testing
  name: smtp4dev
  image:
    repository: rnwood/smtp4dev
    tag: "v3"
  service:
    type: ClusterIP
    smtpPort: 25
    webPort: 80
```

### Non-Standard Port Mapping on OpenShift

The container runs SMTP on port 2525 (via `--smtpport=2525` arg) while the Service exposes port 25 externally. This avoids binding to privileged port 25 inside the container, which is required under OpenShift restricted SCCs.

```yaml
# deploy/helm/spending-monitor/templates/smtp4dev-deployment.yaml
containers:
- name: smtp4dev
  args:
  - "--smtpport=2525"
  - "--urls=http://+:8080"
  - "--imapport="
  - "--pop3port="
  ports:
  - name: smtp
    containerPort: 2525
    protocol: TCP
  - name: web
    containerPort: 8080
    protocol: TCP
```

```yaml
# deploy/helm/spending-monitor/templates/smtp4dev-service.yaml
ports:
- name: smtp
  port: 25
  targetPort: smtp
  protocol: TCP
- name: web
  port: 80
  targetPort: web
  protocol: TCP
```

### OpenShift Route for Web UI

An OpenShift Route is provisioned (also toggleable) to expose the smtp4dev web UI for inspecting captured emails during testing.

```yaml
# deploy/helm/spending-monitor/templates/smtp4dev-route.yaml
{{- if and .Values.smtp4dev.enabled .Values.smtp4dev.route.enabled }}
apiVersion: route.openshift.io/v1
kind: Route
spec:
  tls:
    termination: edge
    insecureEdgeTerminationPolicy: Redirect
  to:
    kind: Service
    name: {{ .Values.smtp4dev.name }}
  port:
    targetPort: web
{{- end }}
```

### Backend Integration via Environment Variables

The FastAPI backend connects to smtp4dev using standard SMTP environment variables. When smtp4dev is deployed, the host is set to the Kubernetes service name `smtp4dev` and TLS/authentication are disabled.

```yaml
# deploy/helm/spending-monitor/values.yaml (env section)
SMTP_HOST: "smtp4dev"
SMTP_PORT: "25"
SMTP_USERNAME: ""
SMTP_PASSWORD: ""
SMTP_FROM_EMAIL: "spending-monitor@localhost"
SMTP_USE_TLS: "false"
SMTP_USE_SSL: "false"
```

The backend's SMTP service skips authentication when credentials are empty, which is the expected path for smtp4dev:

```python
# packages/api/src/services/notifications/smtp.py
if settings.SMTP_USERNAME and settings.SMTP_PASSWORD:
    server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
```

### Local Development with podman-compose

For local development, smtp4dev is run via podman-compose with the web UI exposed on port 3002.

```yaml
# podman-compose.yml
smtp4dev:
  image: docker.io/rnwood/smtp4dev:latest
  container_name: spending-monitor-smtp
  ports:
    - "3002:80"   # Web UI
    - "2525:25"
```

### E2E Testing in CI

smtp4dev is started as one of the infrastructure services during E2E test runs in GitHub Actions:

```yaml
# .github/workflows/coverage-e2e.yml
docker compose -p spending-transaction-monitor -f podman-compose.yml up -d postgres keycloak smtp4dev
```

## Configuration
- **Environment variables:**
  - `SMTP_HOST` — hostname of the SMTP server (set to `smtp4dev` when using the test server)
  - `SMTP_PORT` — SMTP port (`25` for smtp4dev service, maps to container port `2525`)
  - `SMTP_USERNAME` / `SMTP_PASSWORD` — left empty for smtp4dev, set for production
  - `SMTP_FROM_EMAIL` — sender address (`spending-monitor@localhost` for testing)
  - `SMTP_REPLY_TO_EMAIL` — reply-to address
  - `SMTP_USE_TLS` / `SMTP_USE_SSL` — both `false` for smtp4dev, `true` for production
- **Config files:** Pydantic `Settings` class at `packages/api/src/core/config.py` defines SMTP defaults
- **Helm values:** `smtp4dev.enabled`, `smtp4dev.image`, `smtp4dev.service`, `smtp4dev.resources`, `smtp4dev.route`, `smtp4dev.healthCheck`

## Known Gotchas
- The container listens on port 2525 for SMTP and 8080 for the web UI, but the Service maps these to ports 25 and 80 respectively. Connecting directly to the container (e.g., via port-forward) requires using ports 2525/8080, not 25/80.
- IMAP and POP3 are explicitly disabled via empty `--imapport=` and `--pop3port=` args in the Helm deployment to reduce the container's surface area.
- The Helm deployment uses `emptyDir` for storage, meaning captured emails are lost on pod restart. This is intentional for a test tool.
- The `ServerOptions__HostName` env var is set to `smtp4dev` in the deployment template to ensure the SMTP banner identifies correctly.
- The backend defaults `SMTP_PORT` to `8025` in `config.py` but the Helm values override it to `25` — direct local development without podman-compose needs the port explicitly set.

## Testing Notes
- After deployment, access the smtp4dev web UI via the OpenShift Route (or `localhost:3002` in local dev) to verify it is running
- Send a test email through the API and confirm it appears in the smtp4dev web UI
- Health checks use HTTP GET on the web UI port (`/` path) with 10-second intervals

## Related Patterns
- Backend SMTP integration: `fastapi-backend.md`
- Notification system uses Keycloak-authenticated users: `keycloak.md`
