---
name: container-build-ubi9-python-uv-init-first-lib-base
description: UBI9 Python Containerfile copying __init__.py files first for cache-friendly library image used as downstream base
summary: "Solves Docker layer caching for Python library packages on UBI9 Python 3.12 by copying per-subpackage __init__.py files before full source so uv pip install . (uv installed via pip3) resolves package structure and caches the dependency installation layer independently of code changes. Use when building a shared library image published to a registry as a FROM base for downstream application Containerfiles — the image defines no ENTRYPOINT/CMD since it is a base, not a runtime; requires pyproject.toml to declare the same package structure matching the copied __init__.py layout. Critical config: PYTHONPATH includes /app and /app/src for import resolution, HF_HOME=/hf_cache with 777 permissions for HuggingFace model caching, and chmod -R 777 /app for OpenShift arbitrary UID compatibility. Gotchas: Feast feature store files must be duplicated to a second explicit path because feast apply expects them at a fixed location separate from the src/ tree, and the image runs dnf update as root early in the build so security patches are baked into the base layer."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [python]
  ai_pattern: [embeddings, recommendation]
  platform: [openshift]
source_examples:
  - quickstart: "product-recommender-system"
    repo: "https://github.com/rh-ai-quickstart/product-recommender-system"
    notes: "recommendation-core library image published as base for fullstack Containerfile; copies __init__.py first for uv pip install caching"
    approach: "A"
---

# UBI9 Python Library Image with Init-First Cache Pattern

## Overview

Builds a Python library package as a standalone container image using UBI9, copying `__init__.py` files before the full source to allow `uv pip install .` to resolve the package structure for Docker layer caching. The resulting image is published to a registry and used as a base image by downstream Containerfiles.

## Pattern Description

Python packages with `pyproject.toml` require `__init__.py` files to exist for the package to be installable. By copying only the `__init__.py` files first, running `uv pip install .`, and then copying the full source, the dependency installation layer is cached independently of source code changes. The image is published to Quay.io and consumed as a `FROM` base by the fullstack application Containerfile.

## Implementation

### Containerfile with Init-First Pattern

```dockerfile
# recommendation-core/Containerfile
FROM registry.access.redhat.com/ubi9/python-312
USER root
WORKDIR /app/

COPY pyproject.toml pyproject.toml
RUN pip3 install uv
RUN dnf update -y

# Copy only __init__.py files first to enable package resolution for pip install
COPY src/recommendation_core/__init__.py src/recommendation_core/__init__.py
COPY src/recommendation_core/feature_repo/__init__.py src/recommendation_core/feature_repo/__init__.py
COPY src/recommendation_core/models/__init__.py src/recommendation_core/models/__init__.py
COPY src/recommendation_core/service/__init__.py src/recommendation_core/service/__init__.py

# Install the package (cached if only source changes, not deps)
RUN uv pip install .

# Now copy the full source
COPY src/ src/

# Duplicate feature store files to expected path for feast apply
RUN mkdir -p /app/recommendation-core/src/recommendation_core/feature_repo/
COPY src/recommendation_core/feature_repo/ /app/recommendation-core/src/recommendation_core/feature_repo/

ENV PYTHONPATH="/app:/app/src:${PYTHONPATH}"
RUN chmod -R 777 . && ls -la

ENV HF_HOME=/hf_cache
RUN mkdir -p /hf_cache && chmod -R 777 /hf_cache
```

## Configuration

- **Key settings:** `PYTHONPATH` includes both `/app` and `/app/src` for import resolution, `HF_HOME=/hf_cache` with 777 permissions for OpenShift arbitrary UID
- **Defaults:** UBI9 Python 3.12 base image
- **Dependencies:** `pyproject.toml` must define the package structure that matches the `__init__.py` file layout

## Gotchas

- Feature store files are copied twice: once as part of `COPY src/ src/` and again explicitly to `/app/recommendation-core/src/recommendation_core/feature_repo/` because the Feast apply job expects them at that specific path.
- `chmod -R 777 .` is applied to the entire `/app` directory to support OpenShift's arbitrary UID security model.
- The image does not define an `ENTRYPOINT` or `CMD` because it is designed as a base image, not a standalone runtime.

## Related Patterns

- `container-build-ubi-node-custom-base-hf-clip-prebake.md` — the downstream fullstack image that uses this as its base
