---
name: compose-local-dev-multi-agent-tool-mlserver-minio
description: Local compose dev stack for multi-agent tool microservices with MLServer sklearn, MinIO, and guardrails proxy
summary: "Provides a local Docker Compose development environment (from portfolio-manager-agent) for an 8-service multi-agent system mirroring cluster Helm topology: React UI (nginx API proxy, 8080), Flask orchestrator (5000) discovering tool agents via comma-separated TOOL_SERVERS (risk:7001, portfolio:7002, guidelines:7003) with GUARDRAILS_URL, guardrails proxy (8000) with volume-mounted config at GUARDRAILS_CONFIG_PATH, MLServer sklearn (8081->8080) serving investment-guidelines-mlp.joblib from prebaked image, and MinIO mc init container with mc alias set retry loop. Use when building a local dev stack for orchestrator-plus-tool-agent architectures requiring sklearn model serving via MLServer and a guardrails proxy with live-editable config (:ro,z volume mounts for SELinux) -- for simpler agent topologies without model serving or MinIO, use a basic compose stack instead. MLServer requires repo-root build context (context: ../..) because its Dockerfile copies model files from root models/ directory; guidelines agent connects via INFERENCE_URL=http://mlserver:8080 and mounts host PDFs with :ro,z volumes; UI .env_file uses required: false with empty-default VITE_* build args so the stack starts without .env. Common gotchas: model-upload init container only creates MinIO bucket locally (model served from MLServer image, not uploaded), $$(seq 1 30) double-dollar syntax required to escape shell variables from Compose interpolation, and model-upload is the sole service using restart: \"no\" while all others use unless-stopped."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [flask, python]
  ai_pattern: [agents, model-serving, guardrails]
  platform: []
source_examples:
  - quickstart: "portfolio-manager-agent"
    repo: "https://github.com/rh-ai-quickstart/portfolio-manager-agent"
    notes: "8-service compose with orchestrator, 3 tool agents, guardrails proxy, MLServer sklearn, MinIO, and model-upload init container"
    approach: "A"
---

# Multi-Agent Tool Microservices Compose Stack with MLServer and MinIO

## Overview

This pattern provides a local development environment for a multi-agent system where an orchestrator connects to multiple tool-agent microservices, a guardrails proxy, and an sklearn model served via MLServer, with MinIO for model storage. It mirrors the cluster Helm deployment topology but uses local builds and volume mounts for development.

## Pattern Description

The compose file orchestrates 8 services: a React UI that proxies API requests to the orchestrator via nginx, a Flask orchestrator that discovers tool servers via a comma-separated `TOOL_SERVERS` environment variable, three independent Flask tool agents (risk, portfolio, guidelines), a guardrails proxy with volume-mounted config, an MLServer instance serving an sklearn model from a prebaked image, and a MinIO init container that ensures the S3 bucket exists. The guidelines agent connects to MLServer for model inference. Service dependencies ensure tools start before the orchestrator, and the orchestrator starts before the UI.

## Implementation

### Service Topology

```yaml
# deploy/local/compose.yml
services:
  ui:
    build:
      context: ../../frontend
      args:
        VITE_ORCHESTRATOR_URL: /api/chat
        VITE_OPENAI_API_ENDPOINT: ${OPENAI_API_ENDPOINT:-}
        VITE_OPENAI_API_TOKEN: ${OPENAI_API_TOKEN:-}
        VITE_OPENAI_MODEL: ${OPENAI_MODEL:-}
    ports:
      - "8080:8080"
    env_file:
      - path: ../../.env
        required: false
    depends_on:
      orchestrator:
        condition: service_started
    restart: unless-stopped
  orchestrator:
    build:
      context: ../../orchestrator/src
    ports:
      - "5000:5000"
    environment:
      PORT: "5000"
      PYTHONUNBUFFERED: "1"
      TOOL_SERVERS: >-
        http://risk:7001, http://portfolio:7002, http://guidelines:7003
      GUARDRAILS_URL: "http://guardrails:8000"
    depends_on:
      risk:
        condition: service_started
      portfolio:
        condition: service_started
      guidelines:
        condition: service_started
      guardrails:
        condition: service_started
    restart: unless-stopped
```

### Guardrails with Volume-Mounted Config

The guardrails proxy mounts its config directory from the host, enabling live editing without rebuilds:

```yaml
# deploy/local/compose.yml (guardrails service)
  guardrails:
    build:
      context: ../../tools/guardrails/src
    ports:
      - "8000:8000"
    environment:
      PORT: "8000"
      PYTHONUNBUFFERED: "1"
      GUARDRAILS_CONFIG_PATH: "/config"
    volumes:
      - ../../tools/guardrails/config:/config:ro,z
    restart: unless-stopped
```

### MLServer with Repo-Root Build Context

The MLServer image requires the repo root as build context because the Dockerfile copies model files from the root `models/` directory:

```yaml
# deploy/local/compose.yml (mlserver service)
  mlserver:
    build:
      context: ../..
      dockerfile: tools/guidelines-model/Dockerfile
    ports:
      - "8081:8080"
    restart: unless-stopped
```

### MinIO Bucket Init Container

The model-upload service waits for MinIO readiness with a retry loop, then creates the bucket. In local mode, the model is served directly from the MLServer image rather than uploaded to MinIO:

```yaml
# deploy/local/compose.yml (model-upload service)
  model-upload:
    image: docker.io/minio/mc:latest
    depends_on:
      minio:
        condition: service_started
      mlserver:
        condition: service_started
    entrypoint: /bin/sh
    command:
      - -c
      - |
        for i in $$(seq 1 30); do
          mc alias set minio http://minio:9000 minioadmin minioadmin && break
          echo "Waiting for MinIO... ($$i/30)"
          sleep 2
        done
        mc mb --ignore-existing minio/models
        echo "MinIO bucket ready (model served from MLServer image locally)"
    restart: "no"
```

### Guidelines Agent with Volume-Mounted Docs

The guidelines agent mounts PDF documents from the host and connects to MLServer for model inference:

```yaml
# deploy/local/compose.yml (guidelines service)
  guidelines:
    build:
      context: ../../tools/guidelines/src
    environment:
      INFERENCE_URL: "http://mlserver:8080"
    volumes:
      - ../../tools/guidelines/docs:/app/docs:ro,z
    depends_on:
      mlserver:
        condition: service_started
```

## Configuration

- **Key settings:** `TOOL_SERVERS` comma-separated URLs for orchestrator tool discovery; `GUARDRAILS_URL` for guardrails proxy; `INFERENCE_URL` for MLServer endpoint; `VITE_*` build args for frontend configuration
- **Defaults:** UI on 8080, orchestrator on 5000, guardrails on 8000, risk on 7001, portfolio on 7002, guidelines on 7003, MLServer on 8081 (mapped from 8080), MinIO API on 9000 and console on 9001
- **Dependencies:** Requires `.env` file (optional) for API keys; all services use `restart: unless-stopped` except model-upload which uses `restart: "no"`

## Gotchas

- The MLServer build context is `../..` (repo root), not the `tools/guidelines-model/` directory, because the Dockerfile needs to `COPY models/investment-guidelines-mlp.joblib` from the repo root (see `deploy/local/compose.yml` lines 102-104)
- In local mode, the model-upload container only creates the MinIO bucket but does NOT upload the model -- the comment in the compose file explicitly states "model served from MLServer image locally" (see `deploy/local/compose.yml` line 99); on the cluster, a Helm Job handles the full upload
- Volume mounts use the `:z` SELinux label for Podman compatibility on Fedora/RHEL hosts (see guardrails and guidelines volume mounts)
- The UI `.env_file` is marked `required: false` so the compose stack starts even without a `.env` file; API keys are passed as build args with empty defaults (see `deploy/local/compose.yml` lines 12-14)
- The `$$(seq 1 30)` double-dollar syntax in the model-upload command is required by compose to escape the shell variable from Compose variable interpolation (see `deploy/local/compose.yml` line 93)

## Related Patterns

- `container-build-mlserver-model-unwrap-multistage.md` -- the MLServer image built by this compose file
- `container-build-ubi10-minimal-python312-pip-microdnf.md` -- the tool agent images built by this compose file
