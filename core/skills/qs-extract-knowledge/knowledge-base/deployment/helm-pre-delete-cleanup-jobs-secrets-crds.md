---
name: helm-pre-delete-cleanup-jobs-secrets-crds
description: Helm pre-delete hook Jobs that clean up hook-created secrets and operator CRDs that Helm cannot manage directly
summary: "Solves orphaned resource cleanup after helm uninstall for Secrets created by pre-install hooks (untracked by Helm due to before-hook-creation delete policy) and operator-managed CRDs like KeycloakRealmImport that Helm does not own. Use per-subchart pre-delete hook Jobs (not umbrella-level) when each subchart independently creates hook resources -- keycloak cleans keycloak-client-secret, keycloak-db-secret, and keycloakrealmimport CR; pgvector cleans pgvector-database secret -- each with dedicated SA/Role/RoleBinding for least-privilege RBAC. Critical config: helm.sh/hook: pre-delete with hook-weight \"-5\", hook-succeeded,hook-failed delete policy (ensures Job removal regardless of outcome), oc delete --ignore-not-found from quay.io/openshift/origin-cli:latest for idempotent cleanup, and hardcoded secret names matching the pre-install hook templates. Gotchas: Keycloak cleanup RBAC must include k8s.keycloak.org apiGroup for operator-managed keycloakrealmimports; multiple subcharts sharing the same applicationName cause SA/Role naming conflicts; registry.redhat.io image variant may require authentication; complements helm-lookup-secret-idempotency-random-fallback (creation) and helm-pre-install-pvc-cleanup (umbrella-level cleanup)."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  ai_pattern: []
  platform: [openshift]
source_examples:
  - quickstart: "peoplemesh"
    repo: "https://github.com/rh-ai-quickstart/peoplemesh"
    notes: "Pre-delete hooks in keycloak and pgvector subcharts clean up hook-created secrets (keycloak-client-secret, keycloak-db-secret, pgvector-database) and Keycloak CRDs (keycloakrealmimport) with own SA/Role/RoleBinding per subchart"
    approach: "A"
---

# Helm Pre-Delete Cleanup Jobs for Hook-Created Secrets and CRDs

## Overview

This pattern uses Helm pre-delete hook Jobs to clean up resources that Helm cannot manage directly during uninstall: secrets created by pre-install hooks (which are outside Helm's release tracking) and operator-managed CRDs (which Helm does not own). Each subchart that creates hook resources includes its own cleanup Job with dedicated RBAC.

## Pattern Description

When a Helm chart creates Secrets via `pre-install` hooks with `before-hook-creation` delete policy, these Secrets exist in the cluster but are not tracked as part of the Helm release. Running `helm uninstall` does not delete them. Similarly, Keycloak CRDs (`KeycloakRealmImport`) are created by the Keycloak Operator in response to Helm-created CRs, and Helm does not own them. Pre-delete hooks run before the uninstall, using `oc delete --ignore-not-found` to clean up these orphaned resources.

## Implementation

### Keycloak Pre-Delete Cleanup

```yaml
# charts/keycloak/templates/cleanup-secrets-hook.yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ .Values.applicationName }}-cleanup-secrets
  annotations:
    "helm.sh/hook": pre-delete
    "helm.sh/hook-weight": "-5"
    "helm.sh/hook-delete-policy": hook-succeeded,hook-failed
spec:
  template:
    spec:
      serviceAccountName: {{ .Values.applicationName }}-cleanup
      restartPolicy: Never
      containers:
      - name: cleanup
        image: quay.io/openshift/origin-cli:latest
        command:
        - /bin/bash
        - -c
        - |
          echo "Cleaning up Keycloak secrets and realm..."
          oc delete secret keycloak-client-secret keycloak-db-secret -n {{ include "keycloak.namespace" . }} --ignore-not-found
          oc delete keycloakrealmimport peoplemesh-realm -n {{ include "keycloak.namespace" . }} --ignore-not-found
          echo "Cleanup complete"
```

### Keycloak Cleanup RBAC

```yaml
# charts/keycloak/templates/cleanup-secrets-hook.yaml (continued)
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: {{ .Values.applicationName }}-cleanup
rules:
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get", "list", "delete"]
- apiGroups: ["k8s.keycloak.org"]
  resources: ["keycloakrealmimports"]
  verbs: ["get", "list", "delete"]
```

### PgVector Pre-Delete Cleanup

```yaml
# charts/pgvector/templates/cleanup-secrets-hook.yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ .Values.applicationName }}-cleanup-secrets
  annotations:
    "helm.sh/hook": pre-delete
    "helm.sh/hook-weight": "-5"
    "helm.sh/hook-delete-policy": hook-succeeded,hook-failed
spec:
  template:
    spec:
      serviceAccountName: {{ .Values.applicationName }}-cleanup
      restartPolicy: Never
      containers:
      - name: cleanup
        image: quay.io/openshift/origin-cli:latest
        command:
        - /bin/bash
        - -c
        - |
          echo "Cleaning up PgVector secrets..."
          oc delete secret pgvector-database -n {{ .Release.Namespace }} --ignore-not-found
          echo "Cleanup complete"
```

### PgVector Cleanup RBAC

```yaml
# charts/pgvector/templates/cleanup-secrets-hook.yaml (continued)
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: {{ .Values.applicationName }}-cleanup
rules:
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get", "list", "delete"]
```

## Configuration

- **Key settings:** Secret names are hardcoded in the cleanup scripts matching the names used by the pre-install hook templates; `--ignore-not-found` makes cleanup idempotent
- **Defaults:** `hook-succeeded,hook-failed` delete policy means cleanup Jobs are always removed after execution (regardless of outcome); each subchart has its own SA/Role/RoleBinding for least-privilege access
- **Dependencies:** The `quay.io/openshift/origin-cli:latest` image must be accessible; the ServiceAccount, Role, and RoleBinding are defined in the same template file as the Job

## Gotchas

- The Keycloak cleanup RBAC includes `k8s.keycloak.org` apiGroup permissions specifically for deleting `keycloakrealmimports` -- this is needed because the `KeycloakRealmImport` CR is created by the realm-import.yaml template but managed by the Keycloak Operator, and Helm does not track operator-managed resources (see `charts/keycloak/templates/cleanup-secrets-hook.yaml` rules)
- The `hook-succeeded,hook-failed` delete policy (compared to `before-hook-creation,hook-succeeded` used elsewhere) means the cleanup Job is always removed after running; this prevents accumulation of cleanup Jobs across multiple uninstall attempts (see `charts/keycloak/templates/cleanup-secrets-hook.yaml` line 8)
- Each subchart uses its own ServiceAccount named `<applicationName>-cleanup` -- if multiple subcharts share the same applicationName, the RBAC resources will conflict; in this chart they are differentiated as `keycloak-cleanup` and `pgvector-cleanup` (see templates)
- The Keycloak cleanup uses `quay.io/openshift/origin-cli:latest` while the PVC cleanup in the umbrella uses `registry.redhat.io/openshift4/ose-cli:latest` -- these are functionally equivalent but from different registries; the Red Hat registry may require authentication (see different template files)

## Related Patterns

- `helm-pre-install-pvc-cleanup-statefulset-redeployment.md` -- the complementary pre-install PVC cleanup at the umbrella level
- `helm-lookup-secret-idempotency-random-fallback.md` -- the secret creation pattern that produces the resources cleaned up here
