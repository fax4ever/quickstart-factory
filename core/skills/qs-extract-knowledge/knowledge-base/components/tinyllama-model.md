---
name: tinyllama-model
description: "Multi-stage Containerfile building an OCI modelcar image for TinyLlama 1.1B, served by vLLM on CPU via KServe"
summary: "Packages TinyLlama-1.1B-Chat-v1.0 into an OCI modelcar image via a multi-stage Containerfile (huggingface-downloader first stage, UBI9-minimal final stage running as USER 1001 for OpenShift restricted SCC), decoupling model acquisition from serving so KServe can pull weights from a container registry without HuggingFace tokens at deploy time. Use for CPU-only vLLM serving on KServe/RHOAI where no GPU is available — the InferenceService consumes the image via oci:// storageUri through a uri-v1 Secret with opendatahub.io/connection-type-ref annotation; for GPU-based modelcar usage see llama-32-3b-instruct.md. The digest-pinned vLLM CPU runtime (registry.redhat.io/rhaii/vllm-cpu-rhel9) runs with --enable-auto-tool-choice --tool-call-parser hermes, VLLM_CPU_KVCACHE_SPACE controls KV cache in GiB, model.maxModelLen defaults to 2048, and resource defaults are 2-8 CPU / 8Gi memory. VLLM_CPU_KVCACHE_SPACE is set in both InferenceService (4) and ServingRuntime (2) causing tuning confusion; LD_PRELOAD=/usr/lib64/libomp.so improves vLLM performance but breaks pyarrow; Intel CPUs with AVX512 are recommended (AWS m6i.4xlarge known-good); and HF_TOKEN is a build-time-only --build-arg not needed at runtime."
metadata:
  type: component
tags:
  tech_stack: [vllm, kserve, helm, podman]
  ai_pattern: [model-serving]
  platform: [kserve, vllm, rhoai, openshift, openvino]
  data_layer: []
source_examples:
  - quickstart: "llm-cpu-serving"
    repo: "https://github.com/rh-ai-quickstart/llm-cpu-serving"
    notes: "Multi-stage Containerfile that downloads TinyLlama from HuggingFace and produces a minimal UBI9 OCI modelcar image for CPU-only vLLM serving"
    approach: "A"
---

# TinyLlama Model Image

## Overview

The TinyLlama model image is an OCI modelcar container that packages TinyLlama-1.1B-Chat-v1.0 model weights into a minimal container image. In the llm-cpu-serving quickstart, this pre-built image is referenced via an `oci://` storage URI in the KServe InferenceService, allowing vLLM on CPU to pull model weights directly from a container registry without requiring a HuggingFace token or external storage at deploy time. This pattern decouples model acquisition (build time) from model serving (deploy time).

## Tech Stack & Dependencies

- **Runtime:** None (data-only container image, serves as storage for KServe)
- **Container image (build stage):** `quay.io/redhat-ai-services/huggingface-downloader:latest`
- **Container image (final stage):** `registry.access.redhat.com/ubi9/ubi-minimal:9.4`
- **Key dependencies:** HuggingFace token at build time (via `--build-arg HF_TOKEN`), container build tool (podman/docker)
- **Helm subchart:** None (referenced by `storageUri` in the InferenceService)

## Key Patterns

### Multi-Stage Containerfile for Model Packaging

The Containerfile uses a two-stage build. The first stage uses a dedicated `huggingface-downloader` image that includes a `download_model.py` script to fetch model files from HuggingFace Hub. The second stage copies only the downloaded model files into a minimal UBI9 image, keeping the final image small and free of download tooling.

```dockerfile
# From model-image/Containerfile
FROM quay.io/redhat-ai-services/huggingface-downloader:latest as base

ARG HF_TOKEN

ENV MODEL_REPO="TinyLlama/TinyLlama-1.1B-Chat-v1.0"

RUN python3 download_model.py --model-repo ${MODEL_REPO}

FROM registry.access.redhat.com/ubi9/ubi-minimal:9.4

WORKDIR /models/

COPY --from=base /models/. .

USER 1001
```

### OCI Storage URI in KServe InferenceService

The pre-built modelcar image is consumed by KServe via an `oci://` storage URI. A corresponding Secret of type `uri-v1` holds the URI as a data connection, which KServe uses to pull the model weights as an init container at pod startup.

```yaml
# From helm/values.yaml
model:
  storageUri: "oci://quay.io/rh-aiservices-bu/tinyllama:1.0"
  name: "tinyllama"
```

```yaml
# From helm/templates/modelcar-dataconnection.yaml
kind: Secret
metadata:
  name: tinyllama-10-on-quayio
  annotations:
    opendatahub.io/connection-type-ref: uri-v1
    openshift.io/display-name: tinyllama 1.0 on quay.io
data:
  URI: b2NpOi8vcXVheS5pby9yaC1haXNlcnZpY2VzLWJ1L3RpbnlsbGFtYToxLjA=
```

The base64-decoded `URI` value is `oci://quay.io/rh-aiservices-bu/tinyllama:1.0`, matching `model.storageUri` in values.yaml.

### CPU-Only vLLM Serving Runtime

The InferenceService uses a Red Hat vLLM CPU image (not GPU) with specific environment variables for CPU-based key-value cache management. The serving runtime is compiled for Intel x86 CPUs.

```yaml
# From helm/templates/servingruntime.yaml
containers:
  - args:
      - --model
      - /mnt/models
      - --port
      - "8080"
      - --max-model-len
      - {{ .Values.model.maxModelLen | quote }}
      - '--served-model-name'
      - {{ .Values.model.name }}
      - '--enable-auto-tool-choice'
      - '--tool-call-parser'
      - 'hermes'
    image: {{ .Values.images.vllmRuntime }}
```

```yaml
# From helm/values.yaml
images:
  vllmRuntime: "registry.redhat.io/rhaii/vllm-cpu-rhel9@sha256:cf6577f6d526..."
```

### InferenceService with CPU Resources

Unlike GPU-based model serving, this InferenceService requests only CPU and memory. The `VLLM_CPU_KVCACHE_SPACE` environment variable controls CPU key-value cache allocation in GiB.

```yaml
# From helm/templates/inferenceservice.yaml
resources:
  limits:
    cpu: {{ .Values.resources.inference.limits.cpu | quote }}
    memory: {{ .Values.resources.inference.limits.memory | quote }}
  requests:
    cpu: {{ .Values.resources.inference.requests.cpu | quote }}
    memory: {{ .Values.resources.inference.requests.memory | quote }}
env:
  - name: VLLM_CPU_KVCACHE_SPACE
    value: "4"
```

```yaml
# From helm/values.yaml — default resource allocation
resources:
  inference:
    requests:
      cpu: "2"
      memory: "8Gi"
    limits:
      cpu: "8"
      memory: "8Gi"
```

## Configuration

- **Environment variables:**
  - `HF_TOKEN` - HuggingFace token, required only at image build time (via `--build-arg`), not at deploy time
  - `MODEL_REPO` - HuggingFace model repository identifier (default: `TinyLlama/TinyLlama-1.1B-Chat-v1.0`), set in the Containerfile
  - `HF_HOME` - HuggingFace cache directory, set to `/tmp/hf_home` in the InferenceService
  - `VLLM_CPU_KVCACHE_SPACE` - CPU key-value cache size in GiB (set to `4` in InferenceService, `2` in ServingRuntime)

- **Helm values:**
  - `model.storageUri` - OCI URI for the modelcar image (default: `oci://quay.io/rh-aiservices-bu/tinyllama:1.0`)
  - `model.name` - Model name used for InferenceService naming and `--served-model-name` (default: `tinyllama`)
  - `model.maxModelLen` - Maximum model context length (default: `2048`)
  - `model.maxOutputTokens` - Maximum output tokens (default: `512`)
  - `images.vllmRuntime` - vLLM CPU runtime image pinned by digest
  - `resources.inference.requests.cpu` / `memory` - CPU and memory requests (default: `2` CPU, `8Gi`)
  - `resources.inference.limits.cpu` / `memory` - CPU and memory limits (default: `8` CPU, `8Gi`)

- **Config files:**
  - `model-image/Containerfile` - Multi-stage build definition for the OCI modelcar image

## Known Gotchas

- **HF_TOKEN is a build-time secret, not a deploy-time secret:** The `HF_TOKEN` is passed as a `--build-arg` during the container build and is not needed at runtime. However, `ARG HF_TOKEN` without a default value means the build will proceed without a token, which will fail for gated models. TinyLlama is a public model so builds succeed without a token, but the Containerfile still declares the ARG for flexibility. Found in `model-image/Containerfile` line 5.

- **VLLM_CPU_KVCACHE_SPACE is set in two places with different values:** The InferenceService template sets `VLLM_CPU_KVCACHE_SPACE` to `4` (from `helm/templates/inferenceservice.yaml` line 44), while the ServingRuntime template sets it to `2` (from `helm/templates/servingruntime.yaml` line 36). The InferenceService value takes precedence at the container level, but the dual definition can cause confusion during tuning.

- **LD_PRELOAD for jemalloc vs libomp trade-off:** The README documents that the default vLLM CPU image sets `LD_PRELOAD` to jemalloc for pyarrow compatibility, which is unsupported. Setting `LD_PRELOAD` to `/usr/lib64/libomp.so` overrides this and improves vLLM performance, but breaks pyarrow if used. This must be configured manually in the ServingRuntime template. Found in `README.md` lines 97-110.

- **Intel CPU with AVX512 recommended:** The README notes this vLLM CPU version is compiled for Intel CPUs, preferably with AVX512 enabled for compressed model support. AWS m6i.4xlarge is cited as a known-good instance type. Found in `README.md` lines 61-62.

- **Model files land at /models/ in the image, served from /mnt/models by KServe:** The Containerfile sets `WORKDIR /models/` and copies model files there. KServe mounts the modelcar contents at `/mnt/models` (the vLLM `--model /mnt/models` arg), handling the path mapping automatically. Found in `model-image/Containerfile` line 17 and `helm/templates/servingruntime.yaml` line 23.

- **Non-root USER 1001:** The final image runs as non-root user 1001, compatible with OpenShift's restricted SCC without requiring `anyuid`. Found in `model-image/Containerfile` line 21.

## Testing Notes

- Build the modelcar image: `podman build -t quay.io/rh-aiservices-bu/tinyllama:1.0 --build-arg HF_TOKEN=hf_... model-image/`
- Deploy with Helm: `helm install hr-assistant helm/ --namespace hr-assistant`
- Wait for pods: `oc -n hr-assistant get pods -w` -- expect `tinyllama-1b-cpu-predictor` pod with 2/2 ready
- Minimum hardware: 2 CPU cores, 4Gi memory, no GPU required (from README)
- Recommended hardware: 32 cores, 64Gi memory for production throughput (from README)
- Uninstall: `helm uninstall hr-assistant --namespace hr-assistant`

## Related Patterns

- OCI modelcar storage for KServe (see `llama-32-3b-instruct.md` for GPU-based modelcar usage)
- vLLM CPU serving runtime on RHOAI (deployment pattern)
- HuggingFace model download tooling (build pattern)
