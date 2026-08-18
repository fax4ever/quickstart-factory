---
name: compose-local-dev-ollama-llamastack-mcp
description: Local dev compose with Ollama model pull, LlamaStack, MCP servers, and optional MinIO via profiles
summary: "Provides a 9-service Podman Compose local dev environment for AI agent quickstarts combining PostgreSQL, Ollama (auto-pulls llama3.2:1b via inline entrypoint), LlamaStack AI orchestration (ogxai/distribution-starter), FastAPI backend, React/Vite frontend, three MCP tool servers built from mcp_servers/ Containerfiles with socket-based healthchecks, and optional MinIO for attachments. Use for local agentic development needing LlamaStack with Ollama-served models and MCP tool integration; backend supports multi-runner config (LlamaStack local, LangGraph/CrewAI via Red Hat MaaS defaults), MinIO toggled via ENABLE_ATTACHMENTS env var and the \"attachments\" Compose profile with depends_on required: false, and LOCAL_DEV_ENV_MODE=true disables auth for dev. Critical pattern: start-dev.sh handles .env creation from template, profile selection, and orphan container force-removal via podman compose; LlamaStack mounts llamastack-run.yaml as run config with depends_on ollama service_healthy ensuring model availability before orchestration starts. LlamaStack requires user: \"0:0\" and platform: linux/amd64 (no native ARM support), Ollama healthcheck allows up to 15 minutes (30 retries at 30s) for initial model download, volume mounts need :Z suffix for SELinux relabeling on Fedora/RHEL, and podman may lose track of compose-managed containers requiring the startup script's force-remove cleanup of named containers."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [fastapi, react, postgresql, minio]
  ai_pattern: [agents, model-serving]
  platform: []
  data_layer: [pgvector]
source_examples:
  - quickstart: "ai-virtual-agent"
    repo: "https://github.com/rh-ai-quickstart/ai-virtual-agent"
    notes: "9-service compose with Ollama auto-pull, LlamaStack, 3 MCP servers, optional MinIO via profile"
    approach: "A"
---

# Compose Local Dev with Ollama, LlamaStack, and MCP Servers

## Overview

This pattern provides a full local development environment using Docker/Podman Compose with up to 9 services: PostgreSQL, Ollama (model server), LlamaStack (AI orchestration), backend (FastAPI), frontend (React/Vite), three MCP tool servers, and optional MinIO for attachments. Compose profiles control optional services, and the setup is driven by a shell script that handles cleanup and environment configuration.

## Pattern Description

The `compose.yaml` at `deploy/local/` defines the complete local stack. Ollama automatically pulls the `llama3.2:1b` model on first start using an inline entrypoint script. LlamaStack depends on Ollama being healthy before starting. The backend connects to LlamaStack for AI inference and to three MCP servers for tool capabilities. MinIO is gated behind the `attachments` Compose profile, enabling or disabling it with an environment variable. All services share a single bridge network.

## Implementation

### Ollama Service with Inline Model Pull

Ollama's entrypoint starts the server, waits 10 seconds, then runs the model to pull it. The healthcheck verifies the model is loaded:

```yaml
# deploy/local/compose.yaml (excerpt)
ollama:
  image: ollama/ollama:latest
  entrypoint:
    - bash
    - -c
    - "OLLAMA_DEBUG=1 ollama serve & sleep 10; ollama run llama3.2:1b --keepalive 60m hi; wait"
  healthcheck:
    test: ["CMD-SHELL", "ollama list | grep -q llama3.2:1b"]
    interval: 30s
    timeout: 10s
    retries: 30
  volumes:
    - ollama:/root/.ollama
```

### LlamaStack Service

LlamaStack runs the `ogxai/distribution-starter` image with a mounted config file. It depends on Ollama being healthy:

```yaml
# deploy/local/compose.yaml (excerpt)
llamastack:
  image: docker.io/ogxai/distribution-starter:0.6.1
  platform: linux/amd64
  user: "0:0"
  environment:
    - RUN_CONFIG_PATH=/app-config/config.yaml
  volumes:
    - llama:/.llama
    - llamadist:/.llama/distributions
    - ./llamastack-run.yaml:/app-config/config.yaml:Z
  depends_on:
    ollama:
      condition: service_healthy
  healthcheck:
    test: ["CMD-SHELL", "curl -f http://localhost:8321/v1/health || exit 1"]
    start_period: 90s
```

### MCP Server Services

Three MCP servers are built from Containerfiles within the `mcp_servers/` directory. Each uses socket-based healthchecks since they don't expose HTTP:

```yaml
# deploy/local/compose.yaml (excerpt)
travel-research-mcp:
  build:
    context: ../../mcp_servers/travel_research_mcp
    dockerfile: Containerfile
  environment:
    - TAVILY_API_KEY=${TAVILY_API_KEY:-}
    - HOST=0.0.0.0
    - PORT=7001
  healthcheck:
    test: ["CMD-SHELL", "python -c \"import socket; s=socket.create_connection(('localhost',7001),2); s.close()\""]
    interval: 10s
    timeout: 5s
    retries: 5
    start_period: 10s
```

### Optional MinIO via Compose Profile

MinIO is only started when the `attachments` profile is active. The backend's dependency on MinIO is marked `required: false`:

```yaml
# deploy/local/compose.yaml (excerpt)
minio:
  image: quay.io/minio/minio:latest
  command: server /data --console-address ":9001"
  profiles:
    - attachments
  healthcheck:
    test: ["CMD-SHELL", "curl -f http://localhost:9000/minio/health/live || exit 1"]

backend:
  depends_on:
    minio:
      condition: service_healthy
      required: false
```

### Multi-Runner Backend Configuration

The backend is configured with environment variables for three different AI runner endpoints (LlamaStack, LangGraph via MaaS, CrewAI via MaaS):

```yaml
# deploy/local/compose.yaml (excerpt, backend environment)
- LLAMASTACK_URL=${LLAMASTACK_URL:-http://llamastack:8321}
- DEFAULT_INFERENCE_MODEL=${DEFAULT_INFERENCE_MODEL:-ollama/llama3.2:1b}
- LANGGRAPH_LLM_API_BASE=${LANGGRAPH_LLM_API_BASE:-https://llama-4-scout-17b-16e-w4a16-maas-apicast-production.apps.prod.rhoai.rh-aiservices-bu.com:443/v1}
- CREWAI_LLM_API_BASE=${CREWAI_LLM_API_BASE:-https://llama-4-scout-17b-16e-w4a16-maas-apicast-production.apps.prod.rhoai.rh-aiservices-bu.com:443/v1}
```

### Startup Script

The `start-dev.sh` script uses `podman compose`, creates `.env` from template if missing, handles cleanup of orphaned containers, and controls the MinIO profile:

```bash
# deploy/local/scripts/start-dev.sh (excerpt)
ENABLE_ATTACHMENTS=${ENABLE_ATTACHMENTS:-true}
if [ "$ENABLE_ATTACHMENTS" = "true" ]; then
    COMPOSE_PROFILES="--profile attachments"
else
    COMPOSE_PROFILES=""
    export DISABLE_ATTACHMENTS=true
fi
podman compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" $COMPOSE_PROFILES down --remove-orphans
# Force-remove leftover containers
for ctr in "${DEV_CONTAINERS[@]}"; do
    podman rm -f "$ctr" 2>/dev/null || true
done
podman compose -f "$COMPOSE_FILE" --env-file "$ENV_FILE" $COMPOSE_PROFILES up --build -d
```

## Configuration

- **Key settings:** `ENABLE_ATTACHMENTS` (true/false) controls MinIO; `LOCAL_DEV_ENV_MODE` (true/false) disables auth for dev; `ENABLE_COVERAGE` enables coverage collection in backend
- **Defaults:** Attachments enabled, dev mode enabled, coverage disabled; Ollama pulls `llama3.2:1b`; LangGraph and CrewAI point to Red Hat MaaS endpoints by default
- **Dependencies:** Requires `podman` and `podman compose` (the startup script checks for both); `.env` file created from `.env.example` if missing

## Gotchas

- LlamaStack requires `user: "0:0"` and `platform: linux/amd64` in the compose definition (see `compose.yaml` lines 69-70). The `platform` constraint means it may not work natively on ARM-based machines
- The Ollama healthcheck uses `ollama list | grep -q llama3.2:1b` with 30 retries at 30s intervals (up to 15 minutes), reflecting the time needed for initial model download
- The startup script force-removes named containers (`postgresql-dev`, `ollama-dev`, etc.) after `compose down` to handle cases where podman loses track of compose-managed containers (see `start-dev.sh` lines 58-66)
- The `:Z` suffix on volume mounts (e.g., `./llamastack-run.yaml:/app-config/config.yaml:Z`) is required for SELinux relabeling on Fedora/RHEL hosts

## Related Patterns

- `container-build-ubi-multistage-fullstack.md` -- the Containerfiles used by compose build
- `compose-ci-overlay-gha-cache-coverage.md` -- CI overlay that extends this compose file
