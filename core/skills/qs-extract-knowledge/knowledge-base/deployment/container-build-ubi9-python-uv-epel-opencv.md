---
name: container-build-ubi9-python-uv-epel-opencv
description: UBI9/python-311 single-stage container with uv package manager and EPEL-sourced OpenCV system dependencies
summary: "Solves building UBI9/python-311 containers for computer vision workloads (OpenCV, YOLO, OpenVINO) requiring system libraries (mesa-libGL, glib2) unavailable in standard UBI repos. Use when targeting OpenShift with OpenCV/YOLO on UBI9 -- three variants shown: backend with EPEL-sourced system libs, evals without system deps (needs .deepeval chmod 777), and runtime deployer on UBI8/python-312 with --no-dev for smaller images; prefer multi-stage or python-slim alternatives when image size is critical. EPEL enabled via direct RPM URL (dnf install -y https://dl.fedoraproject.org/pub/epel/epel-release-latest-9.noarch.rpm) since epel-release package is absent from UBI repos; uv copied from ghcr.io/astral-sh/uv:0.9.7 with uv sync --locked; USER switches from 0 (root, installs) to 1001 (non-root runtime). Five cache directories (TRANSFORMERS_CACHE, HF_HOME, XDG_CACHE_HOME, MPLCONFIGDIR, YOLO_CONFIG_DIR) must be pre-created with chmod 777 under /tmp because OpenShift arbitrary UIDs cannot create directories at runtime; platform must be pinned via --platform=linux/amd64 as YOLO/OpenVINO lacks ARM support; venv activation is inconsistent across Dockerfiles (PATH-only vs VIRTUAL_ENV+PATH)."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [python, flask]
  ai_pattern: [multimodal, model-serving]
  platform: [openshift]
source_examples:
  - quickstart: "multimodal-compliance-monitor"
    repo: "https://github.com/rh-ai-quickstart/multimodal-compliance-monitor"
    notes: "UBI9/python-311 backend with EPEL for mesa-libGL/glib2, uv sync --locked, YOLO/OpenCV cache dirs at /tmp"
    approach: "A"
---

# UBI9 Python Container with uv and EPEL OpenCV Dependencies

## Overview

A single-stage container build using Red Hat UBI9 Python 3.11 as the base image, with the `uv` package manager copied from its official image for lockfile-based dependency installation, and EPEL repository enabled to install system-level OpenCV dependencies (mesa-libGL, glib2) that are not available in the base UBI repos.

## Pattern Description

Computer vision workloads using OpenCV/YOLO on UBI images require system libraries (libGL, glib2) that are not included in the base UBI Python image and are not available in the standard UBI repos. This pattern enables the EPEL repository to install these libraries, then uses `uv sync --locked` for reproducible Python dependency installation. Multiple writable cache directories are created under `/tmp` for YOLO, HuggingFace, and Matplotlib, ensuring compatibility with OpenShift's arbitrary UID execution model.

## Implementation

### Backend Dockerfile

```dockerfile
# app/backend/Dockerfile
FROM --platform=linux/amd64 registry.access.redhat.com/ubi9/python-311:1-77

USER 0

RUN dnf install -y https://dl.fedoraproject.org/pub/epel/epel-release-latest-9.noarch.rpm && \
    dnf install -y mesa-libGL glib2 && \
    dnf clean all

WORKDIR /backend

COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --locked

COPY ./ ./

ENV PATH="/backend/.venv/bin:$PATH" \
    TRANSFORMERS_CACHE=/tmp/.cache/huggingface \
    HF_HOME=/tmp/.cache/huggingface \
    XDG_CACHE_HOME=/tmp/.cache \
    MPLCONFIGDIR=/tmp/.cache/matplotlib \
    YOLO_CONFIG_DIR=/tmp/Ultralytics

RUN mkdir -p /tmp/.cache/huggingface \
             /tmp/.cache/matplotlib \
             /tmp/Ultralytics \
    && chmod 777 /tmp/.cache/huggingface \
             /tmp/.cache/matplotlib \
             /tmp/Ultralytics

EXPOSE 8888
USER 1001
ENTRYPOINT ["python"]
CMD ["app.py"]
```

### Evals Containerfile (Same Pattern, No System Deps)

The evals image uses the same UBI9/python-311 + uv pattern but without EPEL or OpenCV deps:

```dockerfile
# app/evals/Containerfile
FROM --platform=linux/amd64 registry.access.redhat.com/ubi9/python-311:1-77
USER 0
WORKDIR /evals
COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --locked
COPY . .
RUN mkdir -p /evals/.deepeval && chmod 777 /evals/.deepeval
USER 1001
ENV PATH="/evals/.venv/bin:$PATH"
ENTRYPOINT ["python", "run_eval.py"]
```

### Runtime Deployer Containerfile (UBI8 Variant)

The runtime deployer uses UBI8/python-312 instead of UBI9/python-311, with the same uv pattern:

```dockerfile
# app/runtime/Containerfile
FROM registry.access.redhat.com/ubi8/python-312
USER root
COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --locked
ENV VIRTUAL_ENV=/app/.venv \
    PATH="/app/.venv/bin:$PATH" \
    HF_HOME=/hf_cache
RUN mkdir -p /hf_cache && chmod -R 777 /hf_cache && chmod -R +r .
COPY create_runtime.py .
ENTRYPOINT ["python", "create_runtime.py"]
```

## Configuration

- **Key settings:** EPEL RPM URL (`https://dl.fedoraproject.org/pub/epel/epel-release-latest-9.noarch.rpm`); uv version pinned at `0.9.7`; `uv sync --locked` for reproducible installs; `--no-dev` on the runtime image to exclude dev dependencies
- **Defaults:** Platform fixed to `linux/amd64` via `--platform` flag; user switches from `0` (root, for package installation) to `1001` (non-root, for runtime)
- **Dependencies:** `pyproject.toml` and `uv.lock` must be present; EPEL repo must be accessible at build time

## Gotchas

- EPEL is installed via direct RPM URL (`dnf install -y https://...epel-release-latest-9.noarch.rpm`) rather than the `epel-release` package, because UBI repos do not include the `epel-release` package
- Five cache directories under `/tmp` (`TRANSFORMERS_CACHE`, `HF_HOME`, `XDG_CACHE_HOME`, `MPLCONFIGDIR`, `YOLO_CONFIG_DIR`) must be pre-created with `chmod 777` because OpenShift runs containers with an arbitrary UID that cannot create directories in `/tmp` at runtime
- The backend image pins `--platform=linux/amd64` because YOLO/OpenVINO dependencies do not support ARM architectures
- The runtime deployer uses UBI8/python-312 (not UBI9/python-311 like the backend) and `--no-dev` to exclude dev dependencies, keeping the image smaller
- The deepeval cache directory (`.deepeval`) in the evals image also needs `chmod 777` for the same arbitrary UID reason
- The uv venv is activated via `PATH="/backend/.venv/bin:$PATH"` rather than `VIRTUAL_ENV` + `PATH` combination used in the runtime image -- both approaches work but are inconsistent across Dockerfiles in the same repo

## Related Patterns

- `container-build-ubi-uv-python-multistage.md` -- multi-stage variant of UBI + uv pattern
- `container-build-python-slim-uv-cpu-pytorch-openshift-gid.md` -- alternative using python-slim with uv
