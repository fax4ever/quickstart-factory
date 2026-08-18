---
name: container-build-oci-modelcar-hf-download
description: Multi-stage Containerfile downloading HF model then packaging into minimal UBI modelcar for OCI storage
summary: "Packages HuggingFace model weights into minimal OCI modelcar container images for KServe model serving, using a two-stage Containerfile where stage 1 runs download_model.py via quay.io/redhat-ai-services/huggingface-downloader and stage 2 copies model files into ubi9/ubi-minimal:9.4 at /models/ with USER 1001 for OpenShift non-root compliance. Use when deploying models via KServe storageUri: \"oci://<registry>/<image>:<tag>\" with a runtime like vllm-cpu, requiring a data connection Secret with connection-type-ref: uri-v1 annotation containing the base64-encoded OCI URI linked to the InferenceService via opendatahub.io/connections annotation. Configure HF_TOKEN build arg (--build-arg HF_TOKEN=\"hf_...\") for gated HuggingFace models (optional for public models like TinyLlama), set MODEL_REPO env var for the target repository, and publish the built image to a container registry (Quay/GHCR) referenced in Helm values.yaml as model.storageUri. The downloader image places files at /models/ by convention so COPY --from=base /models/. . must match this path; for gated models HF_TOKEN must be passed at build time; and the data connection Secret must use connection-type-ref: uri-v1 with the InferenceService referencing the Secret name in its opendatahub.io/connections annotation."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [podman, ubi]
  ai_pattern: [model-serving]
  platform: [kserve, openshift, rhoai]
source_examples:
  - quickstart: "llm-cpu-serving"
    repo: "https://github.com/rh-ai-quickstart/llm-cpu-serving"
    notes: "Multi-stage Containerfile using huggingface-downloader to build a TinyLlama OCI modelcar image referenced via oci:// in KServe InferenceService"
    approach: "A"
---

# OCI Modelcar Image with HuggingFace Download

## Overview

This pattern uses a multi-stage Containerfile to download model files from HuggingFace in the build stage and package them into a minimal UBI container image. The resulting image serves as an OCI "modelcar" -- a container that holds only model weights and metadata, referenced by KServe InferenceService via an `oci://` storage URI.

## Pattern Description

The build process has two stages: a downloader stage using a purpose-built `huggingface-downloader` image that runs a Python script to fetch model files from the HuggingFace Hub, and a final stage using `ubi9/ubi-minimal` that copies only the model files into a clean image. The resulting image contains no runtime dependencies -- just model weights at `/models/`. KServe mounts this image as a model source via the `storageUri: "oci://<registry>/<image>:<tag>"` field in the InferenceService spec.

## Implementation

### Multi-Stage Containerfile

```dockerfile
# model-image/Containerfile
FROM quay.io/redhat-ai-services/huggingface-downloader:latest as base

# Set the HF_TOKEN with --build-arg HF_TOKEN="hf_..." at build time
ARG HF_TOKEN

# The model repo to download
ENV MODEL_REPO="TinyLlama/TinyLlama-1.1B-Chat-v1.0"

# Download the necessary model files
RUN python3 download_model.py --model-repo ${MODEL_REPO}

# Final image containing only the essential model files
FROM registry.access.redhat.com/ubi9/ubi-minimal:9.4

WORKDIR /models/

# Copy only the necessary model files from the base image
COPY --from=base /models/. .

# Set the user to 1001
USER 1001
```

### OCI Reference in InferenceService

The built image is pushed to a registry and referenced by the InferenceService:

```yaml
# helm/values.yaml (excerpt)
model:
  storageUri: "oci://quay.io/rh-aiservices-bu/tinyllama:1.0"
```

```yaml
# helm/templates/inferenceservice.yaml (excerpt)
spec:
  predictor:
    model:
      runtime: vllm-cpu
      storageUri: {{ .Values.model.storageUri | quote }}
```

### Data Connection Secret

KServe requires a data connection Secret to access the OCI registry. This Secret encodes the URI and is linked via an annotation on the InferenceService:

```yaml
# helm/templates/modelcar-dataconnection.yaml
kind: Secret
apiVersion: v1
metadata:
  name: tinyllama-10-on-quayio
  labels:
    opendatahub.io/dashboard: 'true'
  annotations:
    opendatahub.io/connection-type-ref: uri-v1
    openshift.io/display-name: tinyllama 1.0 on quay.io
data:
  URI: b2NpOi8vcXVheS5pby9yaC1haXNlcnZpY2VzLWJ1L3RpbnlsbGFtYToxLjA=
type: Opaque
```

## Configuration

- **Key settings:** `HF_TOKEN` build arg required for gated models; `MODEL_REPO` env var specifies the HuggingFace model repository; `storageUri` in values.yaml points to the published OCI image
- **Defaults:** Final image runs as `USER 1001` (OpenShift-compatible non-root); base image is `ubi9/ubi-minimal:9.4`
- **Dependencies:** The `quay.io/redhat-ai-services/huggingface-downloader` image provides the `download_model.py` script; a container registry (Quay, GHCR) to push the built image; KServe with OCI modelcar support on the cluster

## Gotchas

- The downloader image (`quay.io/redhat-ai-services/huggingface-downloader`) places model files at `/models/` by convention -- the `COPY --from=base /models/. .` must match this path (see `model-image/Containerfile`)
- For gated HuggingFace models, the `HF_TOKEN` build arg must be passed at build time (`--build-arg HF_TOKEN="hf_..."`), but for public models like TinyLlama it can be omitted (see `model-image/Containerfile`)
- The data connection Secret uses `connection-type-ref: uri-v1` annotation with base64-encoded URI, and the InferenceService references it via `opendatahub.io/connections: tinyllama-10-on-quayio` annotation (see `helm/templates/modelcar-dataconnection.yaml` and `helm/templates/inferenceservice.yaml`)

## Related Patterns

- `kserve-vllm-cpu-oci-modelcar-no-gpu.md` -- the KServe InferenceService and ServingRuntime that consume this modelcar image
