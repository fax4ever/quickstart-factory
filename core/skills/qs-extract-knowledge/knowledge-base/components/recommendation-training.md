---
name: recommendation-training
description: "KFP v2 pipeline runner that loads Feast data, trains a two-tower model, stores artifacts in MinIO, and pushes embeddings back to Feast"
summary: "Orchestrates a full recommendation model training lifecycle on RHOAI by compiling a KFP v2 pipeline and submitting it to a DSPA endpoint (DS_PIPELINE_URL), executing three stages on a shared recommendation-core base image (BASE_REC_SYS_IMAGE): Feast data loading with streaming PostgreSQL table merge, two-tower PyTorch model training with versioned MinIO artifact storage and PostgreSQL model_version tracking, and candidate generation producing item/user plus CLIP image embeddings pushed to Feast online store via PushMode.ONLINE and materialize_incremental. Use when building end-to-end recommendation pipelines on RHOAI requiring Feast feature store integration, versioned model storage in MinIO, and scheduled retraining -- the runner container only compiles and submits pipeline YAML while actual ML steps run in separate pods; secrets are injected via kfp.kubernetes use_secret_as_env()/use_secret_as_volume() helpers. Deployed as Helm Job + daily CronJob (concurrencyPolicy: Forbid) with idempotent lookup guards preventing duplicate resources on upgrade; init containers block until DSPA health at ds-pipeline-dspa:8888/apis/v2beta1/healthz and feast-apply-job completion are confirmed before the runner starts. Pipeline step caching explicitly disabled via set_caching_options(False), device hardcoded to CPU (CUDA check commented out), resource requests hardcoded in Python not Helm values (TODO exists), categorical features commented out, Containerfile runs as root with chmod -R 777, store.refresh_registry() workaround required before pushing text feature embeddings, hardcoded Feast feature_repo path depends on recommendation-core image structure, and generate_candidates adds disk-pressure toleration for ephemeral storage limits."
metadata:
  type: component
tags:
  tech_stack: [python, pytorch, kfp, feast, minio, pandas, sqlalchemy, clip]
  ai_pattern: [data-pipeline, embeddings, model-serving, fine-tuning]
  platform: [rhoai, openshift, kubeflow-pipelines]
  data_layer: [postgresql, minio, feast]
source_examples:
  - quickstart: "product-recommender-system"
    repo: "https://github.com/rh-ai-quickstart/product-recommender-system"
    notes: "KFP v2 pipeline with three-stage workflow: Feast data loading, two-tower model training, and candidate generation with embedding push"
    approach: "A"
---

# Recommendation Training

## Overview

This component is a Kubeflow Pipelines v2 (KFP) pipeline runner that orchestrates the full recommendation model training lifecycle. It compiles and submits a three-step pipeline (load data, train model, generate candidates) to a DataSciencePipelinesApplication (DSPA) instance on RHOAI. The runner container itself does not perform training directly -- it uses `kfp.compiler` to produce a pipeline YAML and then submits it to the KFP API server, which schedules each step as a separate pod using a shared base image (`recommendation-core`).

## Tech Stack & Dependencies

- **Runtime:** Python 3.11 on `registry.access.redhat.com/ubi9/python-311`
- **Container image:** `quay.io/rh-ai-quickstart/recommendation-training:latest`
- **Key dependencies:** `kfp==2.11.0`, `kfp-kubernetes>=1.4.0`, `tabulate>=0.9.0`
- **Pipeline step base image:** `quay.io/rh-ai-quickstart/recommendation-core:latest` (set via `BASE_REC_SYS_IMAGE` env var)
- **Package manager:** `uv` (installed via pip inside the Containerfile, used to sync dependencies)
- **Helm value:** `pipelineJobImage` in `helm/product-recommender-system/values.yaml`

## Key Patterns

### KFP v2 Pipeline Compilation and Submission

The component compiles a Python-defined pipeline to YAML and submits it to the DSPA endpoint. The pipeline name and run name are set via environment variables:

```python
# from train-workflow.py
compiler.Compiler().compile(
    pipeline_func=batch_recommendation, package_path=pipeline_yaml
)
client = Client(host=os.environ["DS_PIPELINE_URL"], verify_ssl=False)
run = client.create_run_from_pipeline_package(
    pipeline_file=pipeline_yaml, arguments={}, run_name=os.environ["RUN_NAME"]
)
```

### Three-Stage Pipeline Architecture

The pipeline defines three sequential KFP components, each running in its own pod with the `recommendation-core` base image:

1. **`load_data_from_feast`** -- Loads item, user, and interaction datasets from Feast feature store, optionally merging in streaming users and interactions from PostgreSQL tables (`users`, `stream_interaction`).
2. **`train_model`** -- Trains a two-tower recommendation model via `create_and_train_two_tower()`, saves PyTorch state dicts, uploads the user encoder to MinIO, and tracks model version in a PostgreSQL `model_version` table.
3. **`generate_candidates`** -- Loads trained encoders, generates item/user embeddings, pushes them to Feast online store, computes CLIP-based image embeddings, and pre-calculates top-k item recommendations per user via `store.retrieve_online_documents()`.

### Kubernetes Secret Mounting via KFP SDK

Secrets are injected into pipeline steps using `kfp.kubernetes` helpers rather than pod-level volume definitions:

```python
# from train-workflow.py
kubernetes.use_secret_as_env(
    task=task,
    secret_name=os.getenv("DB_SECRET_NAME", "cluster-sample-app"),
    secret_key_to_env={
        "uri": "uri",
        "password": "DB_PASSWORD",
        "host": "DB_HOST",
        "dbname": "DB_NAME",
        "user": "DB_USER",
        "port": "DB_PORT",
    },
)
kubernetes.use_secret_as_volume(
    task=task,
    secret_name=os.getenv("FEAST_SECRET_NAME", "feast-feast-recommendation-registry-tls"),
    mount_path="/app/feature_repo/secrets",
)
```

### Helm Job + CronJob Deployment

The training image is deployed as both a one-time Kubernetes Job and a daily CronJob via Helm templates. Both use idempotent lookup guards to avoid duplicates:

```yaml
# from helm/product-recommender-system/templates/run-pipeline-job.yaml
{{- $jobName := "kfp-run-job" }}
{{- $existingJob := (lookup "batch/v1" "Job" .Release.Namespace $jobName) }}
{{- if not $existingJob }}
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ $jobName }}
```

The CronJob runs on a `"0 0 * * *"` schedule (daily at midnight) with `concurrencyPolicy: Forbid`.

### Init Container Wait Pattern

The Helm job template includes two init containers that block until prerequisites are ready before the pipeline runner starts:

```yaml
# from helm/product-recommender-system/templates/_helpers.tpl
initContainers:
  - name: wait-for-pipeline
    image: {{ .Values.pipelineJobImage }}
    command:
      - /bin/bash
      - -c
      - |
        set -e
        url="https://ds-pipeline-dspa:8888/apis/v2beta1/healthz"
        until curl -ksf "$url"; do sleep 10; done
  - name: wait-for-feast-apply
    image: registry.redhat.io/openshift4/ose-cli:latest
    command:
      - /bin/bash
      - -c
      - |
        set -e
        until oc get job feast-apply-job -n {{ .Release.Namespace }} \
          -o jsonpath='{.status.conditions[?(@.type=="Complete")].status}' \
          | grep -q "True"; do sleep 10; done
```

### Model Versioning via PostgreSQL

Model versions are tracked in a `model_version` table. The table is auto-created on first run. Subsequent runs increment the patch version:

```python
# from train-workflow.py, train_model component
last_version = connection.execute(
    text("SELECT version FROM model_version ORDER BY id DESC LIMIT 1")
).scalar()
major, minor, patch = map(int, last_version.split("."))
new_version = f"{major}.{minor}.{patch + 1}"
```

### MinIO Model Storage

Trained model artifacts are uploaded to MinIO using versioned object names:

```python
# from train-workflow.py, train_model component
bucket_name = "user-encoder"
object_name = f"user-encoder-{new_version}.pth"
configuration = f"user-encoder-config-{new_version}.json"
minio_client.fput_object(
    bucket_name=bucket_name,
    object_name=object_name,
    file_path=user_output_model.path,
)
```

### Feast Feature Store Integration

The `generate_candidates` step pushes multiple embedding types to the Feast online store and then materializes feature views:

```python
# from train-workflow.py, generate_candidates component
store.push("item_embed_push_source", item_embed_df,
           to=PushMode.ONLINE, allow_registry_cache=False)
store.materialize_incremental(current_time, feature_views=[
    "item_embedding", "user_items", "item_features",
    "item_textual_features_embed", "item_name_features_embed",
    "item_category_features_embed",
])
```

## Configuration

- **Environment variables:**
  - `DS_PIPELINE_URL` -- DSPA endpoint (set in Helm template, e.g., `https://ds-pipeline-dspa.<namespace>.svc.cluster.local:8888`)
  - `PIPELINE_NAME` -- Pipeline display name in KFP UI (default: `batch_training`)
  - `RUN_NAME` -- Unique run identifier, auto-generated with timestamp in Helm args
  - `BASE_REC_SYS_IMAGE` -- Base image for KFP pipeline steps (default: `quay.io/rh-ai-quickstart/recommendation-core:latest`)
  - `DB_SECRET_NAME` -- Kubernetes secret containing PostgreSQL connection details (default: `cluster-sample-app`)
  - `MINIO_SECRET_NAME` -- Kubernetes secret for MinIO credentials (default: `ds-pipeline-s3-dspa`)
  - `FEAST_SECRET_NAME` -- TLS secret for Feast registry connection
  - `FEAST_PROJECT_NAME` -- Feast project name (default: `feast_rec_sys`)
  - `FEAST_REGISTRY_URL` -- Feast registry service URL
  - `DATASET_URL` -- Optional external dataset URL; when set, uses `RemoteDatasetProvider` instead of local Feast data
- **Config files:** `recommendation-training/pyproject.toml` (Python dependencies)
- **Helm values:** `pipelineJobImage`, `applicationImage`, `feast.project`, `feast.secret`, `feast.registry`

## Known Gotchas

- **Pipeline step caching is explicitly disabled.** All three pipeline steps call `.set_caching_options(False)`, meaning every run re-executes fully. This is intentional for a training workflow where data changes between runs, as seen in `train-workflow.py`.
- **Device is hardcoded to CPU.** In `generate_candidates`, the code contains a commented-out CUDA check and forces `device = torch.device("cpu")`. This limits inference speed for embedding generation.
- **Categorical features are commented out.** Multiple sections in `generate_candidates` have categorical feature handling commented out (lines creating `TensorDataset`, batch processing), suggesting this code path was disabled during development. Only numerical and text features are active.
- **Resource requests are hardcoded in Python, not Helm.** Each pipeline step has CPU/memory requests set directly in the KFP Python code (e.g., `set_cpu_request("6000m")`, `set_memory_request("4000Mi")`), not via Helm values. The code includes a TODO comment: `# setting resource requests and limits - TODO: use from environment variables`.
- **Disk pressure toleration.** The `generate_candidates` task adds a toleration for `node.kubernetes.io/disk-pressure` with `NoExecute` effect, indicating this step can hit ephemeral storage limits on the node.
- **`store.refresh_registry()` called before pushing text features.** An explicit registry refresh is done before pushing text feature embeddings, with a log message noting it was added to pick up updated feature view schemas. This was likely a fix for a runtime error.
- **Feast feature store path is hardcoded.** The code references `src/recommendation_core/feature_repo/` as a relative path, which depends on the directory structure inside the `recommendation-core` base image.
- **The Containerfile runs as root.** `USER root` is set, and then `chmod -R 777 .` is applied to the working directory. This is required because the KFP executor may run as a different UID.
- **Idempotent Helm Job/CronJob creation.** The Helm template uses `lookup` to check if the Job or CronJob already exists before creating it, preventing Helm upgrade failures from duplicate resources.

## Testing Notes

- Verify the DSPA health endpoint is reachable at `https://ds-pipeline-dspa:8888/apis/v2beta1/healthz` before the pipeline runner starts.
- Check that the `feast-apply-job` has completed successfully before the runner proceeds (the init container handles this).
- After a successful pipeline run, verify that the `model_version` table in PostgreSQL has been incremented.
- Confirm embeddings are present in the Feast online store by querying feature views like `item_embedding` and `user_items`.
- Monitor the `user-encoder` bucket in MinIO for new versioned `.pth` and `.json` files.

## Related Patterns

- Feast feature store configuration: see `featurestore` Helm template
- MinIO object storage: shared infrastructure used for both pipeline artifacts and model storage
- DSPA setup: see `helm/pipeline-server/` for the DataSciencePipelinesApplication definition
- `recommendation-core` base image: contains the actual ML code (`recommendation_core` package) used by all pipeline steps
