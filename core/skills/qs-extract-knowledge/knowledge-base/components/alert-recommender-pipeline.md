---
name: alert-recommender-pipeline
description: "FastAPI + Kubeflow ML pipeline for KNN-based alert recommendation training, model storage, and KServe deployment on RHOAI"
summary: "Orchestrates end-to-end KNN alert recommendation on RHOAI via a FastAPI service wrapping Kubeflow Pipelines v2 — three-source data preparation (PostgreSQL → MinIO → local fallback chain), scikit-learn model training, MinIO artifact storage via boto3, optional Model Registry v1alpha3 registration, and KServe RawDeployment with a custom AlertRecommenderModel (joblib-deserialized scaler, knn_model, alert_labels, threshold) served by MLServer sklearn runtime. Use when building a programmatic KFP pipeline service with DSPA-managed infrastructure (MariaDB metadata store, MinIO artifact store) and REST-triggered runs rather than KFP UI — Helm chart deploys the DSPA CR, init containers sequence startup by waiting for database migration and MinIO health. All KFP tasks receive config through a single Kubernetes Secret compiled from a PipelineRequest Pydantic model and injected via `kfp.kubernetes.use_secret_as_env`; KServe InferenceService uses RawDeployment mode with a `storage-config` Secret pointing to MinIO, and pods require `opendatahub.io/workbenches: \"true\"` label for DSPA NetworkPolicy access. Critical gotchas: numpy must be <2.0 and scikit-learn <1.7.0 to match MLServer sklearn runtime; each @dsl.component must embed all code inline (model class stored as string literal to avoid import chain issues); database init container exits 0 on failure intentionally for cold-start fallback to MinIO data; pipeline caching is explicitly disabled via `set_caching_options(False)`; and BuildConfig `contextDir: ml-pipeline` means COPY paths are relative to that subdirectory not the repo root."
metadata:
  type: component
tags:
  tech_stack: [fastapi, python, scikit-learn, kubeflow-pipelines, mlserver, minio, postgresql, kserve, boto3, pydantic]
  ai_pattern: [data-pipeline, model-serving, recommendations]
  platform: [rhoai, openshift, kserve, vllm]
  data_layer: [minio, postgresql]
source_examples:
  - quickstart: "spending-transaction-monitor"
    repo: "https://github.com/rh-ai-quickstart/spending-transaction-monitor"
    notes: "End-to-end Kubeflow pipeline service orchestrating KNN model training, MinIO model storage, optional Model Registry, and KServe InferenceService deployment"
    approach: "A"
---

# Alert Recommender Pipeline

## Overview

A FastAPI microservice that wraps Kubeflow Pipelines v2 (KFP) to orchestrate an end-to-end ML workflow: data preparation from PostgreSQL or MinIO, KNN model training with scikit-learn, model artifact storage in MinIO, optional registration in RHOAI Model Registry, and deployment as a KServe InferenceService using MLServer. The service exposes REST endpoints to trigger, monitor, and clean up pipeline runs, and is deployed alongside a DataSciencePipelinesApplication (DSPA) on OpenShift AI.

## Tech Stack & Dependencies

- **Runtime:** Python 3.12 on `registry.access.redhat.com/ubi9/python-312:latest`
- **Container image:** `quay.io/rh-ai-quickstart/alert-recommender-pipeline:latest`
- **Key dependencies:**
  - `fastapi>=0.109.0` / `uvicorn>=0.27.0` -- REST API service
  - `kfp>=2.7.0` / `kfp-kubernetes>=1.1.0` -- pipeline compilation, upload, run
  - `kubernetes>=29.0.0` -- in-cluster K8s API calls (secrets, InferenceService, ServingRuntime)
  - `scikit-learn>=1.4.0,<1.7.0` -- KNN model (must match MLServer sklearn version)
  - `numpy>=1.24.0,<2.0` -- pinned below 2.0 for MLServer sklearn compatibility
  - `pandas>=2.0.0` -- feature engineering
  - `boto3>=1.34.0` -- MinIO / S3 model upload
  - `psycopg2-binary>=2.9.0` -- PostgreSQL data loading
  - `joblib>=1.3.0` -- model serialization (MLServer loading format)
- **Helm subchart:** `alert-recommender-pipeline` chart v0.1.0, depends on optional `model-registry` subchart from `ai-architecture-charts`

## Key Patterns

### FastAPI Pipeline Orchestrator

The service acts as a thin REST layer over KFP, compiling and submitting pipelines programmatically rather than through the KFP UI. Pipeline config is stored as a Kubernetes Secret so every KFP task can read it via `kfp.kubernetes.use_secret_as_env`.

```python
# From pipelines/__init__.py -- compile and submit pattern
with tempfile.NamedTemporaryFile(suffix=".yaml") as tmp:
    compiler.Compiler().compile(
        pipeline_func=pipelines.alert_recommender_pipeline(**pipeline_params),
        package_path=tmp.name,
    )
    tmp.flush()
    client = Client(host=os.environ["DS_PIPELINE_URL"], verify_ssl=False)
    pipeline_id = client.get_pipeline_id(pipeline_name)
    # Upload new or versioned pipeline, then run
```

### Multi-Source Data Preparation with Fallback Chain

The `prepare_data` task tries three data sources in order: PostgreSQL database, MinIO S3, then local filesystem. This lets the pipeline work both in production (live DB) and in cold-start scenarios (seeded MinIO data).

```python
# From pipelines/tasks/data_tasks.py -- fallback chain
try:
    users_df, transactions_df, use_real_alerts = load_from_database()
    data_source_used = 'database'
except Exception as e:
    try:
        users_df, transactions_df, use_real_alerts = load_from_minio()
        data_source_used = 'minio'
    except Exception as e2:
        users_df, transactions_df, use_real_alerts = load_from_local()
        data_source_used = 'local'
```

### KFP Secret-Based Configuration

All pipeline tasks receive configuration through a single Kubernetes Secret injected via `kfp.kubernetes.use_secret_as_env`. The secret is created from the `PipelineRequest` Pydantic model before pipeline submission.

```python
# From pipelines/pipelines.py -- secret injection across all tasks
for task in pipeline_tasks:
    kubernetes.use_secret_as_env(
        task=task,
        secret_name=pipeline_name,
        secret_key_to_env=secret_key_to_env
    )
```

### Custom MLServer Model Implementation

The pipeline uploads a custom `AlertRecommenderModel` class (extending `MLModel`) alongside the serialized model to MinIO. The model-settings.json points to this custom implementation for inference.

```python
# From pipelines/tasks/mlserver_model.py
class AlertRecommenderModel(MLModel):
    async def load(self) -> bool:
        model_uri = self.settings.parameters.uri
        self._components = joblib.load(model_uri)
        self._scaler = self._components['scaler']
        self._knn_model = self._components['knn_model']
        self._alert_labels = self._components['alert_labels']
        self._alert_types = self._components['alert_types']
        self._threshold = self._components['threshold']
        self.ready = True
        return self.ready
```

### KServe RawDeployment with MinIO Storage

The deploy task creates an InferenceService in `RawDeployment` mode pointing to a MinIO S3 bucket. It provisions a `storage-config` Secret, a dedicated ServiceAccount, and optionally a ServingRuntime.

```yaml
# From deployment/inference-service.yaml
apiVersion: serving.kserve.io/v1beta1
kind: InferenceService
metadata:
  annotations:
    serving.kserve.io/deploymentMode: RawDeployment
spec:
  predictor:
    minReplicas: 1
    maxReplicas: 3
    model:
      modelFormat:
        name: sklearn
      runtime: mlserver-sklearn
      storage:
        key: minio-secret
        parameters:
          endpoint: http://minio-service.{{ namespace }}.svc.cluster.local:9000
```

### DSPA (DataSciencePipelinesApplication) Integration

The Helm chart deploys a DSPA custom resource that provisions the Kubeflow Pipelines infrastructure (MariaDB metadata store, MinIO artifact store) on OpenShift AI.

```yaml
# From templates/dspa.yaml
apiVersion: datasciencepipelinesapplications.opendatahub.io/v1
kind: DataSciencePipelinesApplication
metadata:
  name: {{ .Values.dspa.name }}
spec:
  dspVersion: v2
  database:
    mariaDB:
      deploy: true
  objectStorage:
    minio:
      deploy: true
```

### Init Container Readiness Chain

The Helm deployment uses init containers to sequence startup: first wait for database migration (check for `users` table), then wait for DSPA and MinIO health endpoints. This prevents the pipeline service from starting before its dependencies are ready.

```yaml
# From templates/deployment.yaml -- database migration wait
- name: wait-for-database-tables
  image: "postgres:16-alpine"
  command:
    - /bin/sh
    - -c
    - |
      TABLE_EXISTS=$(psql -h "$PGHOST" -d "$PGDATABASE" -t -c \
        "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'users';")
      # Retry loop, exits 0 even on failure (pipeline falls back to MinIO)
```

### Model Registry Integration

The pipeline optionally registers trained models with the RHOAI Model Registry (v1alpha3 API). Registration creates a RegisteredModel, ModelVersion, and ModelArtifact. Deployment can then pull model info from the registry instead of pipeline artifacts.

```python
# From pipelines/tasks/registry_tasks.py -- idempotent registration
create_payload = {
    "name": model_name,
    "state": "LIVE",
    "description": "KNN-based collaborative filtering model for alert recommendations",
    "customProperties": {
        "framework": {"metadataType": "MetadataStringValue", "string_value": "sklearn"},
        "algorithm": {"metadataType": "MetadataStringValue", "string_value": "KNN"},
    }
}
```

## Configuration

- **Environment variables:**
  - `DS_PIPELINE_URL` -- Kubeflow Pipelines API endpoint (e.g., `https://ds-pipeline-dspa:8888`)
  - `ALERT_RECOMMENDER_PIPELINE_IMAGE` -- base image for KFP task containers (defaults to `quay.io/rh-ai-quickstart/alert-recommender-pipeline:latest`)
  - `POSTGRES_DB_HOST`, `POSTGRES_DB_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` -- database connection for training data
  - `MINIO_ENDPOINT`, `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`, `BUCKET_NAME` -- MinIO for model storage
  - `MODEL_REGISTRY_URL`, `MODEL_REGISTRY_ENABLED` -- optional RHOAI Model Registry
  - `SERVING_RUNTIME`, `SERVING_RUNTIME_IMAGE`, `CREATE_SERVING_RUNTIME` -- KServe serving runtime config
  - `DEPLOY_MODEL`, `DEPLOY_FROM_REGISTRY`, `MODEL_VERSION_TO_DEPLOY` -- deployment behavior toggles
- **Config files:**
  - `pyproject.toml` -- package metadata and dependency pins
  - `requirements.txt` -- pip dependencies with compatibility comments
  - `constants.py` -- shared defaults (alert types, feature columns, image refs, API versions)
- **Helm values:**
  - `dspa.deploy` -- whether to create a DSPA CR (default `true`)
  - `minio.deploy` / `minio.endpoint` -- MinIO for model artifacts
  - `modelRegistry.enabled` / `modelRegistry.url` -- Model Registry integration
  - `pipelines.alert_recommender.*` -- pipeline hyperparameters (nNeighbors, metric, threshold)
  - `serving.runtime.create` -- whether the Helm chart creates the ServingRuntime
  - `database.waitForMigration` / `database.migrationTimeout` -- init container behavior

## Known Gotchas

- **numpy must be <2.0:** The `pyproject.toml` pins `numpy>=1.24.0,<2.0` with the comment "Must be <2.0 for MLServer sklearn compatibility." Breaking this constraint causes runtime failures in the MLServer inference container.
- **scikit-learn version must match MLServer:** The `requirements.txt` comments note `scikit-learn>=1.4.0,<1.7.0` with "Must match MLServer sklearn version (1.6.x)." A mismatch causes deserialization failures when loading the model.
- **KFP task code is self-contained:** Each `@dsl.component` function must embed all imports and logic inside the function body because KFP extracts only the function source. The `save_model` task embeds the entire `AlertRecommenderModel` class as a string literal (`model_impl_code`) rather than importing it, with the comment: "Embedded MLServer model implementation to avoid import chain issues at runtime."
- **DSPA NetworkPolicy label required:** The Helm deployment template adds `opendatahub.io/workbenches: "true"` label to pod metadata with the comment "Required for DSPA NetworkPolicy to allow traffic." Without this label, pipeline task pods cannot reach the DSPA API.
- **Pipeline caching is explicitly disabled:** Every task calls `task.set_caching_options(False)` in the pipeline definition to ensure fresh runs, presumably because training data changes between runs.
- **Database wait exits 0 on failure:** The init container that checks for database tables exits 0 even if tables are not found, with the comment "Migration may not have run. Pipeline will fall back to MinIO data." This is intentional to avoid blocking deployment in cold-start scenarios.
- **OpenShift BuildConfig uses contextDir:** The `build.yaml` sets `contextDir: ml-pipeline` so the build context is the `ml-pipeline/` directory, not the repo root. The Containerfile paths (`COPY alert-recommender-pipeline/src/...`) are relative to that context.

## Testing Notes

- Health check endpoints: `GET /ping` returns `{"status": "ok"}`, `GET /health` returns version info
- After Helm install, verify the DSPA is ready: `oc get dspa -n <namespace>`
- Verify the pipeline service pod is running and init containers completed: `oc get pods -l app.kubernetes.io/name=alert-recommender-pipeline`
- Trigger a test pipeline: `curl -X POST http://<service>:8080/train -H 'Content-Type: application/json' -d '{"name":"alert-recommender","version":"1.0.0"}'`
- Check pipeline status: `curl http://<service>:8080/status?pipeline_name=alert-recommender-v1-0-0`
- Verify InferenceService deployment: `oc get inferenceservice alert-recommender -n <namespace>`
- Verify model endpoint with KServe v2 protocol: `curl http://alert-recommender-predictor.<namespace>.svc.cluster.local:8080/v2/models/alert-recommender`

## Related Patterns

- KServe InferenceService deployment (RawDeployment mode with MinIO storage)
- DSPA / DataSciencePipelinesApplication on RHOAI
- MLServer sklearn serving runtime
- Model Registry v1alpha3 API integration
- MinIO as S3-compatible model artifact store
