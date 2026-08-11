---
name: helm-nv-ingest-ngc-remote-subchart
description: NV-Ingest from NVIDIA NGC Helm repo as subchart with Milvus GPU, Redis, and extensive value overrides
summary: "Deploys NVIDIA NV-Ingest 26.1.1 as a conditional Helm subchart (`ingestor-server.enabled`) from NGC repo with extensive parent-chart value overrides for OpenShift — disables all 9 NIM operator models to use KServe/vLLM instead, replaces MinIO with ODF ObjectBucketClaim, configures Milvus v2.6.5-gpu (`fullnameOverride: milvus`) on MIG-1g.12gb slices (`nvidia.com/gpu: 0`, 8 CPU/16Gi), and uses Redis 8.2.1 as message queue. Use when integrating NVIDIA's document ingestion pipeline (YOLOX page detection, OCR, VLM captioning) into OpenShift AI where models are served via vLLM/KServe rather than NIM Operator — document processing endpoints split between NVIDIA cloud APIs (YOLOX, OCR) and local vLLM at `http://nim-vlm-predictor:8080/v1`. Critical config: YAML anchors (`&ngc-secret-name`, `&odf-bucket-name`) keep secret and OBC names consistent across parent/subchart; a single NGC secret provides both image-pull and runtime API key via `imagePullSecrets` + `extraEnvFrom` secretRef with `ngcApiSecret.create: false` and `ngcImagePullSecret.create: false` delegating creation to the parent chart; Milvus etcd requires explicitly emptied security contexts (`podSecurityContext: {}`, `containerSecurityContext: {}`) for OpenShift restricted SCC. Gotchas: `MESSAGE_CLIENT_HOST` must be hardcoded with Helm release-name prefix (e.g., `ingest-redis-master`) because NV-Ingest lacks templated release-name substitution in env vars; built-in tracing disabled via `otelDeployed: false`/`zipkinDeployed: false` since observability uses separate charts."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, redis]
  ai_pattern: [rag, data-pipeline]
  platform: [openshift]
  data_layer: [milvus]
source_examples:
  - quickstart: "aml-rag-nvidia"
    repo: "https://github.com/rh-ai-quickstart/aml-rag-nvidia"
    notes: "NV-Ingest 26.1.1 from NGC Helm repo with GPU-accelerated Milvus, Redis 8.2.1, and disabled NIM operators"
    approach: "A"
---

# NV-Ingest NGC Remote Subchart with Heavy Overrides

## Overview

This pattern pulls NVIDIA NV-Ingest as a remote Helm subchart dependency from the NGC (NVIDIA GPU Cloud) Helm repository. The parent chart overrides nearly every aspect of the subchart's configuration: disabling all NIM operator components, replacing built-in MinIO with ODF ObjectBucketClaim storage, configuring Milvus with GPU acceleration on MIG slices, and wiring inter-service communication to local vLLM endpoints instead of NVIDIA API endpoints.

## Pattern Description

The `ingest` chart declares `nv-ingest` as a conditional dependency from `https://helm.ngc.nvidia.com/nvidia/nemo-microservices`. The subchart brings its own sub-dependencies including Milvus (vector DB) and Redis (message queue). The parent chart uses extensive `values.yaml` overrides to adapt the NVIDIA-designed defaults for an OpenShift environment: disabling all NIM operator-managed models (since models are served via KServe/vLLM instead), swapping MinIO for ODF, and adjusting security contexts for OpenShift compatibility.

## Implementation

### Chart.yaml Dependency

```yaml
# charts/ingest/Chart.yaml
dependencies:
  - condition: ingestor-server.enabled
    name: nv-ingest
    repository: https://helm.ngc.nvidia.com/nvidia/nemo-microservices
    version: 26.1.1
```

### Disabling All NIM Operator Models

NV-Ingest defaults to deploying models via NVIDIA NIM Operator. Since this quickstart uses vLLM via KServe, all NIM models are disabled:

```yaml
# charts/ingest/values.yaml (excerpt)
nv-ingest:
  nimOperator:
    embedqa:
      enabled: false
    graphic_elements:
      enabled: false
    page_elements:
      enabled: false
    table_structure:
      enabled: false
    nemoretriever_ocr_v1:
      enabled: false
    nemotron_nano_12b_v2_vl:
      enabled: false
    nemotron_parse:
      enabled: false
    audio:
      enabled: false
    llama_3_2_nv_rerankqa_1b_v2:
      enabled: false
```

### Milvus GPU with MIG Slice and OpenShift Security Fixes

The Milvus subchart within NV-Ingest is overridden to use a MIG GPU slice and remove hardcoded security contexts:

```yaml
# charts/ingest/values.yaml (excerpt)
nv-ingest:
  milvus:
    fullnameOverride: milvus
    image:
      all:
        repository: docker.io/milvusdb/milvus
        tag: v2.6.5-gpu
    etcd:
      enabled: true
      podSecurityContext: {}
      containerSecurityContext: {}
    standalone:
      resources:
        limits:
          nvidia.com/gpu: 0
          nvidia.com/mig-1g.12gb: "1"
        requests:
          nvidia.com/mig-1g.12gb: "1"
    minio:
      enabled: false
```

### NGC Secret for Both Image Pull and API Keys

The parent chart creates a single secret that serves as both a Docker registry pull secret and provides runtime API keys:

```yaml
# charts/ingest/values.yaml (excerpt)
nv-ingest:
  imagePullSecrets:
    - name: *ngc-secret-name
  ngcApiSecret:
    create: false  # NGC_API_KEY from parent chart's nvidiaApiKey secret
  ngcImagePullSecret:
    create: false  # Uses parent chart's nvidiaApiKey secret for image pull
  extraEnvFrom:
    - secretRef:
        name: *ngc-secret-name
```

### NV-Ingest Pointing to vLLM Instead of NVIDIA API

Document processing endpoints are split: some use NVIDIA cloud APIs (YOLOX, OCR), while VLM captioning uses local vLLM:

```yaml
# charts/ingest/values.yaml (excerpt)
nv-ingest:
  envVars:
    VLM_CAPTION_MODEL_NAME: nvidia/NVIDIA-Nemotron-Nano-12B-v2-VL-FP8
    VLM_CAPTION_ENDPOINT: "http://nim-vlm-predictor:8080/v1"
    YOLOX_HTTP_ENDPOINT: "https://ai.api.nvidia.com/v1/cv/nvidia/nemoretriever-page-elements-v3"
    OCR_HTTP_ENDPOINT: "https://ai.api.nvidia.com/v1/cv/nvidia/nemoretriever-ocr-v1"
```

## Configuration

- **Key settings:** `nv-ingest.enabled: true` (conditionally via `ingestor-server.enabled`); Redis 8.2.1 as message queue; Milvus v2.6.5-gpu for vector storage; all NIM operators disabled
- **Defaults:** NV-Ingest requests no full GPUs (`nvidia.com/gpu: 0`, 8 CPU, 16Gi memory); Milvus gets one MIG 1g.12gb slice; Redis uses default settings
- **Dependencies:** NGC API key passed via `--set nvidiaApiKey.password=$NGC_API_KEY`; ODF ObjectBucketClaim for S3 storage; KServe InferenceServices for VLM model endpoint

## Gotchas

- Milvus etcd security contexts are explicitly emptied (`podSecurityContext: {}`, `containerSecurityContext: {}`) to remove hardcoded UID/GID values that conflict with OpenShift's restricted SCC
- The `MESSAGE_CLIENT_HOST` must include the Helm release name prefix (e.g., `ingest-redis-master`) and this value must be hardcoded because the NV-Ingest subchart does not support templated release name substitution in its env vars
- YAML anchors (`&ngc-secret-name`, `&odf-bucket-name`) are used at the top of values.yaml and referenced throughout with `*ngc-secret-name` to keep the NGC secret name and OBC name consistent across the parent chart and subchart overrides
- NV-Ingest's `otelDeployed: false` and `zipkinDeployed: false` disable built-in tracing since observability is handled by separate Helm charts in this quickstart

## Related Patterns

- `odf-obc-init-container-wait.md` -- the OBC integration that provides S3 credentials to NV-Ingest
- `openshift-scc-anyuid-rolebinding.md` -- the SCC grant that NV-Ingest requires to run on OpenShift
- `ngc-secret-dual-pull-and-runtime.md` -- the dual-purpose NGC secret consumed by NV-Ingest
