---
name: text-embeddings-inference
description: "HuggingFace TEI embedding service with pre-baked model, OpenAI-compatible API, deployed as Helm subchart"
summary: "Provides a high-performance Rust-based embedding service (HuggingFace TEI cpu-1.8) with an OpenAI-compatible /embeddings endpoint for RAG quickstarts, using nomic-embed-text-v1.5 pre-baked into the container image via huggingface_hub snapshot_download to HF_HOME=/data (Python installed then removed to reduce image size). Use as a Helm subchart (fullnameOverride: \"alm-embedding\") when you need a self-contained CPU embedding sidecar with no runtime model-registry dependency; the pre-baked image pattern trades larger image size for air-gapped deployment and deterministic startup. Consumer FastAPI services call http://alm-embedding:8080/embeddings using httpx.AsyncClient with connection pooling (max_keepalive=20, max_connections=100), batch at 30 (below MAX_CLIENT_BATCH_SIZE=32, MAX_BATCH_TOKENS=8192), apply nomic task prefixes (\"search_document:\"/\"search_query:\") by model-name detection, and handle both OpenAI and alternative TEI response formats for 768-dim vectors stored in FAISS. OOMKilled at 4Gi during warmup requires memory limits of 8Gi/requests 4Gi; CPU model loading takes 3-5 min requiring livenessProbe.initialDelaySeconds: 300, readinessProbe: 180, and compose start_period: 180s; port must be 8080 (not 80) for OpenShift restricted SCC; embedding dimension 768 is hardcoded in client rather than queried from the service."
metadata:
  type: component
tags:
  tech_stack: [huggingface-tei, python, httpx, faiss]
  ai_pattern: [embeddings, rag, vector-search]
  platform: [openshift, kubernetes]
  data_layer: [faiss]
source_examples:
  - quickstart: "ansible-log-analysis"
    repo: "https://github.com/rh-ai-quickstart/ansible-log-analysis"
    notes: "CPU-only TEI with nomic-embed-text-v1.5 pre-downloaded into image, Helm subchart deployment"
    approach: "A"
---

# Text Embeddings Inference (TEI)

## Overview

HuggingFace Text Embeddings Inference (TEI) provides a high-performance embedding service with an OpenAI-compatible API. In RHOAI quickstarts it runs as a standalone sidecar service that RAG components call over HTTP to generate vector embeddings. The model is pre-downloaded into the container image at build time, eliminating startup download delays and external network dependencies at runtime.

## Tech Stack & Dependencies

- **Runtime:** Rust-based TEI server (`text-embeddings-router`), v1.8
- **Container image:** `ghcr.io/huggingface/text-embeddings-inference:cpu-1.8` (base), custom image at `quay.io/rh-ai-quickstart/alm-rag:tei-rag-v1`
- **Key dependencies:** No runtime dependencies beyond the pre-baked model; consumer services use `httpx` (async) or `requests` (sync) to call the OpenAI-compatible `/embeddings` endpoint
- **Helm subchart:** Custom subchart under `deploy/helm/ansible-log-monitor/charts/text-embeddings-inference/` (appVersion 1.8)

## Key Patterns

### Pre-baked Model Image

The Dockerfile installs Python temporarily to download the model at build time, then removes Python to reduce image size. The model lands in `/data` where TEI's `HF_HOME` points.

```dockerfile
# From services/text-embeddings-inference/Dockerfile
FROM ghcr.io/huggingface/text-embeddings-inference:cpu-1.8

USER root
RUN apt-get update && apt-get install -y python3 python3-pip && \
    pip3 install --no-cache-dir --break-system-packages huggingface_hub && \
    rm -rf /var/lib/apt/lists/*

ENV HF_HOME=/data

RUN python3 -c "from huggingface_hub import snapshot_download; \
    snapshot_download('nomic-ai/nomic-embed-text-v1.5', \
                      cache_dir='/data')"

RUN apt-get remove -y python3 python3-pip && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/*

USER 1000
```

### OpenAI-Compatible API Consumption

Consumer services call the `/embeddings` endpoint using the OpenAI format. The client batches requests to stay within TEI's `MAX_CLIENT_BATCH_SIZE` limit.

```python
# From services/rag/src/rag/embed_and_index.py
url = self.api_url.rstrip("/") + "/embeddings"
BATCH_SIZE = 30  # TEI MAX_CLIENT_BATCH_SIZE is 32, use 30 to be safe

payload = {
    "model": self.model_name,
    "input": batch,
}
response = requests.post(url, json=payload, headers=headers, timeout=120)
result = response.json()
# OpenAI format: {"data": [{"embedding": [...]}, ...]}
if "data" in result:
    batch_embeddings = [item["embedding"] for item in result["data"]]
```

### Async HTTP Client with Connection Pooling

The RAG service's FastAPI backend initialises a persistent `httpx.AsyncClient` at startup for query-time embedding calls, keeping connections alive to avoid per-request TCP overhead.

```python
# From services/rag/main.py
embedding_client = httpx.AsyncClient(
    base_url=embedding_url,
    timeout=30.0,
    limits=httpx.Limits(
        max_keepalive_connections=20,
        max_connections=100,
        keepalive_expiry=30.0,
    ),
)
```

### Nomic Task Prefixes

The nomic-embed-text-v1.5 model uses task-specific prefixes to differentiate document indexing from query embedding. The code detects "nomic" in the model name and adds the appropriate prefix.

```python
# From services/rag/src/rag/embed_and_index.py
use_task_prefix = "nomic" in self.model_name.lower()
if use_task_prefix:
    prefixed_text = f"search_document: {composite_text}"
```

## Configuration

- **Environment variables:**
  - `MODEL_ID` -- model identifier for TEI (set to `nomic-ai/nomic-embed-text-v1.5`)
  - `HF_HOME` -- HuggingFace cache directory, must match where model was pre-downloaded (`/data`)
  - `PORT` -- listening port (default `8080`)
  - `MAX_CLIENT_BATCH_SIZE` -- maximum texts per request (set to `32`)
  - `MAX_BATCH_TOKENS` -- maximum tokens per batch (set to `8192`)
- **Consumer env vars:**
  - `EMBEDDINGS_LLM_URL` -- full URL to the TEI service (default `http://alm-embedding:8080`)
  - `RAG_MODEL_NAME` -- embedding model name (default `nomic-ai/nomic-embed-text-v1.5`)
  - `EMBEDDINGS_LLM_API_KEY` -- optional API key for remote/authenticated deployments
- **Helm values:** Key overrides in `values.yaml`:
  - `fullnameOverride: "alm-embedding"` -- sets the Kubernetes service name
  - `command: ["text-embeddings-router"]` -- explicit entrypoint
  - `service.port: 8080` -- avoids port 80 which requires root
- **Global wiring:** `global-values.yaml` sets `global.servicesNames.embedding: "alm-embedding"` and `global.rag.embedding.apiUrl: "http://alm-embedding:8080"`

## Known Gotchas

- **OOMKilled at 4Gi during warmup:** The values.yaml comment documents that the memory limit was increased from 4Gi to 8Gi because the model loading/warmup phase caused OOMKill at the lower limit. Requests are set to 4Gi, limits to 8Gi. (Source: `values.yaml` line 53 comment)
- **CPU model loading takes 3-5 minutes:** Probe delays are set very high -- `livenessProbe.initialDelaySeconds: 300`, `readinessProbe.initialDelaySeconds: 180` -- because TEI on CPU takes significantly longer to load than on GPU. The compose healthcheck uses `start_period: 180s` for the same reason. (Source: `values.yaml` lines 62-63, `compose.yaml` line 240)
- **Port 80 requires root:** The service port is explicitly set to 8080 instead of the default 80 to avoid needing root permissions on OpenShift's restricted SCC. (Source: `values.yaml` line 48 comment)
- **Batch size safety margin:** The client-side batch size (30) is intentionally lower than the server-side `MAX_CLIENT_BATCH_SIZE` (32) to avoid edge-case rejections. (Source: `embed_and_index.py` line 137 comment)
- **TEI response format varies:** The embedding client handles both OpenAI format (`{"data": [{"embedding": [...]}]}`) and an alternative format (`{"embeddings": [[...]]}`) because TEI versions may differ. (Source: `embed_and_index.py` lines 179-186)
- **Embedding dimension hardcoded to 768:** The `nomic-embed-text-v1.5` model produces 768-dimensional vectors; this is hardcoded in the client rather than queried from the service. (Source: `embed_and_index.py` lines 74-78, `index_loader.py` line 63)

## Testing Notes

- Health check endpoint: `curl http://alm-embedding:8080/health`
- Generate embeddings via OpenAI-compatible API: `curl -X POST http://alm-embedding:8080/embeddings -H "Content-Type: application/json" -d '{"model": "nomic-ai/nomic-embed-text-v1.5", "input": ["search_document: test"]}'` (Source: chart README)
- Allow 3-5 minutes for the service to become ready on CPU before testing
- Verify the embedding dimension matches 768 in the response

## Related Patterns

- `components/fastapi-backend.md` -- consumer pattern for embedding services
- `components/minio.md` -- FAISS index storage backend
- `components/pgvector.md` -- alternative vector storage
- `architectures/rag-pipeline.md` -- overall RAG architecture using TEI
