---
name: container-build-nvidia-distroless-uv-dev-release-target
description: Multi-stage Dockerfile with NVIDIA Ubuntu builder and distroless Python runtime, uv workspace, dev/release targets
summary: "Produces dev (CLI+debug) and release (web-only) container images from a single multi-stage Dockerfile using NVIDIA Ubuntu (nvcr.io/nvidia/base/ubuntu:noble) as builder and NVIDIA distroless Python (nvcr.io/nvidia/distroless/python:3.13) as runtime, avoiding separate Dockerfiles while ensuring production images never contain development tooling. Use when building NVIDIA-based Python applications with uv workspaces that need separate dev and production images -- select via docker build --target dev|release (compose defaults to BUILD_TARGET:-dev). Builder bootstraps Python 3.13 via uv with UV_PYTHON_INSTALL_DIR=/opt/uv-python, runs uv sync --frozen --no-dev --no-install-workspace then individual uv pip install --no-deps -e for each workspace member, selectively copies only runtime source and specific deploy scripts (never the full deploy/ directory), and both runtime targets run as USER 1000:1000 with release setting APP_ENV=production. /opt/uv-python must be explicitly COPY'd from builder to distroless runtime (no package manager available), --break-system-packages is required for pip-installing uv on the Ubuntu builder due to PEP 668, and chown -R 1000:1000 /app is needed in the builder so the non-root distroless user can access all files."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [python, fastapi, uv]
  ai_pattern: [agents]
  platform: [kubernetes]
  data_layer: [postgresql]
source_examples:
  - quickstart: "rh-research"
    repo: "https://github.com/rh-ai-quickstart/rh-research"
    notes: "NVIDIA AI-Q Blueprint backend with dev target (CLI+debug) and release target (web-only production)"
    approach: "A"
---

# NVIDIA Distroless Python Build with Dev/Release Targets

## Overview

A multi-stage Dockerfile pattern that uses NVIDIA-authorized Ubuntu as the builder base and NVIDIA distroless Python as the runtime base, with named build targets (`dev` and `release`) that allow the same Dockerfile to produce different images for development and production. The dev target includes CLI and debug tools; the release target strips them for a minimal production image.

## Pattern Description

The build uses four stages: a shared builder stage that installs all core dependencies using `uv`, a dev-builder stage that adds CLI/debug packages on top, and two final runtime stages (dev and release) that copy from the appropriate builder into a minimal NVIDIA distroless Python image. The `--target` flag at build time selects which image to produce. This avoids maintaining separate Dockerfiles while enforcing that production images never contain development tooling.

## Implementation

### Stage 1: Shared Builder

The builder stage starts from NVIDIA Ubuntu, installs system dependencies, bootstraps Python 3.13 via uv, and creates a virtualenv. It then installs workspace packages using `uv sync --frozen --no-dev --no-install-workspace` for locked dependency resolution, followed by individual editable installs of workspace members.

```dockerfile
FROM nvcr.io/nvidia/base/ubuntu:noble-20260217 AS builder

WORKDIR /app

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y \
    tzdata build-essential ca-certificates curl git python3 python3-pip \
    && rm -rf /var/lib/apt/lists/*

ENV UV_PYTHON_INSTALL_DIR=/opt/uv-python

RUN python3 -m pip install --break-system-packages --no-cache-dir uv \
    && uv python install 3.13 \
    && UV_PYTHON_BIN="$(uv python find 3.13)" \
    && ln -sf "$UV_PYTHON_BIN" /usr/local/bin/python \
    && ln -sf "$UV_PYTHON_BIN" /usr/local/bin/python3

RUN uv venv /app/.venv --python /usr/local/bin/python

ENV VIRTUAL_ENV=/app/.venv
ENV PATH="/app/.venv/bin:$PATH"
ENV UV_PYTHON=/app/.venv/bin/python
```

### Stage 2: Selective Source Copy

Only runtime-relevant source directories and specific deploy scripts are copied -- never the full `deploy/` directory, to avoid leaking `.env`, Helm charts, compose files, or other dev artifacts into the image.

```dockerfile
COPY pyproject.toml uv.lock ./
COPY src/ ./src/
COPY sources/ ./sources/
COPY frontends/aiq_api/ ./frontends/aiq_api/
COPY frontends/cli/ ./frontends/cli/
COPY configs/ ./configs/
# Only copy runtime scripts from deploy/
COPY deploy/entrypoint.py deploy/start_web.py ./deploy/

RUN uv sync --frozen --no-dev --no-install-workspace

RUN uv pip install --no-deps -e . \
    && uv pip install --no-deps -e ./sources/google_scholar_paper_search \
    && uv pip install --no-deps -e ./sources/tavily_web_search \
    && uv pip install --no-deps -e ./frontends/aiq_api \
    && uv pip install "psycopg[binary]>=3.0.0"
```

### Stage 3: Dev vs Release Targets

The dev target layers CLI and debug tools on top of the builder, while release copies only the base builder output.

```dockerfile
FROM builder AS dev-builder
RUN uv pip install --no-deps -e ./frontends/cli \
    && uv pip install --no-deps -e ./frontends/debug

FROM nvcr.io/nvidia/distroless/python:3.13-v4.0.5 AS dev
COPY --from=dev-builder /opt/uv-python /opt/uv-python
COPY --from=dev-builder /app /app
USER 1000:1000

FROM nvcr.io/nvidia/distroless/python:3.13-v4.0.5 AS release
COPY --from=builder /opt/uv-python /opt/uv-python
COPY --from=builder /app /app
USER 1000:1000
ENV APP_ENV=production
```

### Build Commands

```bash
docker build --target dev -t aiq:dev .      # Development (includes CLI)
docker build --target release -t aiq:prod .  # Production (web only)
```

## Configuration

- **Key settings:** `--target dev|release` selects the image variant; `UV_PYTHON_INSTALL_DIR=/opt/uv-python` for uv-managed Python location
- **Defaults:** Dev target is default in docker-compose (`BUILD_TARGET:-dev`); release is used for production deployments
- **Dependencies:** NVIDIA NGC registry access for base images; `uv.lock` must be committed and up-to-date

## Gotchas

- The uv-managed Python installation directory (`/opt/uv-python`) must be explicitly copied from builder to distroless runtime since distroless images have no package manager
- `--break-system-packages` flag is required when using pip to install uv on the Ubuntu builder because of PEP 668 externally-managed environments
- The `chown -R 1000:1000 /app` in the builder ensures the non-root user in the distroless runtime can access all files
- Only specific deploy scripts (`entrypoint.py`, `start_web.py`) are copied -- the comment in the Dockerfile explicitly warns against copying the full `deploy/` directory to avoid leaking secrets

## Related Patterns

- `compose-local-dev-prebuilt-ngc-fallback-build-target-dask.md` -- compose file uses BUILD_TARGET to select dev/release
- `entrypoint-dask-cluster-uvicorn-nat-asyncio-bypass.md` -- the entrypoint.py referenced by this Dockerfile
