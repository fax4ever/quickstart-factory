---
name: model-to-bucket-notebook
description: "Jupyter notebook for downloading HuggingFace models file-by-file and uploading to MinIO with immediate cleanup"
summary: "Downloads HuggingFace models file-by-file via hf_hub_download/list_repo_files and uploads each to MinIO via minio SDK fput_object with immediate os.remove() cleanup, keeping RHOAI workbench PVC disk usage bounded to one file at a time for subsequent OpenShift AI single-model serving. Use when workbench PVC space is limited and bulk snapshot_download would exceed disk — alternatives include boto3-based bulk download (notebooks.md Approach A) or KFP pipeline ingestion (Approach B). All config is hardcoded in notebook cells — MINIO_ENDPOINT placeholder, secure=False for non-TLS in-cluster MinIO, HF_HOME isolated via tempfile.mkdtemp(), default credentials minio/minio123; post-upload, Helm values llmModel.modelEndpoint/llmModel.ollamaModel wire the served model to the backend which validates via assert MODEL_ENDPOINT is not None and appends /v1/chat/completions. fput_object has no retry and failed uploads still delete the local file via os.remove(); no bucket auto-creation; local_dir_use_symlinks=False is deprecated; gated models like Llama 3.1 require huggingface_token; boto3 is imported but unused; variable MINIO_ACSSESS_KEY is misspelled in source; model serving recommends --max-model-len=8192."
metadata:
  type: component
tags:
  tech_stack: [jupyter, python, minio, huggingface-hub, boto3]
  ai_pattern: [model-serving, data-pipeline]
  platform: [rhoai, openshift, vllm]
  data_layer: [minio]
source_examples:
  - quickstart: "product-recommender-system"
    repo: "https://github.com/rh-ai-quickstart/product-recommender-system"
    notes: "File-by-file HuggingFace model download with minio SDK upload and per-file cleanup for memory efficiency"
    approach: "A"
---

# Model-to-Bucket Notebook

## Overview

A Jupyter notebook designed to run inside an RHOAI workbench that downloads an LLM model from HuggingFace Hub and uploads it to a MinIO bucket for subsequent serving via OpenShift AI single-model serving. Unlike bulk `snapshot_download` approaches, this notebook downloads and uploads files individually, deleting each local copy immediately after upload to minimize disk usage on the workbench PVC.

## Tech Stack & Dependencies

- **Runtime:** Python (RHOAI workbench image)
- **Container image:** Standard RHOAI workbench image (no custom Dockerfile)
- **Key dependencies:**
  - `huggingface_hub` (`hf_hub_download`, `list_repo_files`) -- file-level model download
  - `boto3` -- imported but not used (minio SDK used instead)
  - `minio` -- S3-compatible client for uploading to MinIO
- **Helm subchart:** None (notebook is run manually in an RHOAI workbench, not deployed as a service)

## Key Patterns

### File-by-File Download and Upload with Immediate Cleanup

Rather than downloading the entire model snapshot to disk first, the notebook iterates over all files in the HuggingFace repo, downloads each file individually via `hf_hub_download`, uploads it to MinIO via `fput_object`, then immediately deletes the local copy. This keeps disk usage bounded to a single file at a time.

```python
# model_to_bucket.ipynb
files = list_repo_files(repo_id=repo_id, revision=revision, token=huggingface_token)

for file in files:
    try:
        temp_path = hf_hub_download(
            repo_id=repo_id,
            filename=file,
            revision=revision,
            cache_dir=os.environ['HF_HOME'],
            local_dir_use_symlinks=False,
        )
        try:
            client.fput_object(bucket_name, file, temp_path)
        except S3Error as e:
            print("Error occurred: ", e)
        os.remove(temp_path)
    except Exception as e:
        print(f"Error processing {file}: {e}")
```

### HuggingFace Cache Isolation

The notebook disables the default HuggingFace cache and redirects `HF_HOME` to a temporary directory, preventing interference with any other workbench notebooks sharing the same PVC.

```python
# model_to_bucket.ipynb
os.environ['HF_HUB_DISABLE_SYMLINKS_WARNING'] = '1'
os.environ['HF_HUB_ENABLE_HF_TRANSFER'] = '0'
os.environ['HF_HOME'] = tempfile.mkdtemp()
```

### MinIO Client with Hardcoded Credentials

The notebook uses the `minio` Python SDK (not boto3) to create a client with hardcoded placeholder credentials. The `secure=False` flag is set for in-cluster MinIO without TLS.

```python
# model_to_bucket.ipynb
MINIO_ENDPOINT = "SET BUCKET ENDPOINT"
MINIO_ACSSESS_KEY = "minio"
MINIO_SECRET_KEY = "minio123"

client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACSSESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=False
)
```

### Model Serving Integration via Helm Values

After uploading the model to MinIO, the model is served via OpenShift AI single-model serving. The model name and endpoint URL are passed to the Helm chart at install time and consumed by the FastAPI backend as environment variables.

```yaml
# helm/product-recommender-system/values.yaml (lines 226-231)
llmModel:
  ollamaModel: <this is used to set the ollama model used for the reviews summarization>
  modelEndpoint: <this is the url of the model that used to summarize the reviews>
```

```makefile
# helm/Makefile (lines 37-39)
model_args = \
    --set llmModel.ollamaModel=$(MODEL_NAME) \
    --set llmModel.modelEndpoint=$(MODEL_ENDPOINT)
```

The backend consumes these as environment variables with assertion-based validation at startup:

```python
# backend/src/routes/reviews.py (lines 18-24)
MODEL_ENDPOINT = os.getenv("MODEL_ENDPOINT")
MODEL_NAME = os.getenv("MODEL_NAME")

assert MODEL_ENDPOINT is not None, "Must assign value to model endpoint"
assert MODEL_NAME is not None, "Must assign value to model name"

MODEL_ENDPOINT = MODEL_ENDPOINT + "/v1/chat/completions"
```

## Configuration

- **Environment variables:** None (all config is inline in notebook cells as hardcoded values)
- **Notebook-level config (must be edited before running):**
  - `MINIO_ENDPOINT` -- MinIO API endpoint (placeholder: `"SET BUCKET ENDPOINT"`)
  - `MINIO_ACSSESS_KEY` -- MinIO access key (default: `"minio"`)
  - `MINIO_SECRET_KEY` -- MinIO secret key (default: `"minio123"`)
  - `repo_id` -- HuggingFace model repo (default: `"meta-llama/Llama-3.1-8B-Instruct"`)
  - `revision` -- model revision (default: `"main"`)
  - `bucket_name` -- target MinIO bucket (placeholder: `"your-bucket"`)
  - `huggingface_token` -- HuggingFace token for gated models (default: `None`)
- **Config files:** None
- **Helm values:** `llmModel.ollamaModel` and `llmModel.modelEndpoint` must be set at install time via `MODEL_NAME` and `MODEL_ENDPOINT` Makefile variables

## Known Gotchas

- **Typo in variable name:** The notebook uses `MINIO_ACSSESS_KEY` (misspelled "ACCESS") as the variable name for the MinIO access key. This is in the source code at cell `324da76f` of `model_to_bucket.ipynb`.
- **Credentials hardcoded in notebook cells:** MinIO credentials (`minio` / `minio123`) are hardcoded as string literals in the notebook rather than sourced from environment variables or RHOAI workbench data connections. The README instructs users to manually set the endpoint.
- **No bucket auto-creation:** The notebook assumes the target bucket already exists in MinIO. Unlike other approaches that use `bucket_exists()` / `make_bucket()` checks, this notebook does not create the bucket if missing.
- **`boto3` imported but unused:** The notebook installs and imports `boto3` alongside `minio`, but only the `minio` SDK is used for S3 operations. This is a leftover from the pip install line.
- **`local_dir_use_symlinks=False` is deprecated:** The `hf_hub_download` call uses `local_dir_use_symlinks=False`, which has been deprecated in newer versions of `huggingface_hub`.
- **No retry logic on upload:** The `fput_object` call has no retry mechanism. If the upload fails (network issue, MinIO restart), the file is still deleted via `os.remove()` because exception handling only prints the S3Error but continues to the delete step.
- **Gated models require a token:** The `huggingface_token` defaults to `None`. For gated models like Llama 3.1, the user must set this value; the README notes "You will need to provide a Hugging Face token if required."
- **Model endpoint form documented in README:** The README documents the expected endpoint format as `https://<MODEL>-<NAMESPACE>.apps.ai-<CLUSTER>.kni.syseng.devcluster.openshift.com/v1` and recommends adding `--max-model-len=8192` to the model serving configuration parameters.

## Testing Notes

- Run the notebook inside an RHOAI workbench with network access to both HuggingFace Hub and the in-cluster MinIO endpoint
- MinIO must be deployed first via `make minio-install` with valid credentials (userId min 3 chars, password min 8 chars)
- After uploading the model, deploy it via OpenShift AI: Data Science Projects -> Models -> Single-Model -> Deploy
- Verify the model endpoint with a curl test documented in the README: `curl -X POST https://<ENDPOINT>/chat/completions -H "Authorization: Bearer <TOKEN>"`
- The `SUMMARY_LLM_API_KEY` from the deployed model must be added to the Helm values secret (`llama-api`) before deploying the recommender system

## Related Patterns

- See `notebooks.md` for other notebook patterns including bulk `snapshot_download` via boto3 (Approach A) and KFP pipeline-based ingestion (Approach B)
- See `minio.md` for MinIO deployment patterns across quickstarts
- See `model-serving.md` for model serving configuration patterns
