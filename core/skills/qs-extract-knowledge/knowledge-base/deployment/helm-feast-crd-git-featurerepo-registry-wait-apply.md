---
name: helm-feast-crd-git-featurerepo-registry-wait-apply
description: Feast FeatureStore CRD with git-based feature repo, registry TLS secret, and apply-job waiting for registry health
summary: "Deploys Feast on OpenShift via the FeatureStore CRD with a Git-sourced feature repo (feastProjectDir.git with featureRepoPath to a subdirectory), configuring DuckDB offline, PostgreSQL online, and SQL registry stores through a feast-data-stores Secret whose ${variable} placeholders are resolved at runtime by the Feast operator via envFrom from the pgvector subchart Secret, not by Helm. Use when deploying Feast with the operator CRD pattern where feature definitions live in a Git repository and online/registry stores need PostgreSQL persistence; downstream resources (db-init Job, KFP pipeline runner) depend on the feast-apply-job completing successfully. Critical pattern: a feast-apply-job uses an initContainer curl -ksf health-check loop against the registry in-cluster DNS URL (constructed in _helpers.tpl as feast.registry.namespace.svc.cluster.local) before running feast apply with a mounted TLS secret, configured via Helm values feast.project, feast.secret, and feast.registry with serviceAccountName feast-feast-recommendation. Gotchas: Git URL and ref are hardcoded to upstream main branch so forks/branch deploys still pull upstream feature definitions, the initContainer health check skips TLS verification (-ksf flags) while feast apply requires the mounted TLS cert, ${variable} syntax in the Secret is Feast-operator-resolved not Helm-resolved, and MPLCONFIGDIR=/tmp must be set on Feast pods to avoid matplotlib read-only filesystem errors."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, postgresql]
  ai_pattern: [recommendation, data-pipeline]
  platform: [rhoai, openshift]
  data_layer: [pgvector]
source_examples:
  - quickstart: "product-recommender-system"
    repo: "https://github.com/rh-ai-quickstart/product-recommender-system"
    notes: "Feast FeatureStore CRD with git-sourced feature repo, PostgreSQL online/registry stores, and feast-apply-job with registry health initContainer"
    approach: "A"
---

# Feast FeatureStore CRD with Git Feature Repo and Apply Job

## Overview

Deploys a Feast feature store on OpenShift using the Feast operator's `FeatureStore` CRD, with the feature repo sourced from a Git repository. A companion Job runs `feast apply` after waiting for the Feast registry service to become healthy, with TLS certificate mounting for secure registry communication.

## Pattern Description

The template creates three resources: a `feast-data-stores` Secret containing PostgreSQL connection strings for the online store and registry, a `FeatureStore` CRD that configures offline (DuckDB), online (PostgreSQL), and registry (SQL) stores with a Git-sourced feature repo, and a `feast-apply-job` Job that runs `feast apply` after verifying registry health via an initContainer curl check. The feature repo path points to a specific directory in the Git repository.

## Implementation

### Feast Data Stores Secret

```yaml
# helm/product-recommender-system/templates/featurestore.yaml
apiVersion: v1
kind: Secret
metadata:
  name: feast-data-stores
stringData:
  sql: |
    path: postgresql+psycopg://${user}:${password}@${host}:${port}/${dbname}
    cache_ttl_seconds: 60
    sqlalchemy_config_kwargs:
        echo: false
        pool_pre_ping: true
  postgres: |
    host: ${host}
    port: 5432
    database: ${dbname}
    db_schema: public
    user: ${user}
    password: ${password}
```

### FeatureStore CRD with Git Source

```yaml
apiVersion: feast.dev/v1alpha1
kind: FeatureStore
metadata:
  name: feast-recommendation
spec:
  feastProject: {{ .Values.feast.project }}
  feastProjectDir:
    git:
      url: https://github.com/rh-ai-quickstart/product-recommender-system
      ref: main
      featureRepoPath: recommendation-core/src/recommendation_core/feature_repo
  services:
    offlineStore:
      persistence:
        file:
          type: duckdb
    onlineStore:
      persistence:
        store:
          type: postgres
          secretRef:
            name: feast-data-stores
    registry:
      local:
        persistence:
          store:
            type: sql
            secretRef:
              name: feast-data-stores
```

### Apply Job with Registry Health Wait

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: feast-apply-job
spec:
  template:
    spec:
      restartPolicy: Never
      initContainers:
        - name: wait-for-reg
          image: {{ .Values.applicationImage }}
          env:
          {{- include "product-recommender-system.feastEnv" . | nindent 10 }}
          command:
            - /bin/bash
            - -c
            - |
              set -e
              url="https://$FEAST_REGISTRY_URL/health"
              until curl -ksf "$url"; do
                echo "Still waiting for $url ..."
                sleep 10
              done
      containers:
        - name: feast-0
          image: {{ .Values.applicationImage }}
          command:
            - /bin/bash
            - -c
            - |
              export FEAST_PROJECT_NAME={{ .Values.feast.project }}
              cd /app/recommendation-core/src/recommendation_core/feature_repo/
              feast apply
          volumeMounts:
          - name: tls-secret
            mountPath: /app/feature_repo/secrets/tls.crt
            subPath: tls.crt
            readOnly: true
      volumes:
      - name: tls-secret
        secret:
          secretName: {{ .Values.feast.secret }}
      serviceAccountName: feast-feast-recommendation
```

### Feast Environment Helper Template

```yaml
# helm/product-recommender-system/templates/_helpers.tpl
{{- define "product-recommender-system.feastEnv" -}}
- name: FEAST_PROJECT_NAME
  value: {{ .Values.feast.project }}
- name: FEAST_SECRET_NAME
  value: {{ .Values.feast.secret }}
- name: FEAST_REGISTRY_URL
  value: {{ .Values.feast.registry }}.{{ .Release.Namespace }}.svc.cluster.local
{{- end }}
```

## Configuration

- **Key settings:** `feast.project` (Feast project name, default `feast_rec_sys`), `feast.secret` (TLS secret name for registry), `feast.registry` (registry service name for DNS construction)
- **Defaults:** Offline store uses DuckDB (file-based), online store and registry use PostgreSQL via `feast-data-stores` Secret
- **Dependencies:** PostgreSQL (pgvector subchart) must be running, Feast operator must be installed, `applicationImage` must contain the `feast` CLI and feature repo files

## Gotchas

- The Git URL in the FeatureStore CRD is hardcoded to `https://github.com/rh-ai-quickstart/product-recommender-system` with `ref: main`, so forks or branch deployments will still pull feature definitions from the main branch of the upstream repo.
- The `feast-data-stores` Secret uses `${variable}` placeholder syntax in its stringData, which are resolved by the Feast operator at runtime using values from the `pgvector` Secret (via `envFrom` on the Feast service pods), not by Helm templating.
- The registry URL is constructed via `{{ .Values.feast.registry }}.{{ .Release.Namespace }}.svc.cluster.local` in the helper template, using in-cluster DNS.
- The apply job uses `-ksf` flags on curl (insecure, silent, fail-on-error), skipping TLS verification for the health check while still mounting the TLS certificate for the `feast apply` command itself.
- `MPLCONFIGDIR=/tmp` is set on multiple Feast service pods to redirect matplotlib config writes to a writable directory.

## Related Patterns

- `helm-hook-initcontainer-psql-table-existence-poll.md` — the db-init Job that depends on training pipeline completion, which in turn depends on this feast-apply-job
- `helm-lookup-guard-job-cronjob-shared-define-template.md` — the KFP pipeline runner that waits for feast-apply-job completion
