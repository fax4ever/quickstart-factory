---
name: container-build-tei-model-prebake
description: TEI Dockerfile pre-downloading HuggingFace model during build, removing Python after download
summary: "Pre-downloads a HuggingFace embedding model (nomic-ai/nomic-embed-text-v1.5) into a custom TEI CPU container image at build time using huggingface_hub snapshot_download(cache_dir='/data'), eliminating runtime HuggingFace Hub connectivity -- build requires network access but runtime does not. Use when deploying TEI embeddings in environments where runtime model downloads are unacceptable; extends ghcr.io/huggingface/text-embeddings-inference:cpu-1.8 with temporary Python install that is removed post-download to minimize image size, running as non-root UID 1000. Critical config: MODEL_ID env var must exactly match the pre-downloaded model, HF_HOME=/data points TEI to cached artifacts, throughput tuned via MAX_CLIENT_BATCH_SIZE and MAX_BATCH_TOKENS; published image is quay.io/rh-ai-quickstart/alm-rag:tei-rag-v1 (differs from compose service name alm-embedding). Gotchas: pip install requires --break-system-packages due to TEI's externally-managed Python, healthcheck start_period must be 180s even with pre-downloaded model because TEI still loads into memory at startup, and the Dockerfile uses apt-get (Debian-based TEI image) while other quickstart services use UBI-based images with dnf."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [python]
  ai_pattern: [embeddings]
  platform: [openshift]
source_examples:
  - quickstart: "ansible-log-analysis"
    repo: "https://github.com/rh-ai-quickstart/ansible-log-analysis"
    notes: "TEI cpu-1.8 image with nomic-embed-text-v1.5 pre-downloaded via huggingface_hub, Python removed after"
    approach: "A"
---

# TEI Image with Pre-Downloaded HuggingFace Model

## Overview

This pattern builds a custom Text Embeddings Inference (TEI) container image that pre-downloads a HuggingFace model during the Docker build phase. This eliminates the need for model downloads at runtime, reducing startup time and removing the runtime dependency on HuggingFace Hub connectivity. Python is temporarily installed for the download and then removed to minimize image size.

## Pattern Description

The Dockerfile extends the official TEI CPU image (`ghcr.io/huggingface/text-embeddings-inference:cpu-1.8`), temporarily installs Python and `huggingface_hub`, uses `snapshot_download()` to pre-download the model to TEI's expected data directory (`/data`), then removes Python. The final image contains the model artifacts and runs as TEI's default non-root user (UID 1000).

## Implementation

### Dockerfile with Temporary Python Install

```dockerfile
# services/text-embeddings-inference/Dockerfile
FROM ghcr.io/huggingface/text-embeddings-inference:cpu-1.8

# Install Python and huggingface_hub to download model
USER root
RUN apt-get update && apt-get install -y python3 python3-pip && \
    pip3 install --no-cache-dir --break-system-packages huggingface_hub && \
    rm -rf /var/lib/apt/lists/*

# Set HuggingFace cache directory (TEI uses this)
ENV HF_HOME=/data

# Pre-download the model during build
RUN python3 -c "from huggingface_hub import snapshot_download; \
    snapshot_download('nomic-ai/nomic-embed-text-v1.5', \
                      cache_dir='/data')"

# Clean up Python (optional - reduces image size)
RUN apt-get remove -y python3 python3-pip && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

# Switch back to non-root user (TEI runs as UID 1000)
USER 1000
```

### Compose Usage

The pre-built image is used in both local dev compose and Helm deployment:

```yaml
# deploy/local/compose.yaml (excerpt)
alm-embedding:
  image: quay.io/rh-ai-quickstart/alm-rag:tei-rag-v1
  environment:
    - MODEL_ID=nomic-ai/nomic-embed-text-v1.5
    - HF_HOME=/data
    - PORT=8080
    - MAX_CLIENT_BATCH_SIZE=32
    - MAX_BATCH_TOKENS=8192
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:8080/health"]
    start_period: 180s  # Model loading can take 3+ minutes
```

## Configuration

- **Key settings:** `MODEL_ID` environment variable must match the pre-downloaded model (`nomic-ai/nomic-embed-text-v1.5`); `HF_HOME=/data` points TEI to the pre-downloaded artifacts; `MAX_CLIENT_BATCH_SIZE` and `MAX_BATCH_TOKENS` tune throughput
- **Defaults:** TEI CPU variant (no GPU); model pre-downloaded to `/data`; runs as UID 1000
- **Dependencies:** Build requires network access to HuggingFace Hub; runtime does not

## Gotchas

- The `--break-system-packages` flag is needed on `pip3 install` because the TEI base image uses an externally-managed Python environment (see `services/text-embeddings-inference/Dockerfile` line 6)
- The pre-built image is published as `quay.io/rh-ai-quickstart/alm-rag:tei-rag-v1`, not under the `alm-embedding` name, which can cause confusion with the compose service name `alm-embedding` (see `deploy/local/compose.yaml` line 221)
- Even with a pre-downloaded model, the healthcheck `start_period` is set to 180s (3 minutes) because TEI still needs time to load the model into memory at startup (see `compose.yaml` line 239)
- The Dockerfile uses `apt-get` (Debian-based TEI image) while the rest of the quickstart uses UBI-based images with `dnf`/`pip`

## Related Patterns

- `container-build-ubi-uv-python-multistage.md` -- UBI-based Containerfiles for the other services
- `helm-alloy-sidecar-pvc-log-collector.md` -- embedding service referenced by the RAG stack
