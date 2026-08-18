---
name: knowledge-layer
description: "Pluggable document ingestion and retrieval abstraction with swappable backends for NAT-based agent workflows"
summary: "The Knowledge Layer is a NAT plugin (knowledge_retrieval registered via pyproject.toml entry points) providing backend-agnostic document ingestion and semantic search through unified schemas (Chunk, RetrievalResult, FileInfo, CollectionInfo) with two swappable backends: LlamaIndex/ChromaDB for local dev and NVIDIA Foundational RAG Blueprint for production. Use llamaindex backend for local dev with in-process ChromaDB, optional multimodal PDF extraction (tables/charts/images via VLM), and AIQ_CHROMA_DIR persistence; use foundational_rag for production with dual-server architecture (query port 8081, ingestion port 8082) and server-side reranking with 10x VDB_TOP_K_MULTIPLIER — backend selection is type-safe via Pydantic Literal[\"llamaindex\", \"foundational_rag\"]. Backends self-register via @register_retriever/@register_ingestor decorators with lazy imports, session-based collection routing uses Context.conversation_id for per-session document isolation, parallel summary generation runs via ThreadPoolExecutor during ingestion, and TTL cleanup removes stale collections after AIQ_COLLECTION_TTL_HOURS (default 24h) on a configurable interval (AIQ_TTL_CLEANUP_INTERVAL_SECONDS default 3600s). Backend-specific config warnings log but never raise errors making misconfigurations easy to miss; Foundational RAG auto-derives ingestion port 8082 from query URL which breaks with non-standard ports; generate_summary: true without summary_model raises ValueError; SSL verification is globally suppressed via urllib3.disable_warnings() at import; completed jobs pruned after JOB_RETENTION_SECONDS=3600 so late polling returns \"not found\"."
metadata:
  type: component
tags:
  tech_stack: [python, llama-index, chromadb, pydantic, httpx, langchain]
  ai_pattern: [rag, embeddings, vector-search, multimodal, data-pipeline]
  platform: [nvidia-nim, nvidia-rag-blueprint]
  data_layer: [chromadb, milvus]
source_examples:
  - quickstart: "rh-research"
    repo: "https://github.com/rh-ai-quickstart/rh-research"
    notes: "NAT plugin providing backend-agnostic knowledge retrieval with LlamaIndex and Foundational RAG adapters"
    approach: "A"
---

# Knowledge Layer

## Overview

The Knowledge Layer is a pluggable document ingestion and retrieval abstraction for NeMo Agent Toolkit (NAT) workflows. It registers as a NAT function (`knowledge_retrieval`) and exposes semantic search over ingested documents to agents, with swappable backends (LlamaIndex/ChromaDB for local dev, NVIDIA RAG Blueprint for production). The component provides a unified schema (`Chunk`, `RetrievalResult`, `FileInfo`, `CollectionInfo`) so agent code and API routes remain backend-agnostic.

## Tech Stack & Dependencies

- **Runtime:** Python >=3.11,<3.14
- **Container image:** N/A (installed as a pip package within the main backend container)
- **Key dependencies:**
  - Core: `httpx`, `pydantic>=2.0`, `python-dotenv`
  - LlamaIndex backend: `llama-index>=0.10`, `llama-index-embeddings-nvidia`, `llama-index-vector-stores-chroma`, `chromadb>=0.4`, `pdfplumber`, `pypdfium2`, `openai>=1.0`, `docx2txt`
  - Foundational RAG backend: `requests`, `urllib3`, `docx2txt`, `python-pptx`
- **NAT integration:** Registered via `pyproject.toml` entry point `[project.entry-points."nat.plugins"]`

## Key Patterns

### Plugin Registration via Entry Points

The knowledge layer registers itself as a NAT plugin through `pyproject.toml` entry points, which triggers `@register_function` decorators on import.

```toml
# sources/knowledge_layer/pyproject.toml
[project.entry-points."nat.plugins"]
knowledge_layer = "knowledge_layer.register"
```

The `__init__.py` eagerly imports the register module to trigger decorator-based registration, with a graceful fallback when NAT is not installed:

```python
# sources/knowledge_layer/src/__init__.py
try:
    from .register import KnowledgeRetrievalConfig
    from .register import knowledge_retrieval
    __all__ = ["KnowledgeRetrievalConfig", "knowledge_retrieval"]
except ImportError:
    __all__ = []
```

### Backend Factory Pattern with Decorator Registration

Each backend adapter self-registers using `@register_retriever` and `@register_ingestor` decorators. The adapters are lazily imported in `_setup_backend()` only when the matching backend is selected, so unused backends do not need their dependencies installed.

```python
# sources/knowledge_layer/src/register.py
def _setup_backend(config: KnowledgeRetrievalConfig, summary_llm_obj=None):
    backend = config.backend.lower()
    if backend == "llamaindex":
        import knowledge_layer.llamaindex.adapter  # noqa: F401
        backend_config = {"persist_dir": config.chroma_dir, ...}
    elif backend == "foundational_rag":
        import knowledge_layer.foundational_rag.adapter  # noqa: F401
        backend_config = {"rag_url": config.rag_url, ...}
    os.environ["KNOWLEDGE_RETRIEVER_BACKEND"] = backend
    return backend, backend_config
```

### Type-Safe Backend Selection via Pydantic Literal

The `BackendType` is defined as a `Literal` type so Pydantic validates at config load time rather than failing deep in runtime code.

```python
# sources/knowledge_layer/src/register.py
BackendType = Literal["llamaindex", "foundational_rag"]

class KnowledgeRetrievalConfig(FunctionBaseConfig, name="knowledge_retrieval"):
    backend: BackendType = Field(default="llamaindex")
```

### Session-Based Collection Routing

The search function prefers a session-specific collection (from `Context.conversation_id`) over the config default, enabling per-browser-session document isolation in the web UI.

```python
# sources/knowledge_layer/src/register.py (inside search closure)
try:
    ctx = Context.get()
    session_collection = ctx.conversation_id if ctx else None
    target_collection = session_collection or collection
except Exception:
    target_collection = collection
```

### Multimodal PDF Extraction (LlamaIndex Backend)

The LlamaIndex adapter supports optional table, chart, and image extraction from PDFs. Images are classified and captioned in a single VLM call to minimize API usage.

```python
# sources/knowledge_layer/src/llamaindex/adapter.py
def _analyze_image_with_vlm(image_bytes, vlm_model, vlm_base_url, extract_charts=True):
    """Analyze an image using NVIDIA's VLM API - classify AND caption in ONE call."""
    # Single prompt handles both classification and captioning
    if extract_charts:
        prompt = """Analyze this image and respond in the following format:
TYPE: [chart/graph/image]
If this is a chart or graph, extract:
- Chart type (bar, line, pie, scatter, etc.)
- Title and axis labels ..."""
```

### Parallel Summary Generation During Ingestion

Both backends generate document summaries in parallel with the ingestion upload using `ThreadPoolExecutor`. Summaries are stored in a centralized, backend-agnostic registry for agent system prompts.

```python
# sources/knowledge_layer/src/foundational_rag/adapter.py
if self.generate_summary and file_path_obj.suffix.lower() in SUMMARIZABLE_EXTENSIONS:
    executor = ThreadPoolExecutor(max_workers=1)
    summary_future = executor.submit(_generate_file_summary, file_path, self.summary_llm)
# ... upload happens in parallel ...
summary = summary_future.result(timeout=15)
if summary:
    register_summary(collection_name, file_info.file_name, summary)
```

### TTL-Based Collection Cleanup

Both backends mix in `TTLCleanupMixin` to auto-delete stale collections. A background thread runs on a configurable interval (default: hourly) and removes collections inactive for a configurable TTL (default: 24 hours).

```python
# sources/knowledge_layer/src/llamaindex/adapter.py
COLLECTION_TTL_HOURS = float(os.environ.get("AIQ_COLLECTION_TTL_HOURS", "24"))
TTL_CLEANUP_INTERVAL_SECONDS = int(os.environ.get("AIQ_TTL_CLEANUP_INTERVAL_SECONDS", "3600"))

class LlamaIndexIngestor(TTLCleanupMixin, BaseIngestor):
    def __init__(self, config):
        super().__init__(config)
        self._start_ttl_cleanup_task(COLLECTION_TTL_HOURS, TTL_CLEANUP_INTERVAL_SECONDS)
```

### Foundational RAG Dual-Server Architecture

The Foundational RAG adapter communicates with two separate servers: a query server (port 8081) for search/retrieval and an ingestion server (port 8082) for document upload and collection management. The ingestor auto-derives the ingestion URL from the query URL if only one is provided.

```yaml
# configs/config_web_frag.yml
knowledge_search:
  _type: knowledge_retrieval
  backend: foundational_rag
  rag_url: ${RAG_SERVER_URL:-http://localhost:8081}
  ingest_url: ${RAG_INGEST_URL:-http://localhost:8082}
  timeout: 300
```

### Retrieval with Reranking (Foundational RAG)

The Foundational RAG retriever uses a VDB top-k multiplier to fetch more candidates from the vector database, then relies on the server-side reranker to select the final results.

```python
# sources/knowledge_layer/src/foundational_rag/adapter.py
VDB_TOP_K_MULTIPLIER = 10
MAX_VDB_TOP_K = 100

payload = {
    "query": query,
    "collection_names": [collection_name],
    "reranker_top_k": top_k,
    "vdb_top_k": min(top_k * VDB_TOP_K_MULTIPLIER, MAX_VDB_TOP_K),
    "enable_reranker": True,
}
```

## Configuration

- **Environment variables:**
  - `NVIDIA_API_KEY` -- Required for embeddings and VLM calls (all backends)
  - `RAG_SERVER_URL` -- Query server URL for Foundational RAG (default: `http://localhost:8081/v1`)
  - `RAG_INGEST_URL` -- Ingestion server URL for Foundational RAG (default: `http://localhost:8082/v1`)
  - `RAG_API_KEY` -- Optional API key for Foundational RAG authentication
  - `AIQ_CHROMA_DIR` -- ChromaDB persistence directory for LlamaIndex (default: `/tmp/chroma_data`)
  - `AIQ_EMBED_MODEL` -- NVIDIA embedding model (default: `nvidia/llama-nemotron-embed-vl-1b-v2`)
  - `AIQ_EMBED_BASE_URL` -- Embedding API base URL (default: `https://integrate.api.nvidia.com/v1`)
  - `AIQ_EXTRACT_TABLES` / `AIQ_EXTRACT_IMAGES` / `AIQ_EXTRACT_CHARTS` -- Multimodal extraction flags (LlamaIndex only, default: `false`)
  - `AIQ_VLM_MODEL` -- VLM for image captioning (default: `nvidia/nemotron-nano-12b-v2-vl`)
  - `AIQ_COLLECTION_TTL_HOURS` -- Hours before stale collections are deleted (default: `24`)
  - `AIQ_TTL_CLEANUP_INTERVAL_SECONDS` -- Seconds between cleanup runs (default: `3600`)
  - `AIQ_SUMMARY_DB` -- Summary database URL, supports SQLite or PostgreSQL (default: `sqlite+aiosqlite:///./summaries.db`)
  - `AIQ_RETRIEVER_TOP_K` -- Default number of retrieval results (default: `10`)
- **Config files:** NAT workflow YAML (`configs/config_web_default_llamaindex.yml`, `configs/config_web_frag.yml`) under the `functions:` section with `_type: knowledge_retrieval`
- **Key YAML config options:** `backend`, `collection_name`, `top_k`, `generate_summary`, `summary_model`, `summary_db`, `chroma_dir`, `rag_url`, `ingest_url`, `timeout`, `verify_ssl`

## Known Gotchas

- **Backend-specific config warnings:** The `KnowledgeRetrievalConfig` Pydantic validator (`validate_backend_config`) logs warnings when config options for the wrong backend are set (e.g., `rag_url` with `llamaindex`), but does not raise errors -- easy to miss misconfigurations in logs.
- **Temp file prefix stripping:** Both adapters strip a `tmp[8 random chars]_` prefix from document names for display. If the raw name is needed (e.g., for delete operations), use `document_name_raw` from chunk metadata.
- **Foundational RAG port auto-derivation:** If only `rag_url` (port 8081) is provided, the ingestor automatically switches to port 8082 for ingestion. This can be surprising if both servers are on non-standard ports.
- **Summary generation requires explicit LLM config:** Setting `generate_summary: true` without `summary_model` raises a `ValueError` at config validation time. There is no default fallback LLM.
- **ChromaDB telemetry disabled explicitly:** Both ingestor and retriever pass `Settings(anonymized_telemetry=False)` when creating the ChromaDB client to reduce file descriptor usage.
- **SSL verification disabled warning:** The Foundational RAG adapter globally suppresses `InsecureRequestWarning` via `urllib3.disable_warnings()` at module import time (line 82 of `foundational_rag/adapter.py`), which affects the entire process.
- **Completed job pruning:** The Foundational RAG ingestor retains completed/failed jobs in memory for 1 hour (`JOB_RETENTION_SECONDS = 3600`), then prunes them. If polling for status after that window, the job will appear as "not found".

## Testing Notes

- Verify backend registration: `python -c "from aiq_agent.knowledge.factory import list_retrievers, list_ingestors; print(list_retrievers()); print(list_ingestors())"`
- Install the desired backend with optional deps: `uv pip install -e "sources/knowledge_layer[llamaindex]"` or `[foundational_rag]`
- The LlamaIndex backend health check always returns `True` (in-process), while the Foundational RAG backend checks the `/health` endpoint
- Test multimodal extraction by setting `AIQ_EXTRACT_TABLES=true` and ingesting a PDF with tables -- check logs for `Table extraction: N tables`
- Session collection routing can be tested by setting a `Context.conversation_id` and verifying the search targets that collection

## Related Patterns

- Base classes and schemas: `src/aiq_agent/knowledge/base.py`, `src/aiq_agent/knowledge/schema.py`, `src/aiq_agent/knowledge/factory.py`
- Summary registry: `aiq_agent.knowledge.register_summary`, `unregister_summary`, `get_available_documents`
- NVIDIA RAG Blueprint: external dependency for `foundational_rag` backend
