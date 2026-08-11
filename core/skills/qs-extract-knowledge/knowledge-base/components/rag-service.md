---
name: rag-service
description: Custom FastAPI RAG query service with FAISS similarity search, MinIO index storage, and TEI embeddings
summary: "Custom FastAPI RAG microservice providing FAISS IndexFlatIP cosine-similarity search over a MinIO-stored vector index with TEI embedding generation, using a two-image architecture (heavier init image with pypdf/langchain-community for PDF parsing and index building, lighter query image with httpx/faiss-cpu) deployed as Helm subchart charts/rag. Use when building a fully custom RAG pipeline with control over ingestion, embedding, and retrieval rather than pre-built containers like NVIDIA rag-server — key differentiators are MinIO-based index lifecycle via LATEST.json pointer (BUILDING/READY/FAILED states, three artifacts: index.faiss, metadata.pkl, LATEST.json) and dual startup modes (local 20s background polling vs Kubernetes initContainer that waits for the init Job). TEI embedding client batches at 30 requests (TEI MAX_CLIENT_BATCH_SIZE=32), applies Nomic search_document:/search_query: task prefixes, builds composite embeddings from title+description+symptoms with L2 normalization via numpy, and serves queries through httpx.AsyncClient with connection pooling (20 keepalive, 100 max connections); key env vars are MINIO_ENDPOINT, EMBEDDINGS_LLM_URL, RAG_BUCKET_NAME, and RAG_FORCE_REBUILD. FAISS read_index requires temp file download from MinIO (no byte stream support), embedding_dim is hardcoded to 768 for nomic-embed-text-v1.5 in both EmbeddingsConfig and EmbeddingClient, the init job skips rebuild if an existing READY index is found unless RAG_FORCE_REBUILD=true, MinIO clients use secure=False (HTTP only for cluster-internal), and the initContainer name is coupled to the backend release name via {{ .Release.Name }}-backend-rag-init."
metadata:
  type: component
tags:
  tech_stack: [fastapi, python, faiss, numpy, httpx, minio, pydantic, uvicorn]
  ai_pattern: [rag, embeddings, vector-search]
  platform: [openshift, kubernetes]
  data_layer: [faiss, minio]
source_examples:
  - quickstart: "ansible-log-analysis"
    repo: "https://github.com/rh-ai-quickstart/ansible-log-analysis"
    notes: "Custom RAG service for Ansible error retrieval with FAISS index loaded from MinIO and TEI-based query embeddings"
    approach: "A"
---

# RAG Service

## Overview

The rag-service is a custom-built FastAPI microservice that provides similarity search over a FAISS vector index stored in MinIO. Unlike pre-built RAG containers (such as NVIDIA rag-server), this component is fully custom application code with its own ingestion pipeline, embedding client, and query pipeline. In the ansible-log-analysis quickstart, it searches Ansible error knowledge bases parsed from PDFs, returning ranked error entries with resolution steps. It uses TEI (text-embeddings-inference) for query embedding generation and a LATEST.json pointer file in MinIO for index lifecycle management.

## Tech Stack & Dependencies

- **Runtime:** Python >=3.12, FastAPI, uvicorn
- **Container image:** `quay.io/rh-ai-quickstart/alm-rag:latest` (main service), `quay.io/rh-ai-quickstart/alm-rag:init` (init job with lighter dependencies)
- **Key dependencies:**
  - `faiss-cpu` -- in-memory vector similarity search (IndexFlatIP for inner product)
  - `httpx` -- async HTTP client with connection pooling for TEI calls
  - `minio` -- MinIO client for index artifact storage
  - `numpy` -- embedding array operations and L2 normalization
  - `pydantic` -- request/response validation
  - `langchain-core` / `langchain-community` -- Document model and PDF loading (init job only)
  - `pypdf` -- PDF parsing (init job only)
- **Helm subchart:** `charts/rag` (standalone, v0.1.0)

## Key Patterns

### Two-Image Architecture: Init Job and Query Service

The RAG service uses two separate container images from the same codebase. The init image (`alm-rag:init`) has heavier dependencies (pypdf, langchain-community) for PDF parsing and index building, while the main image (`alm-rag:latest`) has only query-time dependencies. This is driven by two separate `pyproject.toml` files:

```toml
# pyproject.rag-init.toml (init job -- heavier)
dependencies = [
    "pypdf==6.1.3",
    "langchain-community>=0.3.27",
    "langchain-core>=0.3.27",
    "faiss-cpu>=1.7.4",
    "minio>=7.2.17",
]
```

```toml
# pyproject.toml (query service -- lighter)
dependencies = [
    "fastapi>=0.116.1",
    "uvicorn>=0.37.0",
    "httpx>=0.27.2",
    "faiss-cpu>=1.7.4",
    "minio>=7.2.17",
]
```

### MinIO Index Lifecycle with LATEST.json Pointer

The index lifecycle is managed through a `LATEST.json` pointer file in MinIO that tracks build status. The init job sets status through `BUILDING -> READY` (or `FAILED`), and the query service and initContainer both check this pointer before loading:

```python
# services/rag/src/rag/embed_and_index.py
pointer = {
    "status": "BUILDING",
    "error_message": None,
    "build_id": build_id,
    "build_ts": build_ts,
}
# ... after successful upload ...
pointer = {
    "status": "READY",
    "total_errors": len(self.error_store),
    "model_name": self.model_name,
    "embedding_dim": self.embedding_dim,
    "build_id": build_id,
    "build_ts": build_ts,
}
```

Three artifacts are stored in MinIO under a fixed bucket (`rag-index`): `index.faiss`, `metadata.pkl`, and `LATEST.json`.

### Dual Startup Strategy: Local Polling vs Kubernetes InitContainer

The service supports two startup modes. For local development, it uses graceful startup with background polling every 20 seconds. For Kubernetes, an initContainer waits for the index to be ready before the main container starts:

```python
# services/rag/main.py -- background polling for local dev
async def poll_for_index():
    poll_interval = 20  # seconds
    while True:
        if index_loader is not None and index_loader.index is not None:
            # Check for rebuilds via LATEST.json build_id
            force_rebuild = os.getenv("RAG_FORCE_REBUILD", "false").lower() == "true"
            if force_rebuild:
                # ... check for new build_id and reload ...
            await asyncio.sleep(poll_interval)
            continue
        success = await load_index()
        await asyncio.sleep(poll_interval)
```

The Kubernetes initContainer runs an inline Python script that first waits for the init Job to complete (using `oc wait`/`kubectl wait`), then polls MinIO for `LATEST.json` with `status: "READY"`.

### TEI Embedding Client with Batching

The embedding client calls TEI (text-embeddings-inference) using the OpenAI-compatible `/embeddings` endpoint. It batches requests to respect TEI's `MAX_CLIENT_BATCH_SIZE` limit and handles both response formats (`data[].embedding` and `embeddings[]`):

```python
# services/rag/src/rag/embed_and_index.py
BATCH_SIZE = 30  # TEI MAX_CLIENT_BATCH_SIZE is 32, use 30 to be safe

for i in range(0, len(texts), BATCH_SIZE):
    batch = texts[i : i + BATCH_SIZE]
    payload = {"model": self.model_name, "input": batch}
    response = requests.post(url, json=payload, headers=headers, timeout=120)
    result = response.json()
    if "data" in result:
        batch_embeddings = [item["embedding"] for item in result["data"]]
    elif "embeddings" in result:
        batch_embeddings = result["embeddings"]
```

### Nomic Task Prefix Convention

The service uses Nomic-specific task prefixes to differentiate document and query embeddings. Documents are prefixed with `search_document:` during indexing, and queries with `search_query:` at query time:

```python
# services/rag/src/rag/embed_and_index.py -- indexing
if use_task_prefix:
    prefixed_text = f"search_document: {composite_text}"

# services/rag/main.py -- querying
query_text = f"search_query: {request.query}"
```

### Composite Embedding from Title + Description + Symptoms

Rather than embedding raw document chunks, the system creates composite texts by concatenating the error title, description, and symptoms fields. This produces a single embedding per error that captures the key identifying information:

```python
# services/rag/src/rag/embed_and_index.py
composite_parts = []
if title:
    composite_parts.append(title)
if description:
    composite_parts.append(description)
if symptoms:
    composite_parts.append(symptoms)
composite_text = "\n\n".join(composite_parts)
```

### Async Index Loading via Thread Pool

FAISS requires file paths for index loading, so the loader downloads artifacts from MinIO to temp files, then loads them. The blocking I/O is offloaded to a thread pool to avoid blocking the FastAPI event loop:

```python
# services/rag/index_loader.py
async def load_index(self):
    if self._loaded and self.index is not None:
        return self.index, self.error_store, self.index_to_error_id
    return await asyncio.to_thread(self._load_index_sync)
```

The temp directory is cleaned up in a `finally` block after loading completes.

### Connection-Pooled HTTP Client for Embedding Service

The query-time embedding calls use a persistent `httpx.AsyncClient` with connection pooling, initialized at startup and closed on shutdown:

```python
# services/rag/main.py
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

## Configuration

- **Environment variables:**
  - `MINIO_ENDPOINT` / `MINIO_PORT` / `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` -- MinIO connection (all sourced from `minio` Secret in Helm)
  - `RAG_BUCKET_NAME` -- MinIO bucket for index artifacts (default: `rag-index`)
  - `EMBEDDINGS_LLM_URL` -- TEI service URL (default: `http://alm-embedding:8080`)
  - `RAG_MODEL_NAME` -- Embedding model name (default: `nomic-ai/nomic-embed-text-v1.5`)
  - `RAG_FORCE_REBUILD` -- Force index rebuild even if READY (default: `false`)
  - `RAG_ENABLED` -- Enable/disable RAG index building in init job (default: `true`)
  - `PORT` -- Service port (default: `8002`)
  - `LOG_LEVEL` / `LOG_FORMAT` -- Logging configuration (`pretty` or `json` format)
  - `DATA_DIR` / `KNOWLEDGE_BASE_DIR` -- Paths for init job data
- **Config files:** `src/utils/config.py` provides a global `config` singleton with `EmbeddingsConfig` (hardcoded model name, env-overridable API URL) and `StorageConfig` (data directory paths)
- **Helm values:** Key overrides include `rag.bucketName`, `rag.maxWait` (initContainer timeout, default 300s), `rag.forceRebuild`, `rag.initImage` (separate image for init job), `rag.dataDir`, `rag.knowledgeBaseDir`, resource requests/limits

## Known Gotchas

- **FAISS requires temp files for MinIO loading:** FAISS `read_index` only accepts file paths, not byte streams. The `RAGIndexLoader` must download `index.faiss` from MinIO to a temp file before loading it. The temp directory is cleaned up in a `finally` block, but if the process crashes between download and cleanup, orphaned temp files may accumulate. This pattern is documented in `index_loader.py`: "Uses temp files for FAISS compatibility (FAISS prefers file paths)."
- **Embedding model hardcoded in config:** The model name `nomic-ai/nomic-embed-text-v1.5` is hardcoded in `src/utils/config.py` as `EmbeddingsConfig.MODEL_NAME`. While `RAG_MODEL_NAME` env var exists for the query service, the init pipeline config class ignores it, so model changes require updating both places.
- **Init job checks existing index before rebuilding:** The `rag_init_pipeline.py` skips index building if it finds an existing READY index in MinIO. To force a rebuild, set `RAG_FORCE_REBUILD=true` env var. This is intentional for faster Helm upgrades but can be confusing when knowledge base content changes.
- **Embedding dimension hardcoded to 768:** The `EmbeddingClient` in `embed_and_index.py` sets `self.embedding_dim = 768` regardless of model, with a comment noting this is the nomic-embed-text-v1.5 dimension. Switching embedding models requires updating this value.
- **MinIO client uses `secure=False`:** Both `minio.py` and `index_loader.py` create MinIO clients with `secure=False` (HTTP), as noted in comments: "Use HTTP for internal services" / "Use HTTP for internal OpenShift services." This is appropriate for cluster-internal communication but not for external MinIO endpoints.
- **initContainer references backend release name:** The Helm deployment initContainer constructs the init job name as `{{ .Release.Name }}-backend-rag-init`, coupling the rag subchart to the backend chart's naming convention. If the parent chart changes how it names the backend, the initContainer will wait for a non-existent job.

## Testing Notes

- `/health` endpoint returns service status even when index is not loaded (returns `unhealthy` with reason)
- `/ready` endpoint returns HTTP 503 until FAISS index is loaded, then 200 with index size
- Liveness probe configured with 60-second initial delay and 30-second period; readiness with 30-second initial delay and 10-second period
- `POST /rag/reload` endpoint allows reloading the index from MinIO without pod restart
- `tests/test_embeddings.py` verifies TEI embedding generation with task prefix comparison (requires running TEI service)
- `tests/test_queries.py` provides interactive and batch query testing modes (requires built index)

## Related Patterns

- MinIO for artifact storage (index.faiss, metadata.pkl, LATEST.json)
- TEI (text-embeddings-inference) for embedding generation
- FAISS IndexFlatIP for cosine similarity search on normalized vectors
- Kubernetes Job for init pipeline (PDF ingestion and index building)
- Helm subchart deployment with initContainer for startup ordering
