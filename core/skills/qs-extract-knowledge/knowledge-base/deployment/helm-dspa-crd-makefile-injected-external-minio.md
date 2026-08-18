---
name: helm-dspa-crd-makefile-injected-external-minio
description: DataSciencePipelinesApplication CRD with Makefile-injected MinIO endpoint for external object storage
summary: "Deploys a DataSciencePipelinesApplication (DSPA) CRD for OpenShift AI Data Science Pipelines via a separate Helm pipeline-server chart whose MinIO external storage values (`minio.apiEndpoint`, `minio.defaultBucket`, `minio.defaultRegion`) are Makefile-injected at install time by discovering the MinIO API route and `minio-config` ConfigMap via `oc get`/`jq`, then passing them as `--set` flags to `helm upgrade --install`. Use when DSPA needs HTTPS external MinIO object storage with credentials from a pre-existing `minio-secret` (keys `MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD`) created by a separately deployed MinIO chart that must be installed first. The DSPA spec enables `dspVersion: v2` (Kubeflow Pipelines v2), deploys internal MariaDB (10Gi PVC, user `mlpipeline`), enables OAuth and pod-to-pod TLS, and grants `anyuid` SCC to `pipeline-runner-dspa` ServiceAccount via RoleBinding. Gotchas: Chart.yaml has copy-paste `name: minio` instead of `pipeline-server`; values.yaml has empty defaults so manual `helm install` without Makefile yields blank storage config; hard-coded `minio-secret` reference couples to MinIO chart's Secret name; `managedPipelines.instructLab.state: Removed` explicitly disables InstructLab pipelines."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, minio]
  ai_pattern: [data-pipeline]
  platform: [rhoai, openshift]
source_examples:
  - quickstart: "product-recommender-system"
    repo: "https://github.com/rh-ai-quickstart/product-recommender-system"
    notes: "DSPA CRD in separate pipeline-server chart with MinIO endpoint, bucket, and region injected at deploy time from Makefile oc discovery"
    approach: "A"
---

# DataSciencePipelinesApplication CRD with Makefile-Injected External MinIO

## Overview

Deploys a DataSciencePipelinesApplication (DSPA) custom resource for OpenShift AI's Data Science Pipelines using a dedicated Helm chart whose values are populated at install time by the Makefile after discovering the MinIO route endpoint dynamically.

## Pattern Description

The pipeline-server chart is minimal: a single DSPA CRD template and an SCC RoleBinding. The DSPA CRD configures Kubeflow Pipelines v2 with external MinIO storage via HTTPS, using the MinIO route hostname discovered by the Makefile. The Makefile reads the MinIO API route, bucket name, and region from the already-deployed MinIO chart's resources, then passes them as `--set` flags to `helm upgrade --install`.

## Implementation

### DSPA CRD Template

```yaml
# helm/pipeline-server/templates/pipeline-application.yaml
apiVersion: datasciencepipelinesapplications.opendatahub.io/v1
kind: DataSciencePipelinesApplication
metadata:
  name: dspa
  namespace: {{ .Release.Namespace }}
spec:
  apiServer:
    deploy: true
    enableOauth: true
    enableSamplePipeline: false
  database:
    mariaDB:
      deploy: true
      pipelineDBName: mlpipeline
      pvcSize: 10Gi
      username: mlpipeline
  dspVersion: v2
  objectStorage:
    externalStorage:
      bucket: {{ .Values.minio.defaultBucket }}
      host: {{ .Values.minio.apiEndpoint }}
      region: {{ .Values.minio.defaultRegion }}
      s3CredentialsSecret:
        accessKey: MINIO_ROOT_USER
        secretKey: MINIO_ROOT_PASSWORD
        secretName: minio-secret
      scheme: https
  podToPodTLS: true
```

### SCC RoleBinding for Pipeline Runner

```yaml
# helm/pipeline-server/templates/scc-rolebinding.yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: pipeline-runner-dspa-anyuid
  namespace: {{ .Release.Namespace }}
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: system:openshift:scc:anyuid
subjects:
  - kind: ServiceAccount
    name: pipeline-runner-dspa
    namespace: {{ .Release.Namespace }}
```

### Makefile Injection at Install Time

```makefile
# helm/Makefile (pipeline-server-install target)
$(eval MINIO_API_HOST = $(shell oc get route minio-api -n $(NAMESPACE) -o jsonpath='{.spec.host}'))
$(eval DEFAULT_BUCKET= $(shell oc get configmap minio-config -n $(NAMESPACE) -o json | jq -r '.data["DEFAULT_BUCKET"]'))
$(eval DEFAULT_REGION= $(shell oc get configmap minio-config -n $(NAMESPACE) -o json | jq -r '.data["DEFAULT_REGION"]'))
@helm -n $(NAMESPACE) upgrade --install pipeline-server $(PIPELINE_SERVER_CHART) \
    --set minio.apiEndpoint=$(MINIO_API_HOST) \
    --set minio.defaultBucket=$(DEFAULT_BUCKET) \
    --set minio.defaultRegion=$(DEFAULT_REGION)
```

## Configuration

- **Key settings:** `minio.apiEndpoint` (MinIO route hostname), `minio.defaultBucket` (default: `recommender`), `minio.defaultRegion` (default: `us-east-1`)
- **Defaults:** MariaDB deployed internally for pipeline metadata, OAuth enabled on API server, pod-to-pod TLS enabled, `dspVersion: v2`
- **Dependencies:** MinIO chart must be installed and its API route must be ready before this chart is installed; the `minio-secret` must exist in the same namespace

## Gotchas

- The pipeline-server `Chart.yaml` has `name: minio` (a copy-paste error from the MinIO chart) instead of `name: pipeline-server`, though this does not affect deployment since Helm uses the release name, not the chart name.
- The `values.yaml` comments say "set by make file" with empty defaults, meaning a manual `helm install` without the Makefile will deploy a DSPA with blank storage configuration.
- The `s3CredentialsSecret` references `minio-secret` by name, which is created by the separate MinIO chart -- if the MinIO chart changes its Secret name, this breaks.
- The `managedPipelines.instructLab.state: Removed` setting explicitly disables InstructLab managed pipelines in the DSPA spec.

## Related Patterns

- `makefile-runtime-secret-bridge-multi-chart-oc-discovery.md` — the Makefile that orchestrates the install order and discovers MinIO values
