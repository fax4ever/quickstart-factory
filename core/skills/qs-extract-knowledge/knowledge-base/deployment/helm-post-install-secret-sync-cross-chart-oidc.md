---
name: helm-post-install-secret-sync-cross-chart-oidc
description: Helm post-install Job that syncs OIDC client secret from Keycloak subchart to app subchart via oc patch and triggers deployment restart
summary: "Solves cross-subchart OIDC credential synchronization in Helm umbrella charts where the Keycloak subchart creates keycloak-client-secret (clientSecret, issuerUrl) that the application subchart cannot reference at template render time because Helm renders all subchart templates before any resources exist. Use when an umbrella chart has a Keycloak subchart producing OIDC credentials consumed by an application subchart that needs those values in its own Secret — the app Secret template uses Helm lookup with placeholder fallback for first install while the post-install Job bridges the timing gap; pairs with helm-keycloak-rhbk-crd-subchart-oidc-autoconfig (source Secret) and helm-lookup-secret-idempotency-random-fallback (lookup pattern). The Job (hook-weight 5, before-hook-creation/hook-succeeded delete policy) runs ose-cli:latest, polls 60x2s for keycloak-client-secret in .Release.Namespace, extracts values via base64 -d, patches the app secret (name derived from .Values.applicationName) using oc patch --type=json with op: replace and base64 -w0 re-encoding, then triggers oc rollout restart — requires a ServiceAccount with RBAC for secrets get/list/patch and deployments get/patch. On first install lookup always returns nil so the sync Job is essential for patching real values; on helm upgrade lookup may succeed making the patch redundant but harmless; oc rollout restart adds 30-60s even if values are unchanged; Keycloak secret must be a regular resource (not a hook) so it persists for the Job to read; failed Jobs are preserved for debugging while before-hook-creation clears stale failures."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  ai_pattern: []
  platform: [openshift]
source_examples:
  - quickstart: "peoplemesh"
    repo: "https://github.com/rh-ai-quickstart/peoplemesh"
    notes: "Post-install Job waits for keycloak-client-secret, patches peoplemesh-secrets with OIDC values, restarts peoplemesh deployment to pick up new env vars"
    approach: "A"
---

# Helm Post-Install Secret Sync for Cross-Chart OIDC Coordination

## Overview

This pattern uses a Helm post-install/post-upgrade Job to synchronize OIDC credentials from one subchart (Keycloak) to another subchart (application) within the same umbrella chart release. The Job waits for the source Secret to appear, patches the target Secret with the OIDC values, and restarts the application deployment to pick up the new environment variables.

## Pattern Description

In a Helm umbrella chart, subcharts deploy independently and cannot directly reference each other's templates or values at render time. When the Keycloak subchart creates a `keycloak-client-secret` Secret (containing clientSecret and issuerUrl), the application subchart needs those values in its own Secret but cannot guarantee they exist during templating. The solution is a post-install Job that bridges the gap: it polls for the Keycloak secret, extracts the values, patches the application secret using `oc patch`, and performs a rolling restart.

## Implementation

### Secret Sync Job

```yaml
# charts/peoplemesh/templates/secrets-sync-job.yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ .Values.applicationName }}-secrets-sync
  annotations:
    "helm.sh/hook": post-install,post-upgrade
    "helm.sh/hook-weight": "5"
    "helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded
spec:
  template:
    spec:
      serviceAccountName: {{ .Values.applicationName }}-secrets-sync
      restartPolicy: Never
      containers:
        - name: sync-secrets
          image: registry.redhat.io/openshift4/ose-cli:latest
          command:
            - /bin/bash
            - -c
            - |
              set -e
              echo "Waiting for keycloak-client-secret to exist..."
              for i in {1..60}; do
                if oc get secret keycloak-client-secret -n {{ .Release.Namespace }} >/dev/null 2>&1; then
                  echo "Found keycloak-client-secret"
                  break
                fi
                echo "Waiting... ($i/60)"
                sleep 2
              done

              # Get values from keycloak-client-secret
              CLIENT_SECRET=$(oc get secret keycloak-client-secret -n {{ .Release.Namespace }} -o jsonpath='{.data.clientSecret}' | base64 -d)
              ISSUER_URL=$(oc get secret keycloak-client-secret -n {{ .Release.Namespace }} -o jsonpath='{.data.issuerUrl}' | base64 -d)

              # Patch the existing secret with OIDC values
              oc patch secret {{ .Values.applicationName }}-secrets -n {{ .Release.Namespace }} \
                --type='json' \
                -p="[
                  {\"op\":\"replace\",\"path\":\"/data/OIDC_KEYCLOAK_CLIENT_SECRET\",\"value\":\"$(echo -n "$CLIENT_SECRET" | base64 -w0)\"},
                  {\"op\":\"replace\",\"path\":\"/data/OIDC_KEYCLOAK_ISSUER_URL\",\"value\":\"$(echo -n "$ISSUER_URL" | base64 -w0)\"}
                ]"

              # Restart deployment to pick up new secrets
              oc rollout restart deployment/{{ .Values.applicationName }} -n {{ .Release.Namespace }}
```

### Placeholder Values in App Secret

The application Secret template uses a `lookup` to attempt to read the Keycloak client secret at template time, falling back to placeholder values if it does not yet exist:

```yaml
# charts/peoplemesh/templates/secrets.yaml (excerpt)
{{- $keycloakSecret := lookup "v1" "Secret" .Release.Namespace "keycloak-client-secret" }}
{{- if $keycloakSecret }}
OIDC_KEYCLOAK_CLIENT_SECRET: {{ index $keycloakSecret.data "clientSecret" | b64dec | quote }}
OIDC_KEYCLOAK_ISSUER_URL: {{ index $keycloakSecret.data "issuerUrl" | b64dec | quote }}
{{- else }}
# Fallback if keycloak-client-secret doesn't exist yet (first install, will be patched by sync job)
OIDC_KEYCLOAK_CLIENT_SECRET: "none"
OIDC_KEYCLOAK_ISSUER_URL: {{ include "peoplemesh.keycloakIssuerUrl" . | quote }}
{{- end }}
```

### RBAC for Secret Sync

```yaml
# charts/peoplemesh/templates/secrets-sync-rbac.yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: {{ .Values.applicationName }}-secrets-sync
rules:
  - apiGroups: [""]
    resources: ["secrets"]
    verbs: ["get", "list", "patch"]
  - apiGroups: ["apps"]
    resources: ["deployments"]
    verbs: ["get", "patch"]
```

## Configuration

- **Key settings:** The source Secret name (`keycloak-client-secret`) and the keys (`clientSecret`, `issuerUrl`) are hardcoded in the Job script; the target Secret name is derived from the application name
- **Defaults:** The Job polls for up to 120 seconds (60 iterations x 2 second sleep) for the source Secret to appear; uses JSON patch type (`--type='json'`) with `op: replace` semantics
- **Dependencies:** The Keycloak subchart must create `keycloak-client-secret` as a regular (non-hook) resource; `ose-cli:latest` image must be pullable from `registry.redhat.io`

## Gotchas

- On first install, Helm renders all subchart templates before any resources are created, so the `lookup` in the app Secret template will always return nil and use the placeholder values; the sync Job then patches in the real values after both subcharts finish deploying (see `charts/peoplemesh/templates/secrets.yaml` line 47 comment)
- On subsequent `helm upgrade`, the `lookup` may succeed (if the Secret already exists from the previous install), making the sync Job's patch redundant but harmless; the deployment restart still triggers regardless (see `charts/peoplemesh/templates/secrets-sync-job.yaml` line 56)
- The `before-hook-creation,hook-succeeded` delete policy means the Job is cleaned up on success but persists on failure for debugging; the `before-hook-creation` part ensures a failed Job from a previous run does not block the next attempt (see `charts/peoplemesh/templates/secrets-sync-job.yaml` line 10)
- The `oc rollout restart` triggers a pod replacement even if the Secret values have not changed; this adds 30-60 seconds to the install time but ensures the app always picks up the correct OIDC configuration (see `charts/peoplemesh/templates/secrets-sync-job.yaml` line 56)

## Related Patterns

- `helm-keycloak-rhbk-crd-subchart-oidc-autoconfig.md` -- the Keycloak subchart that creates the source Secret
- `helm-lookup-secret-idempotency-random-fallback.md` -- the lookup pattern used for the fallback in the app Secret
