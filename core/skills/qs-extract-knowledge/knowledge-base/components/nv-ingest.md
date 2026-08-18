---
name: nv-ingest
description: NVIDIA NV-Ingest document processing pipeline with ingestor-server wrapper, Milvus GPU vector store, and ODF object storage
summary: "Solves multimodal document extraction (text, tables, charts from PDFs) for RAG pipelines using NVIDIA NV-Ingest deployed as an NGC Helm subchart wrapped by a custom ingestor-server (Python/uvicorn port 8082) that orchestrates chunking (512/150 overlap), embedding via local vLLM KServe endpoint, and writes to Milvus GPU vector store using MIG slices (nvidia.com/mig-1g.12gb), connected through Redis message queue with batch tuning (FILES_PER_BATCH: 16, CONCURRENT_BATCHES: 4). Use when ingesting multimodal PDFs on OpenShift with ODF storage -- ODF ObjectBucketClaim (storageClassName: openshift-storage.noobaa.io) replaces MinIO, requiring a bitnami/kubectl init container polling for async-provisioned OBC Secret/ConfigMap plus startup-command remapping of OBC env vars to MINIO_ACCESSKEY/MINIO_ENDPOINT names. NV-Ingest requests zero local GPUs and calls cloud-hosted NIM endpoints (page-elements-v3, graphic-elements-v1, table-structure-v1, OCR-v1, nemotron-parse) via a dual-purpose NGC Secret (kubernetes.io/dockerconfigjson for nvcr.io image pulls + NGC_API_KEY/NVIDIA_API_KEY env vars); a shared prompt.yaml ConfigMap configures RAG/VLM/summary prompts across ingestor-server and rag-server charts. Critical gotchas: Redis MESSAGE_CLIENT_HOST is hardcoded to the Helm release name (\"ingest-redis-master\"), three ServiceAccounts (default, <release>-nv-ingest, ingestor-server) need anyuid SCC, Milvus MinIO port forced to 80 for ODF, etcd securityContexts blanked for OpenShift restricted SCC, and embedding endpoints differ between ingestor-server (local vLLM KServe) and nv-ingest subchart (cloud API)."
metadata:
  type: component
tags:
  tech_stack: [python, uvicorn, redis, helm]
  ai_pattern: [rag, data-pipeline, embeddings, multimodal]
  platform: [rhoai, openshift, kubernetes, triton]
  data_layer: [milvus, redis]
source_examples:
  - quickstart: "aml-rag-nvidia"
    repo: "https://github.com/rh-ai-quickstart/aml-rag-nvidia"
    notes: "NV-Ingest subchart with custom ingestor-server wrapper, ODF ObjectBucketClaim for S3 storage, Milvus GPU-accelerated vector store, and multimodal document extraction"
    approach: "A"
---

# NV-Ingest

## Overview

NV-Ingest is NVIDIA's document processing microservice that extracts text, tables, charts, and images from documents (primarily PDFs) and feeds them into a RAG pipeline. In this quickstart it is deployed as a Helm subchart dependency pulled from the NGC Helm repository, wrapped by a custom ingestor-server Deployment that orchestrates ingestion jobs, manages chunking, generates embeddings, and stores results in a Milvus GPU-accelerated vector database. The ingest chart also provisions ODF-backed S3 object storage via an ObjectBucketClaim and deploys Redis as a message queue between the ingestor-server and NV-Ingest.

## Tech Stack & Dependencies

- **Runtime:** Python / uvicorn (`nvidia_rag.ingestor_server.server:app` on port 8082)
- **Container image (ingestor-server):** `quay.io/rh-ee-gurvsing/ingestor-server:0.3`
- **Container image (nv-ingest):** `nvcr.io/nvidia/nemo-microservices/nv-ingest:26.1.1`
- **Key dependencies:** NV-Ingest subchart (NGC cloud-hosted NIMs for OCR/page/table/graphic detection), Milvus v2.6.5-gpu, Redis 8.2.1, ODF NooBaa (S3-compatible object storage), embedding model endpoint, VLM caption model endpoint, summary LLM endpoint
- **Helm subchart:** `nv-ingest` v26.1.1 from `https://helm.ngc.nvidia.com/nvidia/nemo-microservices`

## Key Patterns

### Dual-Layer Architecture: Ingestor-Server Wrapping NV-Ingest

The chart deploys two distinct services. The ingestor-server is a custom Python/uvicorn application that manages the end-to-end ingestion workflow (chunking, embedding, vector store writes, summarization). It communicates with the NV-Ingest subchart service over Redis as a message queue for the raw document extraction step.

```yaml
# charts/ingest/values.yaml -- ingestor-server to nv-ingest connection
envVars:
  APP_NVINGEST_MESSAGECLIENTHOSTNAME: "nv-ingest"
  APP_NVINGEST_MESSAGECLIENTPORT: "7670"
  APP_NVINGEST_EXTRACTTEXT: "True"
  APP_NVINGEST_EXTRACTTABLES: "True"
  APP_NVINGEST_EXTRACTCHARTS: "True"
  APP_NVINGEST_EXTRACTIMAGES: "False"
  NV_INGEST_FILES_PER_BATCH: "16"
  NV_INGEST_CONCURRENT_BATCHES: "4"
```

### ODF ObjectBucketClaim for S3 Storage

Instead of deploying MinIO, the chart uses OpenShift Data Foundation (ODF) via an `ObjectBucketClaim` resource. ODF asynchronously provisions the bucket and creates a Secret (S3 credentials) and ConfigMap (endpoint/bucket name) with the same name as the OBC. The ingestor-server uses an init container to wait for these resources before starting.

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

The ingestor-server maps the OBC-provided environment variables to MINIO-compatible names in its startup command:

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

Because ODF provisions the bucket asynchronously, the ingestor-server uses a `bitnami/kubectl` init container that polls for the OBC Secret and ConfigMap every 2 seconds. Dedicated RBAC resources (ServiceAccount, Role, RoleBinding) grant the init container `get` access to the specific Secret and ConfigMap.

```yaml
# charts/ingest/templates/ingestor-server-deployment.yaml
initContainers:
  - name: wait-for-obc-secret
    image: {{ $cfg.waitForOBCSecret.image }}
    command:
      - /bin/sh
      - -c
      - |
        until kubectl get secret {{ $obc.name }} -n {{ .Release.Namespace }} 2>/dev/null && kubectl get configmap {{ $obc.name }} -n {{ .Release.Namespace }} 2>/dev/null; do
          echo "Waiting for OBC secret and configmap {{ $obc.name }}..."
          sleep 2
        done
        echo "OBC secret and configmap ready"
```

### Milvus GPU-Accelerated Vector Store with MIG Support

Milvus is deployed as a sub-dependency of the nv-ingest subchart using the GPU-enabled image (`milvusdb/milvus:v2.6.5-gpu`). The chart overrides the default GPU resource to use a MIG slice (`nvidia.com/mig-1g.12gb`) instead of a full GPU, and disables the built-in MinIO in favor of the ODF-backed bucket via `extraEnv` mappings.

```yaml
# charts/ingest/values.yaml -- Milvus standalone resource overrides
standalone:
  resources:
    limits:
      nvidia.com/gpu: 0
      nvidia.com/mig-1g.12gb: "1"
    requests:
      nvidia.com/mig-1g.12gb: "1"
```

### NV-Ingest Cloud-Hosted NIM Endpoints

NV-Ingest itself does not run GPU workloads locally (its GPU limit is set to 0). Instead, it calls NVIDIA cloud-hosted NIM endpoints for document analysis tasks. All NIM operator sub-services are explicitly disabled in the values, pointing NV-Ingest to the cloud API endpoints instead.

```yaml
# charts/ingest/values.yaml -- cloud-hosted NIM endpoints
envVars:
  YOLOX_HTTP_ENDPOINT: "https://ai.api.nvidia.com/v1/cv/nvidia/nemoretriever-page-elements-v3"
  YOLOX_GRAPHIC_ELEMENTS_HTTP_ENDPOINT: "https://ai.api.nvidia.com/v1/cv/nvidia/nemoretriever-graphic-elements-v1"
  YOLOX_TABLE_STRUCTURE_HTTP_ENDPOINT: "https://ai.api.nvidia.com/v1/cv/nvidia/nemoretriever-table-structure-v1"
  OCR_HTTP_ENDPOINT: "https://ai.api.nvidia.com/v1/cv/nvidia/nemoretriever-ocr-v1"
  NEMOTRON_PARSE_HTTP_ENDPOINT: "https://integrate.api.nvidia.com/v1/chat/completions"
```

### NGC API Key as Dual-Purpose Secret

The chart creates a single Secret (`ngc-api`) that serves as both a `kubernetes.io/dockerconfigjson` image pull secret (for pulling images from `nvcr.io`) and a source of `NGC_API_KEY` / `NVIDIA_API_KEY` environment variables for the NV-Ingest container. The nv-ingest subchart's own secret creation is disabled (`ngcApiSecret.create: false`, `ngcImagePullSecret.create: false`) to avoid duplication.

```yaml
# charts/ingest/templates/nvidia-api-key-secret.yaml
type: kubernetes.io/dockerconfigjson
data:
  .dockerconfigjson: {{ $config | b64enc | quote }}
  NGC_API_KEY: {{ $nak.password | b64enc | quote }}
  NVIDIA_API_KEY: {{ $nak.password | b64enc | quote }}
```

### Prompt Configuration via ConfigMap

The ingestor-server and rag-server share a prompt configuration file (`prompt.yaml`) mounted via a ConfigMap. This file defines RAG, chat, query rewriting, reflection, VLM, document summary, and filter expression prompts. The ConfigMap is created by the ingest chart but consumed by both services.

```yaml
# charts/ingest/templates/ingestor-server-prompt-configmap.yaml
data:
  prompt.yaml: |-
{{ .Files.Get "files/prompt.yaml" | indent 4 }}
```

### SCC Requirements for OpenShift

Both the default ServiceAccount and the nv-ingest ServiceAccount require `anyuid` SCC on OpenShift. Two separate RoleBindings handle this -- one for the ingestor-server's own ServiceAccount (created alongside the OBC RBAC) and one for the default SA and the `<release>-nv-ingest` SA.

```yaml
# charts/ingest/templates/scc-rolebinding.yaml
subjects:
  - kind: ServiceAccount
    name: default
    namespace: {{ .Release.Namespace }}
  - kind: ServiceAccount
    name: {{ .Release.Name }}-nv-ingest
    namespace: {{ .Release.Namespace }}
```

## Configuration

- **Environment variables (ingestor-server):**
  - `APP_VECTORSTORE_URL`: Milvus endpoint (default: `http://milvus:19530`)
  - `APP_EMBEDDINGS_SERVERURL`: Embedding model vLLM endpoint (default: `nemoretriever-embedding-ms-predictor:8080/v1`)
  - `APP_EMBEDDINGS_MODELNAME`: Embedding model name (`nvidia/llama-nemotron-embed-1b-v2`)
  - `APP_EMBEDDINGS_DIMENSIONS`: Embedding dimensions (`2048`)
  - `APP_NVINGEST_CHUNKSIZE` / `APP_NVINGEST_CHUNKOVERLAP`: Chunking parameters (`512` / `150`)
  - `SUMMARY_LLM` / `SUMMARY_LLM_SERVERURL`: Summary generation LLM (`nvidia/Llama-3_3-Nemotron-Super-49B-v1_5-FP8`)
  - `REDIS_HOST`: Redis host; uses `__RELEASE_NAME__-redis-master` placeholder replaced at template render time
  - `ENABLE_MINIO_BULK_UPLOAD`: Enables bulk upload to object storage (`True`)
  - `NV_INGEST_FILES_PER_BATCH` / `NV_INGEST_CONCURRENT_BATCHES`: Batch processing tuning (`16` / `4`)

- **Environment variables (nv-ingest):**
  - `MESSAGE_CLIENT_HOST`: Redis host for task queue (must match release name: `ingest-redis-master`)
  - `MESSAGE_CLIENT_PORT` / `MESSAGE_CLIENT_TYPE`: Redis connection (`6379` / `redis`)
  - `INGEST_DYNAMIC_MEMORY_THRESHOLD`: Memory pressure threshold (`0.80`)
  - `NV_INGEST_MAX_UTIL`: Max utilization workers (`4`)
  - `COMPONENTS_TO_READY_CHECK`: Readiness check scope (`ALL`)

- **Helm values:**
  - `nvidiaApiKey.password`: NGC API key (set via `--set nvidiaApiKey.password=$NGC_API_KEY`)
  - `objectStorage.odf.objectBucketClaim.enabled`: Toggle ODF S3 bucket provisioning
  - `objectStorage.odf.objectBucketClaim.storageClassName`: ODF storage class (`openshift-storage.noobaa.io`)
  - `nv-ingest.milvus.standalone.resources`: GPU/MIG resource overrides for Milvus

- **Persistence:** 10Gi PVC at `/data/` for ingestor-server temporary and processed files

## Known Gotchas

- **Release name hardcoded in Redis host:** The nv-ingest subchart's `MESSAGE_CLIENT_HOST` is set to `ingest-redis-master` which assumes the Helm release name is `ingest`. A comment in `values.yaml` warns: "Ensure the below variable matches your release name (must be hardcoded due to nv-ingest subchart)." Using a different release name will break the NV-Ingest to Redis connection.
- **Milvus MinIO port forced to 80:** The Milvus `extraEnv` sets `MINIO_PORT: "80"` with the comment "Force HTTP port 80; avoids TLS cert verification issues with ODF." This bypasses the OBC-provided `BUCKET_PORT` value, which may cause issues if the ODF endpoint is not on port 80.
- **etcd security contexts removed for OpenShift:** The Milvus etcd sub-dependency has `podSecurityContext: {}` and `containerSecurityContext: {}` to override upstream defaults that conflict with OpenShift's restricted SCC. This is a silent compatibility fix.
- **Three service accounts need anyuid SCC:** The deployment requires `anyuid` SCC for the `default` SA, the `<release>-nv-ingest` SA, and the `ingestor-server` SA. Missing any one of these will cause pod scheduling failures. The README notes this requires `cluster-admin or SCC management rights`.
- **NV-Ingest GPU set to zero:** The nv-ingest container itself requests zero GPUs (`nvidia.com/gpu: 0`); all heavy document analysis runs on NVIDIA's cloud-hosted NIMs. This requires an NGC API key with the appropriate entitlements for page-elements-v3, graphic-elements-v1, table-structure-v1, OCR-v1, and nemotron-parse.
- **Embedding endpoint mismatch between ingestor-server and nv-ingest:** The ingestor-server sets `APP_EMBEDDINGS_SERVERURL` to the local vLLM KServe endpoint (`nemoretriever-embedding-ms-predictor:8080/v1`), while the nv-ingest subchart sets `EMBEDDING_NIM_ENDPOINT` to the cloud API (`https://integrate.api.nvidia.com/v1/embeddings`). These serve different purposes but the inconsistency can cause confusion during debugging.

## Testing Notes

- Verify the OBC has been provisioned: `oc get objectbucketclaim default-bucket` should show `Bound`
- Verify the OBC Secret and ConfigMap exist: `oc get secret default-bucket` and `oc get configmap default-bucket`
- Check ingestor-server init container completed: `oc logs <ingestor-server-pod> -c wait-for-obc-secret`
- Verify NV-Ingest is healthy: `oc logs <nv-ingest-pod>` should show `COMPONENTS_TO_READY_CHECK: ALL` passing
- Verify Milvus is running with GPU: `oc get pod milvus-standalone-0` and check logs for GPU indexing
- Test document upload through the ingestor-server API on port 8082

## Related Patterns

- `components/minio.md` -- Alternative S3 storage when ODF is not available
- `components/llm-service.md` -- vLLM model serving endpoints consumed by ingestor-server
- `deployment/helm-subchart-wiring.md` -- How the nv-ingest subchart is wired as a dependency
