---
name: helm-keycloak-realm-files-get-configmap-dev-mode
description: Keycloak deployed via start-dev with realm JSON embedded in ConfigMap using .Files.Get, KC_PROXY_HEADERS for OpenShift Routes
summary: "Deploys Keycloak 26.0 (quay.io/keycloak/keycloak:26.0) in start-dev mode as a Helm Deployment, embedding realm JSON into a ConfigMap via .Files.Get and auto-importing at startup with --import-realm for dev/demo OpenShift environments. Use as a simpler operator-free alternative to the RHBK operator with KeycloakRealmImport CRD (helm-keycloak-openshift-oauth-patch-realmimport); admin credentials come from SecretKeyRef (KC_BOOTSTRAP_ADMIN_USERNAME/PASSWORD), KC_PROXY_HEADERS=xforwarded handles OpenShift Route headers, and KEYCLOAK_ISSUER auto-generates from the keycloak-prefixed sharedHost Route when keycloak.enabled + routes.enabled + routes.sharedHost are all set. Realm JSON must reside in the chart's files/ directory (mounted to /opt/keycloak/data/import, not configurable via values); health probes target port 9000 at /health/ready with failureThreshold: 12 (~2 min startup); resources request 512Mi/250m, limit 1536Mi/1000m. start-dev disables HTTPS (relies on Route edge TLS termination), .Files.Get bundles realm at chart-build time requiring repackaging for changes, and --import-realm re-imports on every pod restart resetting manual admin console modifications."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  ai_pattern: []
  platform: [openshift]
source_examples:
  - quickstart: "multi-agent-loan-origination"
    repo: "https://github.com/rh-ai-quickstart/multi-agent-loan-origination"
    notes: "Keycloak 26.0 in start-dev mode with realm JSON embedded via .Files.Get, KC_PROXY_HEADERS=xforwarded for OpenShift Routes, health on port 9000"
    approach: "A"
---

# Keycloak Dev-Mode Deployment with .Files.Get Realm Import

## Overview

This pattern deploys Keycloak 26.0 in development mode (`start-dev`) within a Helm chart, embedding the realm configuration JSON into a ConfigMap using Helm's `.Files.Get` function. The realm is auto-imported on startup via the `--import-realm` flag, and `KC_PROXY_HEADERS=xforwarded` enables proper header handling behind OpenShift Routes.

## Pattern Description

Rather than using the RHBK operator and `KeycloakRealmImport` CRD (as in the `helm-keycloak-openshift-oauth-patch-realmimport` pattern), this approach deploys Keycloak as a simple Deployment with a community image. The realm JSON file is stored in the chart's `files/` directory and embedded into a ConfigMap using `.Files.Get`, then mounted into the Keycloak container at the import path. This is simpler and operator-free, suitable for dev/demo environments.

## Implementation

### ConfigMap with Embedded Realm JSON

```yaml
# deploy/helm/mortgage-ai/templates/keycloak.yaml (excerpt)
{{- if .Values.keycloak.enabled }}
apiVersion: v1
kind: ConfigMap
metadata:
  name: {{ .Values.keycloak.name }}-realm
data:
  mortgage-ai-realm.json: |
    {{- .Files.Get "files/mortgage-ai-realm.json" | nindent 4 }}
```

### Keycloak Deployment with Realm Import

```yaml
# deploy/helm/mortgage-ai/templates/keycloak.yaml (excerpt)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Values.keycloak.name }}
spec:
  replicas: 1
  template:
    spec:
      containers:
        - name: keycloak
          image: "quay.io/keycloak/keycloak:26.0"
          args:
            - start-dev
            - --import-realm
          ports:
            - name: http
              containerPort: 8080
            - name: health
              containerPort: 9000
          env:
            - name: KC_BOOTSTRAP_ADMIN_USERNAME
              valueFrom:
                secretKeyRef:
                  name: {{ include "mortgage-ai.fullname" . }}-secret
                  key: KC_BOOTSTRAP_ADMIN_USERNAME
            - name: KC_BOOTSTRAP_ADMIN_PASSWORD
              valueFrom:
                secretKeyRef:
                  name: {{ include "mortgage-ai.fullname" . }}-secret
                  key: KC_BOOTSTRAP_ADMIN_PASSWORD
            - name: KC_HEALTH_ENABLED
              value: "true"
            - name: KC_PROXY_HEADERS
              value: "xforwarded"
            - name: KC_HTTP_ENABLED
              value: "true"
          volumeMounts:
            - name: realm-config
              mountPath: /opt/keycloak/data/import
              readOnly: true
          livenessProbe:
            httpGet:
              path: /health/ready
              port: 9000
            initialDelaySeconds: 30
            failureThreshold: 12
      volumes:
        - name: realm-config
          configMap:
            name: {{ .Values.keycloak.name }}-realm
```

### Auto-Generated KEYCLOAK_ISSUER in Secret

The Secret template auto-generates the Keycloak issuer URL from the Route hostname:

```yaml
# deploy/helm/mortgage-ai/templates/secret.yaml (excerpt)
{{- $kcIssuer := .Values.secrets.KEYCLOAK_ISSUER }}
{{- if and (not $kcIssuer) .Values.keycloak.enabled .Values.routes.enabled .Values.routes.sharedHost }}
{{- $kcIssuer = printf "https://keycloak-%s" .Values.routes.sharedHost }}
{{- end }}
KEYCLOAK_ISSUER: {{ $kcIssuer | toString | b64enc | quote }}
```

## Configuration

- **Key settings:** `keycloak.enabled` (default: true) toggles the entire Keycloak stack; the realm JSON file must exist at `deploy/helm/mortgage-ai/files/mortgage-ai-realm.json`; `KC_PROXY_HEADERS=xforwarded` enables X-Forwarded-* header processing behind the OpenShift Route
- **Defaults:** Keycloak 26.0; admin credentials from Secret; health check on port 9000 (separate from HTTP port 8080); resources request 512Mi/250m, limit 1536Mi/1000m
- **Dependencies:** The realm JSON file in `files/` directory must be valid JSON; the Route for Keycloak uses a `keycloak-` prefixed hostname (see `helm-openshift-routes-shared-host-path-multiplexing`)

## Gotchas

- The `start-dev` mode disables HTTPS and enables development features -- this is appropriate for demos and local dev but not production; Keycloak's HTTP is terminated at the OpenShift Route with edge TLS (see `deploy/helm/mortgage-ai/templates/keycloak.yaml` line 39)
- The `.Files.Get` function reads from the chart's `files/` directory, not the template -- the realm JSON must be packaged with the chart; it is not configurable via values (see `deploy/helm/mortgage-ai/templates/keycloak.yaml` line 9-10)
- Keycloak health is on port 9000 (not 8080) -- the liveness and readiness probes target `/health/ready` on the health port, with `failureThreshold: 12` and `periodSeconds: 10` giving Keycloak up to 2 minutes of startup time (see `deploy/helm/mortgage-ai/templates/keycloak.yaml` lines 68-76)
- The KEYCLOAK_ISSUER auto-generation logic uses the `keycloak-` prefixed shared host only when all three conditions are met: no explicit issuer, keycloak enabled, and routes with sharedHost configured -- this prevents incorrect issuer URLs when Keycloak is external (see `deploy/helm/mortgage-ai/templates/secret.yaml` lines 25-28)
- The realm JSON import is not idempotent in all cases -- `start-dev --import-realm` re-imports on every restart which may reset manual realm changes made via the admin console (see Keycloak documentation)

## Related Patterns

- `helm-keycloak-openshift-oauth-patch-realmimport.md` -- operator-based Keycloak with RHBK, OAuth cluster patch, and KeycloakRealmImport CRD
- `helm-openshift-routes-shared-host-path-multiplexing.md` -- the Route pattern that provides the Keycloak hostname
