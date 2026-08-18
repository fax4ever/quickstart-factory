---
name: embedding-proxy
description: "NIM-to-vLLM translation proxy that strips NIM-specific fields from OpenAI-format embedding requests before forwarding to vLLM"
summary: "Stdlib-only Python HTTP proxy (ThreadingHTTPServer on python:3.12-slim, zero pip deps) that strips NIM-specific fields (input_type, truncate, dimensions) from OpenAI-format /v1/embeddings requests before forwarding to vLLM, enabling NIM-oriented code like NVIDIA's rag-server to use vLLM-served embedding models without modification. Use when a NIM-native client sends extra embedding fields that vLLM rejects; the sibling ranking-proxy handles /v1/ranking-to-/v1/rerank translation with full request/response restructuring rather than simple field stripping, and the proxy can be disabled via embeddingProxy.enabled when the upstream natively accepts NIM fields. Deployed as a ConfigMap-injected script within the rag-server Helm chart (deployment + service + configmap templates), with UPSTREAM_URL pointing to the KServe predictor (e.g., http://nemoretriever-embedding-ms-predictor:8080); rag-server's APP_EMBEDDINGS_SERVERURL routes through the proxy while the ingest chart points directly to the model. Stripping input_type loses query/passage embedding distinction (configure at vLLM serving level via --chat-template if needed), resource limits are intentionally small (cpu: 500m/128Mi), /health returns local status for probes without hitting upstream, and upstream failures return structured 502 JSON rather than HTML errors."
metadata:
  type: component
tags:
  tech_stack: [python, helm]
  ai_pattern: [embeddings, model-serving]
  platform: [vllm, openshift, kubernetes, kserve]
  data_layer: []
source_examples:
  - quickstart: "aml-rag-nvidia"
    repo: "https://github.com/rh-ai-quickstart/aml-rag-nvidia"
    notes: "Embedding translation proxy deployed as a sidecar Deployment within the rag-server Helm chart, translating NIM /v1/embeddings requests for a vLLM-served embedding model"
    approach: "A"
---

# Embedding Proxy

## Overview

A lightweight Python HTTP proxy that translates NVIDIA NIM embedding API requests into vLLM-compatible OpenAI `/v1/embeddings` requests. Both NIM and vLLM use the OpenAI embeddings format, but NIM clients send extra fields (`input_type`, `truncate`, `dimensions`) that vLLM rejects. The proxy strips these fields transparently, allowing NIM-oriented application code (such as NVIDIA's rag-server) to work against a vLLM-served embedding model without modification.

## Tech Stack & Dependencies

- **Runtime:** Python 3.12 (`python:3.12-slim` container image)
- **Container image:** Stock `python:3.12-slim` -- no custom build, no pip install
- **Key dependencies:** Python stdlib only (`http.server`, `urllib.request`, `json`, `logging`) -- zero third-party packages
- **Helm subchart:** Deployed as part of the `rag-server` chart (not a standalone subchart). Three templates: `embedding-proxy-deployment.yaml`, `embedding-proxy-service.yaml`, `embedding-proxy-configmap.yaml`

## Key Patterns

### ConfigMap-Injected Proxy Script

The entire proxy application is a single Python script embedded in a Helm ConfigMap template and mounted into the container at `/app/proxy.py`. This avoids building a custom container image -- the stock `python:3.12-slim` image runs the script directly.

```yaml
# charts/rag-server/templates/embedding-proxy-configmap.yaml
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

The deployment mounts this ConfigMap as a single file:

```yaml
# charts/rag-server/templates/embedding-proxy-deployment.yaml
volumeMounts:
- name: proxy-script
  mountPath: /app/proxy.py
  subPath: proxy.py
  readOnly: true
volumes:
- name: proxy-script
  configMap:
    name: {{ include "rag-server.fullname" . }}-embedding-proxy
```

### NIM-to-vLLM Field Stripping

The proxy intercepts POST requests to `/embeddings` or `/v1/embeddings`, strips three NIM-specific fields that vLLM does not accept, and forwards the cleaned request upstream. The stripping is a simple set-difference filter.

```python
# From the proxy.py ConfigMap
NIM_ONLY_FIELDS = {"input_type", "truncate", "dimensions"}

def translate_nim_to_vllm(nim_body: dict) -> dict:
    """Strip NIM-specific fields that vLLM does not accept."""
    errors = []
    if "input" not in nim_body:
        errors.append("'input' field is required")
    if errors:
        raise ValueError("; ".join(errors))
    vllm_body = {k: v for k, v in nim_body.items() if k not in NIM_ONLY_FIELDS}
    return vllm_body
```

### Feature-Flag Gated Deployment

All three embedding-proxy Kubernetes resources (Deployment, Service, ConfigMap) are wrapped with `{{- if .Values.embeddingProxy.enabled }}`, allowing the proxy to be disabled when using a NIM-native upstream that accepts the extra fields.

```yaml
# charts/rag-server/values.yaml
embeddingProxy:
  enabled: true
  port: 8080
  upstream: "http://nemoretriever-embedding-ms-predictor:8080"
  image:
    repository: python
    tag: "3.12-slim"
```

### Transparent Model and Health Passthrough

The proxy passes GET requests for `/v1/models` directly to the upstream, enabling clients to discover available models through the proxy. A local `/health` endpoint returns `{"status": "ok"}` for Kubernetes liveness and readiness probes without hitting the upstream.

```python
# From the proxy.py ConfigMap
def do_GET(self):
    if self.path == "/health":
        self._send_json(200, {"status": "ok"})
        return
    if self.path in ("/v1/models", "/models"):
        status, data = proxy_upstream("GET", "/v1/models")
        self._send_raw(status, data)
        return
    self._send_json(404, {"error": "not found"})
```

### Upstream Error Propagation

The proxy returns a 502 with a structured JSON error when the upstream is unreachable, rather than crashing or returning an HTML error page. HTTP errors from the upstream are forwarded with their original status code.

```python
# From the proxy.py ConfigMap
except URLError as exc:
    err = json.dumps({"error": f"upstream unreachable: {exc.reason}"}).encode()
    return 502, err
```

## Configuration

- **Environment variables:**
  - `UPSTREAM_URL` -- full URL of the upstream vLLM embedding endpoint (default: `http://localhost:8080`). Set via `embeddingProxy.upstream` in Helm values. In the quickstart, points to the KServe predictor service `http://nemoretriever-embedding-ms-predictor:8080`
  - `PROXY_PORT` -- port the proxy listens on (default: `8080`). Set via `embeddingProxy.port` in Helm values
- **Config files:** None -- all behavior is in the ConfigMap-embedded `proxy.py`
- **Helm values:**
  - `embeddingProxy.enabled` -- boolean feature flag to deploy/skip the proxy
  - `embeddingProxy.port` -- proxy listen port (default `8080`)
  - `embeddingProxy.upstream` -- upstream vLLM endpoint URL
  - `embeddingProxy.image.repository` / `embeddingProxy.image.tag` -- container image (default `python:3.12-slim`)

## Known Gotchas

- **Stripping `input_type` loses query/passage distinction:** The proxy strips `input_type` (which tells NIM whether the input is a query or a passage), meaning the upstream vLLM model will not distinguish between query and passage embeddings. A code comment in the proxy notes: "If the upstream vLLM model requires this distinction, configure it at the vLLM serving level (e.g., via --chat-template or task-specific prompt prefixes)."
- **Sibling ranking-proxy uses a different translation pattern:** The rag-server chart also includes a `ranking-proxy` that translates NIM `/v1/ranking` requests to vLLM `/v1/rerank` format. Unlike the embedding proxy (which only strips fields), the ranking proxy restructures the entire request/response body (`query.text` to `query`, `passages[].text` to `documents[]`, and response `results[].relevance_score` to `rankings[].logit`).
- **Rag-server points to the proxy, not the model directly:** The rag-server's `APP_EMBEDDINGS_SERVERURL` is set to `http://rag-server-embedding-proxy:8080/v1` (the proxy), while the ingest chart's `APP_EMBEDDINGS_SERVERURL` points directly to `nemoretriever-embedding-ms-predictor:8080/v1` (the model). This difference exists because the ingest chart does not send NIM-specific fields.
- **ThreadingHTTPServer for concurrency:** The proxy uses Python's `ThreadingHTTPServer` (not asyncio) for concurrent request handling. This is adequate for a translation proxy with minimal CPU work but means each concurrent request occupies a thread.
- **Resource limits are intentionally small:** The proxy deployment sets `cpu: 500m / memory: 128Mi` limits and `cpu: 100m / memory: 64Mi` requests, reflecting that it performs only JSON field filtering with no model loading or heavy computation.

## Testing Notes

- Liveness probe: `GET /health` on the proxy port (initialDelaySeconds: 5, periodSeconds: 10)
- Readiness probe: `GET /health` on the proxy port (initialDelaySeconds: 3, periodSeconds: 5)
- Verify the proxy is running: `curl http://rag-server-embedding-proxy:8080/health` should return `{"status": "ok"}`
- Verify upstream connectivity: `curl http://rag-server-embedding-proxy:8080/v1/models` should return the model list from the upstream vLLM endpoint
- Test field stripping: send a request with `input_type` and `truncate` fields and verify they are not forwarded upstream (check proxy logs for "Stripped NIM-specific fields" info message)

## Related Patterns

- Sibling component: ranking-proxy (same ConfigMap-injected pattern, translates NIM ranking to vLLM rerank)
- Upstream: KServe InferenceService for the embedding model (`nemoretriever-embedding-ms`) served via vLLM
- Consumer: rag-server application reads `APP_EMBEDDINGS_SERVERURL` pointing to the proxy service
