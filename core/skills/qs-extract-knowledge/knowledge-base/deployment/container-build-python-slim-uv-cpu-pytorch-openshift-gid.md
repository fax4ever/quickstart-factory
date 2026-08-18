---
name: container-build-python-slim-uv-cpu-pytorch-openshift-gid
description: Multi-stage python:3.11-slim with uv, CPU-only PyTorch index, monorepo cross-package COPY, and OpenShift GID 0 permissions
summary: "This pattern builds a FastAPI container using two-stage python:3.11-slim with uv (from ghcr.io/astral-sh/uv:latest), forcing CPU-only PyTorch via --extra-index-url https://download.pytorch.org/whl/cpu to avoid ~25GB CUDA libraries, while handling monorepo cross-package COPY (sibling packages/db/, config/, data/) by setting the build context to the repo root. Use for Python API containers needing CPU-only embedding inference (sentence-transformers/nomic-embed-text) on OpenShift restricted SCC -- the GID 0 pattern uses chown appuser:0 + chmod g+w on cache dirs only (not g=u), keeping source and config read-only. Critical config: HF_HOME=/app/.cache/huggingface for model cache with start_period=40s HEALTHCHECK to accommodate first-run download latency; runtime serves uvicorn on port 8000 and the same image supports alternate entry points (e.g., MCP server) via CMD override. Gotchas: uv pip install -e .[dev] || uv pip install -e . fallback may leak dev dependencies into production, --extra-index-url slows resolution for all packages not just PyTorch, and the runtime stage redundantly copies uv from both the builder and ghcr.io."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [python, fastapi]
  ai_pattern: [agents, embeddings]
  platform: [openshift]
source_examples:
  - quickstart: "multi-agent-loan-origination"
    repo: "https://github.com/rh-ai-quickstart/multi-agent-loan-origination"
    notes: "Multi-stage python:3.11-slim with uv from ghcr.io, CPU-only PyTorch via --extra-index-url, cross-package COPY from monorepo root, GID 0 with g+w for OpenShift"
    approach: "A"
---

# Python Slim Multi-Stage with uv and CPU-Only PyTorch

## Overview

This pattern builds a FastAPI application container using a multi-stage `python:3.11-slim` build with the `uv` package manager, specifically configured for CPU-only PyTorch (avoiding ~25GB of CUDA libraries) and OpenShift's arbitrary UID security model via GID 0 permissions. It handles monorepo cross-package dependencies where the API package depends on a sibling DB package.

## Pattern Description

The Containerfile uses two stages: a builder stage that installs `uv` from its official container image and installs dependencies with a CPU-only PyTorch extra-index-url, and a runtime stage that copies the installed site-packages, application source, and config/data directories. The build context is the monorepo root (not the package directory), enabling COPY of sibling packages. OpenShift compatibility uses `chown -R appuser:0` with `chmod -R g+w` on cache directories rather than the `chmod -R g=u` pattern.

## Implementation

### Builder Stage with uv and CPU-Only PyTorch

```dockerfile
# packages/api/Containerfile
FROM python:3.11-slim AS builder

# Install uv from official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Copy API package files (needed for version detection and dependencies)
COPY packages/api/pyproject.toml ./packages/api/
COPY packages/api/src/ ./packages/api/src/
# Copy DB package (API depends on it)
COPY packages/db/ ./packages/db/

WORKDIR /app/packages/api

# Install dependencies -- use CPU-only PyTorch to avoid shipping ~25GB of
# unused CUDA libraries.  The embedding model runs on CPU in the container.
RUN uv pip install --system \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    -e .[dev] \
    || uv pip install --system \
    --extra-index-url https://download.pytorch.org/whl/cpu \
    -e .
```

### Runtime Stage with GID 0 Permissions

```dockerfile
# packages/api/Containerfile (continued)
FROM python:3.11-slim AS runtime

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Create non-root user
RUN groupadd -r appuser && useradd -r -g appuser appuser

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application source
COPY packages/api/src/ ./packages/api/src/
COPY packages/api/pyproject.toml ./packages/api/

# Copy DB package source (API depends on it via editable install)
COPY packages/db/ ./packages/db/

# Copy config files (models.yaml, agent configs, keycloak realm)
COPY config/ ./config/
# Copy compliance KB data for seeding
COPY data/ ./data/

WORKDIR /app/packages/api

# HuggingFace model cache -- sentence-transformers downloads models here
ENV HF_HOME=/app/.cache/huggingface
RUN mkdir -p /app/.cache/huggingface

# Set ownership -- use group 0 (root) with g+w so OpenShift's arbitrary
# UIDs (restricted SCC) can write to the cache directory.
RUN chown -R appuser:0 /app && chmod -R g+w /app/.cache

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/')" || exit 1

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## Configuration

- **Key settings:** `--extra-index-url https://download.pytorch.org/whl/cpu` forces CPU-only PyTorch; `HF_HOME=/app/.cache/huggingface` sets HuggingFace cache location; `chown -R appuser:0` assigns GID 0 for OpenShift arbitrary UID; build context must be monorepo root
- **Defaults:** Port 8000; `start_period=40s` in HEALTHCHECK accommodates model loading; the dev extras (`-e .[dev]`) are attempted first with fallback to base install
- **Dependencies:** Monorepo root as build context (not `packages/api/`); `packages/db/` must be present at build time for editable install; `config/` and `data/` directories are copied for runtime config and seed data

## Gotchas

- The `uv pip install --system` command with `|| uv pip install --system` fallback tries the `[dev]` extra first, then falls back to base -- this means the production image may include dev dependencies if the `[dev]` extra succeeds (see `packages/api/Containerfile` lines 22-27)
- The `--extra-index-url https://download.pytorch.org/whl/cpu` applies to all packages, not just PyTorch -- pip/uv will check this index for every dependency, which can slow builds but won't pull wrong packages (see `packages/api/Containerfile` comment on line 21)
- The `COPY --from=builder /usr/local/bin /usr/local/bin` copies all binaries from the builder stage, including uv -- the runtime also independently copies uv from `ghcr.io/astral-sh/uv:latest`, resulting in two potential uv installs (see `packages/api/Containerfile` lines 33, 43)
- The `chmod -R g+w /app/.cache` only applies g+w to the cache directory, not the entire `/app` -- the source code and config remain read-only to non-owner users, which is the intended security posture (see `packages/api/Containerfile` line 67)
- The HuggingFace model cache (`HF_HOME`) means the first startup downloads the embedding model (`nomic-ai/nomic-embed-text-v1.5`), adding latency to initial pod startup -- this is why `start_period=40s` is set in the HEALTHCHECK (see `packages/api/Containerfile` lines 61-62)
- The same Containerfile is reused by the MCP risk server in compose.yml with a different command (`python -m src.mcp_server`) -- one image serves two different entry points (see `compose.yml` lines 119-126)

## Related Patterns

- `container-build-python-slim-nonroot-fastapi.md` -- simpler single-stage python-slim without uv or multi-stage
- `container-build-ubi-uv-python-multistage.md` -- UBI-based variant with uv
- `container-build-python-slim-pip-uv-version-sed.md` -- python-slim with uv but different install strategy
