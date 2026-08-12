---
name: compose-local-dev-prebuilt-ngc-fallback-build-target-dask
description: Docker Compose with prebuilt NGC registry image fallback, BUILD_TARGET switching, and Dask env configuration
summary: "Eliminates separate dev/prod Docker Compose files by combining local builds (via --build flag) and prebuilt NGC registry image pulls (nvcr.io/nvidia/blueprint/) in a single configuration, supporting backend, frontend, PostgreSQL (postgres:16-alpine), and optional Dask distributed computing. Use when operators need to switch between local builds with BUILD_TARGET selecting dev (CLI included) or release Dockerfile targets and prebuilt NGC images by simply omitting --build; BACKEND_IMAGE/FRONTEND_IMAGE env vars override registry defaults. Critical config: image fields use env-var substitution with NGC defaults, PostgreSQL healthcheck runs dual pg_isready against both aiq_jobs and aiq_checkpoints databases with service_healthy condition blocking backend startup, Dask tuning uses DASK_NWORKERS (default 1) and DASK_NTHREADS (default 4), and frontend has explicit resource limits (cpus: 0.5, memory: 512M). Gotchas: env_file path resolves relative to compose file location (deploy/compose/) so the actual file is deploy/.env, init-db.sql mounted into docker-entrypoint-initdb.d/ executes only on first container start not on restarts with existing data volumes, and configs directory is bind-mounted read-only so workflow YAML edits require a backend restart."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [fastapi, react, postgresql]
  ai_pattern: [agents]
  platform: [kubernetes]
  data_layer: [postgresql, chromadb]
source_examples:
  - quickstart: "rh-research"
    repo: "https://github.com/rh-ai-quickstart/rh-research"
    notes: "AI-Q Blueprint compose with dual mode (local build vs NGC prebuilt), BUILD_TARGET for dev/release, Dask cluster config"
    approach: "A"
---

# Docker Compose with Prebuilt NGC Registry Fallback and Build Target Switching

## Overview

A Docker Compose configuration that supports two deployment modes from the same file: building images locally from source (with a switchable dev/release target), or using pre-built images from the NVIDIA NGC container registry. This eliminates the need for separate compose files for development vs production while allowing operators to skip long local builds when registry images are available.

## Pattern Description

Each service specifies both an `image:` field (with an env-var default pointing to the NGC registry) and a `build:` block. When `docker compose up --build` is used, the local build runs; when `--build` is omitted, the pre-built image is pulled. The backend service additionally supports a `BUILD_TARGET` environment variable that switches between dev (CLI included) and release (production-only) Dockerfile targets.

## Implementation

### Dual Mode: Build vs Prebuilt

The `image:` field uses env-var substitution with an NGC registry default. Operators override these to use custom registries or local tags.

```yaml
services:
  aiq-agent:
    image: ${BACKEND_IMAGE:-nvcr.io/nvidia/blueprint/aiq-agent:2.0.0}
    build:
      context: ../..
      dockerfile: deploy/Dockerfile
      target: ${BUILD_TARGET:-dev}
    container_name: aiq-agent
    env_file:
      - ../.env
```

Usage patterns:

```bash
# Build locally (default dev target)
docker compose --env-file ../.env -f docker-compose.yaml up -d --build

# Build locally with release target
BUILD_TARGET=release docker compose --env-file ../.env -f docker-compose.yaml up -d --build

# Use pre-built NGC images (skip --build)
BACKEND_IMAGE=nvcr.io/nvidia/blueprint/aiq-agent:2.0.0 \
FRONTEND_IMAGE=nvcr.io/nvidia/blueprint/aiq-frontend:2.0.0 \
docker compose --env-file ../.env -f docker-compose.yaml up -d
```

### Multi-Database PostgreSQL Healthcheck

The PostgreSQL healthcheck verifies both databases are ready, not just the primary one. This is important because the backend initContainer needs both `aiq_jobs` and `aiq_checkpoints` databases.

```yaml
  postgres:
    image: postgres:16-alpine
    environment:
      POSTGRES_USER: aiq
      POSTGRES_PASSWORD: aiq_dev
      POSTGRES_DB: aiq_jobs
    volumes:
      - postgres-data:/var/lib/postgresql/data
      - ./init-db.sql:/docker-entrypoint-initdb.d/init-db.sql:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U aiq -d aiq_jobs && pg_isready -U aiq -d aiq_checkpoints"]
      interval: 5s
      timeout: 5s
      retries: 5
```

### Service Dependency and Resource Limits

The backend depends on PostgreSQL being healthy before starting. The frontend has explicit resource constraints.

```yaml
  aiq-agent:
    depends_on:
      postgres:
        condition: service_healthy

  frontend:
    image: ${FRONTEND_IMAGE:-nvcr.io/nvidia/blueprint/aiq-frontend:2.0.0}
    build:
      context: ../../frontends/ui
      dockerfile: deploy/Dockerfile
    depends_on:
      - aiq-agent
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 512M
        reservations:
          cpus: '0.1'
          memory: 256M
```

### Dask Cluster Environment Variables

The backend service exposes Dask distributed computing configuration as environment variables, allowing operators to tune the embedded Dask cluster without modifying code.

```yaml
    environment:
      - DASK_NWORKERS=${DASK_NWORKERS:-1}
      - DASK_NTHREADS=${DASK_NTHREADS:-4}
      # Optional: bound per-worker memory (Dask spills/restarts above this)
      # - DASK_MEMORY_LIMIT=${DASK_MEMORY_LIMIT:-}
      # Optional: recycle workers after this many seconds
      # - DASK_LIFETIME=${DASK_LIFETIME:-}
```

## Configuration

- **Key settings:** `BACKEND_IMAGE`/`FRONTEND_IMAGE` for registry overrides; `BUILD_TARGET` for dev/release; `DASK_NWORKERS`/`DASK_NTHREADS` for compute tuning
- **Defaults:** Dev build target, 1 Dask worker with 4 threads, auth disabled on frontend
- **Dependencies:** NGC registry access for prebuilt images; `deploy/.env` file with API keys; `init-db.sql` in compose directory

## Gotchas

- The `env_file: [../.env]` path resolves relative to the compose file location (`deploy/compose/`), so the actual file is at `deploy/.env` -- this path is also used by CI workflows
- The PostgreSQL healthcheck checks both `aiq_jobs` AND `aiq_checkpoints` databases -- if only one database exists, the healthcheck fails and the backend won't start
- `init-db.sql` is mounted into PostgreSQL's `docker-entrypoint-initdb.d/` directory as read-only, so it runs automatically on first container start but NOT on restarts with existing data volumes
- The configs directory is bind-mounted read-only (`../../configs:/app/configs:ro`) so workflow YAML files can be edited on the host and picked up by restarting the backend

## Related Patterns

- `container-build-nvidia-distroless-uv-dev-release-target.md` -- the backend Dockerfile referenced by this compose
- `container-build-nvidia-ubuntu-nextjs-npm-strip-healthcheck.md` -- the frontend Dockerfile referenced by this compose
- `entrypoint-dask-cluster-uvicorn-nat-asyncio-bypass.md` -- the entrypoint that consumes DASK_* env vars
