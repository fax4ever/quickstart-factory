---
name: helm-lookup-guard-job-cronjob-shared-define-template
description: Helm lookup guards idempotent Job and CronJob creation with shared define template and dual initContainer wait chain
summary: "Uses Helm `lookup` on `batch/v1` Job/CronJob to conditionally render `kfp-run-job` and `kfp-run-cronjob` only when absent, preventing `helm upgrade` conflicts, while sharing a single pod template via `define`/`include` in `_helpers.tpl` with `nindent` alignment. Use when deploying a Kubeflow pipeline runner as both one-shot Job and daily CronJob (`schedule: \"0 0 * * *\"`, `concurrencyPolicy: Forbid`) that depends on upstream DSPA pipeline server health and a prerequisite feast-apply-job -- the shared template avoids spec duplication across both resource types. The pod runs under `pipeline-runner-dspa` SA (requires SCC anyuid and Job-read RBAC) with dual initContainers polling `ds-pipeline-dspa:8888/apis/v2beta1/healthz` and checking feast-apply-job completion via `oc get job`; the main container uses `pipelineJobImage`/`applicationImage` Values with `DS_PIPELINE_URL` constructed from `.Release.Namespace`. Critical gotchas: `lookup` returns empty during `helm template` dry-run so guards only work on live install/upgrade, both initContainer wait loops lack timeouts and block indefinitely if upstream never readies, DSPA service name is hardcoded, and timestamp-based run names (`batch_training_$(date)`) ensure uniqueness across CronJob invocations."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  ai_pattern: [data-pipeline]
  platform: [rhoai, openshift]
source_examples:
  - quickstart: "product-recommender-system"
    repo: "https://github.com/rh-ai-quickstart/product-recommender-system"
    notes: "KFP pipeline runner as both Job and daily CronJob using lookup-guarded rendering, shared define template, and dual initContainer chain (pipeline server health + feast-apply-job completion)"
    approach: "A"
---

# Helm Lookup-Guarded Job/CronJob with Shared Define Template

## Overview

Uses the Helm `lookup` function to conditionally render a Job and CronJob only if they do not already exist in the cluster, sharing a common pod template via Helm's `define`/`include` mechanism. Both use a dual initContainer wait chain to ensure upstream services are ready before running a Kubeflow pipeline.

## Pattern Description

The template checks for existing Job and CronJob resources at render time using `lookup`. If a resource already exists, it is skipped to prevent conflicts on `helm upgrade`. A shared template (`pipeline-job-template`) defined in `_helpers.tpl` provides the pod spec used by both the one-shot Job and the daily CronJob, avoiding duplication. The pod template includes two initContainers: one waiting for the Data Science Pipeline server health endpoint and another waiting for the Feast apply job to complete.

## Implementation

### Lookup-Guarded Job and CronJob

```yaml
# helm/product-recommender-system/templates/run-pipeline-job.yaml
{{- $jobName := "kfp-run-job" }}
{{- $existingJob := (lookup "batch/v1" "Job" .Release.Namespace $jobName) }}
{{- if not $existingJob }}
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ $jobName }}
  labels:
    pipelines.kubeflow.org/v2_component: 'true'
spec:
  template:
    {{- include "product-recommender-system.pipeline-job-template" . | nindent 4 }}
{{- end }}

---
{{- $cronJobName := "kfp-run-cronjob" }}
{{- $existingCronJob := (lookup "batch/v1" "CronJob" .Release.Namespace $cronJobName) }}
{{- if not $existingCronJob }}
apiVersion: batch/v1
kind: CronJob
metadata:
  name: {{ $cronJobName }}
spec:
  schedule: "0 0 * * *"
  concurrencyPolicy: Forbid
  jobTemplate:
    spec:
      template:
        {{- include "product-recommender-system.pipeline-job-template" . | nindent 8 }}
{{- end }}
```

### Shared Pipeline Job Template

```yaml
# helm/product-recommender-system/templates/_helpers.tpl
{{- define "product-recommender-system.pipeline-job-template" -}}
metadata:
  labels:
    pipelines.kubeflow.org/v2_component: 'true'
spec:
  serviceAccountName: pipeline-runner-dspa
  initContainers:
    - name: wait-for-pipeline
      image: {{ .Values.pipelineJobImage }}
      command:
        - /bin/bash
        - -c
        - |
          set -e
          url="https://ds-pipeline-dspa:8888/apis/v2beta1/healthz"
          until curl -ksf "$url"; do
            echo "Still waiting for $url ..."
            sleep 10
          done
    - name: wait-for-feast-apply
      image: registry.redhat.io/openshift4/ose-cli:latest
      command:
        - /bin/bash
        - -c
        - |
          set -e
          until oc get job feast-apply-job -n {{ .Release.Namespace }} -o jsonpath='{.status.conditions[?(@.type=="Complete")].status}' | grep -q "True"; do
            echo "Still waiting for feast-apply-job..."
            sleep 10
          done
  containers:
  - name: kfp-runner
    image: {{ .Values.pipelineJobImage }}
    env:
      - name: PIPELINE_NAME
        value: 'batch_training'
      - name: DS_PIPELINE_URL
        value: https://ds-pipeline-dspa.{{ .Release.Namespace }}.svc.cluster.local:8888
      - name: BASE_REC_SYS_IMAGE
        value: {{ .Values.applicationImage }}
    command: ['/bin/sh']
    args: ['-c', 'export RUN_NAME="batch_training_$(date +%Y_%m_%d_%H_%M_%S)" && ./entrypoint.sh']
  restartPolicy: Never
{{- end }}
```

## Configuration

- **Key settings:** `pipelineJobImage` (recommendation-training image), `applicationImage` (recommendation-core image), `DS_PIPELINE_URL` constructed from release namespace
- **Defaults:** CronJob runs daily at midnight (`0 0 * * *`), `concurrencyPolicy: Forbid` prevents overlapping runs
- **Dependencies:** Pipeline server (DSPA) must be healthy, feast-apply-job must have completed, `pipeline-runner-dspa` ServiceAccount must exist with SCC anyuid

## Gotchas

- The `lookup` function returns empty during `helm template` (dry-run), so the guard only works during live `helm install/upgrade` -- `helm template` will always render both resources.
- The initContainer `wait-for-feast-apply` uses `oc get job` which requires the `pipeline-runner-dspa` SA to have permissions to read Jobs in the namespace.
- Pipeline run names include timestamps (`batch_training_$(date +%Y_%m_%d_%H_%M_%S)`) generated at pod execution time, ensuring uniqueness across CronJob runs.
- The `ds-pipeline-dspa:8888` service name is hardcoded in the initContainer, creating a tight coupling to the DSPA chart's service naming convention.
- Both initContainer wait loops have no timeout and will wait indefinitely if the upstream service never becomes ready.

## Related Patterns

- `helm-feast-crd-git-featurerepo-registry-wait-apply.md` — the feast-apply-job that this template's initContainer waits for
- `helm-dspa-crd-makefile-injected-external-minio.md` — the DSPA CRD that provides the pipeline server this template waits for
- `helm-hook-initcontainer-psql-table-existence-poll.md` — the db-init Job that depends on this pipeline runner completing
