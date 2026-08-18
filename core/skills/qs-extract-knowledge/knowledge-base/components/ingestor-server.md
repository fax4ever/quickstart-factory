---
name: ingestor-server
description: NVIDIA RAG blueprint ingestor server for document processing, chunking, and vector store population via NV-Ingest
summary: "NVIDIA RAG blueprint Uvicorn/FastAPI document ingestion backend (port 8082, custom image quay.io/rh-ee-gurvsing/ingestor-server:0.3) that orchestrates NV-Ingest extraction, llama-nemotron-embed-1b-v2 embeddings (2048d), Llama-3_3-Nemotron-Super-49B summarization, and Milvus vector storage for RHOAI quickstarts. Deploy via charts/ingest Helm subchart bundling nv-ingest v26.1.1 (GPU=0, vision tasks delegated to cloud NGC NIMs), Milvus with MIG slice (nvidia.com/mig-1g.12gb), Redis, ODF ObjectBucketClaim replacing MinIO, dual-purpose NGC API key Secret (dockerconfigjson + API auth), externalized prompt templates (RAG/summarization/query-rewriting/groundedness/VLM) via ConfigMap, and deviceConfigs map for shared GPU tolerations. Critical pattern: init container with scoped RBAC polls for asynchronously-provisioned OBC Secret/ConfigMap, then a shell wrapper translates OBC env vars (AWS_ACCESS_KEY_ID to MINIO_ACCESSKEY) before launching uvicorn; __RELEASE_NAME__ placeholders in values.yaml resolve Redis hostname at render time. Gotchas: anyuid SCC required for three SAs (ingestor-server, default, <release>-nv-ingest), NV-Ingest Redis hostname hardcoded to release-name prefix (mismatch breaks connectivity), Milvus etcd securityContext must be empty {} for OpenShift restricted SCC, Milvus MINIO_PORT forced to \"80\" for ODF HTTP, and NGC Helm repo needs literal $oauthtoken username for authenticated access."
metadata:
  type: component
tags:
  tech_stack: [fastapi, uvicorn, python, redis]
  ai_pattern: [rag, embeddings, data-pipeline, vector-search, multimodal]
  platform: [rhoai, openshift, kserve, vllm]
  data_layer: [milvus, minio]
source_examples:
  - quickstart: "aml-rag-nvidia"
    repo: "https://github.com/rh-ai-quickstart/aml-rag-nvidia"
    notes: "Custom ingestor server image wrapping NVIDIA RAG blueprint with NV-Ingest subchart, ODF object storage, Milvus GPU-accelerated vector DB, and configurable prompt templates"
    approach: "A"
---

# Ingestor Server

## Overview

The ingestor server is the document ingestion backend for NVIDIA RAG blueprint-based quickstarts. It runs as a Uvicorn/FastAPI application that orchestrates document processing through NVIDIA's NV-Ingest service, generates embeddings via NVIDIA NIM endpoints, and stores vectors in Milvus. On RHOAI, it is deployed as a Kubernetes Deployment within a dedicated Helm subchart (`charts/ingest`) that also manages the NV-Ingest dependency, Milvus (GPU-accelerated), Redis, ODF object storage via ObjectBucketClaim, and NGC API key secrets.

## Tech Stack & Dependencies

- **Runtime:** Python / Uvicorn / FastAPI (NVIDIA RAG blueprint `nvidia_rag.ingestor_server.server:app`)
- **Container image:** `quay.io/rh-ee-gurvsing/ingestor-server:0.3` (custom build wrapping NVIDIA blueprint)
- **Key dependencies:** NV-Ingest (document extraction), Milvus (vector store), Redis (message queue for NV-Ingest), NVIDIA NIM embedding model, NVIDIA NIM VLM (for image/chart captioning), NVIDIA NIM LLM (for document summarization), S3-compatible object storage (ODF/NooBaa)
- **Helm subchart:** `nv-ingest` v26.1.1 from `https://helm.ngc.nvidia.com/nvidia/nemo-microservices` (deployed as a dependency when `ingestor-server.enabled`)

## Key Patterns

### ODF ObjectBucketClaim for S3-Compatible Storage

Instead of deploying a standalone MinIO instance, the chart uses OpenShift Data Foundation (ODF) ObjectBucketClaim to provision S3-compatible storage. The OBC automatically creates a Secret and ConfigMap with credentials that are injected into the ingestor-server, NV-Ingest, and Milvus pods.

```yaml
# charts/ingest/templates/object-bucket-claim.yaml
apiVersion: objectbucket.io/v1alpha1
kind: ObjectBucketClaim
metadata:
  name: {{ $obc.name }}
spec:
  bucketName: {{ $obc.bucketName }}
  storageClassName: openshift-storage.noobaa.io
```

The ingestor-server deployment translates OBC environment variables to the MINIO_* variables the application expects via a shell wrapper command:

```yaml
# charts/ingest/templates/ingestor-server-deployment.yaml
command:
  - /bin/sh
  - -c
  - |
    export MINIO_ACCESSKEY="$${AWS_ACCESS_KEY_ID}"
    export MINIO_SECRETKEY="$${AWS_SECRET_ACCESS_KEY}"
    export MINIO_ENDPOINT="$${BUCKET_HOST}:80"
    export MINIO_BUCKET="$${BUCKET_NAME}"
    export NVINGEST_MINIO_BUCKET="$${BUCKET_NAME}"
    exec uvicorn nvidia_rag.ingestor_server.server:app --port 8082 --host 0.0.0.0 --workers 1
```

### Init Container Waiting for OBC Secret

Because the ObjectBucketClaim is provisioned asynchronously by the ODF operator, the ingestor-server deployment uses an init container that polls for the OBC Secret and ConfigMap before starting the main container. This requires a dedicated ServiceAccount with RBAC permissions to read the specific Secret and ConfigMap.

```yaml
# charts/ingest/templates/ingestor-server-deployment.yaml
initContainers:
  - name: wait-for-obc-secret
    image: bitnami/kubectl:latest
    command:
      - /bin/sh
      - -c
      - |
        until kubectl get secret {{ $obc.name }} -n {{ .Release.Namespace }} && \
              kubectl get configmap {{ $obc.name }} -n {{ .Release.Namespace }}; do
          echo "Waiting for OBC secret and configmap..."
          sleep 2
        done
```

The RBAC is scoped to only the specific OBC resource name:

```yaml
# charts/ingest/templates/ingestor-server-rbac.yaml
rules:
  - apiGroups: [""]
    resources: ["secrets", "configmaps"]
    resourceNames: [{{ $obc.name | quote }}]
    verbs: ["get"]
```

### NGC API Key as Dual-Purpose Secret

The NGC API key Secret serves double duty: it is both a `kubernetes.io/dockerconfigjson` image pull secret (for pulling NV-Ingest images from `nvcr.io`) and a source of `NGC_API_KEY` / `NVIDIA_API_KEY` environment variables consumed by NV-Ingest for cloud-hosted NIM inference.

```yaml
# charts/ingest/templates/nvidia-api-key-secret.yaml
type: kubernetes.io/dockerconfigjson
data:
  .dockerconfigjson: {{ $config | b64enc | quote }}
  NGC_API_KEY: {{ $nak.password | b64enc | quote }}
  NVIDIA_API_KEY: {{ $nak.password | b64enc | quote }}
```

### NV-Ingest Subchart with Cloud-Hosted NIMs

The NV-Ingest subchart runs document extraction locally but delegates specialized vision tasks (page element detection, graphic elements, table structure, OCR, document parsing) to NVIDIA cloud-hosted NIMs via the NGC API. This hybrid approach avoids deploying additional GPU-intensive vision models locally.

```yaml
# charts/ingest/values.yaml (nv-ingest section)
YOLOX_HTTP_ENDPOINT: "https://ai.api.nvidia.com/v1/cv/nvidia/nemoretriever-page-elements-v3"
YOLOX_GRAPHIC_ELEMENTS_HTTP_ENDPOINT: "https://ai.api.nvidia.com/v1/cv/nvidia/nemoretriever-graphic-elements-v1"
YOLOX_TABLE_STRUCTURE_HTTP_ENDPOINT: "https://ai.api.nvidia.com/v1/cv/nvidia/nemoretriever-table-structure-v1"
OCR_HTTP_ENDPOINT: "https://ai.api.nvidia.com/v1/cv/nvidia/nemoretriever-ocr-v1"
NEMOTRON_PARSE_HTTP_ENDPOINT: "https://integrate.api.nvidia.com/v1/chat/completions"
```

### Milvus GPU-Accelerated Vector Database with MIG Slice

Milvus is deployed as a subchart of NV-Ingest with GPU acceleration enabled, but instead of requiring a full GPU, it uses a MIG (Multi-Instance GPU) slice (`nvidia.com/mig-1g.12gb`). The built-in MinIO is disabled in favor of ODF object storage.

```yaml
# charts/ingest/values.yaml (nv-ingest.milvus section)
standalone:
  resources:
    limits:
      nvidia.com/gpu: 0
      nvidia.com/mig-1g.12gb: "1"
    requests:
      nvidia.com/mig-1g.12gb: "1"
minio:
  enabled: false
externalS3:
  enabled: true
  useSSL: false
```

### Device-Based Tolerations

The chart uses a `deviceConfigs` map to define GPU tolerations that can be referenced by component name, allowing different components to share toleration configuration.

```yaml
# charts/ingest/values.yaml
deviceConfigs:
  nvidia-gpu:
    tolerations:
      - effect: NoSchedule
        key: nvidia.com/gpu
        operator: Exists

ingestor-server:
  device: nvidia-gpu  # References deviceConfigs entry
```

The deployment template resolves this indirection at render time, with per-component `tolerations` taking priority over the device config lookup.

### Configurable Prompt Templates via ConfigMap

All prompt templates (RAG, chat, summarization, query rewriting, reflection/grounding checks, VLM, filter expressions, query decomposition) are stored in a `prompt.yaml` file mounted as a ConfigMap. This externalizes prompt engineering from the application image, enabling iteration without rebuilds.

```yaml
# charts/ingest/templates/ingestor-server-prompt-configmap.yaml
data:
  prompt.yaml: |-
{{ .Files.Get "files/prompt.yaml" | indent 4 }}
```

The prompt file includes templates for multiple RAG pipeline stages: chat, RAG retrieval, query rewriting, relevance checking, groundedness checking, response regeneration, document summarization (both deep and shallow), iterative summarization, VLM multimodal, metadata filter expression generation, and query decomposition (multi-query, follow-up, final response).

### Release Name Substitution in Environment Variables

The deployment template supports `__RELEASE_NAME__` and `__RELEASE_NAMESPACE__` placeholders in environment variable values, which are substituted at Helm render time. This is used for the Redis hostname which includes the Helm release name.

```yaml
# charts/ingest/values.yaml
REDIS_HOST: "__RELEASE_NAME__-redis-master"

# charts/ingest/templates/ingestor-server-deployment.yaml
value: "{{ $v | replace "__RELEASE_NAME__" $.Release.Name | replace "__RELEASE_NAMESPACE__" $.Release.Namespace }}"
```

## Configuration

- **Environment variables:**
  - `APP_VECTORSTORE_URL` / `APP_VECTORSTORE_NAME`: Milvus connection (default `http://milvus:19530`)
  - `APP_EMBEDDINGS_SERVERURL` / `APP_EMBEDDINGS_MODELNAME` / `APP_EMBEDDINGS_DIMENSIONS`: Embedding model endpoint (NVIDIA llama-nemotron-embed-1b-v2, 2048 dimensions)
  - `APP_NVINGEST_MESSAGECLIENTHOSTNAME` / `APP_NVINGEST_MESSAGECLIENTPORT`: NV-Ingest message queue connection (default `nv-ingest:7670`)
  - `APP_NVINGEST_EXTRACT*`: Document extraction flags (text, tables, charts, images)
  - `APP_NVINGEST_CAPTIONMODELNAME` / `APP_NVINGEST_CAPTIONENDPOINTURL`: VLM for image/chart captioning
  - `SUMMARY_LLM` / `SUMMARY_LLM_SERVERURL`: LLM for document summarization (Llama-3_3-Nemotron-Super-49B-v1_5-FP8)
  - `MINIO_*`: Object storage credentials (injected from OBC when enabled, or set manually)
  - `REDIS_HOST` / `REDIS_PORT`: Redis message queue for NV-Ingest (uses `__RELEASE_NAME__` substitution)
  - `PROMPT_CONFIG_FILE`: Path to mounted prompt template YAML (default `/prompt.yaml`)
  - `NV_INGEST_FILES_PER_BATCH` / `NV_INGEST_CONCURRENT_BATCHES`: Ingestion throughput tuning (16 files/batch, 4 concurrent)
  - `ENABLE_MINIO_BULK_UPLOAD`: Enable bulk upload to object storage (default `True`)
  - `ENABLE_CITATIONS`: Enable citation support in responses (default `True`)
- **Config files:** `files/prompt.yaml` (all prompt templates, mounted at `/prompt.yaml`)
- **Helm values:** `ingestor-server.*` for the ingestor pod; `nv-ingest.*` for the NV-Ingest subchart; `objectStorage.odf.*` for ODF OBC; `nvidiaApiKey.*` for NGC credentials

## Known Gotchas

- **OBC Secret race condition:** The ObjectBucketClaim is provisioned asynchronously, so the OBC Secret and ConfigMap may not exist when the pod first starts. The init container (`wait-for-obc-secret`) handles this, but it requires a dedicated ServiceAccount and RBAC (Role + RoleBinding scoped to the specific OBC name). Without the init container, the deployment will fail with missing environment variables.
- **anyuid SCC required for three service accounts:** The ingestor-server, `default`, and `<release>-nv-ingest` service accounts all need the `system:openshift:scc:anyuid` ClusterRole bound to them. The chart creates separate RoleBindings: one in `scc-rolebinding.yaml` for `default` and `nv-ingest`, and another in `ingestor-server-rbac.yaml` for the ingestor-server SA. Missing any of these causes pod scheduling failures on OpenShift.
- **NV-Ingest Redis hostname is hardcoded:** The `MESSAGE_CLIENT_HOST` in the NV-Ingest subchart values is set to `ingest-redis-master` (hardcoded release name prefix). A comment in `values.yaml` warns: "Ensure the below variable matches your release name (must be hardcoded due to nv-ingest subchart)." If you install with a different release name, NV-Ingest cannot connect to Redis.
- **Milvus etcd security context must be cleared:** For OpenShift compatibility, the Milvus etcd subchart's `podSecurityContext` and `containerSecurityContext` must be set to empty objects `{}`. The upstream defaults conflict with OpenShift's restricted SCC.
- **Milvus ODF port override:** The Milvus `MINIO_PORT` is hardcoded to `"80"` to force HTTP. A comment in `values.yaml` explains: "Force HTTP port 80; avoids TLS cert verification issues with ODF." Without this override, Milvus fails to connect to ODF-backed object storage.
- **NGC Helm repo requires authenticated access:** The `nv-ingest` dependency chart is hosted at `helm.ngc.nvidia.com` which requires `helm repo add` with `--username='$oauthtoken' --password=$NGC_API_KEY` before running `helm dependency update`. The username is literally the string `$oauthtoken`, not a shell variable.
- **OBC env var keys differ from MINIO_* keys:** The OBC Secret provides `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`, but the ingestor-server application expects `MINIO_ACCESSKEY` and `MINIO_SECRETKEY`. The shell command wrapper in the deployment template handles the translation. If OBC is disabled, these must be set manually.
- **NV-Ingest GPU set to 0:** Despite being a GPU-intensive document processing service, NV-Ingest's `nvidia.com/gpu` limit is set to `0` in the chart values. It relies on the cloud-hosted NGC NIMs for vision tasks rather than local GPU inference.

## Testing Notes

- Verify the OBC Secret and ConfigMap exist in the namespace before the ingestor pod reaches Running state
- Check NV-Ingest connectivity by confirming Redis pods are healthy and the `nv-ingest` service resolves on port 7670
- Confirm Milvus standalone pod is running with the MIG GPU slice allocated (`nvidia.com/mig-1g.12gb`)
- Validate NGC API key by checking NV-Ingest logs for successful connections to cloud-hosted NIM endpoints
- The ingestor-server listens on port 8082 (ClusterIP service) and can be tested with document upload endpoints

## Related Patterns

- `llm-service.md` — vLLM model serving for the embedding and LLM models consumed by this component
- `minio.md` — alternative to ODF ObjectBucketClaim for S3-compatible storage
- `pgvector.md` — alternative vector database to Milvus
