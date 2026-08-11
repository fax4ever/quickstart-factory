---
name: rag-server
description: NVIDIA RAG orchestration server with NIM-to-vLLM translation proxies for embedding and reranking
summary: "NVIDIA's pre-built RAG orchestration container (rag-server:2.4.0, pulled via ngc-api image pull secret) connects LLM, embedding, reranking models and Milvus vector database for retrieval-augmented generation, with two Python sidecar translation proxies that convert NIM API format to vLLM-compatible endpoints on KServe/RHOAI, eliminating dedicated NIM containers. Use when deploying NVIDIA RAG blueprint architecture on RHOAI with vLLM-served models; all customization is via 50+ environment variables and Helm values with __RELEASE_NAME__/__RELEASE_NAMESPACE__ replacement for cross-chart service discovery, prompt templates mounted from the ingest chart's ConfigMap, and optional ODF/S3 for multimodal content. The embedding proxy strips NIM-specific fields (input_type, truncate, dimensions) while the ranking proxy converts between NIM /v1/ranking (query object + passages) and vLLM /v1/rerank (query string + documents) formats; uvicorn runs 8 workers on port 8081 with 8Gi/16Gi memory requests (CPU-only), Redis tracks summary status, and Prometheus metrics on emptyDir are ephemeral. Cross-chart ConfigMap dependency on ingest chart's ingestor-server-prompt causes pod crash loops if ingest chart is not deployed first; GPU_CAGRA index type requires GPU-enabled Milvus; hardcoded KServe predictor service names (nim-llm-predictor, nemoretriever-embedding-ms-predictor) must match model-serving chart; stripping input_type may degrade asymmetric embedding retrieval quality."
metadata:
  type: component
tags:
  tech_stack: [python, uvicorn, fastapi, helm]
  ai_pattern: [rag, embeddings, vector-search, reranking, multimodal]
  platform: [vllm, rhoai, openshift, kserve, nvidia-nim]
  data_layer: [milvus]
source_examples:
  - quickstart: "aml-rag-nvidia"
    repo: "https://github.com/rh-ai-quickstart/aml-rag-nvidia"
    notes: "NVIDIA RAG blueprint server with embedding/ranking translation proxies for vLLM on RHOAI"
    approach: "A"
---

# RAG Server

## Overview

The rag-server component is the NVIDIA RAG orchestration server (`nvcr.io/nvidia/blueprint/rag-server`) that handles the query/answer pipeline in a RAG architecture. It connects an LLM, embedding model, reranking model, and vector database to process user queries with retrieval-augmented generation. In the aml-rag-nvidia quickstart, it ships as a Helm subchart with two sidecar translation proxies that adapt NVIDIA NIM API formats to vLLM-compatible endpoints, enabling the use of vLLM-served models through KServe on RHOAI instead of requiring dedicated NIM containers.

## Tech Stack & Dependencies

- **Runtime:** Python (uvicorn ASGI server), NVIDIA RAG server application (`nvidia_rag.rag_server.server:app`)
- **Container image:** `nvcr.io/nvidia/blueprint/rag-server:2.4.0` (pre-built NVIDIA image from NGC)
- **Key dependencies:**
  - LLM endpoint (vLLM via KServe `nim-llm-predictor:8080`)
  - Embedding model endpoint (via translation proxy to vLLM `nemoretriever-embedding-ms-predictor:8080`)
  - Reranking model endpoint (via translation proxy to vLLM `nemoretriever-ranking-ms-predictor:8080`)
  - Milvus vector database (`milvus:19530`)
  - Redis (for summary status tracking, `ingest-redis-master:6379`)
  - S3-compatible object storage (MinIO/ODF for multimodal content)
  - Prompt ConfigMap from ingest chart (`ingestor-server-prompt`)
- **Helm subchart:** `charts/rag-server` (standalone, v0.1.0)
- **Image pull secret:** `ngc-api` (NGC registry authentication)

## Key Patterns

### Pre-built NVIDIA Container with Helm-only Customization

The rag-server uses a pre-built NVIDIA container image with no custom application code in the repo. All customization is done through environment variables and Helm values. The deployment command explicitly invokes uvicorn:

```yaml
# charts/rag-server/templates/deployment.yaml
command:
  - "uvicorn"
  - "nvidia_rag.rag_server.server:app"
  - "--port"
  - "8081"
  - "--host"
  - "0.0.0.0"
  - "--workers"
  - "{{ .Values.server.workers }}"
```

### NIM-to-vLLM Embedding Translation Proxy

A lightweight Python sidecar proxy strips NIM-specific fields (`input_type`, `truncate`, `dimensions`) from embedding requests so vLLM can accept them. This enables the NVIDIA RAG server (which expects NIM API format) to work with vLLM-served embedding models on KServe:

```python
# charts/rag-server/templates/embedding-proxy-configmap.yaml (inline Python)
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

The proxy runs as a separate Deployment using `python:3.12-slim` with the script mounted from a ConfigMap. The rag-server points its embedding URL at the proxy (`http://rag-server-embedding-proxy:8080/v1`), which forwards to the actual vLLM endpoint.

### NIM-to-vLLM Ranking Translation Proxy

A second sidecar proxy converts between NIM `/v1/ranking` format (query object + passages array) and vLLM `/v1/rerank` format (query string + documents array), translating both request and response:

```python
# charts/rag-server/templates/ranking-proxy-configmap.yaml (inline Python)
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

def translate_vllm_to_nim(vllm_body: dict) -> dict:
    """Translate a vLLM /v1/rerank response to a NIM /v1/ranking response."""
    results = vllm_body.get("results", [])
    rankings = [
        {"index": r["index"], "logit": r["relevance_score"]}
        for r in results
    ]
    return {"rankings": rankings}
```

### Cross-Chart ConfigMap Dependency for Prompts

The rag-server mounts a prompt configuration file (`/prompt.yaml`) from a ConfigMap created by the ingest chart. This couples the rag-server and ingest chart at the Kubernetes resource level:

```yaml
# charts/rag-server/templates/deployment.yaml
volumes:
  - name: prompt-config
    configMap:
      name: ingestor-server-prompt  # Reference ConfigMap from ingest chart
```

The prompt ConfigMap contains system/human prompt templates for chat, RAG, query rewriting, reflection, and other behaviors. It is mounted read-only and referenced via `PROMPT_CONFIG_FILE: "/prompt.yaml"`.

### Dynamic Environment Variable Injection

All environment variables are iterated from `values.yaml` with release-aware string replacement for cross-chart service discovery:

```yaml
# charts/rag-server/templates/deployment.yaml
env:
{{- range $key, $value := .Values.envVars }}
- name: {{ $key }}
  value: "{{ $value | replace "__RELEASE_NAME__" $.Release.Name | replace "__RELEASE_NAMESPACE__" $.Release.Namespace }}"
{{- end }}
```

### Optional ODF Object Storage Integration

The chart supports injecting OBC (ObjectBucketClaim) secrets and configmaps for S3/MinIO access via the `extraEnvFrom` field, with `MINIO_SECURE: "True"` set by default:

```yaml
# charts/rag-server/values.yaml
extraEnvFrom: []
  # - secretRef:
  #     name: default-bucket
  # - configMapRef:
  #     name: default-bucket
```

## Configuration

- **Environment variables:** Over 50 env vars control LLM, embedding, reranking, vector DB, feature flags, and observability. Key groups:
  - `APP_LLM_*` -- LLM model name and vLLM server URL (e.g., `nvidia/Llama-3_3-Nemotron-Super-49B-v1_5-FP8`)
  - `APP_EMBEDDINGS_*` -- Embedding model name, URL (points to translation proxy), dimensions (`2048`)
  - `APP_RANKING_*` -- Reranking model name and URL (points to translation proxy)
  - `APP_VECTORSTORE_*` -- Milvus connection, index type (`GPU_CAGRA`), search type (`dense` or `hybrid`)
  - `APP_TRACING_*` -- OpenTelemetry endpoints for observability
  - `ENABLE_*` -- Feature flags for reranker, guardrails, citations, reflection, query decomposition, VLM inference
  - `NGC_API_KEY` / `NVIDIA_API_KEY` -- Injected from the image pull secret
- **Config files:** `/prompt.yaml` (mounted from ingest chart ConfigMap)
- **Helm values:** Key overrides include `server.workers` (default 8), `image.tag`, `embeddingProxy.enabled`, `rankingProxy.enabled`, `promptConfig.enabled`, `extraEnvFrom`

## Known Gotchas

- **Cross-chart ConfigMap dependency:** The rag-server depends on the `ingestor-server-prompt` ConfigMap from the ingest chart. If the ingest chart is not deployed first (or the ConfigMap name changes), the rag-server pod will fail to start with a missing volume mount. The README states "Deploy order does not matter, the deployments will resolve," but this specific ConfigMap dependency means the rag-server pod will be in a crash loop until the ingest chart creates the ConfigMap.
- **Translation proxy strips `input_type`:** The embedding proxy strips the `input_type` field (query vs passage distinction) from NIM requests. As noted in the proxy code comment: "stripping input_type means the model will not distinguish between query and passage embeddings. If the upstream vLLM model requires this distinction, configure it at the vLLM serving level." This could affect retrieval quality with models that use asymmetric embeddings.
- **GPU_CAGRA index type requires GPU-enabled Milvus:** The default `APP_VECTORSTORE_INDEXTYPE: "GPU_CAGRA"` and `APP_VECTORSTORE_ENABLEGPUSEARCH: "True"` require Milvus to be deployed with GPU access. Without GPU-enabled Milvus, vector operations will fail.
- **Prometheus multiproc dir on emptyDir:** The `PROMETHEUS_MULTIPROC_DIR` points to `/tmp-data/prom_data` on an `emptyDir` volume. This means Prometheus metrics are ephemeral and lost on pod restart.
- **Hardcoded service names for upstream models:** Service URLs like `nim-llm-predictor:8080` and `nemoretriever-embedding-ms-predictor:8080` are hardcoded in `values.yaml` and must match the KServe predictor service names from the model-serving chart.
- **High memory requirements:** The rag-server requests 8Gi memory with a 16Gi limit, with 8 uvicorn workers configured by default. This is a CPU-only component (no GPU) but still resource-intensive.

## Testing Notes

- Health endpoint at `/v1/health` on port 8081 (used by both liveness and readiness probes)
- Readiness probe starts after 10 seconds with 15-second intervals; liveness starts after 30 seconds with 30-second intervals
- Both translation proxies have independent `/health` endpoints on port 8080
- Verify all three deployments are running: `rag-server`, `rag-server-embedding-proxy`, `rag-server-ranking-proxy`
- Test embedding proxy translation by sending a NIM-format request with `input_type` field and verifying it is stripped
- Test ranking proxy by sending NIM `/v1/ranking` format and verifying the response is in NIM format (with `logit` field)

## Related Patterns

- Milvus vector database configuration (data layer)
- KServe/vLLM model serving for LLM, embedding, and reranking models
- Ingest chart for document processing and prompt ConfigMap
- OpenTelemetry observability integration
