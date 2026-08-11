---
name: ranking-proxy
description: "Lightweight Python proxy translating NIM /v1/ranking requests to vLLM /v1/rerank format for reranking models"
summary: "Solves NIM-to-vLLM API translation for reranking by deploying a stdlib-only Python 3.12-slim HTTP server as a ConfigMap-embedded script in the rag-server Helm chart, converting NVIDIA NIM /v1/ranking requests (query.text + passages[].text) to vLLM /v1/rerank format (flat query + documents[]) for models like llama-nemotron-rerank-1b-v2 served via KServe InferenceService. Use when switching reranking from NGC-hosted NIMs to self-hosted vLLM — enable via rankingProxy.enabled with ENABLE_RERANKER=\"True\" and APP_RANKING_SERVERURL pointing to the proxy; follows the same ConfigMap-embedded pattern as the sibling embedding-proxy. Critical config: rankingProxy.upstream must point to the KServe predictor service (default http://nemoretriever-ranking-ms-predictor:8080), the proxy accepts both /ranking and /v1/ranking inbound but always forwards to /v1/rerank, and exposes /health and /v1/models endpoints for diagnostics. Gotchas: only Python stdlib (http.server, urllib, json) is available — third-party imports crash at runtime; the Service name derives from the Helm fullname helper so fullnameOverride changes both proxy Service and rag-server APP_RANKING_SERVERURL together; resource limits are intentionally minimal (500m CPU, 128Mi memory)."
metadata:
  type: component
tags:
  tech_stack: [python, vllm]
  ai_pattern: [rag, reranking]
  platform: [rhoai, openshift, kserve, vllm]
  data_layer: []
source_examples:
  - quickstart: "aml-rag-nvidia"
    repo: "https://github.com/rh-ai-quickstart/aml-rag-nvidia"
    notes: "ConfigMap-embedded Python proxy converting NIM ranking API to vLLM rerank API for llama-nemotron-rerank-1b-v2"
    approach: "A"
---

# Ranking Proxy

## Overview

The ranking proxy is a lightweight Python HTTP server that translates NVIDIA NIM `/v1/ranking` requests into vLLM-compatible `/v1/rerank` requests. It exists because the NVIDIA RAG server (rag-server) emits ranking calls in NIM format, but the upstream model is served by vLLM via KServe InferenceService, which exposes the OpenAI-compatible `/v1/rerank` endpoint with a different payload schema. The proxy is deployed as a ConfigMap-embedded script inside the rag-server Helm chart, conditionally enabled via `rankingProxy.enabled`.

## Tech Stack & Dependencies

- **Runtime:** Python 3.12-slim (stdlib only -- no pip dependencies)
- **Container image:** `python:3.12-slim`
- **Key dependencies:** Upstream vLLM reranking model served via KServe InferenceService (e.g., `nemoretriever-ranking-ms-predictor`)
- **Helm subchart:** None -- deployed as templates within the `rag-server` chart (ConfigMap + Deployment + Service)

## Key Patterns

### ConfigMap-Embedded Application Code

The entire proxy application is embedded as a Python script inside a Kubernetes ConfigMap, then volume-mounted into a minimal `python:3.12-slim` container. This avoids building a custom container image for a simple translation layer.

```yaml
# From charts/rag-server/templates/ranking-proxy-configmap.yaml
data:
  proxy.py: |
    import json
    import logging
    import os
    import sys
    from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError, URLError
```

The deployment mounts the ConfigMap as a file and runs it directly:

```yaml
# From charts/rag-server/templates/ranking-proxy-deployment.yaml
command: ["python", "/app/proxy.py"]
volumeMounts:
- name: proxy-script
  mountPath: /app/proxy.py
  subPath: proxy.py
  readOnly: true
volumes:
- name: proxy-script
  configMap:
    name: {{ include "rag-server.fullname" . }}-ranking-proxy
```

### NIM-to-vLLM Request Translation

The proxy converts between two different API schemas for the same reranking operation. NIM uses `query.text` + `passages[].text`, while vLLM uses flat `query` + `documents[]`.

```python
# From ranking-proxy-configmap.yaml -- translate_nim_to_vllm()
def translate_nim_to_vllm(nim_body: dict) -> dict:
    """Translate a NIM /v1/ranking request to a vLLM /v1/rerank request."""
    vllm_body = {
        "query": nim_body["query"]["text"],
        "documents": [p["text"] for p in nim_body["passages"]],
        "top_n": len(nim_body["passages"]),
    }
    if "model" in nim_body:
        vllm_body["model"] = nim_body["model"]
    return vllm_body
```

### vLLM-to-NIM Response Translation

The response path maps vLLM's `results[].relevance_score` back to NIM's `rankings[].logit` format.

```python
# From ranking-proxy-configmap.yaml -- translate_vllm_to_nim()
def translate_vllm_to_nim(vllm_body: dict) -> dict:
    """Translate a vLLM /v1/rerank response to a NIM /v1/ranking response."""
    results = vllm_body.get("results", [])
    rankings = [
        {"index": r["index"], "logit": r["relevance_score"]}
        for r in results
    ]
    return {"rankings": rankings}
```

### Conditional Deployment via Helm Toggle

All three ranking-proxy resources (ConfigMap, Deployment, Service) are gated by a single Helm value, so the proxy can be disabled when the upstream already speaks the expected API format.

```yaml
# From charts/rag-server/values.yaml
rankingProxy:
  enabled: true
  port: 8080
  upstream: "http://nemoretriever-ranking-ms-predictor:8080"
  image:
    repository: python
    tag: "3.12-slim"
```

Each template wraps its content with:

```yaml
{{- if .Values.rankingProxy.enabled }}
...
{{- end }}
```

## Configuration

- **Environment variables:**
  - `UPSTREAM_URL` -- URL of the vLLM reranking model endpoint (default: `http://localhost:8080`, set via `rankingProxy.upstream`)
  - `PROXY_PORT` -- Port the proxy listens on (default: `8080`, set via `rankingProxy.port`)

- **Helm values:**
  - `rankingProxy.enabled` -- Toggle the entire proxy on/off
  - `rankingProxy.port` -- Proxy listen port (default `8080`)
  - `rankingProxy.upstream` -- vLLM model service URL (default `http://nemoretriever-ranking-ms-predictor:8080`)
  - `rankingProxy.image.repository` / `rankingProxy.image.tag` -- Container image (default `python:3.12-slim`)

- **Rag-server env vars that point to this proxy:**
  - `APP_RANKING_SERVERURL: "http://rag-server-ranking-proxy:8080/v1"` -- the rag-server uses this URL to reach the proxy
  - `APP_RANKING_MODELNAME: "nvidia/llama-nemotron-rerank-1b-v2"` -- model name passed through to vLLM
  - `ENABLE_RERANKER: "True"` -- feature flag enabling reranking in the RAG pipeline

## Known Gotchas

- **Service name must match rag-server env var:** The proxy Service is named `{{ fullname }}-ranking-proxy` which resolves to `rag-server-ranking-proxy`. The rag-server `APP_RANKING_SERVERURL` must match this exactly (`http://rag-server-ranking-proxy:8080/v1`). If the chart's `fullnameOverride` changes, both the proxy service name and the rag-server env var change together since they use the same Helm helper.

- **Endpoint path differences:** The rag-server sends requests to `/v1/ranking` or `/ranking`, but the proxy forwards to `/v1/rerank` on the upstream vLLM endpoint. The proxy accepts both `/ranking` and `/v1/ranking` on inbound (see `do_POST` handler) but always forwards to `/v1/rerank`.

- **No external dependencies in the container:** The proxy uses only Python stdlib (`http.server`, `urllib`, `json`). This is intentional -- the `python:3.12-slim` image has no pip packages installed. If you add imports of third-party libraries the container will fail at runtime.

- **Resource limits are minimal:** The proxy is CPU-bound translation only (500m CPU limit, 128Mi memory limit). These are appropriate for the stdlib HTTP server approach.

- **Paired with embedding-proxy:** This proxy follows the same ConfigMap-embedded pattern as the sibling `embedding-proxy` (also in the rag-server chart). Both were introduced in the same commit (`d1557b3 request translation logic for embedding and ranking vLLM endpoints`) to handle NIM-to-vLLM API translation when switching model serving from NGC-hosted NIMs to self-hosted vLLM.

## Testing Notes

- Verify the proxy pod is running: check for a pod named `rag-server-ranking-proxy-*`
- The `/health` endpoint returns `{"status": "ok"}` -- use it for basic liveness verification
- The `/v1/models` GET endpoint proxies through to the upstream vLLM model list -- use it to confirm upstream connectivity
- Test the translation with a NIM-format ranking request to `/v1/ranking` and verify the response has `rankings[].logit` fields

## Related Patterns

- `components/embedding-proxy` -- sibling proxy using the same ConfigMap-embedded pattern for embedding API translation
- The upstream reranking model (`nvidia/llama-nemotron-rerank-1b-v2`) is deployed via the model-serving chart as a KServe InferenceService
