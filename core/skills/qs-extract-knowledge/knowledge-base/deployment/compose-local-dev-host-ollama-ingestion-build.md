---
name: compose-local-dev-host-ollama-ingestion-build
description: Podman Compose local dev with host-based Ollama, build-from-source UI and ingestion, OS-aware networking
summary: "Deploys a local RAG development stack via Podman Compose (platform: linux/amd64) with Ollama running on the host for GPU passthrough, three services — LlamaStack (llamastack/distribution-ollama:0.2.9, port 8321), build-from-source Streamlit UI (port 8501), and build-from-source run-once ingestion container — plus pgvector for vector storage. Use for local dev when Ollama should remain on the host for GPU performance and model caching; the OS-aware Makefile start target (with check-deps, check-ollama prerequisites) auto-detects Linux (172.17.0.1) vs macOS/Windows (host.docker.internal) for OLLAMA_URL, and a hybrid `make dev` target runs only LlamaStack containerized while the frontend runs locally via start.sh for rapid iteration. The ingestion service uses restart: \"no\" to run once and exit, depends_on service_started (not service_healthy) to avoid waiting for LlamaStack's 120s healthcheck start_period, mounts ingestion-config.yaml:ro, and can be re-run via `make ingest` (podman-compose up --build rag-ingestion); optional TAVILY_SEARCH_API_KEY enables web search. The compose file defaults OLLAMA_URL to host.docker.internal which fails on Linux where containers must reach the host via 172.17.0.1 — running podman-compose directly without the Makefile skips OS detection and breaks Linux container-to-host networking; also the Makefile adds sleep 30 after podman-compose up despite LlamaStack's own healthcheck for additional service readiness."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [streamlit, llamastack, podman]
  ai_pattern: [rag, embeddings]
  platform: []
  data_layer: [pgvector]
source_examples:
  - quickstart: "RAG"
    repo: "https://github.com/rh-ai-quickstart/RAG"
    notes: "3-service podman-compose (LlamaStack + build-from-source ingestion + build-from-source UI) with host-based Ollama, OS-aware OLLAMA_URL, and run-once ingestion container"
    approach: "A"
---

# Compose Local Dev with Host-Based Ollama and Build-From-Source Services

## Overview

This pattern runs a local RAG development stack using Podman Compose with Ollama running directly on the host machine (not containerized), two services built from local source (UI and ingestion), and one pre-built image (LlamaStack). It detects the host OS to configure container-to-host networking for Ollama access.

## Pattern Description

The `deploy/local/podman-compose.yml` defines three services: a LlamaStack server (pre-built distribution-ollama image), a RAG ingestion service (built from `ingestion-service/Containerfile`), and a RAG UI (built from `frontend/Containerfile`). Ollama runs on the host for better GPU performance and model caching. The Makefile detects Linux vs macOS/Windows to set the correct Ollama URL for container-to-host networking. The ingestion service runs once and exits (`restart: "no"`), while the UI runs continuously. The accompanying Makefile provides a `dev` target that starts only backend containers and runs the UI locally via `start.sh` for rapid frontend iteration.

## Implementation

### Podman Compose with Host Ollama

```yaml
# deploy/local/podman-compose.yml (excerpt)
services:
  # NOTE: Ollama runs on the host machine for better performance
  llamastack:
    image: llamastack/distribution-ollama:0.2.9
    platform: linux/amd64
    container_name: rag-llamastack
    restart: on-failure:50
    environment:
      INFERENCE_MODEL: "llama3.2:3b-instruct-fp16"
      OLLAMA_URL: "${OLLAMA_URL:-http://host.docker.internal:11434}"
      TAVILY_SEARCH_API_KEY: "${TAVILY_SEARCH_API_KEY:-}"
    ports:
      - "8321:8321"
    volumes:
      - llamastack_data:/root/.llama
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8321/"]
      interval: 30s
      timeout: 10s
      retries: 10
      start_period: 120s
```

### Run-Once Ingestion Container

The ingestion service builds from source, depends on LlamaStack being started, mounts a config file read-only, and exits after one run:

```yaml
# deploy/local/podman-compose.yml (ingestion service)
rag-ingestion:
  platform: linux/amd64
  build:
    context: ../../ingestion-service
    dockerfile: Containerfile
  container_name: rag-ingestion
  depends_on:
    llamastack:
      condition: service_started
  environment:
    INGESTION_CONFIG: "/config/ingestion-config.yaml"
  volumes:
    - ./ingestion-config.yaml:/config/ingestion-config.yaml:ro
  restart: "no"  # Run once and exit
```

### OS-Aware Networking in Makefile

The Makefile detects the OS and sets the Ollama URL accordingly for container-to-host communication:

```makefile
# deploy/local/Makefile (start target excerpt)
start: check-deps check-ollama
    @TAVILY_KEY=$$(cat /tmp/tavily_key_start 2>/dev/null || echo ""); \
    if [ "$$(uname)" = "Linux" ]; then \
        echo "Detected Linux - using 172.17.0.1 for container networking..."; \
        export OLLAMA_URL="http://172.17.0.1:11434"; \
    else \
        echo "Detected macOS/Windows - using host.docker.internal..."; \
        export OLLAMA_URL="http://host.docker.internal:11434"; \
    fi; \
    export TAVILY_SEARCH_API_KEY="$$TAVILY_KEY"; \
    podman-compose up -d
```

### Hybrid Dev Mode (Backend in Containers, UI Local)

The `dev` target starts only backend containers and runs the frontend locally for rapid iteration:

```makefile
# deploy/local/Makefile (dev target excerpt)
dev: check-ollama
    @TAVILY_KEY=$$(cat /tmp/tavily_key_dev 2>/dev/null || echo ""); \
    export OLLAMA_URL="http://..."; \
    export TAVILY_SEARCH_API_KEY="$$TAVILY_KEY"; \
    podman-compose up -d llamastack; \
    sleep 30; \
    cd ../../frontend && \
    VERSION=$(VERSION) TAVILY_SEARCH_API_KEY="$$TAVILY_KEY" ./start.sh
```

## Configuration

- **Key settings:** `OLLAMA_MODEL` (default `llama3.2:3b-instruct-fp16`), `TAVILY_SEARCH_API_KEY` (optional, for web search), `OLLAMA_URL` (auto-detected by OS)
- **Defaults:** LlamaStack on port 8321, RAG UI on port 8501, Ollama on port 11434 (host)
- **Dependencies:** Requires `podman`, `podman-compose`, `uv`, and `ollama` installed on the host

## Gotchas

- Ollama runs on the host (not in a container) for better GPU passthrough performance; the `check-ollama` target verifies the Ollama API is reachable before starting containers
- Linux containers use `172.17.0.1` (default bridge gateway) while macOS/Windows uses `host.docker.internal` for reaching the host's Ollama; the compose file defaults to `host.docker.internal` and the Makefile overrides via `OLLAMA_URL` env var
- The `start_period: 120s` healthcheck setting for LlamaStack gives it 2 minutes for initial startup, but the Makefile also adds a `sleep 30` after `podman-compose up` for service readiness
- The ingestion container (`restart: "no"`) runs once to process documents and exits; to re-run ingestion, use `make ingest` which runs `podman-compose up --build rag-ingestion`
- The `depends_on` for ingestion uses `service_started` (not `service_healthy`) because LlamaStack's healthcheck has a long `start_period` and waiting for healthy would delay ingestion unnecessarily

## Related Patterns

- `makefile-interactive-values-init-model-cli-override.md` -- the Helm deployment Makefile for the same repo (cluster deployment vs local dev)
- `compose-local-dev-ollama-llamastack-mcp.md` -- alternative pattern with Ollama IN the compose stack and MCP servers
