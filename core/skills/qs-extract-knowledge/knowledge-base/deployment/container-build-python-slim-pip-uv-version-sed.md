---
name: container-build-python-slim-pip-uv-version-sed
description: python:3.12-slim Containerfile with pip-installed uv and sed-based LlamaStack version injection at build time
summary: "Builds single-stage Streamlit frontend containers from python:3.12-slim with pip-installed uv (unpinned latest) via two approaches: Approach A (f5-ai-guardrails, f5-api-security) applies sed-based build-time version injection replacing __LLAMASTACK_VERSION__ placeholder in pyproject.toml via ARG (default 0.6.0) before conditional uv sync --frozen or fresh sync with uv retained at runtime (uv run entrypoint), setting UV_CACHE_DIR/XDG_CACHE_HOME for cache redirection; Approach B (RAG) copies pyproject.toml first for layer caching, installs into system site-packages via uv pip install --system with PIP_NO_CACHE_DIR=1, removes uv after build (pip uninstall -y uv), and uses python -m streamlit entrypoint for a smaller final image. Use Approach A when CI must inject SDK versions at build time (passed via docker/build-push-action@v5 build-args to Quay.io) and uv is needed at runtime; use Approach B for smaller self-contained images with concrete dependency versions and no runtime uv -- prefer container-build-ubi-uv-python-multistage.md for production needing pinned uv (COPY --from=ghcr.io/astral-sh/uv:<version>) and UBI base. Critical config: Approach A requires sed -i \"s/__LLAMASTACK_VERSION__/${LLAMASTACK_VERSION}/g\" pyproject.toml before sync with UV_CACHE_DIR=/app/.uv-cache and XDG_CACHE_HOME=/app/.cache; Approach B cleans /root/.cache/uv and /root/.cache/pip in the same RUN layer as install; both use chown -R 1001:0 with chmod -R g+rwX for OpenShift arbitrary UID on port 8501. Common gotcha: the committed pyproject.toml contains __LLAMASTACK_VERSION__ placeholder (not a valid version) so uv sync fails without the sed step in Approach A; Approach B removes uv so uv run is unavailable at runtime; cache directories require chmod 777 regardless of running UID; pip install uv pulls the latest unpinned version at build time; python:3.12-slim may not meet production compliance mandating UBI."
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
  - quickstart: "f5-api-security"
    repo: "https://github.com/rh-ai-quickstart/F5-API-Security"
    notes: "Same python:3.12-slim + uv + sed pattern, LLAMASTACK_VERSION=0.6.1, Streamlit UI for F5 API Security RAG chatbot"
    approach: "A"
  - quickstart: "RAG"
    repo: "https://github.com/rh-ai-quickstart/RAG"
    notes: "python:3.12-slim + transient uv (installed via pip, used for system install, then uninstalled); no sed version injection, uses uv pip install --system -r pyproject.toml instead of uv sync, python -m streamlit entrypoint"
    approach: "B"
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

---

## Approach B: Transient uv with System Install (from RAG)

### When to Use

When the Containerfile should produce a self-contained image that does not retain uv at runtime. Dependencies are installed into system site-packages, and the entrypoint invokes `python -m streamlit` directly (no `uv run`). No build-time version injection is needed because `pyproject.toml` contains final version strings.

### Differences from Approach A

- No `sed` version injection step -- `pyproject.toml` has concrete dependency versions, not placeholders
- Uses `uv pip install --system -r pyproject.toml` to install into system site-packages instead of `uv sync` into a `.venv`
- Uninstalls `uv` after dependency installation (`pip uninstall -y uv`) to reduce final image size
- Entrypoint uses `python -m streamlit run` instead of `uv run streamlit run`
- No `UV_CACHE_DIR`/`XDG_CACHE_HOME` env vars needed since uv is removed after build
- Copies `pyproject.toml` first for layer caching, then copies app source separately

### Containerfile

```dockerfile
# frontend/Containerfile
FROM python:3.12-slim

WORKDIR /app

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Copy dependency metadata first for better layer caching.
COPY pyproject.toml ./

# Install dependencies into system site-packages during build.
RUN pip install --no-cache-dir uv && \
    uv pip install --system -r pyproject.toml && \
    pip uninstall -y uv && \
    rm -rf /root/.cache/uv /root/.cache/pip

# Copy the rest of the application source.
COPY . /app/

# Ensure all app files have proper ownership and permissions for non-root users
RUN chown -R 1001:0 /app && \
    chmod -R g+rwX /app

EXPOSE 8501

ENTRYPOINT ["python", "-m", "streamlit", "run", "/app/llama_stack_ui/distribution/ui/app.py", \
  "--server.port=8501", "--server.address=0.0.0.0"]
```

### Configuration

- **Key settings:** `PIP_NO_CACHE_DIR=1` prevents pip from caching downloads; `uv pip install --system` installs into `/usr/local/lib/python3.12/site-packages` instead of a venv
- **Defaults:** Port 8501 for Streamlit; non-root user 1001:0 for OpenShift arbitrary UID
- **Dependencies:** `pyproject.toml` with concrete versions (no placeholders)

### Gotchas

- The `pip uninstall -y uv` step removes uv from the final image, so `uv run` is not available at runtime -- the entrypoint must use `python -m` directly
- The `COPY pyproject.toml ./` before `COPY . /app/` provides Docker layer caching -- dependency installation is skipped on rebuild unless `pyproject.toml` changes
- The `rm -rf /root/.cache/uv /root/.cache/pip` cleanup runs in the same RUN layer as the install, preventing cache directories from appearing in the final image layer

---

## Choosing Between Approaches

| Criteria | Approach A | Approach B |
|----------|-----------|-----------|
| Version injection | sed replaces placeholder in pyproject.toml | None needed -- concrete versions in pyproject.toml |
| Install method | `uv sync --frozen` into .venv | `uv pip install --system` into site-packages |
| uv at runtime | Retained; entrypoint uses `uv run` | Removed after build; entrypoint uses `python -m` |
| Layer caching | Full source COPY before install | pyproject.toml copied first for cache-friendly builds |
| Image size | Larger (uv + .venv + cache dirs) | Smaller (no uv, no .venv, caches cleaned) |
