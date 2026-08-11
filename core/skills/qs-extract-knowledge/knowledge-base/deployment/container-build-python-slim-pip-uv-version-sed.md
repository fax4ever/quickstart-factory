---
name: container-build-python-slim-pip-uv-version-sed
description: python:3.12-slim Containerfile with pip-installed uv and sed-based LlamaStack version injection at build time
summary: "Builds a Streamlit frontend container using single-stage python:3.12-slim with pip-installed uv and sed-based build-time version injection, replacing a __LLAMASTACK_VERSION__ placeholder in pyproject.toml via ARG before uv sync. Use for dev/demo Streamlit apps where UBI compliance is not required -- prefer container-build-ubi-uv-python-multistage.md for production needing pinned uv (COPY --from=ghcr.io/astral-sh/uv:<version>) and UBI base; CI passes the version via docker/build-push-action@v5 build-args to Quay.io. Critical config: sed -i \"s/__LLAMASTACK_VERSION__/${LLAMASTACK_VERSION}/g\" pyproject.toml runs before conditional uv sync --frozen (or uv sync if no lockfile); UV_CACHE_DIR=/app/.uv-cache and XDG_CACHE_HOME=/app/.cache redirect caches, chown -R 1001:0 with chmod -R g+rwX handles OpenShift arbitrary UID, port 8501 exposed. Common gotcha: the committed pyproject.toml contains __LLAMASTACK_VERSION__ placeholder (not a valid version) so uv sync fails without the sed step; cache directories require chmod 777 regardless of running UID; pip install uv pulls the latest unpinned version at build time; python:3.12-slim may not meet production compliance mandating UBI."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [python, streamlit, llamastack]
  ai_pattern: [rag]
  platform: [openshift]
source_examples:
  - quickstart: "f5-ai-guardrails"
    repo: "https://github.com/rh-ai-quickstart/f5-ai-guardrails"
    notes: "python:3.12-slim base, uv via pip, sed replaces __LLAMASTACK_VERSION__ in pyproject.toml, OpenShift UID 1001 ownership"
    approach: "A"
---

# Python Slim Container with pip-installed uv and Version Injection

## Overview

This pattern builds a Streamlit frontend container using `python:3.12-slim` as the base image (not UBI), installs `uv` via `pip`, and uses `sed` to inject a build-time version string into `pyproject.toml` before dependency resolution. It handles OpenShift's arbitrary UID constraints by setting file ownership to `1001:0` with group write permissions.

## Pattern Description

The `frontend/Containerfile` uses a single-stage build with `python:3.12-slim`. The `uv` package manager is installed via `pip install uv` (unlike the COPY-from-image approach used in UBI-based builds). A `__LLAMASTACK_VERSION__` placeholder in `pyproject.toml` is replaced at build time via `sed`, allowing the LlamaStack SDK version to be pinned via a `--build-arg` without modifying the source file. The frozen lockfile is used when present (`uv sync --frozen`); otherwise a fresh lock is created.

## Implementation

### Containerfile

```dockerfile
# frontend/Containerfile
FROM python:3.12-slim

ARG LLAMASTACK_VERSION=0.6.0
WORKDIR /app
COPY . /app/

RUN sed -i "s/__LLAMASTACK_VERSION__/${LLAMASTACK_VERSION}/g" pyproject.toml

# Install uv
RUN pip install uv

# Set UV cache directory to a writable location
ENV UV_CACHE_DIR=/app/.uv-cache
ENV XDG_CACHE_HOME=/app/.cache

# Create cache directories with proper permissions
RUN mkdir -p /app/.uv-cache /app/.cache && \
    chmod -R 777 /app/.uv-cache /app/.cache

# Install dependencies using uv
RUN if [ -f "uv.lock" ]; then \
        echo "Lockfile found, using frozen sync"; \
        uv sync --frozen; \
    else \
        echo "Lockfile not found, creating new one"; \
        uv sync; \
    fi

# Ensure all app files have proper ownership and permissions for non-root users
RUN chown -R 1001:0 /app && \
    chmod -R g+rwX /app

EXPOSE 8501

ENTRYPOINT ["uv", "run", "streamlit", "run", \
  "/app/llama_stack_ui/distribution/ui/app.py", \
  "--server.port=8501", "--server.address=0.0.0.0"]
```

### CI Build with Version Injection

The GitHub Actions workflow passes the LlamaStack version as a build argument:

```yaml
# .github/workflows/build-and-push.yaml (lines 33-43)
- name: Build and push f5-ai-guardrails
  uses: docker/build-push-action@v5
  with:
    context: frontend
    file: frontend/Containerfile
    push: true
    tags: |
      quay.io/rh-ai-quickstart/f5-ai-guardrails:${{ steps.version.outputs.f5_tag }}
      quay.io/rh-ai-quickstart/f5-ai-guardrails:latest
    build-args: |
      LLAMASTACK_VERSION=0.6.0
```

## Configuration

- **Key settings:** `ARG LLAMASTACK_VERSION=0.6.0` defaults the LlamaStack version; `UV_CACHE_DIR` and `XDG_CACHE_HOME` redirect cache to writable locations; `chown -R 1001:0` enables OpenShift arbitrary UID
- **Defaults:** Base image is `python:3.12-slim` (not UBI); uv is installed via pip (not copied from official image); port 8501 for Streamlit
- **Dependencies:** Requires `pyproject.toml` with `__LLAMASTACK_VERSION__` placeholder and optionally `uv.lock` in the `frontend/` directory

## Gotchas

- This uses `python:3.12-slim` instead of Red Hat UBI -- suitable for development/demo but may not meet production compliance requirements that mandate UBI base images
- The `uv` installation via `pip install uv` pulls the latest version at build time (not pinned), unlike the `COPY --from=ghcr.io/astral-sh/uv:<version>` pattern which pins to a specific release
- The `sed` version injection modifies `pyproject.toml` in-place at build time -- the committed `pyproject.toml` contains `__LLAMASTACK_VERSION__` as a placeholder string (not a valid version), so `uv sync` would fail without the sed step
- Cache directories require `chmod -R 777` (not just group write) because the uv runtime writes to them regardless of the running UID
- The `uv run` entrypoint means uv resolves the virtual environment on each container start; this works because `uv sync --frozen` already installed everything into `.venv`

## Related Patterns

- `container-build-ubi-uv-python-multistage.md` -- alternative approach using UBI8 base and COPY-from-image uv installation
- `github-actions-single-image-chart-version-tag.md` -- the CI workflow that builds this Containerfile
