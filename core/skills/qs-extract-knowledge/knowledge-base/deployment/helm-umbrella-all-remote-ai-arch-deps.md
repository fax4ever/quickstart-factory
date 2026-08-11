---
name: helm-umbrella-all-remote-ai-arch-deps
description: Umbrella Helm chart where every dependency is a remote ai-architecture-charts subchart
summary: "Deploys a complete AI quickstart stack (pgvector, mcp-servers, llm-service, llama-stack, configure-pipeline, ingestion-pipeline, oracle-db) via a single umbrella Helm chart at deploy/cluster/helm/ where all 7 dependencies are sourced from the ai-architecture-charts remote repository (https://rh-ai-quickstart.github.io/ai-architecture-charts). Use when every infrastructure component is available as an ai-architecture-charts subchart and no local chart customization is needed -- the parent chart contains only app-specific templates (deployment, service, route, RBAC, secrets) while delegating all infrastructure to versioned remote subcharts configured through nested values.yaml overrides. oracle-db is conditionally enabled via oracle-db.enabled (default false); llama-stack supports custom auth provider delegation (provider_config.type: \"custom\") pointing to the app's /validate endpoint with permit/forbid RBAC access policies; MCP server definitions use streamable-http transport under double-nested keys (mcp-servers.mcp-servers.<name>). The double-nested mcp-servers key structure is required by the chart's internal values layout, configure-pipeline MinIO credentials must be manually synced with any MinIO settings elsewhere in the release, and helm dependency update (Makefile deps target) must run before install."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  ai_pattern: [agents, rag, model-serving]
  platform: [openshift, rhoai]
  data_layer: [pgvector]
source_examples:
  - quickstart: "ai-virtual-agent"
    repo: "https://github.com/rh-ai-quickstart/ai-virtual-agent"
    notes: "All 7 dependencies sourced from ai-architecture-charts; no local subcharts"
    approach: "A"
  - quickstart: "f5-ai-guardrails"
    repo: "https://github.com/rh-ai-quickstart/f5-ai-guardrails"
    notes: "3 remote ai-architecture-charts deps (pgvector, llm-service, llama-stack) in RAG umbrella chart at deploy/helm/rag/"
    approach: "A"
  - quickstart: "f5-api-security"
    repo: "https://github.com/rh-ai-quickstart/F5-API-Security"
    notes: "3 remote ai-architecture-charts deps (pgvector 0.1.0, llm-service 0.5.10, llama-stack 0.8.6) in RAG umbrella chart at deploy/helm/rag/ with local UI deployment template"
    approach: "A"
---

# Helm Umbrella with All-Remote ai-architecture-charts Dependencies

## Overview

This pattern uses a single umbrella Helm chart where every dependency is pulled from the `ai-architecture-charts` remote repository. Unlike mixed approaches that include local subcharts, this pattern relies entirely on remote chart versions and configures them through nested `values.yaml` overrides.

## Pattern Description

The umbrella chart at `deploy/cluster/helm/` defines all its dependencies in `Chart.yaml` pointing to the same Helm repository (`https://rh-ai-quickstart.github.io/ai-architecture-charts`). The parent chart contains only application-specific templates (deployment, service, route, RBAC, secrets) while delegating infrastructure concerns (database, model serving, ingestion, MCP servers) to remote subcharts. Subchart behavior is customized exclusively through values overrides.

## Implementation

### Chart.yaml Dependencies

All seven dependencies reference the same remote repository. One dependency (`oracle-db`) is conditionally enabled:

```yaml
# deploy/cluster/helm/Chart.yaml
dependencies:
  - name: pgvector
    version: 0.5.5
    repository: https://rh-ai-quickstart.github.io/ai-architecture-charts
  - name: mcp-servers
    version: 0.5.15
    repository: https://rh-ai-quickstart.github.io/ai-architecture-charts
  - name: llm-service
    version: 0.5.9
    repository: https://rh-ai-quickstart.github.io/ai-architecture-charts
  - name: llama-stack
    version: 0.8.6
    repository: https://rh-ai-quickstart.github.io/ai-architecture-charts
  - name: configure-pipeline
    version: 0.5.6
    repository: https://rh-ai-quickstart.github.io/ai-architecture-charts
  - name: ingestion-pipeline
    version: 0.6.5
    repository: https://rh-ai-quickstart.github.io/ai-architecture-charts
  - name: oracle-db
    version: 0.5.5
    repository: https://rh-ai-quickstart.github.io/ai-architecture-charts
    condition: oracle-db.enabled
```

### Subchart Configuration via values.yaml

Subcharts are configured through nested keys in `values.yaml`. The `mcp-servers` subchart uses a double-nested key because the chart expects its server definitions under its own `mcp-servers` key:

```yaml
# deploy/cluster/helm/values.yaml (excerpt)
mcp-servers:
  mcp-servers:
    travel-research:
      enabled: true
      deploymentMode: deployment
      image:
        repository: quay.io/rh-ai-quickstart/mcp-travel-research
        tag: "latest"
      transport: streamable-http
      port: 8000
      targetPort: 8000
```

### LlamaStack Auth Delegation

The `llama-stack` subchart is configured with a custom auth provider that points back to the application's own `/validate` endpoint, along with detailed RBAC access policies:

```yaml
# deploy/cluster/helm/values.yaml (excerpt)
llama-stack:
  auth:
    provider_config:
      type: "custom"
      endpoint: http://ai-virtual-agent:8887/validate
    access_policy:
    - permit:
        actions: [create]
        resource: session::*
      description: all users have create access to sessions
    - forbid:
        actions: [create, update, delete]
      unless: user with admin in roles
      description: only users with the admin role can create, update or delete resources
```

## Configuration

- **Key settings:** Each subchart is versioned independently in `Chart.yaml`; `values.yaml` provides subchart-specific overrides under the subchart name key
- **Defaults:** `oracle-db.enabled: false` disables the Oracle DB subchart by default; all other subcharts are always installed
- **Dependencies:** Requires `helm dependency update` before install (handled by the `deps` Makefile target)

## Gotchas

- The `mcp-servers` subchart requires a double-nested key (`mcp-servers.mcp-servers.<server-name>`) because the chart's internal values structure expects server definitions under its own `mcp-servers` key (visible in `deploy/cluster/helm/values.yaml` lines 244-270)
- The `configure-pipeline` subchart's MinIO credentials must be kept in sync with any MinIO-related settings elsewhere (see `values.yaml` lines 159-171)

## Related Patterns

- `openshift-oauth-proxy-sidecar.md` -- the parent chart's deployment template that runs alongside these subcharts
- `makefile-split-cluster-local-interactive-env.md` -- the install script that passes values to `helm upgrade --install`
