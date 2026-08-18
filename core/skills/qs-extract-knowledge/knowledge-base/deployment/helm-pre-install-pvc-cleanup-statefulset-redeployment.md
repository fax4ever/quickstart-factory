---
name: helm-pre-install-pvc-cleanup-statefulset-redeployment
description: Helm pre-install hook Job that deletes leftover PVCs from previous StatefulSet installs to avoid name conflicts on re-deployment
summary: "Solves StatefulSet PVC name conflicts on Helm re-install — Kubernetes does not garbage-collect PVCs owned by deleted StatefulSets, so a pre-install hook Job (weight -30, backoffLimit 2) runs `oc delete pvc` with `--ignore-not-found=true` against hardcoded PVC names following the `<volumeClaimTemplate>-<statefulset>-<ordinal>` convention. Use in umbrella charts where StatefulSets (e.g., PostgreSQL, pgvector) create PVCs that persist after `helm uninstall`; the hook fires only on pre-install (not pre-upgrade) to preserve data during upgrades. RBAC resources (ServiceAccount, Role with get/list/delete on PVCs, RoleBinding) must use hook-weight -40 with `before-hook-creation` delete policy so they exist before the Job (-30) and are recreated cleanly on repeated install attempts; the Job uses `registry.redhat.io/openshift4/ose-cli:latest`. PVC names are hardcoded — if StatefulSet or volumeClaimTemplate names change, cleanup silently skips due to `--ignore-not-found=true` and stale PVCs remain causing the same conflict the hook was meant to prevent; the Job's `before-hook-creation,hook-succeeded` delete policies clean up successful runs but preserve failures for debugging."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  ai_pattern: []
  platform: [openshift]
source_examples:
  - quickstart: "peoplemesh"
    repo: "https://github.com/rh-ai-quickstart/peoplemesh"
    notes: "Pre-install hook Job at weight -30 deletes named PVCs (postgres-data-keycloak-postgres-db-0, pgvector-data-pgvector-0) with own RBAC (SA, Role, RoleBinding at weight -40), uses ose-cli:latest image"
    approach: "A"
---

# Helm Pre-Install PVC Cleanup for StatefulSet Re-Deployment

## Overview

This pattern uses a Helm pre-install hook Job to delete leftover PersistentVolumeClaims from previous installations. StatefulSet PVCs persist after `helm uninstall` because Kubernetes does not garbage-collect PVCs owned by deleted StatefulSets, and re-installing with the same StatefulSet names causes PVC name conflicts. The cleanup Job runs before the new install, removing stale PVCs to ensure a clean deployment.

## Pattern Description

When a StatefulSet is deleted (via `helm uninstall`), its PVCs remain in the namespace. If the user re-installs the same chart, the new StatefulSet attempts to create PVCs with the same names (`<template-name>-<statefulset-name>-0`), which fail because the old PVCs still exist and may contain stale data. This pre-install hook deletes the known PVC names before the new chart resources are created, using its own ServiceAccount/Role/RoleBinding to have `delete` permissions on PVCs.

## Implementation

### Pre-Install Cleanup Job

```yaml
# peoplemesh-umbrella/templates/cleanup-pvcs-job.yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ .Release.Name }}-cleanup-pvcs
  namespace: {{ .Release.Namespace }}
  annotations:
    # Run before install to clean up any leftover PVCs from previous installs
    "helm.sh/hook": pre-install
    "helm.sh/hook-weight": "-30"
    "helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded
spec:
  backoffLimit: 2
  template:
    spec:
      serviceAccountName: {{ .Release.Name }}-cleanup
      restartPolicy: Never
      containers:
        - name: cleanup
          image: registry.redhat.io/openshift4/ose-cli:latest
          command:
            - /bin/bash
            - -c
            - |
              set -e
              echo "Cleaning up old PVCs in namespace {{ .Release.Namespace }}..."
              oc delete pvc postgres-data-keycloak-postgres-db-0 -n {{ .Release.Namespace }} --ignore-not-found=true
              oc delete pvc pgvector-data-pgvector-0 -n {{ .Release.Namespace }} --ignore-not-found=true
              echo "PVC cleanup completed!"
```

### RBAC for Cleanup Job

```yaml
# peoplemesh-umbrella/templates/cleanup-rbac.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: {{ .Release.Name }}-cleanup
  annotations:
    "helm.sh/hook": pre-install
    "helm.sh/hook-weight": "-40"
    "helm.sh/hook-delete-policy": before-hook-creation
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: {{ .Release.Name }}-cleanup
  annotations:
    "helm.sh/hook": pre-install
    "helm.sh/hook-weight": "-40"
    "helm.sh/hook-delete-policy": before-hook-creation
rules:
  - apiGroups: [""]
    resources: ["persistentvolumeclaims"]
    verbs: ["get", "list", "delete"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: {{ .Release.Name }}-cleanup
  annotations:
    "helm.sh/hook": pre-install
    "helm.sh/hook-weight": "-40"
    "helm.sh/hook-delete-policy": before-hook-creation
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: {{ .Release.Name }}-cleanup
subjects:
  - kind: ServiceAccount
    name: {{ .Release.Name }}-cleanup
```

## Configuration

- **Key settings:** PVC names are hardcoded in the cleanup script based on the StatefulSet naming convention (`<volumeClaimTemplate-name>-<statefulset-name>-<ordinal>`); hook weights are set so RBAC (-40) is created before the Job (-30)
- **Defaults:** `backoffLimit: 2` retries the cleanup twice; `--ignore-not-found=true` makes the delete idempotent (succeeds even if PVCs do not exist)
- **Dependencies:** Requires the `ose-cli:latest` image from `registry.redhat.io`; the ServiceAccount must be created before the Job runs (ensured by hook-weight ordering)

## Gotchas

- The PVC names are hardcoded based on the convention `<volumeClaimTemplate-name>-<statefulset-name>-<ordinal>` -- if the StatefulSet or volumeClaimTemplate names change, the cleanup Job will silently do nothing because of `--ignore-not-found=true` and the stale PVCs will remain (see `peoplemesh-umbrella/templates/cleanup-pvcs-job.yaml` lines 35-36)
- The hook only triggers on `pre-install`, not `pre-upgrade` -- this is intentional because upgrades should preserve data; re-installs (after a full uninstall) are the scenario that needs PVC cleanup (see `peoplemesh-umbrella/templates/cleanup-pvcs-job.yaml` line 14)
- The `before-hook-creation` delete policy on the RBAC resources means they are deleted and recreated on each install attempt, which prevents conflicts from previous failed installs (see `peoplemesh-umbrella/templates/cleanup-rbac.yaml` annotations)
- The `before-hook-creation,hook-succeeded` policies on the Job mean: (1) any old cleanup Job is deleted before a new one is created, and (2) the Job is deleted after successful completion; failed Jobs persist for debugging (see `peoplemesh-umbrella/templates/cleanup-pvcs-job.yaml` line 16)

## Related Patterns

- `helm-umbrella-all-local-file-ref-conditional-deps.md` -- the umbrella chart that includes this cleanup hook
- `helm-pre-delete-cleanup-jobs-secrets-crds.md` -- the complementary pre-delete hooks that clean up secrets and CRDs
