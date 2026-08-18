---
name: nim-to-vllm-translation-proxy-configmap
description: Inline Python translation proxies bridging NVIDIA NIM API format to vLLM via ConfigMap-mounted scripts
summary: "Deploys two inline Python HTTP proxies (embedding + ranking) as Kubernetes Deployments to translate NVIDIA NIM API format to vLLM format, solving incompatibility when the NVIDIA RAG server communicates with vLLM-served models instead of NIM endpoints. Use when vLLM serves embedding/ranking models but upstream consumers expect NIM-format APIs at /v1/embeddings and /v1/ranking — avoids custom container images by embedding proxy scripts in Helm ConfigMaps mounted via subPath into python:3.12-slim containers with only stdlib dependencies. Embedding proxy strips NIM-only fields (input_type, truncate, dimensions); ranking proxy translates NIM /v1/ranking (query.text, passages[].text) to vLLM /v1/rerank (query string, documents[] array) and reverse-maps relevance_score to logit; all resources in single deployment.yaml gated by .Values.embeddingProxy.enabled/.Values.rankingProxy.enabled with UPSTREAM_URL defaulting to KServe predictor services. RAG server envVars (e.g., APP_EMBEDDINGS_SERVERURL) must point to proxy services not directly to model endpoints; stripping input_type loses query vs passage embedding distinction; relevance_score-to-logit mapping is semantically different but functionally compatible; both proxies require upstream KServe InferenceService predictor endpoints to be running."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, python, vllm]
  ai_pattern: [embeddings, rag]
  platform: [openshift, kserve, vllm]
source_examples:
  - quickstart: "aml-rag-nvidia"
    repo: "https://github.com/rh-ai-quickstart/aml-rag-nvidia"
    notes: "Two translation proxies (embedding + ranking) deployed as separate Deployments with ConfigMap-mounted Python scripts"
    approach: "A"
---

# NIM-to-vLLM API Translation Proxy via ConfigMap

## Overview

This pattern deploys lightweight Python HTTP proxies as separate Kubernetes Deployments, each translating between NVIDIA NIM API format and vLLM API format. The proxy source code is embedded inline in Helm ConfigMaps and mounted into minimal `python:3.12-slim` containers. This avoids building custom container images while solving API incompatibility between the NVIDIA RAG server (which speaks NIM format) and vLLM model endpoints.

## Pattern Description

The NVIDIA RAG server expects NIM-compatible embedding and ranking APIs, but when models are served via vLLM (rather than NVIDIA NIMs), the request/response formats differ. Two proxies are deployed: an embedding proxy that strips NIM-specific fields (`input_type`, `truncate`, `dimensions`) from `/v1/embeddings` requests, and a ranking proxy that translates NIM `/v1/ranking` requests (with `query.text` and `passages[].text` format) to vLLM `/v1/rerank` requests (with `query` string and `documents[]` array format), plus reverse-translates the response.

## Implementation

### Embedding Proxy ConfigMap

The embedding proxy strips NIM-only fields that vLLM rejects:

```yaml
# charts/rag-server/templates/deployment.yaml (ConfigMap section)
data:
  proxy.py: |
    NIM_ONLY_FIELDS = {"input_type", "truncate", "dimensions"}

    def translate_nim_to_vllm(nim_body: dict) -> dict:
        """Strip NIM-specific fields that vLLM does not accept.
        Note: stripping input_type means the model will not distinguish
        between query and passage embeddings."""
        vllm_body = {k: v for k, v in nim_body.items()
                     if k not in NIM_ONLY_FIELDS}
        return vllm_body
```

### Ranking Proxy ConfigMap

The ranking proxy does a structural transformation between NIM and vLLM reranking formats:

```yaml
# charts/rag-server/templates/deployment.yaml (ranking proxy section)
data:
  proxy.py: |
    def translate_nim_to_vllm(nim_body: dict) -> dict:
        """Translate NIM /v1/ranking request to vLLM /v1/rerank."""
        vllm_body = {
            "query": nim_body["query"]["text"],
            "documents": [p["text"] for p in nim_body["passages"]],
            "top_n": len(nim_body["passages"]),
        }
        if "model" in nim_body:
            vllm_body["model"] = nim_body["model"]
        return vllm_body

    def translate_vllm_to_nim(vllm_body: dict) -> dict:
        """Translate vLLM /v1/rerank response to NIM /v1/ranking."""
        results = vllm_body.get("results", [])
        rankings = [
            {"index": r["index"], "logit": r["relevance_score"]}
            for r in results
        ]
        return {"rankings": rankings}
```

### Proxy Deployment Pattern

Each proxy runs as a separate Deployment with the ConfigMap script mounted as a volume:

```yaml
# charts/rag-server/templates/deployment.yaml (embedding proxy Deployment)
spec:
  containers:
  - name: embedding-proxy
    image: "{{ .Values.embeddingProxy.image.repository }}:{{ .Values.embeddingProxy.image.tag }}"
    command: ["python", "/app/proxy.py"]
    env:
    - name: UPSTREAM_URL
      value: "{{ .Values.embeddingProxy.upstream }}"
    - name: PROXY_PORT
      value: "{{ .Values.embeddingProxy.port }}"
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

### Values Configuration

```yaml
# charts/rag-server/values.yaml (excerpt)
embeddingProxy:
  enabled: true
  port: 8080
  upstream: "http://nemoretriever-embedding-ms-predictor:8080"
  image:
    repository: python
    tag: "3.12-slim"

rankingProxy:
  enabled: true
  port: 8080
  upstream: "http://nemoretriever-ranking-ms-predictor:8080"
  image:
    repository: python
    tag: "3.12-slim"
```

## Configuration

- **Key settings:** `embeddingProxy.upstream` and `rankingProxy.upstream` point to the KServe predictor services; both proxies default to port 8080
- **Defaults:** Both proxies enabled by default; use `python:3.12-slim` base image (no pip install needed -- pure stdlib `http.server` and `urllib`)
- **Dependencies:** The upstream KServe InferenceService predictor endpoints must be running; the RAG server `envVars` must point to the proxy services, not directly to the model endpoints (e.g., `APP_EMBEDDINGS_SERVERURL: "http://rag-server-embedding-proxy:8080/v1"`)

## Gotchas

- The proxy Python scripts use only stdlib (`http.server`, `urllib`, `json`) -- no third-party dependencies, which is why `python:3.12-slim` works without any `pip install`
- Stripping `input_type` from embedding requests means vLLM does not distinguish between query and passage embeddings; the inline comment notes this trade-off and suggests configuring distinction at the vLLM serving level if needed
- The ranking proxy translates `relevance_score` from vLLM to `logit` in the NIM response format -- these are semantically different (score vs logit) but the RAG server consumes them the same way
- All proxy resources (ConfigMap, Deployment, Service) are defined in the same `deployment.yaml` template file, gated by `.Values.embeddingProxy.enabled` and `.Values.rankingProxy.enabled` conditions

## Related Patterns

- `kserve-multi-model-mig-gpu-slicing.md` -- the model endpoints that these proxies translate requests for
