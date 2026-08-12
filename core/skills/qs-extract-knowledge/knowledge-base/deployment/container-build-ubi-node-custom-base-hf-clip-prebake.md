---
name: container-build-ubi-node-custom-base-hf-clip-prebake
description: Multi-stage Containerfile using UBI9 Node.js for frontend and self-published recommendation-core as backend base
summary: "Solves building a production fullstack container where UBI9 nodejs-22 compiles React into frontend/dist and the backend inherits from the quickstart's own self-published quay.io/rh-ai-quickstart/recommendation-core:latest library image, pre-downloading HuggingFace CLIP (openai/clip-vit-base-patch32) models at build time to avoid runtime latency. Use when the quickstart has a separately-published library base image on Quay and needs ML models baked in -- requires CI workflow_run chaining to ensure the base image is built before this Containerfile runs. Critical config: HF_HOME=/hf_cache with chmod -R 777 for OpenShift arbitrary UID, PYTHONPATH spans backend and recommendation-core src paths, NODE_OPTIONS=--max-old-space-size=2048 for frontend build, uv for pip install, and uvicorn main:app on port 8000 as entrypoint. Gotchas: unpinned :latest base image tag means broken recommendation-core publishes cascade downstream, --reload flag left in production uvicorn entrypoint is a dev convenience leak, and static product images copied from recommendation-core source tree layout creates tight coupling between images."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [fastapi, react, python, nodejs]
  ai_pattern: [embeddings, recommendation]
  platform: [openshift]
source_examples:
  - quickstart: "product-recommender-system"
    repo: "https://github.com/rh-ai-quickstart/product-recommender-system"
    notes: "UBI9 Node.js frontend build stage + recommendation-core:latest as backend base + CLIP model pre-download"
    approach: "A"
---

# Multi-Stage Containerfile with Custom Base Image and HuggingFace Model Pre-Bake

## Overview

Builds a production fullstack container image using a multi-stage Containerfile where the frontend is built in a UBI9 Node.js stage and the backend stage uses the quickstart's own separately-published library image as a base, pre-downloading HuggingFace CLIP models during build.

## Pattern Description

Rather than starting from a standard UBI Python base, the backend stage inherits from `quay.io/rh-ai-quickstart/recommendation-core:latest` -- the quickstart's own library image built and published by a separate CI workflow. This creates an image dependency chain where the library image must be built first. The frontend stage uses `ubi9/nodejs-22` to build React assets that are copied into the backend stage. HuggingFace CLIP models are pre-downloaded during the build to avoid runtime download latency.

## Implementation

### Frontend Build Stage

```dockerfile
# Containerfile (root)
FROM registry.access.redhat.com/ubi9/nodejs-22 AS frontend-builder
USER root
WORKDIR /app/frontend
COPY frontend/package*.json ./
COPY frontend/ ./
ENV NODE_OPTIONS=--max-old-space-size=2048
RUN npm install --debug && npm run build
```

### Backend Stage Using Self-Published Base

```dockerfile
FROM quay.io/rh-ai-quickstart/recommendation-core:latest
USER root
WORKDIR /app/backend
COPY backend/pyproject.toml pyproject.toml
COPY recommendation-core/ /app/recommendation-core/
COPY backend/ ./
COPY --from=frontend-builder /app/frontend/dist ./public
COPY recommendation-core/src/recommendation_core/generation/data/generated_images ./public/images
```

### HuggingFace CLIP Model Pre-Download

```dockerfile
ENV HF_HOME=/hf_cache
ENV PYTHONPATH=/app/backend:/app/backend/src:/app/recommendation-core/src

RUN pip install --upgrade pip && pip3 install uv && uv pip install -r pyproject.toml && \
    mkdir -p /hf_cache && \
    python3 -c "from transformers import CLIPProcessor, CLIPModel; \
                CLIPProcessor.from_pretrained('openai/clip-vit-base-patch32'); \
                CLIPModel.from_pretrained('openai/clip-vit-base-patch32')" && \
    chmod -R 777 /hf_cache && \
    chmod -R +r .

EXPOSE 8000
WORKDIR /app/backend/src
ENTRYPOINT ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
```

## Configuration

- **Key settings:** `HF_HOME=/hf_cache` for HuggingFace cache, `PYTHONPATH` includes both backend and recommendation-core source paths, `NODE_OPTIONS=--max-old-space-size=2048` for frontend build memory
- **Defaults:** CLIP model `openai/clip-vit-base-patch32` is hardcoded in the pre-download step
- **Dependencies:** `recommendation-core:latest` image must be published to Quay before this Containerfile can build; CI enforces this via `workflow_run` chaining

## Gotchas

- The `recommendation-core:latest` base image tag means this build always uses the latest published library image; no version pinning exists, so a broken recommendation-core publish will break downstream builds.
- Static product images are copied from `recommendation-core/src/recommendation_core/generation/data/generated_images` into `./public/images`, coupling the image to the recommendation-core source tree layout.
- The `--reload` flag in the uvicorn entrypoint is a development convenience left in the production image.
- `chmod -R 777 /hf_cache` is applied to allow OpenShift's arbitrary UID to access the pre-downloaded models.

## Related Patterns

- `container-build-ubi9-python-uv-init-first-lib-base.md` — the recommendation-core library image that serves as this Containerfile's base
- `github-actions-workflow-run-cascade-build-chain.md` — CI ensures recommendation-core is built before this image
