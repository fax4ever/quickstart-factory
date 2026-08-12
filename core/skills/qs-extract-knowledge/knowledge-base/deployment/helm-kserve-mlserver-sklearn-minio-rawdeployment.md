---
name: helm-kserve-mlserver-sklearn-minio-rawdeployment
description: KServe InferenceService with custom MLServer sklearn ServingRuntime in RawDeployment mode using MinIO S3 model storage
summary: "Deploys scikit-learn models via KServe InferenceService using a custom MLServer ServingRuntime (seldonio/mlserver:1.7.1-sklearn) in RawDeployment mode with MinIO S3 model storage, providing V2 inference protocol endpoints (HTTP 8080/gRPC 8081) without requiring Knative, GPU, or external model registries. Use when serving traditional ML classifiers/regressors on OpenShift AI with in-cluster MinIO; three Helm-templated resources coordinate -- ServingRuntime (multiModel: false, autoSelect: true auto-matches sklearn format), InferenceService (storageUri: s3://models/<name>, annotation serving.kserve.io/deploymentMode: RawDeployment), and ServiceAccount bound to a Secret with KServe S3 annotations for MinIO auth. Critical config: Secret annotations serving.kserve.io/s3-endpoint must use fully qualified namespace DNS (minio.<namespace>.svc.cluster.local:9000) with serving.kserve.io/s3-usehttps: \"0\" for plain HTTP MinIO; in RawDeployment mode KServe creates a Service named after the InferenceService (accessed via http://guidelines-mlp:80). Common gotchas: MLSERVER_MODELS_DIR must be /models/_mlserver_models (not /opt/mlserver/models) because KServe's storage initializer downloads to /models/; s3-endpoint is namespace-scoped and breaks if MinIO is in a different namespace; model files must be pre-uploaded to MinIO via a separate Job."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  ai_pattern: [model-serving]
  platform: [kserve, rhoai, openshift]
source_examples:
  - quickstart: "portfolio-manager-agent"
    repo: "https://github.com/rh-ai-quickstart/portfolio-manager-agent"
    notes: "Custom MLServer sklearn ServingRuntime with InferenceService in RawDeployment mode, MinIO for model storage, ServiceAccount with KServe S3 annotations"
    approach: "A"
---

# KServe MLServer sklearn with MinIO S3 in RawDeployment Mode

## Overview

This pattern deploys a scikit-learn model via KServe InferenceService using a custom MLServer ServingRuntime in RawDeployment mode, with model weights stored in MinIO S3. It provides a full model-serving stack without requiring Knative, GPU, or external model registries -- suited for traditional ML models (classifiers, regressors) that need standardized V2 inference protocol endpoints.

## Pattern Description

Three resources coordinate to serve the model: a ServingRuntime that defines the MLServer container with the sklearn plugin, an InferenceService that references the runtime and points to the MinIO model path, and a ServiceAccount bound to a Secret with KServe S3 annotations. The S3 annotations on the Secret tell KServe's storage initializer where to find MinIO and how to authenticate, while the ServiceAccount links the Secret to the InferenceService predictor.

## Implementation

### Custom ServingRuntime

The ServingRuntime defines the MLServer container image with sklearn support, using the V2 inference protocol:

```yaml
# deploy/helm/templates/servingruntime-mlserver.yaml
apiVersion: serving.kserve.io/v1alpha1
kind: ServingRuntime
metadata:
  name: mlserver-sklearn
  namespace: {{ .Values.namespace }}
spec:
  supportedModelFormats:
    - name: sklearn
      version: "1"
      autoSelect: true
  multiModel: false
  protocolVersions:
    - v2
  containers:
    - name: kserve-container
      image: docker.io/seldonio/mlserver:1.7.1-sklearn
      ports:
        - containerPort: 8080
          protocol: TCP
      env:
        - name: MLSERVER_MODELS_DIR
          value: /models/_mlserver_models
        - name: MLSERVER_GRPC_PORT
          value: "8081"
        - name: MLSERVER_HTTP_PORT
          value: "8080"
        - name: MLSERVER_LOAD_MODELS_AT_STARTUP
          value: "true"
        - name: MLSERVER_HOST
          value: "0.0.0.0"
```

### InferenceService in RawDeployment Mode

The InferenceService references the ServingRuntime and the MinIO model path:

```yaml
# deploy/helm/templates/inferenceservice-guidelines-mlp.yaml
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  name: guidelines-mlp
  namespace: {{ .Values.namespace }}
  annotations:
    serving.kserve.io/deploymentMode: RawDeployment
spec:
  predictor:
    serviceAccountName: model-serving
    model:
      modelFormat:
        name: sklearn
      runtime: mlserver-sklearn
      storageUri: s3://models/guidelines-mlp
```

### ServiceAccount with MinIO Secret

The ServiceAccount references the MinIO credentials Secret, which carries KServe S3 annotations:

```yaml
# deploy/helm/templates/sa-model-serving.yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: model-serving
  namespace: {{ .Values.namespace }}
secrets:
  - name: minio-credentials
```

```yaml
# deploy/helm/templates/secret-minio.yaml
apiVersion: v1
kind: Secret
metadata:
  name: minio-credentials
  namespace: {{ .Values.namespace }}
  annotations:
    serving.kserve.io/s3-endpoint: minio.{{ .Values.namespace }}.svc.cluster.local:9000
    serving.kserve.io/s3-usehttps: "0"
    serving.kserve.io/s3-region: us-east-1
type: Opaque
stringData:
  AWS_ACCESS_KEY_ID: {{ .Values.minio.rootUser }}
  AWS_SECRET_ACCESS_KEY: {{ .Values.minio.rootPassword }}
```

## Configuration

- **Key settings:** `serving.kserve.io/deploymentMode: RawDeployment` bypasses Knative requirement; `storageUri: s3://models/guidelines-mlp` points to the MinIO bucket path; `serving.kserve.io/s3-usehttps: "0"` disables HTTPS for internal MinIO
- **Defaults:** MLServer listens on HTTP 8080 and gRPC 8081; models loaded at startup from `_mlserver_models` directory; `multiModel: false` serves one model per runtime pod; MinIO credentials default to `minioadmin/minioadmin`
- **Dependencies:** MinIO deployment in the same namespace; model files uploaded to `s3://models/guidelines-mlp/` (via the model-upload Job); KServe controller installed on the cluster

## Gotchas

- The `serving.kserve.io/s3-endpoint` annotation on the Secret uses the fully qualified DNS name `minio.{{ .Values.namespace }}.svc.cluster.local:9000` -- this is namespace-scoped and will not work if MinIO is deployed in a different namespace (see `deploy/helm/templates/secret-minio.yaml`)
- The `serving.kserve.io/s3-usehttps: "0"` annotation is critical for MinIO since it runs plain HTTP internally; omitting this causes KServe's storage initializer to attempt HTTPS and fail (see `deploy/helm/templates/secret-minio.yaml`)
- The `MLSERVER_MODELS_DIR` is set to `/models/_mlserver_models` (not `/opt/mlserver/models`) because KServe's storage initializer downloads models to `/models/` and MLServer looks for its directory structure within that path (see `deploy/helm/templates/servingruntime-mlserver.yaml`)
- The guidelines tool agent references the InferenceService via `guidelines.inferenceUrl` in values.yaml, defaulting to `http://guidelines-mlp:80` -- in RawDeployment mode, KServe creates a Service named after the InferenceService (see `deploy/helm/values.yaml`)
- The `autoSelect: true` in the ServingRuntime means KServe will automatically use this runtime for any InferenceService with `modelFormat.name: sklearn`, without requiring an explicit `runtime:` reference (see `deploy/helm/templates/servingruntime-mlserver.yaml`)

## Related Patterns

- `helm-model-upload-job-initcontainer-prebaked-minio.md` -- the Job that uploads model files to MinIO for this InferenceService
- `kserve-rawdeployment-detector-fleet-gpu-toggle.md` -- similar RawDeployment pattern for vLLM-based models
- `kserve-vllm-cpu-oci-modelcar-no-gpu.md` -- alternative KServe pattern using OCI modelcar instead of S3
