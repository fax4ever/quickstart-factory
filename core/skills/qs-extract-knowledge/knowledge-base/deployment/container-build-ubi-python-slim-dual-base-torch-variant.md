---
name: container-build-ubi-python-slim-dual-base-torch-variant
description: Containerfile with switchable UBI9/python-slim base via BASE_IMAGE ARG, conditional dnf/apt package install, and TORCH_VARIANT cpu/cuda toggle
summary: "Provides a single Containerfile supporting dual base images (UBI9/python-312 for OpenShift production, python:3.12-slim for local dev) via BASE_IMAGE ARG, with a separate TORCH_VARIANT ARG toggling PyTorch CPU (~176MB via download.pytorch.org/whl/cpu index) or CUDA (~800MB) installation through curl-installed uv and uv pip install --system. Use when the same Containerfile must serve both OpenShift production (UBI9) and fast local builds (python-slim) with optional GPU support -- CI workflows pass TORCH_VARIANT=cuda for production images; for python-slim-only builds without dual-base switching, see container-build-python-slim-uv-cpu-pytorch-openshift-gid.md. Conditional logic greps BASE_IMAGE to select dnf (with --allowerasing) or apt-get for system packages, skips user creation on UBI (user 1001 pre-exists), removes /etc/rhsm-host to prevent host RHEL subscription leaking, and uses --python $(which python3) --system for monorepo editable installs (uv pip install -e ./packages/db and ./packages/api). BASE_IMAGE ARG must be re-declared after FROM per Docker multi-stage ARG scoping rules; uv pip install --system is required instead of uv sync because UBI lacks a default venv; the sibling DB Containerfile uses a different strategy (python:3.12-slim only with uv venv and PATH prepend), showing two build approaches coexisting in the same repo."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [python, fastapi, uv, pytorch]
  ai_pattern: [embeddings]
  platform: [openshift]
source_examples:
  - quickstart: "spending-transaction-monitor"
    repo: "https://github.com/rh-ai-quickstart/spending-transaction-monitor"
    notes: "API Containerfile with UBI9 default base switchable to python:3.12-slim, conditional dnf/apt install, uv from curl, TORCH_VARIANT=cpu/cuda PyTorch install"
    approach: "A"
---

# Dual-Base Containerfile with PyTorch CPU/CUDA Variant Toggle

## Overview

This pattern builds a Python API container that supports two base images (UBI9 for production/OpenShift, python:3.12-slim for faster local builds) via a single `BASE_IMAGE` build argument, with conditional system package installation (dnf for UBI, apt-get for Debian) and a separate `TORCH_VARIANT` argument to control PyTorch CPU vs CUDA installation. This enables a single Containerfile to serve both lightweight local development and GPU-enabled production builds.

## Pattern Description

The Containerfile uses a two-ARG approach: `BASE_IMAGE` selects the OS family (defaulting to UBI9/python-312), and `TORCH_VARIANT` selects the PyTorch index URL (cpu or cuda). A shell conditional on the base image name determines which package manager and packages to install. The `uv` package manager is installed from curl regardless of base image. The pattern supports monorepo workspace builds where the API package depends on a sibling DB package, both installed as editable packages via `uv pip install -e`.

## Implementation

### Dual Base Image Selection

```dockerfile
# Override with: --build-arg BASE_IMAGE=python:3.12-slim
ARG BASE_IMAGE=registry.access.redhat.com/ubi9/python-312:latest
FROM ${BASE_IMAGE}

USER root

ARG TORCH_VARIANT=cpu
```

Source: `packages/api/Containerfile`

### Conditional System Package Installation

The Containerfile re-declares the `BASE_IMAGE` ARG after FROM (required by Docker multi-stage scoping) and branches on the image name to select the correct package manager:

```dockerfile
ARG BASE_IMAGE
RUN if echo "${BASE_IMAGE}" | grep -q "ubi"; then \
        rm -f /etc/rhsm-host 2>/dev/null || true && \
        dnf install -y gcc gcc-c++ postgresql-devel curl --allowerasing && dnf clean all; \
    else \
        apt-get update && apt-get install -y --no-install-recommends \
            gcc g++ libpq-dev curl \
            && rm -rf /var/lib/apt/lists/*; \
    fi
```

Source: `packages/api/Containerfile`

### PyTorch CPU/CUDA Variant Installation

```dockerfile
RUN if [ "$TORCH_VARIANT" = "cpu" ]; then \
        echo "Installing PyTorch CPU version (lightweight, ~176MB)..." && \
        uv pip install --python $(which python3) --system --no-cache \
            --index-url https://download.pytorch.org/whl/cpu torch; \
    else \
        echo "Installing PyTorch CUDA version (GPU-enabled, ~800MB)..." && \
        uv pip install --python $(which python3) --system --no-cache torch; \
    fi
```

Source: `packages/api/Containerfile`

### Monorepo Editable Package Installation

The API depends on a sibling DB package within the monorepo, both installed as editable packages via `uv pip install -e`:

```dockerfile
RUN mkdir -p /app/packages/api /app/packages/db
COPY packages/api/ ./packages/api/
COPY packages/db/ ./packages/db/
COPY data/ ./data/

RUN uv pip install --python $(which python3) --system --no-cache -e ./packages/db
RUN uv pip install --python $(which python3) --system --no-cache -e ./packages/api[dev]
```

Source: `packages/api/Containerfile`

### Non-Root User with UBI Compatibility

```dockerfile
ARG BASE_IMAGE
RUN if ! echo "${BASE_IMAGE}" | grep -q "ubi"; then \
        useradd -u 1001 -m appuser || true; \
    fi && \
    chown -R 1001:0 /app && chmod -R g=u /app

USER 1001
```

Source: `packages/api/Containerfile`. UBI images already have user 1001, so user creation is skipped for UBI bases.

## Configuration

- **BASE_IMAGE:** `registry.access.redhat.com/ubi9/python-312:latest` (default) or `python:3.12-slim` for local builds
- **TORCH_VARIANT:** `cpu` (default, ~176MB) or `cuda` (GPU-enabled, ~800MB)
- **uv installation:** Curl-based (`curl -LsSf https://astral.sh/uv/install.sh | sh`) rather than COPY from uv image
- **UBI subscription:** `rm -f /etc/rhsm-host` prevents host RHEL subscription from leaking into the build
- **CI builds:** The GitHub Actions workflow passes `TORCH_VARIANT=cuda` for production images

## Gotchas

- The `BASE_IMAGE` ARG must be re-declared after FROM for the conditional logic to access it, per Docker's multi-stage ARG scoping rules (visible in source where `ARG BASE_IMAGE` appears twice)
- The `--allowerasing` flag on `dnf install` is required because UBI9/python-312 has conflicting packages that need replacement
- `uv pip install --system` is used instead of `uv sync` because the UBI base image does not use a venv by default; `--python $(which python3)` ensures the correct interpreter is found regardless of base image
- The DB Containerfile (`packages/db/Containerfile`) uses a different approach: `python:3.12-slim` base only, with `uv venv` and `PATH` prepend for venv activation, showing two build strategies coexisting in the same repo

## Related Patterns

- `container-build-ubi-uv-python-multistage.md` - UBI with uv using COPY --from pattern
- `container-build-python-slim-uv-cpu-pytorch-openshift-gid.md` - Python slim with uv and CPU PyTorch
