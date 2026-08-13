---
name: helm-dspa-subchart-embedded-minio-kserve-pipeline-jobs
description: Self-contained subchart deploying DSPA CRD with embedded MinIO+MariaDB, KServe ServingRuntime, Model Registry dep, and templated pipeline trigger Jobs
summary: "Packages a complete ML pipeline deployment as a self-contained Helm subchart deploying DSPA v2 CRD with embedded MariaDB+MinIO for pipeline artifacts, a separate standalone MinIO Deployment for model storage, KServe MLServer sklearn ServingRuntime (protocolVersions v2, multiModel false), Model Registry remote ai-architecture-charts dependency in `rhoai-model-registries` namespace, RBAC for the DSPA-created pipeline-runner ServiceAccount, and range-loop Jobs with a `preparePipelineData` helper template that POST KNN hyperparameters to the pipeline FastAPI service. Use when packaging turnkey Kubeflow Pipelines v2 infrastructure as a conditionally-enabled subchart with two-level toggles (`chart.enabled` + `dspa.deploy`) and optional dynamic ServingRuntime creation via `serving.runtime.createViaPipeline: true` -- prefer `helm-dspa-crd-makefile-injected-external-minio` when using external object storage instead of embedded MinIO. Jobs require an initContainer wait loop on pipeline-service `/ping`, use `image-registry.openshift-image-registry.svc:5000/openshift/tools:latest` from the OpenShift internal registry, carry `opendatahub.io/workbenches: \"true\"` pod label for DSPA NetworkPolicy, and set `backoffLimit: 3`. The chart deploys two separate MinIO instances (DSPA-embedded for artifacts vs standalone for models) with different `s3CredentialsSecret` configs and endpoints, and the Model Registry namespace `rhoai-model-registries` must be pre-created via Makefile `oc create namespace` before Helm install."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, minio]
  ai_pattern: [model-serving, data-pipeline]
  platform: [kserve, rhoai, openshift]
source_examples:
  - quickstart: "spending-transaction-monitor"
    repo: "https://github.com/rh-ai-quickstart/spending-transaction-monitor"
    notes: "alert-recommender-pipeline subchart with DSPA v2 (embedded MariaDB+MinIO), MLServer sklearn ServingRuntime, model-registry remote dep, range-loop pipeline trigger Jobs with preparePipelineData helper"
    approach: "A"
---

# DSPA Subchart with Embedded Storage, KServe Runtime, and Pipeline Trigger Jobs

## Overview

This pattern packages a complete ML pipeline deployment as a self-contained Helm subchart that deploys a DataSciencePipelinesApplication (DSPA) CRD with embedded MariaDB and MinIO storage, a KServe ServingRuntime for sklearn model serving, a Model Registry remote dependency, RBAC for pipeline runners, and templated Jobs that trigger pipeline execution via the pipeline service's REST API. The subchart is conditionally enabled from the parent umbrella chart.

## Pattern Description

The subchart serves as a turnkey ML pipeline deployment: DSPA provisions Kubeflow Pipelines v2 infrastructure, MinIO stores trained models, KServe's ServingRuntime defines how to serve sklearn models, and pipeline trigger Jobs POST training requests to the pipeline FastAPI service. A `range` loop over `.Values.pipelines` generates one Job per enabled pipeline configuration, with a `preparePipelineData` helper template assembling the JSON payload from values. The Model Registry is a remote ai-architecture-charts dependency.

## Implementation

### DSPA CRD with Embedded Storage

```yaml
apiVersion: datasciencepipelinesapplications.opendatahub.io/v1
kind: DataSciencePipelinesApplication
metadata:
  name: {{ .Values.dspa.name }}
spec:
  dspVersion: v2
  database:
    mariaDB:
      deploy: true
      pipelineDBName: {{ .Values.dspa.database.name }}
      passwordSecret:
        name: {{ .Values.dspa.name }}-db-secret
        key: password
      pvcSize: {{ .Values.dspa.database.storage }}
  objectStorage:
    minio:
      deploy: true
      image: "quay.io/minio/minio:latest"
      bucket: {{ .Values.dspa.objectStorage.bucket }}
      s3CredentialsSecret:
        accessKey: accesskey
        secretKey: secretkey
        secretName: {{ .Values.dspa.name }}-minio-secret
      pvcSize: {{ .Values.dspa.objectStorage.storage }}
```

Source: `deploy/helm/alert-recommender-pipeline/templates/dspa.yaml`. DSPA deploys its own MariaDB and MinIO (separate from the app's MinIO for model storage).

### KServe MLServer ServingRuntime

```yaml
apiVersion: serving.kserve.io/v1alpha1
kind: ServingRuntime
metadata:
  name: {{ .Values.serving.runtime.existingRuntime | default "alert-recommender-runtime" }}
spec:
  supportedModelFormats:
    - name: sklearn
      version: "1"
      autoSelect: true
  protocolVersions:
    - v2
  multiModel: false
  containers:
    - name: kserve-container
      image: docker.io/seldonio/mlserver:1.7.0-sklearn
      env:
        - name: MLSERVER_MODEL_IMPLEMENTATION
          value: "mlserver_sklearn.SKLearnModel"
```

Source: `deploy/helm/alert-recommender-pipeline/templates/serving-runtime.yaml`

### Range-Loop Pipeline Trigger Jobs

```yaml
{{- $enabledPipelines := include "alert-recommender-pipeline.enabledPipelines" . | fromJson -}}
{{- range $pipelineKey, $pipelineConfig := $enabledPipelines }}
apiVersion: batch/v1
kind: Job
metadata:
  name: add-{{ $pipelineKey | lower | replace "_" "-" | trunc 50 }}-pipeline
spec:
  template:
    metadata:
      labels:
        opendatahub.io/workbenches: "true"  # Required for DSPA NetworkPolicy
    spec:
      initContainers:
        - name: wait-for-pipeline-service
          image: "image-registry.openshift-image-registry.svc:5000/openshift/tools:latest"
          command: ["/bin/bash", "-c", "until curl -ksf http://...pipeline-service:8080/ping; do sleep 10; done"]
      containers:
        - name: create-pipeline
          image: "image-registry.openshift-image-registry.svc:5000/openshift/tools:latest"
          command: ["/bin/bash", "-c", "curl -sfX POST .../train -d '{{ $pipelineData }}'"]
      restartPolicy: Never
  backoffLimit: 3
{{- end }}
```

Source: `deploy/helm/alert-recommender-pipeline/templates/pipeline-job.yaml` (abridged)

### Pipeline Data Preparation Helper

```yaml
{{- define "alert-recommender-pipeline.preparePipelineData" -}}
{{- $data := dict 
    "name" $config.name
    "version" $config.version
    "n_neighbors" $config.nNeighbors
    "metric" $config.metric
    "minio_endpoint" $root.Values.minio.endpoint
    "namespace" $root.Release.Namespace
    "deploy_model" $config.deployModel
    "register_model" $config.registerModel
    "model_registry_url" $root.Values.modelRegistry.url
    "serving_runtime" $runtimeName
    "create_serving_runtime" $createRuntime
-}}
{{ $data | toJson }}
{{- end }}
```

Source: `deploy/helm/alert-recommender-pipeline/templates/_helpers.tpl` (abridged)

### RBAC for Pipeline Runner

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: {{ fullname }}-dspa-runner
subjects:
  - kind: ServiceAccount
    name: pipeline-runner-{{ .Values.dspa.name }}
roleRef:
  kind: Role
  name: {{ fullname }}
```

Source: `deploy/helm/alert-recommender-pipeline/templates/rbac.yaml`. The DSPA-created `pipeline-runner-dspa` ServiceAccount is bound to the chart's Role for Secret, KServe, and MinIO management.

## Configuration

- **Parent chart toggle:** `alert-recommender-pipeline.enabled: false` (default) in umbrella values
- **DSPA deploy toggle:** `dspa.deploy: true/false` -- separate from chart enablement to allow using external DSPA
- **Model Registry:** Remote dep from ai-architecture-charts, deployed to `rhoai-model-registries` namespace
- **Pipeline configs:** Under `.Values.pipelines.alert_recommender` with KNN hyperparameters (`nNeighbors`, `metric`, `threshold`)
- **MinIO:** Separate from DSPA's MinIO -- this chart deploys its own MinIO Deployment for model storage

## Gotchas

- The chart deploys two separate MinIO instances: one embedded in DSPA (for pipeline artifacts) and one standalone (for model storage), using different credentials and endpoints
- Pipeline trigger Jobs use `image-registry.openshift-image-registry.svc:5000/openshift/tools:latest` -- this requires the OpenShift internal registry and the `tools` imagestream to be available
- The `opendatahub.io/workbenches: "true"` label on pipeline Job pods is required for the DSPA NetworkPolicy to allow traffic from Jobs to the pipeline service
- `serving.runtime.create: false` and `serving.runtime.createViaPipeline: true` in the parent chart's override means the pipeline itself creates the ServingRuntime rather than the chart, allowing dynamic configuration
- Model Registry is deployed to a different namespace (`rhoai-model-registries`) which requires the Makefile to create it via `oc create namespace rhoai-model-registries` before deployment

## Related Patterns

- `helm-dspa-crd-makefile-injected-external-minio.md` - DSPA with external MinIO
- `helm-kserve-mlserver-sklearn-minio-rawdeployment.md` - KServe MLServer without DSPA
- `helm-kserve-runtime-deployer-job-inline-rbac.md` - KServe runtime deployment Jobs
