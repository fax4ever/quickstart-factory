---
name: container-build-parameterized-containerfile-template
description: Shared Containerfile templates parameterized via build ARGs for SERVICE_NAME and MODULE_NAME across 8 images
summary: "Eliminates per-microservice Containerfiles in a Python monorepo by defining two shared templates (Containerfile.services-template for 6 app services exposing port 8080, Containerfile.mcp-template for 2 MCP servers exposing port 8000) parameterized via SERVICE_NAME and MODULE_NAME build ARGs and invoked through a Makefile build_template_image function. Use when multiple Python services share common libraries and the same UBI9/python-312 base image but differ only in entrypoint module and shared-library subsets -- prefer over per-service Containerfiles (see container-build-ubi-uv-python-multistage.md) when 3+ services follow the same build pattern. Templates use multi-stage builds with uv (UV_VERSION=0.8.9, default) or pip fallback (USE_PIP_INSTALL=true for QEMU/Mac M1, splits requirements into editable vs non-editable for local shared-library paths) and stage the venv to /app/service.venv to prevent 590MB layer duplication when copying to the python-312-minimal runtime stage. Build targets require check-lockfile-<service> and check-deps-<template> prerequisites validating lockfile consistency across shared libraries (shared-models, shared-clients, agent-service, mock-employee-data); pip is pinned >=26.0 in the runtime stage for CVE-2025-8869; a HuggingFace cache directory is pre-created for all services even when unused."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [python, fastapi]
  ai_pattern: [agents]
  platform: [openshift]
source_examples:
  - quickstart: "it-self-service-agent"
    repo: "https://github.com/rh-ai-quickstart/it-self-service-agent"
    notes: "Two Containerfile templates (services-template, mcp-template) building 8 images via build ARGs"
    approach: "A"
---

# Parameterized Containerfile Templates

## Overview

Instead of maintaining individual Dockerfiles per microservice, this pattern uses shared Containerfile templates parameterized via `--build-arg` for `SERVICE_NAME` and `MODULE_NAME`. Two templates cover all eight container images in the monorepo: one for application services and one for MCP servers, each accepting the service directory and Python module entrypoint as build arguments.

## Pattern Description

The repo defines `Containerfile.services-template` (for 6 application services) and `Containerfile.mcp-template` (for 2 MCP servers) at the repo root. Both are multi-stage builds using UBI9/python-312 with uv, but they differ in which shared libraries they copy (services-template copies shared-models, shared-clients, agent-service, mock-employee-data, tracing-config; mcp-template copies only shared-models, tracing-config, mcp-common). A Makefile `build_template_image` function invokes the container tool with the correct build args.

## Implementation

### Makefile Build Function

A single `define` function standardizes how all images are built from templates:

```makefile
# Makefile
define build_template_image
	@echo "Building $(2) using template: $(1)"
	$(CONTAINER_TOOL) build -t $(1) --platform=$(ARCH) \
		-f $(3) \
		--build-arg SERVICE_NAME=$(4) \
		--build-arg MODULE_NAME=$(5) \
		--build-arg USE_PIP_INSTALL=$(USE_PIP_INSTALL) \
		--build-arg UV_VERSION=$(UV_VERSION) \
		$(if $(6),$(6),.)
	@echo "Successfully built $(1)"
endef
```

### Target Invocations

Each service calls the same function with different parameters:

```makefile
# Makefile (excerpts)
build-request-mgr-image: check-lockfile-request-manager check-deps-services-template
	$(call build_template_image,$(REQUEST_MGR_IMG),request manager image,Containerfile.services-template,request-manager,request_manager.main,.)

build-mcp-snow-image: check-lockfile-mcp-snow check-deps-mcp-template
	$(call build_template_image,$(MCP_SNOW_IMG),snow MCP image,Containerfile.mcp-template,mcp-servers/snow,snow.server,.)
```

### Services Template Key Sections

The services template copies all shared libraries into the builder, installs dependencies conditionally (uv vs pip), then stages the venv to avoid duplication:

```dockerfile
# Containerfile.services-template (excerpt)
ARG SERVICE_NAME
ARG MODULE_NAME
ARG USE_PIP_INSTALL=false
ARG UV_VERSION=0.8.9

FROM registry.access.redhat.com/ubi9/python-312:9.7 as builder
USER root
ARG UV_VERSION
RUN pip3 install --no-cache-dir uv==${UV_VERSION}
WORKDIR /app
COPY shared-models ./shared-models/
COPY shared-clients ./shared-clients/
COPY agent-service ./agent-service/
COPY tracing-config/ ./tracing-config
ARG SERVICE_NAME
COPY ${SERVICE_NAME}/pyproject.toml ${SERVICE_NAME}/uv.lock ${SERVICE_NAME}/requirements.txt ./${SERVICE_NAME}/
WORKDIR /app/${SERVICE_NAME}
```

### Dual Install Strategy (uv vs pip)

Both templates support a `USE_PIP_INSTALL` build arg as a workaround for QEMU issues on Mac M1:

```dockerfile
# Containerfile.services-template (excerpt)
RUN if [ "$USE_PIP_INSTALL" = "true" ]; then \
        python3 -m venv .venv && \
        grep -E "^(-e |\.\./)" requirements.txt > /tmp/editable-requirements.txt 2>/dev/null || true && \
        grep -vE "^(-e |\.\./)" requirements.txt > /tmp/non-editable-requirements.txt && \
        if [ -s /tmp/editable-requirements.txt ]; then \
            .venv/bin/pip install --no-deps -r /tmp/editable-requirements.txt; \
        fi && \
        .venv/bin/pip install --require-hashes --use-deprecated=legacy-resolver -r /tmp/non-editable-requirements.txt; \
    else \
        uv sync --frozen --no-dev; \
    fi
```

### Venv Staging to Avoid Duplication

The services template stages the venv to `/app/service.venv` in the builder to prevent a 590MB duplication when the runtime stage copies the full service directory:

```dockerfile
# Containerfile.services-template (excerpt)
RUN cp -r /app/${SERVICE_NAME}/.venv /app/service.venv && rm -rf /app/${SERVICE_NAME}/.venv
# Production stage
FROM registry.access.redhat.com/ubi9/python-312-minimal:9.7
COPY --from=builder /app/service.venv /app/.venv
```

## Configuration

- **Key settings:** `SERVICE_NAME` specifies the subdirectory (e.g., `request-manager`, `mcp-servers/snow`); `MODULE_NAME` specifies the Python module for uvicorn (e.g., `request_manager.main`, `snow.server`); `USE_PIP_INSTALL` defaults to `false` (uv); `UV_VERSION` pinned to `0.8.9`
- **Defaults:** Services template exposes port 8080, MCP template exposes port 8000; both support `UVICORN_WORKERS` env var at runtime for multi-process concurrency
- **Dependencies:** Each build target has `check-lockfile-<service>` and `check-deps-<template>` prerequisites that verify lockfiles are current before building

## Gotchas

- The services template uses `ubi9/python-312-minimal:9.7` (minimal) for the runtime stage but `ubi9/python-312:9.7` (full) for the builder, reducing runtime image size (see `Containerfile.services-template`)
- Both templates pin pip to `>=26.0` in the runtime stage to address CVE-2025-8869 (`pip3 install --no-cache-dir --upgrade 'pip>=26.0'` in `Containerfile.services-template`)
- The services template creates a HuggingFace cache directory (`/app/.cache/huggingface/transformers`) with proper permissions even though not all services need it -- this is safe for all services (see `Containerfile.services-template`)
- The `check-deps-services-template` prerequisite validates lockfiles across four shared libraries (shared-models, shared-clients, agent-service, mock-employee-data) ensuring consistency before any service image build (see `Makefile`)

## Related Patterns

- `container-build-ubi-uv-python-multistage.md` -- similar UBI + uv pattern but with per-service Containerfiles instead of shared templates
