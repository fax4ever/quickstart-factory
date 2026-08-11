---
name: clustering-service
description: FastAPI microservice serving a pre-trained scikit-learn clustering model loaded from MinIO object storage
summary: "Solves real-time scikit-learn clustering inference via FastAPI POST /cluster endpoint (InputData.embeddings: list[list[float]] returns labels) for assigning cluster IDs to embedding vectors, used in Ansible log analysis pipelines on OpenShift. Use when serving a pre-trained joblib-serialized scikit-learn model with MinIO-based artifact storage and conditional loading (MINIO_BUCKET_NAME toggles MinIO vs local file fallback); a planned migration to RHOAI model registry exists via an unwired load_from_model_registry function (model_registry==0.2.21) that shells out to oc whoami. Helm init container runs oc wait on backend-init job (requires batch jobs RBAC Role) to ensure MinIO bucket is populated before pod starts, with model credentials sourced from minio Secret keys (host/port/user/password), service on port 8001, and /health probes (readiness 5s, liveness 30s initial delay). Model loads at module global scope so MinIO unreachability crashes the pod immediately, MinIO client hardcodes secure=False with no TLS toggle env var, Containerfile unnecessarily sets HF_HOME=/hf_cache (carried from template), and readiness/liveness probe timing may need tuning for large models."
metadata:
  type: component
tags:
  tech_stack: [fastapi, python, scikit-learn, uvicorn, joblib, minio]
  ai_pattern: [model-serving, embeddings]
  platform: [openshift, kubernetes]
  data_layer: [minio]
source_examples:
  - quickstart: "ansible-log-analysis"
    repo: "https://github.com/rh-ai-quickstart/ansible-log-analysis"
    notes: "Clustering service that loads a joblib-serialized scikit-learn model from MinIO and exposes a /cluster prediction endpoint"
    approach: "A"
---

# Clustering Service

## Overview

A lightweight FastAPI microservice that serves a pre-trained scikit-learn clustering model for inference. The service loads a joblib-serialized model from MinIO object storage at startup and exposes a REST endpoint that accepts embedding vectors and returns cluster labels. In the ansible-log-analysis quickstart, it assigns cluster IDs to log embeddings as part of an Ansible log monitoring pipeline.

## Tech Stack & Dependencies

- **Runtime:** Python 3.12 on `registry.access.redhat.com/ubi8/python-312`
- **Container image:** `quay.io/rh-ai-quickstart/alm-clustering:latest`
- **Key dependencies:** FastAPI >= 0.116.1, scikit-learn >= 1.7.1, minio >= 7.2.17, uvicorn >= 0.37.0, model_registry == 0.2.21
- **Helm subchart:** `deploy/helm/ansible-log-monitor/charts/clustering` (application chart, v0.1.0)
- **Package management:** uv (copied from `ghcr.io/astral-sh/uv:0.9.7` in the container build)

## Key Patterns

### Model Loading with MinIO Fallback

The service uses a conditional loading strategy at startup: if `MINIO_BUCKET_NAME` is set, it loads the model from MinIO object storage; otherwise it falls back to a local file. This allows the same code to work in both local development and cluster deployment.

```python
# from services/clustering/main.py
if os.getenv("MINIO_BUCKET_NAME"):
    model: BaseEstimator = load_from_minio(
        os.getenv("MINIO_BUCKET_NAME"), "clustering_model.joblib"
    )
else:
    model = joblib.load("clustering_model.joblib")
```

### MinIO Client Model Retrieval

The model loader creates a MinIO client using environment variables and loads the joblib model directly into memory from the object store without writing to disk.

```python
# from services/clustering/model_loader.py
minio_client = Minio(
    endpoint=f"{endpoint}:{port}",
    access_key=access_key,
    secret_key=secret_key,
    secure=False,
)
response = minio_client.get_object(bucket_name, file_name)
with io.BytesIO() as buffer:
    buffer.write(response.data)
    buffer.seek(0)
    return joblib.load(buffer)
```

### Init Container Job Dependency

The Helm deployment uses an init container with `quay.io/openshift/origin-cli:latest` to wait for a backend init job to complete before starting the clustering pod. This ensures the MinIO bucket and model artifact are populated before the service tries to load the model.

```yaml
# from charts/clustering/templates/deployment.yaml
initContainers:
  - name: wait-for-{{ .Values.global.servicesNames.backend }}-init
    image: quay.io/openshift/origin-cli:latest
    command:
      - sh
      - -c
      - |
        oc wait --for=condition=complete --timeout=600s \
          job/{{ .Values.global.servicesNames.backend }}-init \
          -n {{ .Release.Namespace }}
```

### RBAC for Init Container

The init container uses `oc wait` to watch batch jobs, so the chart creates a Role and RoleBinding granting `get`, `list`, `watch` on jobs in the `batch` API group to the service account.

```yaml
# from charts/clustering/templates/role.yaml
rules:
  - apiGroups: ["batch"]
    resources: ["jobs"]
    verbs: ["get", "list", "watch"]
```

### Prediction Endpoint

The `/cluster` POST endpoint accepts a 2D array of embedding vectors and returns cluster labels from the loaded scikit-learn model.

```python
# from services/clustering/main.py
class InputData(BaseModel):
    embeddings: list[list[float]]  # 2D array: list of embedding vectors

@app.post("/cluster")
def predict(data: InputData):
    input_array = np.array(data.embeddings)
    prediction = model.predict(input_array)
    return {"labels": prediction.tolist()}
```

### Container Build with uv

The Containerfile uses the `uv` package manager copied from the official image, runs `uv sync --no-dev` for reproducible dependency installation, and sets up a HuggingFace cache directory with open permissions.

```dockerfile
# from services/clustering/Containerfile
FROM registry.access.redhat.com/ubi8/python-312
COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml ./
RUN uv sync --no-dev
ENV VIRTUAL_ENV=/app/.venv
ENV PATH="/app/.venv/bin:$PATH"
ENV HF_HOME=/hf_cache
```

## Configuration

- **Environment variables:**
  - `MINIO_ENDPOINT` - MinIO host (from `minio` Secret, key `host`)
  - `MINIO_PORT` - MinIO port (from `minio` Secret, key `port`)
  - `MINIO_ACCESS_KEY` - MinIO access key (from `minio` Secret, key `user`)
  - `MINIO_SECRET_KEY` - MinIO secret key (from `minio` Secret, key `password`)
  - `MINIO_BUCKET_NAME` - Bucket containing the model artifact (defaults to `clustering-model` in Helm values)
  - `MODEL_REGISTRY_NAMESPACE` - Namespace for RHOAI model registry (used by alternate `load_from_model_registry` path)
  - `MODEL_REGISTRY_CONTAINER` - Service name for model registry (used by alternate loader)
- **Config files:** None; all configuration is via environment variables
- **Helm values:**
  - `image.repository` / `image.tag` - Container image coordinates
  - `service.port` / `service.targetPort` - Both default to `8001`
  - `env` - Array of environment variable definitions referencing the `minio` Secret
  - `rbac.create` - Whether to create the Role/RoleBinding for init container job watching (default `true`)

## Known Gotchas

- The model is loaded at module import time (global scope in `main.py`), not lazily. If MinIO is unreachable or the model artifact is missing at startup, the pod will crash immediately. The init container mitigating this waits on the backend-init job, not on MinIO readiness directly.
- The `TODO` comment in `main.py` line 10 notes the intent to switch from MinIO to the RHOAI model registry for cluster deployments. A `load_from_model_registry` function exists in `model_loader.py` but is not wired into `main.py` yet.
- The `load_from_model_registry` function shells out to `oc whoami` and `oc whoami -t` to get credentials, which requires the `oc` CLI to be available in the container and an active OpenShift session -- this would not work in a standard container without additional setup.
- The MinIO client is configured with `secure=False` (no TLS). The comment in `model_loader.py` line 32 says "Set to True if using HTTPS" but there is no environment variable to toggle this.
- `readinessProbe` has `initialDelaySeconds: 5` while `livenessProbe` has `initialDelaySeconds: 30`, giving the model 25 seconds to load before liveness checks begin. If the model is large, this may need tuning.
- The Containerfile creates an `HF_HOME=/hf_cache` directory even though this service does not use HuggingFace directly -- this appears to be carried over from another service's Containerfile template.

## Testing Notes

- Health check available at `GET /health` returning `{"status": "healthy"}`
- Kubernetes probes are configured against `/health` on the `http` named port
- Test the prediction endpoint with: `POST /cluster` with body `{"embeddings": [[0.1, 0.2, ...], [0.3, 0.4, ...]]}`
- The Helm chart includes a test connection template at `templates/tests/test-connection.yaml`

## Related Patterns

- MinIO object storage for model artifacts (see `minio.md`)
- Model serving patterns for scikit-learn vs deep learning models (see `model-serving.md`)
- FastAPI backend patterns (see `fastapi-backend.md`)
