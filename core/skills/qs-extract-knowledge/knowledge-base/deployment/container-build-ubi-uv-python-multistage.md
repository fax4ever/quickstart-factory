---
name: container-build-ubi-uv-python-multistage
description: Multi-stage UBI8 Python Containerfile with uv copied from official image for dependency management
summary: "Builds Python containers on Red Hat UBI8/python-312 using the uv package manager (COPY --from ghcr.io/astral-sh/uv:0.9.7) with multi-stage builds that split dependency installation from project installation for optimal Docker layer caching. Three variants: multi-stage root Containerfile (uv sync --frozen --no-install-project then --no-editable --no-dev, copies only .venv and source to runtime stage) for the main app, single-stage service Containerfiles for lightweight services using the same uv pattern, and a non-uv pip variant for services with requirements.txt instead of pyproject.toml/uv.lock. Critical config: OpenShift arbitrary UID support requires chgrp -R 0 / chmod -R g=u on app and cache directories, runtime venv activation via VIRTUAL_ENV=/app/.venv with PATH prepend, build-time UV_HTTP_TIMEOUT=600 for large packages, and TORCH_CUDA_ARCH_LIST=\"\" to skip CUDA compilation. Common gotchas: deepeval cache directory requires chmod -R 777 with HOME=/app to avoid PermissionError, HuggingFace cache needs /hf_cache with 777 permissions and HF_HOME env var, rag service Containerfile builds from repo root context (COPY services/rag/...) while other services build from their own directory, and README.md must be present for pyproject.toml package metadata resolution."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [python, fastapi]
  ai_pattern: []
  platform: [openshift]
source_examples:
  - quickstart: "ansible-log-analysis"
    repo: "https://github.com/rh-ai-quickstart/ansible-log-analysis"
    notes: "Multi-stage UBI8/python-312 with uv for backend; single-stage variants for services"
    approach: "A"
---

# Multi-Stage UBI Python Containerfile with uv

## Overview

This pattern uses multi-stage container builds based on Red Hat UBI8 Python 3.12 images with the `uv` package manager copied from its official container image. The builder stage installs dependencies and the project separately for optimal layer caching, and the runtime stage copies only the virtual environment and source code. Service-specific Containerfiles use simpler single-stage variants of the same pattern.

## Pattern Description

The root `Containerfile` uses a two-stage build: a builder stage that copies `uv` from `ghcr.io/astral-sh/uv:0.9.7`, installs dependencies via `uv sync --frozen --no-install-project`, then installs the project itself. The runtime stage copies the completed `.venv` directory and application source. OpenShift compatibility is handled via `chgrp -R 0` and `chmod -R g=u` for arbitrary UID support. Service Containerfiles (ui, annotation-interface, clustering, rag) use single-stage builds with the same uv pattern.

## Implementation

### Root Containerfile (Multi-Stage)

```dockerfile
# Containerfile (root)
FROM registry.access.redhat.com/ubi8/python-312 AS builder
USER root
COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN UV_HTTP_TIMEOUT=600 \
    TORCH_CUDA_ARCH_LIST="" \
    uv sync --frozen --no-install-project --no-dev
COPY README.md ./
COPY src/ ./src/
COPY data/logs/failed/ ./data/logs/failed/
RUN UV_HTTP_TIMEOUT=600 \
    TORCH_CUDA_ARCH_LIST="" \
    uv sync --frozen --no-dev --no-editable

FROM registry.access.redhat.com/ubi8/python-312
USER root
WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
COPY --from=builder /app/README.md /app/
COPY --from=builder /app/pyproject.toml /app/
COPY data/knowledge_base/ ./data/knowledge_base/
COPY backend_init_pipeline.py ./
ENV VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    HF_HOME=/hf_cache
RUN mkdir -p /app/data/logs/failed /hf_cache && \
    chgrp -R 0 /app /hf_cache && \
    chmod -R g=u /app /hf_cache
EXPOSE 8000
ENTRYPOINT ["uvicorn", "alm.main_fastapi:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Service Containerfile (Single-Stage)

Service Containerfiles use a simpler single-stage pattern with the same uv approach:

```dockerfile
# services/ui/Containerfile
FROM registry.access.redhat.com/ubi8/python-312
USER root
COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml ./
RUN uv sync --no-dev
ENV VIRTUAL_ENV=/app/.venv
ENV PATH="/app/.venv/bin:$PATH"
COPY app.py .
EXPOSE 7860
ENTRYPOINT ["python","app.py"]
```

### Non-uv Service Containerfile

The aap-log-collector uses pip instead of uv (it has a `requirements.txt` rather than `pyproject.toml`):

```dockerfile
# services/aap-log-collector/Containerfile
FROM registry.access.redhat.com/ubi8/python-312
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
USER root
RUN chmod -R g=u /app
USER 1001
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "app.main"]
```

## Configuration

- **Key settings:** `UV_HTTP_TIMEOUT=600` extends the download timeout for large packages; `TORCH_CUDA_ARCH_LIST=""` prevents CUDA dependency compilation; `--frozen` flag ensures lockfile is respected exactly
- **Defaults:** All images use `registry.access.redhat.com/ubi8/python-312` base; uv version pinned to `0.9.7`
- **Dependencies:** Requires `pyproject.toml` and `uv.lock` in each service directory; the root Containerfile also needs `README.md` for proper package metadata

## Gotchas

- The root Containerfile splits dependency installation into two steps (`--no-install-project` then full install) for Docker layer caching -- changes to source code do not re-download dependencies (see `Containerfile` lines 14-19, 24-27)
- The annotation-interface Containerfile creates `.deepeval` directory with `chmod -R 777` and sets `HOME=/app` to fix a PermissionError from deepeval's cache directory (see `services/annotation_interface/Containerfile` lines 18-19)
- The clustering service creates `/hf_cache` with `chmod -R 777` for HuggingFace model downloads at runtime (see `services/clustering/Containerfile` lines 17-19)
- The rag service Containerfile builds from the repo root context but copies from `services/rag/` paths (`COPY services/rag/pyproject.toml ./`), while other service Containerfiles build from their own directory context (see `services/rag/Containerfile` lines 12, 20)

## Related Patterns

- `container-build-tei-model-prebake.md` -- different build pattern for the TEI embedding service
- `github-actions-path-filtered-matrix-skopeo-retag.md` -- CI workflow that builds these Containerfiles
