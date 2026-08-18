---
name: container-build-clone-patch-third-party-mcp
description: Container build that clones a third-party MCP server repo and applies sed patches for Kubernetes compatibility
summary: "Clones EnterpriseDB/pg-airman-mcp at HEAD (no version pin) in a multi-stage uv-based container build, applying sed patches to fix MCP SDK v1.8.0+ DNS rebinding protection (TransportSecuritySettings(enable_dns_rebinding_protection=False)) that rejects Kubernetes service DNS names, add a noop Field parameter so vLLM can call zero-parameter tool functions, and inject missing Pydantic/MCP imports. Use when upstream MCP server image lacks critical Kubernetes fixes not yet merged; two build artifacts exist -- OpenShift BuildConfig inline Dockerfile for cluster builds vs standalone Dockerfile for local docker builds -- applying similar but not identical patches. Runtime stage requires libpq5 for psycopg2 PostgreSQL connectivity, fixes shebangs from /tmp builder paths to /app, and sets chmod g=u / chgrp 0 / USER 1000 for OpenShift arbitrary UID support; defaults to quay.io/rh-ai-quickstart/pg-airman-mcp:latest when not cluster-built. Builds are non-reproducible due to unpinned HEAD clone that may break on upstream API changes; BuildConfig and Dockerfile patches can silently diverge; network access required during build for git clone."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [python]
  ai_pattern: [agents]
  platform: [openshift]
source_examples:
  - quickstart: "data-governance-co-pilot"
    repo: "https://github.com/rh-ai-quickstart/data-governance-co-pilot"
    notes: "Clones EnterpriseDB/pg-airman-mcp, applies 3 sed patches (DNS rebinding, noop parameter, imports), builds with uv"
    approach: "A"
---

# Clone-and-Patch Third-Party MCP Server Build

## Overview

This pattern builds a custom container image by cloning a third-party open-source repository at build time, applying source code patches via `sed` to fix compatibility issues, and producing a multi-stage image suitable for Kubernetes/OpenShift deployment. It is used when the upstream image lacks critical fixes that the upstream maintainer has not yet merged.

## Pattern Description

The pg-airman-mcp BuildConfig clones EDB's `pg-airman-mcp` repository from GitHub during the builder stage, then applies three `sed`-based patches to the server source code: disabling MCP SDK's DNS rebinding protection (which rejects requests from Kubernetes DNS names), adding a workaround parameter to a tool function that otherwise fails schema validation, and injecting required Python imports. The builder stage uses `uv` for dependency management, and the runtime stage is a slim Python image with `libpq5` for PostgreSQL connectivity.

## Implementation

### BuildConfig with Clone and Patch

```yaml
# helm/pg-airman-mcp/buildconfig.yaml (inline Dockerfile excerpt)
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

# Clone third-party repo at build time
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
WORKDIR /tmp
RUN git clone https://github.com/EnterpriseDB/pg-airman-mcp.git
WORKDIR /tmp/pg-airman-mcp

# Apply patches:
# 1. Disable DNS rebinding protection for Kubernetes
# 2. Add REQUIRED noop parameter to list_schemas
# 3. Add required imports
RUN sed -i '/from mcp.server.fastmcp import FastMCP/a \
    from mcp.server.transport_security import TransportSecuritySettings' \
    src/pg_airman_mcp/server.py && \
    sed -i 's/from pydantic import BaseModel/from pydantic import BaseModel, Field/' \
    src/pg_airman_mcp/server.py && \
    sed -i 's/mcp = FastMCP("pg-airman-mcp")/mcp = FastMCP(\n    "pg-airman-mcp",\n    transport_security=TransportSecuritySettings(\n        enable_dns_rebinding_protection=False,\n    )\n)/' \
    src/pg_airman_mcp/server.py && \
    sed -i "s/async def list_schemas() -> ResponseType:/async def list_schemas(noop: str = Field(description=\"Workaround parameter, always use 'doit'\")) -> ResponseType:/" \
    src/pg_airman_mcp/server.py

# Build with uv
RUN uv venv /tmp/pg-airman-mcp/.venv && \
    . /tmp/pg-airman-mcp/.venv/bin/python && \
    uv pip install .
```

### Runtime Stage with libpq Fix

The upstream Dockerfile was missing the `libpq5` runtime library, causing psycopg2 to fail:

```dockerfile
# helm/pg-airman-mcp/buildconfig.yaml (runtime stage)
FROM python:3.12-slim-bookworm

# CRITICAL FIX: Install libpq5 (runtime library) not just libpq-dev (headers)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    dnsutils iputils-ping net-tools \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /tmp/pg-airman-mcp /app
WORKDIR /app

# Fix shebangs (builder path -> runtime path)
RUN find /app/.venv/bin -type f -exec sed -i \
    's|#!/tmp/pg-airman-mcp/.venv/bin/python|#!/app/.venv/bin/python|g' {} \;

# OpenShift compatibility: support arbitrary user IDs
RUN chmod +x /app/docker-entrypoint.sh && \
    chmod -R g=u /app && \
    chgrp -R 0 /app

USER 1000
ENV PATH="/app/.venv/bin:$PATH"
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["pg-airman-mcp"]
```

### Standalone Dockerfile (Alternative)

A standalone `Dockerfile` also exists in the chart directory with slightly different but equivalent logic, using `--mount=type=bind` for the lock/toml files:

```dockerfile
# helm/pg-airman-mcp/Dockerfile (standalone version)
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev || \
    uv sync --frozen --no-dev
```

## Configuration

- **Key settings:** The git clone always fetches `main` branch HEAD; no version pinning of the upstream repo
- **Defaults:** Image defaults to `quay.io/rh-ai-quickstart/pg-airman-mcp:latest` when not cluster-built; user 1000 for OpenShift non-root compatibility
- **Dependencies:** Requires network access during build for `git clone` from GitHub; `libpq5` must match the PostgreSQL client version expected by psycopg2

## Gotchas

- The upstream repo is cloned at HEAD without version pinning -- builds are not reproducible and may break if the upstream changes the API surface (see `helm/pg-airman-mcp/buildconfig.yaml`)
- The DNS rebinding protection patch targets MCP SDK v1.8.0+ which introduced strict Host header validation; without this patch, Kubernetes service DNS names (e.g., `pg-airman-mcp-service.namespace.svc.cluster.local`) are rejected as DNS rebinding attacks (see `helm/pg-airman-mcp/buildconfig.yaml` inline comment)
- The `noop` parameter workaround adds a required string parameter to the `list_schemas` tool function because vLLM's tool calling fails on functions with zero parameters -- the parameter itself is unused (see `helm/pg-airman-mcp/buildconfig.yaml` inline comment)
- Two build artifacts exist: the `Dockerfile` (for standalone docker builds) and the `buildconfig.yaml` (for OpenShift builds) -- they apply similar but not identical patches, and diverging is a maintenance risk (see `helm/pg-airman-mcp/Dockerfile` vs `helm/pg-airman-mcp/buildconfig.yaml`)

## Related Patterns

- `openshift-buildconfig-inline-dockerfile-dual-source.md` -- the BuildConfig mechanism that hosts this inline Dockerfile
- `mcp-service-session-affinity-transport-toggle.md` -- the Service and deployment configuration for the built image
