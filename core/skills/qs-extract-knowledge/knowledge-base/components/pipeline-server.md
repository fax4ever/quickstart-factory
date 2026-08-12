---
name: pipeline-server
description: "Helm chart deploying OpenShift AI DataSciencePipelinesApplication (DSPA) with MinIO-backed object storage"
summary: "Deploys an OpenShift AI DataSciencePipelinesApplication CR (datasciencepipelinesapplications.opendatahub.io/v1, dspVersion v2) at helm/pipeline-server/ to provision Kubeflow Pipelines with OAuth-enabled API server, operator-managed MariaDB (10Gi PVC), and external MinIO artifact storage authenticated via minio-secret (MINIO_ROOT_USER/MINIO_ROOT_PASSWORD keys). Use when quickstarts need multi-step ML training or data-processing pipelines orchestrated on RHOAI — the Makefile dynamically discovers MinIO API endpoint and bucket from deployed routes/configmaps, then creates a ds-pipeline-s3-dspa secret with MinIO ClusterIP for downstream pod-to-pod access; sample pipelines and InstructLab are explicitly disabled. Critical config: DSPA CR connects to external MinIO via s3CredentialsSecret referencing minio-secret, Helm values (minio.apiEndpoint, minio.defaultBucket, minio.defaultRegion) are all set dynamically by Makefile — never manually — and pipeline-runner-dspa SA requires anyuid SCC RoleBinding via system:openshift:scc:anyuid ClusterRole. Gotchas: Chart.yaml is misnamed as \"minio\" (copy-paste artifact causing linting confusion), strict deploy ordering requires MinIO route ready before pipeline-server install, chart cannot run standalone without Makefile wrapper, and ds-pipeline-s3-dspa secret intentionally uses internal ClusterIP not the external route."
metadata:
  type: component
tags:
  tech_stack: [helm, kubeflow-pipelines, mariadb, minio]
  ai_pattern: [data-pipeline]
  platform: [rhoai, openshift, kserve]
  data_layer: []
source_examples:
  - quickstart: "product-recommender-system"
    repo: "https://github.com/rh-ai-quickstart/product-recommender-system"
    notes: "DSPA v2 with external MinIO storage, MariaDB metadata, and anyuid SCC for pipeline runner"
    approach: "A"
---

# Pipeline Server

## Overview

The pipeline server component deploys an OpenShift AI DataSciencePipelinesApplication (DSPA) custom resource that provisions Kubeflow Pipelines v2 infrastructure. It acts as the ML pipeline orchestration layer, enabling quickstarts to define, run, and track multi-step training and data processing workflows. On RHOAI, the DSPA operator manages the API server, persistence agent, scheduled workflows, MariaDB metadata store, and object storage connections.

## Tech Stack & Dependencies

- **Runtime:** OpenShift AI DSPA operator (manages all pipeline server pods)
- **Container image:** Managed by DSPA operator (no user-specified image)
- **Key dependencies:** MinIO (external object storage), MariaDB (operator-deployed metadata DB), `minio-secret` Kubernetes secret
- **Helm subchart:** Standalone Helm chart at `helm/pipeline-server/` (not a subchart dependency)

## Key Patterns

### DataSciencePipelinesApplication Custom Resource

The core of this component is a single DSPA CR that configures the full pipeline server stack. The CR uses the `datasciencepipelinesapplications.opendatahub.io/v1` API and connects to an externally deployed MinIO instance for artifact storage.

```yaml
apiVersion: datasciencepipelinesapplications.opendatahub.io/v1
kind: DataSciencePipelinesApplication
metadata:
  name: dspa
spec:
  dspVersion: v2
  apiServer:
    deploy: true
    enableOauth: true
    enableSamplePipeline: false
  database:
    mariaDB:
      deploy: true
      pipelineDBName: mlpipeline
      pvcSize: 10Gi
  objectStorage:
    externalStorage:
      bucket: {{ .Values.minio.defaultBucket }}
      host: {{ .Values.minio.apiEndpoint }}
      s3CredentialsSecret:
        accessKey: MINIO_ROOT_USER
        secretKey: MINIO_ROOT_PASSWORD
        secretName: minio-secret
      scheme: https
```

Source: `helm/pipeline-server/templates/pipeline-application.yaml`

### Dynamic MinIO Endpoint Discovery via Makefile

The pipeline-server values are injected at deploy time by the Makefile, which discovers the MinIO API endpoint and bucket name from the already-deployed MinIO chart's route and configmap. This avoids hardcoding endpoints.

```makefile
$(eval MINIO_API_HOST = $(shell oc get route minio-api \
    -n $(NAMESPACE) -o jsonpath='{.spec.host}'))
$(eval DEFAULT_BUCKET= $(shell oc get configmap minio-config \
    -n $(NAMESPACE) -o json | jq -r '.data["DEFAULT_BUCKET"]'))
helm upgrade --install pipeline-server $(PIPELINE_SERVER_CHART) \
    --set minio.apiEndpoint=$(MINIO_API_HOST) \
    --set minio.defaultBucket=$(DEFAULT_BUCKET) \
    --set minio.defaultRegion=$(DEFAULT_REGION)
```

Source: `helm/Makefile`, lines 128-141

### Anyuid SCC RoleBinding for Pipeline Runner

The pipeline runner service account requires the `anyuid` SCC to execute pipeline steps. This is granted via a RoleBinding to the `system:openshift:scc:anyuid` ClusterRole.

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: pipeline-runner-dspa-anyuid
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: system:openshift:scc:anyuid
subjects:
  - kind: ServiceAccount
    name: pipeline-runner-dspa
```

Source: `helm/pipeline-server/templates/scc-rolebinding.yaml`

### Post-Deploy Dynamic Secret for Downstream Consumers

After the pipeline-server installs, the Makefile creates a `ds-pipeline-s3-dspa` secret containing MinIO connection details (host, port, accesskey, secretkey). Downstream components (e.g., the product-recommender-system chart) mount this secret to access MinIO without knowing its address at chart-authoring time.

```makefile
oc create secret generic ds-pipeline-s3-dspa -n $(NAMESPACE) \
    --from-literal=host=$(MINIO_SERVICE_HOST) \
    --from-literal=port=$(MINIO_SERVICE_PORT) \
    --from-literal=accesskey=$(MINIO_ACCESS_KEY_VALUE) \
    --from-literal=secretkey=$(MINIO_SECRET_KEY_VALUE) \
    --from-literal=secure=false \
    --dry-run=client -o yaml | oc apply -f -
```

Source: `helm/Makefile`, lines 152-164

## Configuration

- **Environment variables:** None directly on the pipeline-server; all configuration is through the DSPA spec and Helm values
- **Config files:** `values.yaml` exposes `minio.defaultRegion`, `minio.defaultBucket`, `minio.apiEndpoint` -- all set dynamically at deploy time via the Makefile
- **Helm values:**
  - `minio.apiEndpoint` -- External MinIO API route hostname (set by Makefile, not manually)
  - `minio.defaultBucket` -- S3 bucket for pipeline artifacts (set by Makefile)
  - `minio.defaultRegion` -- S3 region (set by Makefile)

## Known Gotchas

- The `Chart.yaml` has `name: minio` despite being the pipeline-server chart. This appears to be a copy-paste artifact from the minio chart -- it does not affect deployment since Helm install uses the release name `pipeline-server` from the Makefile, but it could cause confusion during chart linting or debugging.
  Source: `helm/pipeline-server/Chart.yaml`, line 2
- The DSPA spec explicitly sets `managedPipelines.instructLab.state: Removed`, indicating InstructLab pipelines are intentionally disabled for this quickstart.
  Source: `helm/pipeline-server/templates/pipeline-application.yaml`, lines 19-20
- The `values.yaml` comments state `apiEndpoint` is "set by make file dynamically during deployment; do not set here" -- this means the chart cannot be installed standalone without the Makefile wrapper.
  Source: `helm/pipeline-server/values.yaml`, line 4
- The deployment ordering is strict: MinIO must be installed and its route ready before pipeline-server-install can discover the endpoint. The Makefile enforces this via target dependencies (`install: ... minio-install pipeline-server-install ...`).
  Source: `helm/Makefile`, line 111
- The `ds-pipeline-s3-dspa` secret uses the MinIO ClusterIP (internal service address), not the external route, for downstream pod-to-pod communication. This is intentional -- pods should use internal networking rather than going through the router.
  Source: `helm/Makefile`, lines 154-155

## Testing Notes

- Verify the DSPA pods are running: `oc get pod -l app=ds-pipeline-dspa -n <namespace>`
- The Makefile includes a retry loop (25 attempts, 5s intervals) waiting for the pipeline pod to appear, followed by `oc wait --for=condition=Ready --timeout=180s`
- Access the pipeline UI via the route: `oc get route ds-pipeline-dspa -n <namespace> -o jsonpath='{.spec.host}'`
- Confirm the `ds-pipeline-s3-dspa` secret was created after pipeline-server install

## Related Patterns

- `minio.md` -- MinIO object storage that this pipeline server connects to for artifact storage
- `model-serving.md` -- Model serving endpoints that training pipelines may produce artifacts for
