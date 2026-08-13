---
name: compose-local-dev-keycloak-llamastack-smtp-migrations
description: Podman Compose local dev with Keycloak, LlamaStack, smtp4dev, dedicated migrations container, pgAdmin profile, and IMAGE_TAG registry/local toggle
summary: "Provides an 8-service Podman Compose local development stack for full-stack AI applications (FastAPI + React + nginx) combining PostgreSQL/pgvector, Keycloak authentication, LlamaStack LLM inference, smtp4dev email testing, and a dedicated one-shot migrations container that runs Alembic migrations, CSV data loading, and Keycloak realm setup gated on service health checks. Use when the quickstart requires Keycloak auth, LlamaStack inference, and email testing in a single local environment with an IMAGE_TAG toggle between pre-built quay.io images (latest) and locally built images (local); for Ollama-based inference see compose-local-dev-ollama-llamastack-mcp, for observability stacks see compose-local-dev-loki-grafana-hybrid-services. LlamaStack requires a run-config.yaml volume mount with custom entrypoint `llama stack run /run-config.yaml` and persistent llamastack-data volume; the migrations container uses `depends_on` with `condition: service_healthy` on both Postgres and Keycloak; optional pgAdmin starts only with `--profile tools`; all services share a single .env.development and are pinned to `linux/amd64` for Apple Silicon compatibility. Keycloak health check uses TCP port probe (`bash -c '</dev/tcp/127.0.0.1/8080'`) requiring 60s start_period rather than HTTP endpoint, API image reference lacks registry prefix (inconsistent with other quay.io-prefixed services), UI has commented-out image lines needing manual toggle between local and registry variants, and API data/model volume mounts (`./data:/app/data`, `ml_models:/tmp/ml_models`) do not carry over to OpenShift deployment."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [fastapi, react, postgresql, nginx]
  ai_pattern: [agents]
  platform: []
  data_layer: [pgvector]
source_examples:
  - quickstart: "spending-transaction-monitor"
    repo: "https://github.com/rh-ai-quickstart/spending-transaction-monitor"
    notes: "podman-compose.yml with pgvector, Keycloak, smtp4dev, LlamaStack, nginx proxy, dedicated migrations container, pgAdmin in tools profile, IMAGE_TAG-based registry/local toggle"
    approach: "A"
---

# Podman Compose Local Dev with Keycloak, LlamaStack, SMTP, and Migrations Container

## Overview

This pattern provides a local development environment using Podman Compose with a full application stack: PostgreSQL with pgvector, Keycloak for auth, LlamaStack for LLM inference, smtp4dev for email testing, nginx for reverse proxying, and a dedicated migrations container that runs database setup as a one-shot job. An `IMAGE_TAG` environment variable controls whether services pull pre-built images from Quay or use locally built ones.

## Pattern Description

The compose file defines 8 services plus a `tools` profile for optional pgAdmin. Infrastructure services (Postgres, Keycloak, smtp4dev) start first with health checks. A dedicated `migrations` container depends on Postgres and Keycloak being healthy, runs the migration startup script, then exits. Application services (API, UI) depend on infrastructure. The `IMAGE_TAG` variable toggles between `latest` (pulls from quay.io) and `local` (uses locally built images), enabling both quick-start and development build workflows.

## Implementation

### Migrations as Dedicated One-Shot Container

```yaml
migrations:
  image: quay.io/rh-ai-quickstart/spending-monitor-db:${IMAGE_TAG:-latest}
  platform: linux/amd64
  container_name: spending-monitor-migrations
  env_file:
    - .env.development
  depends_on:
    postgres:
      condition: service_healthy
    keycloak:
      condition: service_healthy
  networks:
    - spending-monitor
```

Source: `podman-compose.yml`. The migrations container uses the db image which includes `startup.sh` for Alembic migrations, CSV data loading, and Keycloak realm setup.

### LlamaStack with Run Config Volume Mount

```yaml
llamastack:
  image: docker.io/ogxai/distribution-starter:0.5.2
  platform: linux/amd64
  container_name: spending-monitor-llamastack
  env_file:
    - .env.development
  ports:
    - "8321:8321"
  volumes:
    - ./run-config.yaml:/run-config.yaml:ro
    - llamastack-data:/root/.llama
  entrypoint: llama
  command: ["stack", "run", "/run-config.yaml"]
```

Source: `podman-compose.yml`. LlamaStack uses a custom entrypoint and persistent volume for model data.

### IMAGE_TAG-Based Registry Toggle

```yaml
api:
  image: spending-monitor-api:${IMAGE_TAG:-latest}
  build:
    context: .
    dockerfile: packages/api/Containerfile
  # ...

ui:
  image: quay.io/rh-ai-quickstart/spending-monitor-ui:${IMAGE_TAG:-latest}
  build:
    context: .
    dockerfile: packages/ui/Containerfile
```

Source: `podman-compose.yml`. When `IMAGE_TAG=latest`, pre-built images are pulled. When `IMAGE_TAG=local`, locally built images are used. The API image reference is unqualified (no registry prefix) for local builds.

### Optional pgAdmin via Profile

```yaml
pgadmin:
  image: docker.io/dpage/pgadmin4:latest
  ports:
    - "8081:80"
  profiles:
    - tools  # Only start with --profile tools
```

Source: `podman-compose.yml`. Started via `podman-compose --profile tools up -d pgadmin`.

### Nginx Reverse Proxy

```yaml
nginx:
  image: docker.io/library/nginx:alpine
  ports:
    - "3000:80"
  depends_on:
    - ui
    - api
  volumes:
    - ./nginx.conf:/etc/nginx/nginx.conf:ro
```

Source: `podman-compose.yml`. Nginx proxies `localhost:3000` to UI and API, matching the E2E test URL.

## Configuration

- **Port mapping:** Postgres 5432, Keycloak 8080, API 8000, UI (via nginx) 3000, smtp4dev web 3002, LlamaStack 8321, pgAdmin 8081
- **Env file:** `.env.development` shared across all services
- **Platform:** All services pinned to `linux/amd64`
- **Volumes:** `postgres_data` (persistent DB), `llamastack-data` (model cache), `ml_models` (shared model dir between API and ML services)
- **Networks:** Single `spending-monitor` bridge network

## Gotchas

- Some service image references include the registry prefix (`quay.io/...`) while the API image does not, making the compose file inconsistent -- the API is intended for local builds while other services default to pre-built images
- The `UI` service has commented-out image lines (e.g., `#image: spending-monitor-ui:${IMAGE_TAG:-latest}`) showing both local and registry variants, requiring manual toggle
- `platform: linux/amd64` is set on all services to avoid ARM compatibility issues on Apple Silicon Macs during local development
- The Keycloak health check uses `bash -c '</dev/tcp/127.0.0.1/8080'` (TCP port check) rather than HTTP health endpoint, with a long `start_period: 60s` because Keycloak takes significant time to initialize
- The API mounts `./data:/app/data` for live sample data access and `ml_models:/tmp/ml_models` for ML model sharing, but these volumes are not used in the OpenShift deployment

## Related Patterns

- `compose-local-dev-ollama-llamastack-mcp.md` - LlamaStack with Ollama
- `compose-local-dev-loki-grafana-hybrid-services.md` - Compose with observability stack
- `compose-profile-layered-optional-services.md` - Profile-based optional services
