---
name: compose-profile-layered-optional-services
description: Compose profiles for auth/ai/observability/full layers with host.docker.internal LLM proxy and MCP server image reuse
summary: "Organizes a multi-service local dev stack into always-on base services (PostgreSQL+pgvector on host port 5433, FastAPI:8000, React:3000, MCP risk server:8081, MinIO:9090/9091) and optional Compose profile layers (auth=Keycloak:8080, ai=LlamaStack:8321, observability=MLflow:5000), where each optional service belongs to both its named profile and a `full` profile so `--profile full` activates everything. Use when a quickstart has optional capabilities that not all developers need running simultaneously -- choose this over flat compose files when services like auth, AI inference, or observability should be independently toggleable; `AUTH_DISABLED` defaults to true for local dev. Critical config: MCP risk server reuses the API Containerfile with `command: python -m src.mcp_server`, API reaches host LLMs via `LLM_BASE_URL` defaulting to `http://host.docker.internal:1234/v1`, MinIO pre-creates buckets via `entrypoint: sh` with `command: -c 'mkdir -p /data/mlflow /data/documents && exec minio server ...'`, and MLflow shares PostgreSQL (`MLFLOW_BACKEND_STORE_URI`) and stores artifacts in MinIO (`MLFLOW_S3_ENDPOINT_URL`). Gotchas: `host.docker.internal` requires `--add-host host.docker.internal:host-gateway` on Linux Docker (Podman auto-resolves), MCP server image rebuilds are coupled to API image rebuilds, healthchecks must use python urllib instead of curl on python:3.11-slim, and the PostgreSQL init script always creates the mlflow database and role-isolation accounts (lending_app/compliance_app) even when the observability profile is inactive."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [fastapi, react, postgresql, minio]
  ai_pattern: [agents, model-serving]
  platform: []
  data_layer: [pgvector]
source_examples:
  - quickstart: "multi-agent-loan-origination"
    repo: "https://github.com/rh-ai-quickstart/multi-agent-loan-origination"
    notes: "Compose with auth/ai/observability/full profiles, host.docker.internal for LLM, MCP server reusing API image with different command, MinIO entrypoint creating multiple buckets"
    approach: "A"
---

# Compose Profiles for Layered Optional Services

## Overview

This pattern uses Docker/Podman Compose profiles to create a layered local development stack where a minimal set of always-on services can be progressively extended with optional capabilities. Services are organized into additive profile layers (auth, ai, observability) that can be combined individually or activated all at once via a `full` profile.

## Pattern Description

The compose file defines a base stack (database, API, UI, MCP server, MinIO) that runs without any profile flags. Additional services are grouped into named profiles: `auth` adds Keycloak, `ai` adds LlamaStack, `observability` adds MLflow. Each optional service belongs to both its specific profile and the `full` profile, enabling `--profile full` to activate everything. The API service uses `host.docker.internal` to reach an LLM running on the host machine, and the MCP risk server reuses the same container image as the API but with a different command.

## Implementation

### Profile Organization

```yaml
# compose.yml (structure)
services:
  # ------------------------------------------------ always-on
  mortgage-ai-db:    # PostgreSQL + pgvector
  mortgage-ai-api:   # FastAPI backend
  mortgage-ai-ui:    # React frontend
  mcp-risk-server:   # MCP server (reuses API image)
  minio:             # S3-compatible storage

  # ------------------------------------------------ auth profile
  keycloak:
    profiles: ["auth", "full"]

  # ------------------------------------------------ ai profile
  llamastack:
    profiles: ["ai", "full"]

  # ------------------------------------------------ observability profile
  mlflow:
    profiles: ["observability", "full"]
```

### MCP Server Reusing API Image with Different Command

```yaml
# compose.yml (excerpt)
mcp-risk-server:
  build:
    context: .
    dockerfile: packages/api/Containerfile
  command: python -m src.mcp_server
  ports:
    - "8081:8081"
  healthcheck:
    test: ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8081/health')\""]
```

### Host LLM Proxy via host.docker.internal

```yaml
# compose.yml (excerpt)
mortgage-ai-api:
  environment:
    LLM_BASE_URL: "${LLM_BASE_URL:-http://host.docker.internal:1234/v1}"
    LLM_API_KEY: "${LLM_API_KEY:-not-needed}"
    LLM_MODEL: "${LLM_MODEL:-}"
```

### MinIO with Pre-Created Buckets

```yaml
# compose.yml (excerpt)
minio:
  image: docker.io/minio/minio:latest
  entrypoint: sh
  command: -c 'mkdir -p /data/mlflow /data/documents && exec minio server --address ":9000" --console-address ":9001" /data'
  healthcheck:
    test: ["CMD-SHELL", "curl -sf http://localhost:9000/minio/health/live || exit 1"]
```

### MLflow Sharing PostgreSQL with API

```yaml
# compose.yml (excerpt)
mlflow:
  image: ghcr.io/mlflow/mlflow:v2.21.3
  profiles: ["observability", "full"]
  depends_on:
    mortgage-ai-db:
      condition: service_healthy
    minio:
      condition: service_healthy
  environment:
    MLFLOW_BACKEND_STORE_URI: postgresql://user:password@mortgage-ai-db:5432/mlflow
    MLFLOW_DEFAULT_ARTIFACT_ROOT: s3://mlflow
    MLFLOW_S3_ENDPOINT_URL: http://minio:9000
```

### Database Init Script for Multi-Role Isolation

```bash
# config/postgres/init-databases.sh
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE EXTENSION IF NOT EXISTS vector;
    CREATE DATABASE mlflow;
    CREATE ROLE lending_app WITH LOGIN PASSWORD 'lending_pass';
    CREATE ROLE compliance_app WITH LOGIN PASSWORD 'compliance_pass';
    GRANT CONNECT ON DATABASE "mortgage-ai" TO lending_app;
    GRANT CONNECT ON DATABASE "mortgage-ai" TO compliance_app;
EOSQL
```

## Configuration

- **Key settings:** Profiles `auth`, `ai`, `observability`, and `full`; `LLM_BASE_URL` defaults to `host.docker.internal:1234/v1` for local LLM; `AUTH_DISABLED` defaults to `true` for local dev; PostgreSQL exposed on host port 5433 (not 5432) to avoid conflicts
- **Defaults:** MinIO on ports 9090/9091 (console); API on 8000; UI on 3000; Keycloak on 8080; MLflow on 5000; LlamaStack on 8321
- **Dependencies:** API depends on db (healthy), minio (healthy), and mcp-risk-server (healthy); UI depends on API (healthy); MLflow depends on db and minio (healthy); the init script creates the `mlflow` database used by the MLflow service

## Gotchas

- The MCP risk server reuses the API Containerfile image but overrides `command: python -m src.mcp_server` -- this means any image rebuild for the API also rebuilds the MCP server, and the MCP server includes all API dependencies even though it only needs a subset (see `compose.yml` lines 119-126)
- The MinIO entrypoint overrides the default with `sh -c 'mkdir -p /data/mlflow /data/documents && exec minio server ...'` to pre-create buckets as directories before the server starts -- this avoids needing an init container or mc client setup (see `compose.yml` lines 209-210)
- The PostgreSQL init script creates both the `mlflow` database and the HMDA isolation roles (`lending_app`, `compliance_app`) in a single entrypoint script -- the `mlflow` database is only used when the observability profile is active, but it's always created (see `config/postgres/init-databases.sh`)
- The `host.docker.internal` hostname works natively on Docker Desktop but requires `--add-host host.docker.internal:host-gateway` on Linux Docker -- Podman handles this automatically (see `compose.yml` line 64)
- The API healthcheck uses `python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health/')"` instead of curl because curl is not available in the python:3.11-slim image (see `compose.yml` lines 88-91)

## Related Patterns

- `compose-local-dev-ollama-llamastack-mcp.md` -- alternative compose pattern with Ollama model pull and MCP socket servers
- `compose-local-dev-loki-grafana-hybrid-services.md` -- compose pattern with observability stack
