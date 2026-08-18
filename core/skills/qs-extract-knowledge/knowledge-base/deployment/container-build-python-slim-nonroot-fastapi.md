---
name: container-build-python-slim-nonroot-fastapi
description: python:3.11-slim single-stage Containerfile with pip install, non-root user 1001, and HEALTHCHECK for FastAPI
summary: "Provides the simplest single-stage Containerfile pattern for deploying FastAPI applications on OpenShift using python:3.11-slim with pip install --no-cache-dir, non-root UID 1001:0 (useradd + chmod -R g=u) for arbitrary UID support, and static frontend assets served directly by FastAPI without a separate frontend container. Choose over UBI-based patterns (container-build-ubi-uv-python-multistage, container-build-ubi-multistage-fullstack) when simplicity outweighs production compliance, and over container-build-python-slim-pip-uv-version-sed when uv tooling and version injection are unnecessary; minimal deps are fastapi, uvicorn[standard], aiohttp (SSE streaming), and pydantic with no compiled extensions. Critical config: single uvicorn worker (no --workers flag) is correct for async SSE; HEALTHCHECK uses python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8080/health')\" since curl is unavailable in python-slim; set PYTHONDONTWRITEBYTECODE=1 and PYTHONUNBUFFERED=1; .cache directory needs chown -R 1001:0. Gotchas: python:3.11-slim is not UBI-compliant and uses an older Python than other quickstarts risking compliance failure; adding --workers creates multiple event loops breaking SSE; the HEALTHCHECK comment claims \"lighter than python import\" but actually is a Python import; COPY static/ bundles frontend assets into the API container."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [python, fastapi]
  ai_pattern: [guardrails]
  platform: [openshift]
source_examples:
  - quickstart: "lemonade-stand-assistant"
    repo: "https://github.com/rh-ai-quickstart/lemonade-stand-assistant"
    notes: "python:3.11-slim with pip (no uv), non-root UID 1001, HEALTHCHECK using urllib, OpenShift group permissions"
    approach: "A"
---

# Python Slim FastAPI Container with Non-Root User

## Overview

This pattern builds a FastAPI application container from `python:3.11-slim` using a simple single-stage build with `pip` (no `uv`), a non-root user for OpenShift compatibility, and a `HEALTHCHECK` instruction using Python's standard library. It represents the simplest container build pattern for Python web services in the quickstart ecosystem.

## Pattern Description

The Containerfile creates a minimal FastAPI container without multi-stage builds, without `uv`, and without UBI base images. Dependencies are installed via `pip install --no-cache-dir -r requirements.txt`. A non-root user (UID 1001) is created for OpenShift's arbitrary UID support, and the working directory is set with proper group ownership (`chown -R 1001:0`, `chmod -R g=u`). The container includes a `HEALTHCHECK` instruction for container runtime health monitoring.

## Implementation

### Containerfile

```dockerfile
# lemonade-stand-app/Containerfile
FROM python:3.11-slim

LABEL maintainer="ckavili@redhat.com"
LABEL description="FastAPI chat application for lemonade stand demo"
LABEL version="2.0"

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Create non-root user for OpenShift compatibility
RUN useradd -m -u 1001 appuser

WORKDIR /application

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app_fastapi.py .
COPY static/ ./static/

# Create cache directory with proper permissions
RUN mkdir -p /application/.cache && \
    chown -R 1001:0 /application && \
    chmod -R g=u /application

USER 1001

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')" || exit 1

CMD ["python", "-m", "uvicorn", "app_fastapi:app", "--host", "0.0.0.0", "--port", "8080"]
```

### Requirements

The dependency list is minimal with only four packages:

```
# lemonade-stand-app/requirements.txt
fastapi>=0.104.0
uvicorn[standard]>=0.24.0  # includes uvloop + httptools for better performance
aiohttp>=3.9.0  # async HTTP client for SSE streaming
pydantic>=2.0.0
```

## Configuration

- **Key settings:** Port 8080 (FastAPI default for OpenShift); UID 1001 with group 0; `PYTHONDONTWRITEBYTECODE=1` prevents `.pyc` file creation; `PYTHONUNBUFFERED=1` ensures real-time logging
- **Defaults:** Single uvicorn worker (no `--workers` flag); uses `python:3.11-slim` (not python:3.12 or UBI); pip install (not uv)
- **Dependencies:** Minimal: `fastapi`, `uvicorn[standard]`, `aiohttp`, `pydantic` -- no build tools, no compiled extensions

## Gotchas

- Uses `python:3.11-slim` rather than UBI or python:3.12 -- this may not meet production compliance requirements and uses an older Python version than other quickstarts (see `lemonade-stand-app/Containerfile`)
- The `HEALTHCHECK` instruction uses `python -c "import urllib.request; ..."` instead of `curl` -- the comment says "lighter than python import" but it actually is a Python import; `curl` is not available in python-slim (see `lemonade-stand-app/Containerfile`)
- Single uvicorn worker is appropriate for async FastAPI with SSE streaming (the comment says "single worker for async, high concurrency") -- adding `--workers` would create multiple event loops (see `lemonade-stand-app/Containerfile`)
- The `COPY static/ ./static/` line means the container includes static frontend assets served directly by FastAPI, not a separate frontend container (see `lemonade-stand-app/Containerfile`)

## Related Patterns

- `container-build-python-slim-pip-uv-version-sed.md` -- similar python:slim base but with uv and sed-based version injection
- `container-build-ubi-uv-python-multistage.md` -- UBI-based multi-stage build with uv for production containers
- `container-build-ubi-multistage-fullstack.md` -- UBI-based multi-stage build for fullstack apps
