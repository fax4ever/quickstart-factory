---
name: makefile-local-podman-compose-host-ollama-key-persist
description: Local dev Makefile wrapping podman-compose with host Ollama management, Tavily API key persistence, and hybrid dev mode
summary: "Provides a deploy/local/Makefile managing a local RAG stack via podman-compose with host-side Ollama (default llama3.2:3b-instruct-fp16), including automated install/verification (setup-ollama/check-ollama), Tavily API key persistence, hybrid dev mode running LlamaStack in a container while Streamlit runs locally, and UI container build/push targets (PLATFORM=linux/amd64, registry default quay.io/rh-ai-quickstart). Use when developing a podman-compose-based RAG quickstart needing host Ollama management, persistent API key handling across sessions, and a hybrid dev loop with backend containers plus local frontend — requires podman, podman-compose, uv, and ollama verified by check-deps. The get_tavily_key define retrieves keys from environment variable, ~/.rag_tavily_key (chmod 600), or interactive prompt with optional save; the dev target uses platform-specific Ollama URLs (http://172.17.0.1:11434 on Linux, http://host.docker.internal:11434 otherwise) and starts only LlamaStack (port 8321) before running cd ../../frontend && ./start.sh for the Streamlit UI (port 8501). Key gotchas: get_tavily_key writes to /tmp/tavily_key_<target> because Makefile define blocks and recipe lines run in separate shells; the dev target's cd ../../frontend is relative to deploy/local/ so frontend must be at repo root; stop cleans up both compose-managed and manually-started containers; ingest uses --build to rebuild before running."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [podman, streamlit, llamastack]
  ai_pattern: [rag]
  platform: []
source_examples:
  - quickstart: "RAG"
    repo: "https://github.com/rh-ai-quickstart/RAG"
    notes: "deploy/local/Makefile with setup-ollama/check-ollama host management, get_tavily_key define with ~/.rag_tavily_key persistence, dev target running backend containers + local Streamlit"
    approach: "A"
---

# Local Dev Makefile with Podman Compose, Host Ollama, and API Key Persistence

## Overview

This pattern provides a Makefile that manages a local RAG development stack through podman-compose, with Ollama running on the host machine. It includes automated Ollama installation and model setup, a persistent API key storage mechanism for the Tavily search API, and a hybrid development mode that runs backend services in containers while running the frontend UI locally for rapid iteration.

## Pattern Description

The `deploy/local/Makefile` defines targets for the full local development lifecycle: `setup-ollama` installs Ollama on the host and pulls the required model, `check-ollama` verifies it is running and the model is available, `start` brings up all compose services, and `dev` starts only backend containers while running the UI locally via `start.sh`. A reusable `get_tavily_key` Makefile define block handles API key retrieval from three sources (environment variable, saved file at `~/.rag_tavily_key`, or interactive prompt) with optional persistence.

## Implementation

### Tavily API Key Persistence Pattern

The `get_tavily_key` define block checks three sources in priority order: environment variable, saved file, and interactive prompt with optional save:

```makefile
# deploy/local/Makefile (get_tavily_key, lines 38-93)
TAVILY_KEY_FILE := $(HOME)/.rag_tavily_key

define get_tavily_key
    @if [ -n "$(TAVILY_SEARCH_API_KEY)" ]; then \
        echo "Using TAVILY_SEARCH_API_KEY from environment"; \
        echo "$(TAVILY_SEARCH_API_KEY)" > /tmp/tavily_key_$(1); \
    elif [ -f "$(TAVILY_KEY_FILE)" ]; then \
        TAVILY_KEY=$$(cat "$(TAVILY_KEY_FILE)" 2>/dev/null | tr -d '\n\r'); \
        if [ -n "$$TAVILY_KEY" ]; then \
            echo "$$TAVILY_KEY" > /tmp/tavily_key_$(1); \
        fi; \
    else \
        read -p "TAVILY_SEARCH_API_KEY: " tavily_key; \
        if [ -n "$$tavily_key" ]; then \
            read -p "Save API key to $(TAVILY_KEY_FILE)? " save_key; \
            if [ "$$save_key" = "y" ] || [ "$$save_key" = "Y" ]; then \
                echo "$$tavily_key" > "$(TAVILY_KEY_FILE)"; \
                chmod 600 "$(TAVILY_KEY_FILE)"; \
            fi; \
            echo "$$tavily_key" > /tmp/tavily_key_$(1); \
        fi; \
    fi
endef
```

### Host Ollama Setup and Verification

Two targets manage Ollama on the host: `setup-ollama` handles cross-platform installation, and `check-ollama` verifies the service and model:

```makefile
# deploy/local/Makefile (setup-ollama, lines 126-161)
OLLAMA_MODEL := llama3.2:3b-instruct-fp16
OLLAMA_HOST_URL := http://localhost:11434

setup-ollama:
    @if command -v ollama >/dev/null 2>&1; then \
        echo "Ollama is already installed."; \
    else \
        if [ "$$(uname)" = "Linux" ]; then \
            curl -fsSL https://ollama.ai/install.sh | sh; \
        fi; \
    fi
    @ollama pull $(OLLAMA_MODEL)

check-ollama:
    @curl -sf $(OLLAMA_HOST_URL)/api/version > /dev/null 2>&1 || { \
        echo "Ollama is not running at $(OLLAMA_HOST_URL)"; exit 1; }
    @ollama list | grep -q "$(OLLAMA_MODEL)" || { \
        ollama pull $(OLLAMA_MODEL); }
```

### Hybrid Dev Mode

The `dev` target starts only LlamaStack in a container and runs the UI locally via `start.sh`:

```makefile
# deploy/local/Makefile (dev target, lines 309-338)
dev: check-ollama
    @$(call get_tavily_key,dev)
    @TAVILY_KEY=$$(cat /tmp/tavily_key_dev 2>/dev/null || echo ""); \
    rm -f /tmp/tavily_key_dev; \
    if [ "$$(uname)" = "Linux" ]; then \
        export OLLAMA_URL="http://172.17.0.1:11434"; \
    else \
        export OLLAMA_URL="http://host.docker.internal:11434"; \
    fi; \
    export TAVILY_SEARCH_API_KEY="$$TAVILY_KEY"; \
    podman-compose up -d llamastack; \
    sleep 30; \
    cd ../../frontend && \
    VERSION=$(VERSION) TAVILY_SEARCH_API_KEY="$$TAVILY_KEY" ./start.sh
```

### Container UI Build and Push

Targets for building and pushing the UI container to a registry:

```makefile
# deploy/local/Makefile (build targets, lines 297-307)
CONTAINER_REGISTRY ?= quay.io/rh-ai-quickstart
PLATFORM := linux/amd64

build-ui:
    @podman build --platform $(PLATFORM) -t llamastack-dist-ui:$(VERSION) \
        -f $(DIST_UI_DIR)/Containerfile $(DIST_UI_DIR)

build-and-push-ui: build-ui
    @podman login $(CONTAINER_REGISTRY)
    @podman tag llamastack-dist-ui:$(VERSION) $(CONTAINER_REGISTRY)/llamastack-dist-ui:$(VERSION)
    @podman push $(CONTAINER_REGISTRY)/llamastack-dist-ui:$(VERSION)
```

## Configuration

- **Key settings:** `OLLAMA_MODEL` (default `llama3.2:3b-instruct-fp16`), `TAVILY_SEARCH_API_KEY` (env var or `~/.rag_tavily_key`), `VERSION` (default `0.6.0`), `CONTAINER_REGISTRY` (default `quay.io/rh-ai-quickstart`)
- **Defaults:** LlamaStack port 8321, RAG UI port 8501, Ollama port 11434; `PLATFORM=linux/amd64`
- **Dependencies:** `podman`, `podman-compose`, `uv`, `ollama` (verified by `check-deps`)

## Gotchas

- The `get_tavily_key` define writes the key to a temporary file (`/tmp/tavily_key_<target>`) then reads it back in the same recipe; this workaround is needed because Makefile `define` blocks and recipe lines run in separate shell invocations
- The saved key file at `~/.rag_tavily_key` is created with `chmod 600` for security, but the file is plain text -- not encrypted
- The `dev` target's `cd ../../frontend && ./start.sh` navigates relative to the Makefile's location (`deploy/local/`), so the frontend directory must be at the repo root
- The `stop` target cleans up both compose-managed containers and manually-started containers (`podman stop rag-ui-manual`) to handle cases where a user ran the UI container outside compose
- The `ingest` target uses `podman-compose up --build rag-ingestion` which rebuilds the ingestion image before running it, ensuring code changes are picked up

## Related Patterns

- `compose-local-dev-host-ollama-ingestion-build.md` -- the podman-compose.yml this Makefile manages
- `makefile-interactive-values-init-model-cli-override.md` -- the Helm deployment Makefile for the same repo (cluster deployment)
