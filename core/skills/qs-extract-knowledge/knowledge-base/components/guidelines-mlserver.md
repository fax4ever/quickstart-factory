---
name: guidelines-mlserver
description: "MLServer sklearn runtime serving a joblib MLP classifier via KServe InferenceService with S3/MinIO model storage"
summary: "Serves a scikit-learn MLP classifier via MLServer 1.7.1 sklearn runtime (seldonio/mlserver:1.7.1-sklearn) as a KServe InferenceService in RawDeployment mode with MinIO S3-backed model storage, registered through a custom ServingRuntime CR with V2 inference protocol. Use when serving joblib-serialized sklearn models needing KServe-managed inference with S3 storage — RawDeployment avoids Knative/serverless dependency; requires a multi-stage Dockerfile running unwrap_model.py at build time if the joblib artifact wraps the model in a dict with metadata rather than storing the Pipeline directly. Critical config: model-settings.json co-located with the artifact sets implementation to mlserver_sklearn.SKLearnModel and URI; the MinIO Secret must carry KServe annotations (serving.kserve.io/s3-endpoint, s3-usehttps: \"0\", s3-region); Helm values configure image.tags.guidelinesModel and guidelines.inferenceUrl (default http://guidelines-mlp:80); consumer sets INFERENCE_URL env var. The V2 predict_proba output is a flat array [neg_0, pos_0, ...] requiring data[i*2+1] indexing for positive-class probabilities, the model-upload Job needs a retry loop (30 attempts, 2s sleep) for MinIO readiness via mc alias set, and local compose bypasses MinIO entirely by serving from the baked-in image path."
metadata:
  type: component
tags:
  tech_stack: [mlserver, scikit-learn, joblib, python]
  ai_pattern: [model-serving]
  platform: [kserve, rhoai, openshift]
  data_layer: [minio]
source_examples:
  - quickstart: "portfolio-manager-agent"
    repo: "https://github.com/rh-ai-quickstart/portfolio-manager-agent"
    notes: "MLServer sklearn runtime serving an investment-guidelines MLP classifier via KServe RawDeployment with MinIO-backed S3 storage"
    approach: "A"
---

# Guidelines MLServer

## Overview

MLServer sklearn runtime used to serve a scikit-learn MLP classifier as a KServe InferenceService. In the portfolio-manager-agent quickstart, the guidelines-model component packages a pre-trained joblib model into a multi-stage Docker image, uploads it to MinIO via a Kubernetes Job, and serves it through the KServe V2 inference protocol. The guidelines agent application calls this model server to classify investment guideline sentences as prohibited or permitted.

## Tech Stack & Dependencies

- **Runtime:** MLServer 1.7.1 with sklearn runtime (`docker.io/seldonio/mlserver:1.7.1-sklearn`)
- **Container image:** Multi-stage build from `seldonio/mlserver:1.7.1-sklearn`
- **Key dependencies:** scikit-learn (MLP pipeline), joblib (model serialization), MinIO (S3-compatible model storage), KServe (InferenceService CRD)
- **Helm subchart:** None -- uses custom Helm templates for ServingRuntime, InferenceService, and model-upload Job

## Key Patterns

### Multi-Stage Dockerfile with Model Unwrapping

The Dockerfile uses a builder stage to unwrap a project-specific joblib format (dict with metadata) into a plain sklearn Pipeline that MLServer expects. This avoids runtime deserialization issues.

```dockerfile
FROM docker.io/seldonio/mlserver:1.7.1-sklearn AS builder

USER 0
COPY models/investment-guidelines-mlp.joblib /tmp/wrapped-model.joblib
COPY tools/guidelines-model/unwrap_model.py /tmp/unwrap_model.py
COPY tools/guidelines-model/model-settings.json /tmp/model-settings.json

RUN python /tmp/unwrap_model.py \
        /tmp/wrapped-model.joblib \
        /opt/mlserver/models/guidelines-mlp/investment-guidelines-mlp.joblib && \
    cp /tmp/model-settings.json /opt/mlserver/models/guidelines-mlp/model-settings.json && \
    rm -f /tmp/wrapped-model.joblib /tmp/unwrap_model.py /tmp/model-settings.json

FROM docker.io/seldonio/mlserver:1.7.1-sklearn

COPY --from=builder /opt/mlserver/models /opt/mlserver/models

ENV MLSERVER_MODELS_DIR=/opt/mlserver/models
```

### Model Unwrapping Script

The quickstart saves models in a wrapped dict format with metadata. MLServer requires `joblib.load()` to return the model directly, so a build-time script extracts it:

```python
payload = joblib.load(src)
model = (
    payload["model"]
    if isinstance(payload, dict) and "model" in payload
    else payload
)
joblib.dump(model, dst)
```

### model-settings.json Configuration

MLServer uses a `model-settings.json` file co-located with the model artifact to configure model name, implementation, and URI:

```json
{
  "name": "guidelines-mlp",
  "implementation": "mlserver_sklearn.SKLearnModel",
  "parameters": {
    "uri": "./investment-guidelines-mlp.joblib"
  }
}
```

### KServe InferenceService with RawDeployment Mode

The model is served via a KServe InferenceService using RawDeployment mode (no serverless/Knative dependency) with S3 storage URI pointing to MinIO:

```yaml
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  name: guidelines-mlp
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

### Custom ServingRuntime for MLServer sklearn

A ServingRuntime CR registers MLServer as the sklearn serving backend with V2 protocol:

```yaml
apiVersion: serving.kserve.io/v1alpha1
kind: ServingRuntime
metadata:
  name: mlserver-sklearn
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
```

### Model Upload via Kubernetes Job

A Kubernetes Job uses an init container to extract model files from the guidelines-model image, then the main container uploads them to MinIO using the `mc` (MinIO client) CLI:

```yaml
initContainers:
  - name: prepare-model
    image: {{ .Values.image.repository }}:{{ .Values.image.tags.guidelinesModel }}
    command:
      - sh
      - -c
      - cp /opt/mlserver/models/guidelines-mlp/* /export/
containers:
  - name: upload
    image: docker.io/minio/mc:latest
    command:
      - sh
      - -c
      - |
        mc mb --ignore-existing minio/models
        mc cp --recursive /export/ minio/models/guidelines-mlp/
```

### V2 Inference Protocol Client Call

The consuming guidelines agent calls the model server using the KServe V2 inference API, sending text sentences as BYTES datatype with `content_type: str` parameter:

```python
url = f"{INFERENCE_URL}/v2/models/guidelines-mlp/infer"
payload = {
    "inputs": [
        {
            "name": "predict_input",
            "datatype": "BYTES",
            "shape": [len(sentences)],
            "data": sentences,
            "parameters": {"content_type": "str"},
        }
    ],
    "outputs": [{"name": "predict_proba"}],
}
resp = requests.post(url, json=payload, timeout=30)
# Shape [N, 2]: pairs of (neg_prob, pos_prob) — extract positive class
data = resp.json()["outputs"][0]["data"]
return [data[i * 2 + 1] for i in range(len(sentences))]
```

## Configuration

- **Environment variables:**
  - `MLSERVER_MODELS_DIR=/opt/mlserver/models` -- directory where MLServer scans for model directories
  - `MLSERVER_HTTP_PORT=8080` -- HTTP port for the V2 REST API
  - `MLSERVER_GRPC_PORT=8081` -- gRPC port
  - `MLSERVER_LOAD_MODELS_AT_STARTUP=true` -- load models eagerly on container start
  - `MLSERVER_HOST=0.0.0.0` -- bind address
  - `INFERENCE_URL` -- set on the consumer (guidelines agent) to point to the MLServer endpoint
- **Config files:** `model-settings.json` -- placed alongside the model artifact, configures model name, implementation class, and URI
- **Helm values:**
  - `image.tags.guidelinesModel` -- tag for the guidelines-model container image (default: `guidelines-model`)
  - `guidelines.inferenceUrl` -- URL the guidelines agent uses to reach the model server (default: `http://guidelines-mlp:80`)

## Known Gotchas

- **Wrapped joblib format requires unwrapping at build time:** The quickstart saves models as `{"model": Pipeline(...), "saved_at": "...", "sklearn_version": "...", "type": "..."}` but MLServer expects `joblib.load()` to return the pipeline directly. The `unwrap_model.py` script handles this in the Dockerfile builder stage. Source: `tools/guidelines-model/unwrap_model.py` docstring.
- **V2 predict_proba output shape is flat:** The MLServer sklearn runtime returns `predict_proba` output as a flat array `[neg_0, pos_0, neg_1, pos_1, ...]` rather than a 2D array. The client must index with `data[i * 2 + 1]` to extract positive-class probabilities. Source: `tools/guidelines/src/app.py` line 576.
- **MinIO S3 endpoint requires KServe annotations on the secret:** The `minio-credentials` Secret needs `serving.kserve.io/s3-endpoint`, `serving.kserve.io/s3-usehttps: "0"`, and `serving.kserve.io/s3-region` annotations for KServe to locate the MinIO instance. Source: `deploy/helm/templates/secret-minio.yaml`.
- **Model upload Job uses retry loop for MinIO readiness:** The upload container polls MinIO with `mc alias set` up to 30 times with 2-second sleeps before uploading, since MinIO may not be ready when the Job starts. Source: `deploy/helm/templates/job-model-upload.yaml`.
- **Local compose uses MLServer image directly:** In local development (`deploy/local/compose.yml`), the MLServer container is built from the same Dockerfile and serves models from the baked-in image path, bypassing the MinIO upload step entirely.

## Testing Notes

- Verify the InferenceService reaches Ready state: `oc wait --for=condition=Ready isvc/guidelines-mlp -n <namespace> --timeout=10s`
- Confirm the model-upload Job completed (or was TTL-cleaned after success)
- Test the V2 inference endpoint directly: `POST /v2/models/guidelines-mlp/infer` with BYTES-typed text input
- Integration tests in `tests/integration/test_model_serving.py` validate InferenceService readiness, Job completion, and end-to-end guideline classification through both UI and direct orchestrator endpoints

## Related Patterns

- KServe InferenceService deployment patterns
- MinIO S3 model storage
- scikit-learn model serving
