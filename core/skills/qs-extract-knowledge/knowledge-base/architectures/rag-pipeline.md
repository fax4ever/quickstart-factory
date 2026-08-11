---
name: rag-pipeline
description: RAG patterns from LlamaStack vector stores to NVIDIA Blueprints to standalone FAISS microservices to Helm-only dual-frontend deployments
summary: "Implements retrieval-augmented generation across seven approaches: (A) LlamaStack with external ingestion pipeline, pgvector vector stores, and transparent file_search retrieval via Responses API requiring no RAG-specific prompting; (B) NVIDIA RAG Blueprint with NV-Ingest document processing, GPU-accelerated Milvus GPU_CAGRA, vLLM on KServe with MIG-sliced GPUs, NIM-to-vLLM translation proxies for embedding/reranking, ODF ObjectBucketClaim for S3 storage, and optional query rewriting/reflection/decomposition with /no_think Nemotron directive; (C) standalone FAISS microservice with TEI nomic-embed-text-v1.5 (search_document:/search_query: prefixes), MinIO LATEST.json pointer file for init-job-to-service coordination, and results consumed as agent-internal context enrichment from static PDFs; (D) frontend-only Streamlit using LlamaStack rag_tool APIs with manual CONTEXT: prompt injection, direct pgvector access via asyncpg, all-MiniLM-L6-v2 at 384 dimensions, and triple-fallback vector DB registration; (E) startup-time ingestion of curated text files via LlamaStack OpenAI-compatible files.create/vector_stores.files.create with per-agent knowledge_bases YAML config, explicit extra_body={\"provider_id\": \"pgvector\"}, and transparent file_search retrieval identical to Approach A; (F) dual-mode Streamlit frontend with Direct mode (vector_stores.search + manual context injection) and Agent-based mode (Responses API file_search), Docling-based ingestion service (DocumentConverter + HybridChunker filtering TEXT/PARAGRAPH labels) with multi-source support (GitHub/S3/URL), Kubeflow Pipelines for automated ingestion, OpenAI-compatible Files API for document management, frontend-integrated input/output shields via safety.run_shield, file citation stripping for four marker formats, reasoning_content support for R1-style models, suggested questions via ConfigMap, and Podman Compose local dev with host Ollama; (G) Helm-only dual-frontend RAG with AnythingLLM (LanceDB + native embeddings + LocalAI provider) and LlamaStackDistribution CR (inline Milvus SQLite-backed + sentence-transformers granite-embedding-125m-english at 768 dimensions + remote::vllm), Kubernetes Job seeding from web URLs with HTML stripping (script/style/nav/header/footer/aside removal), admin username auto-discovery via Kubernetes RoleBindings for SHA-256-hashed vector store naming matching RHOAI Playground convention, SQLite sidecar for AnythingLLM API key injection, zero custom code, and CPU-only inference. Choose A for custom FastAPI backends needing LlamaStack-integrated transparent retrieval; B for no-custom-code GPU-heavy deployments with pre-built NVIDIA RAG server and built-in multimodal/reranking capabilities; C for agent-pipeline context enrichment from curated PDF knowledge bases with minimal GPU requirements (TEI only); D for minimal-complexity frontend-only demos where RAG is a supporting feature alongside other capabilities like guardrails; E for curated text knowledge bases bundled with the application or ConfigMap-mounted, requiring automatic startup ingestion and per-agent knowledge base assignment without user-facing document management; F for self-contained RAG chatbots needing automated multi-source ingestion (GitHub/S3/URL), dual retrieval modes (Direct control vs Agent-based transparency), standard OpenAI-compatible document management without direct database access, and optional local development support; G for zero-custom-code CPU-only deployments needing two independent UIs (AnythingLLM workbench for daily use + RHOAI Playground for exploration) with deploy-time document seeding from web URLs and no GPU requirements. Critical config: A requires update_vector_store_ids() to sync dual metadata (PostgreSQL + LlamaStack); B needs cross-chart ConfigMap (ingestor-server-prompt) installed before rag-server, anyuid SCC for three service accounts, and NV-Ingest MESSAGE_CLIENT_HOST hardcoded to ingest-redis-master; C requires TEI connection pooling and FAISS index files on disk (faiss.read_index needs file paths not buffers); D hardcodes embedding dimension 384 and uses direct pgvector queries with vs_{id.replace('-','_')} table naming; E requires extra_body={\"provider_id\": \"pgvector\"} for LlamaStack 0.3.3+ vector store creation and creates new UUID-suffixed vector stores each restart; F uses legacy vector_dbs.register() in ingestion service but vector_stores.create() in UI, Docling HybridChunker discards tables/images, and vector_stores.search response format varies across LlamaStack versions (data/chunks/results fallback); G's rag-seed Job uses llama-stack-client SDK with SHA-256-hashed admin username for vector store naming matching RHOAI Playground auto-provisioning, inline Milvus stores data in SQLite at pod-local path requiring PVC for persistence, and AnythingLLM uses native embedding engine separate from vLLM inference endpoint. Common gotchas: A's dual metadata can desync if update_vector_store_ids fails and RAG only works with LlamaStack runner (not LangGraph/CrewAI); B depends on NVIDIA cloud NIMs for OCR/table/graphic detection (external network dependency) and embedding proxy strips input_type losing query-vs-passage distinction; C's FAISS index must fit entirely in RAM and RAGHandler singleton silently returns empty strings if RAG is disabled; D bypasses LlamaStack for document management via direct pgvector access that breaks if LlamaStack changes its internal schema; E accumulates stale vector stores across restarts (_get_vector_store_id selects latest by created_at) and only supports .txt files (no PDF/DOCX); F's search_vector_stores_fallback() must explicitly re-search after streaming because Responses API stream doesn't consistently include file_search results, file citation stripping handles partial markers during streaming to prevent UI flicker, and ingestion service uses rag_tool.insert (pre-chunked via Docling) while UI uses files.create (server-side chunking via LlamaStack pypdf provider); G's inline Milvus (SQLite-backed) loses all indexed documents on pod restart without a PVC, the RHOAI Playground auto-provisioning vector store hash must match the seed Job's naming convention, and AnythingLLM's hardcoded API key (sk-automation-workspace-setup) is injected via SQLite sidecar that runs indefinitely."
metadata:
  type: architecture
tags:
  tech_stack: [fastapi, llamastack, python, vllm, nvidia-rag-blueprint, langchain, langgraph, gradio, streamlit, cloudevents, docling, deepeval, anythingllm]
  ai_pattern: [rag, embeddings, vector-search, reranking, multimodal, evaluation]
  platform: [llamastack, rhoai, openshift, kubernetes, kserve, vllm, tei, ollama, kubeflow-pipelines]
  data_layer: [pgvector, milvus, faiss, minio, lancedb]
source_examples:
  - quickstart: "ai-virtual-agent"
    repo: "https://github.com/rh-ai-quickstart/ai-virtual-agent"
    notes: "RAG via LlamaStack vector stores with external ingestion pipeline API and file_search tool integration into agent responses"
    approach: "A"
  - quickstart: "aml-rag-nvidia"
    repo: "https://github.com/rh-ai-quickstart/aml-rag-nvidia"
    notes: "NVIDIA RAG Blueprint server with NV-Ingest document processing, GPU-accelerated Milvus, vLLM via KServe, and NIM-to-vLLM translation proxies -- no custom backend code"
    approach: "B"
  - quickstart: "ansible-log-analysis"
    repo: "https://github.com/rh-ai-quickstart/ansible-log-analysis"
    notes: "Standalone FAISS microservice with PDF knowledge base ingestion, MinIO index storage, TEI embeddings, and RAG used as context enrichment within an agent pipeline"
    approach: "C"
  - quickstart: "f5-ai-guardrails"
    repo: "https://github.com/rh-ai-quickstart/f5-ai-guardrails"
    notes: "Frontend-only Streamlit RAG using LlamaStack rag_tool APIs for retrieval and manual prompt context injection, with direct pgvector access for document management"
    approach: "D"
  - quickstart: "f5-api-security"
    repo: "https://github.com/rh-ai-quickstart/f5-api-security"
    notes: "Frontend-only Streamlit RAG using OpenAI-compatible vector_stores.search API (LlamaStack 0.6.1+) for retrieval, files.create/vector_stores.files.create for document ingestion, manual prompt context injection, direct pgvector access, and optional F5 XC endpoint routing for inference"
    approach: "D"
  - quickstart: "it-self-service-agent"
    repo: "https://github.com/rh-ai-quickstart/it-self-service-agent"
    notes: "Startup-time knowledge base ingestion via LlamaStack OpenAI-compatible vector_stores API with pgvector provider, file_search tool via Responses API, and per-agent knowledge_bases YAML config"
    approach: "E"
  - quickstart: "RAG"
    repo: "https://github.com/rh-ai-quickstart/RAG"
    notes: "Dual-mode Streamlit frontend with Direct mode (vector_stores.search + manual context injection) and Agent-based mode (Responses API file_search), Docling-based ingestion service with multi-source support (GitHub/S3/URL), Kubeflow Pipelines for automated ingestion, and OpenAI-compatible Files API for document management"
    approach: "F"
  - quickstart: "llm-cpu-serving"
    repo: "https://github.com/rh-ai-quickstart/llm-cpu-serving"
    notes: "Helm-only dual-frontend RAG with AnythingLLM (LanceDB + native embeddings + LocalAI provider) and Llama Stack Distribution CR (inline Milvus + sentence-transformers + remote::vllm), no custom code, document seeding via Kubernetes Jobs"
    approach: "G"
---

# RAG Pipeline

## Overview

This architecture implements retrieval-augmented generation by managing knowledge bases as LlamaStack vector stores, delegating document ingestion to an external pipeline service, and wiring retrieval into agent responses via the `file_search` tool type. The backend provides a CRUD API for knowledge bases that coordinates between a local PostgreSQL database (metadata tracking) and the LlamaStack server (vector store lifecycle), while an external ingestion pipeline handles document chunking, embedding, and indexing.

## Data Flow

1. Admin creates a knowledge base via `POST /api/v1/knowledge_bases/` with a name, embedding model, and data source configuration
2. The backend stores metadata in PostgreSQL and calls the external ingestion pipeline API to create a pipeline (`/add` endpoint)
3. The ingestion pipeline processes documents: chunking, embedding via the specified model, and indexing into a LlamaStack vector store backed by pgvector
4. When listing knowledge bases, the backend queries the ingestion pipeline for status (`/status` endpoint) and syncs `vector_store_id` from LlamaStack
5. A virtual agent is configured with `knowledge_base_ids` (vector store names) which are resolved to `vector_store_ids` (LlamaStack IDs)
6. At chat time, the LlamaStackRunner converts knowledge base associations into `file_search` tools with `vector_store_ids`
7. LlamaStack's Responses API handles retrieval internally -- embedding the query, searching the vector store, and injecting retrieved chunks into the LLM context

## Component Wiring

| From | To | Protocol | Purpose |
|------|----|----------|---------|
| React frontend | FastAPI backend | REST | Knowledge base CRUD operations |
| FastAPI backend | PostgreSQL | SQLAlchemy async | Knowledge base metadata persistence |
| FastAPI backend | Ingestion pipeline service | HTTP (httpx) | Create, delete, and check status of ingestion pipelines |
| FastAPI backend | LlamaStack server | HTTP (AsyncLlamaStackClient) | Vector store lifecycle (list, delete, sync IDs) |
| Ingestion pipeline | LlamaStack server | Internal | Document processing, embedding, vector store population |
| LlamaStackRunner | LlamaStack server | HTTP | file_search tool execution during Responses API calls |

## Key Integration Points

### Knowledge Base Creation with Pipeline

Creating a knowledge base involves two coordinated steps: persisting metadata locally and triggering the external ingestion pipeline.

```python
# backend/app/api/v1/knowledge_bases.py (lines 24-35)
async def create_knowledge_base_internal(
    kb: KnowledgeBaseCreate, db: AsyncSession
) -> KnowledgeBaseResponse:
    db_kb = await knowledge_bases.create(db, obj_in=kb)
    await create_ingestion_pipeline(kb)
    db_kb.status = await get_pipeline_status(db_kb.vector_store_name)
    return db_kb
```

### Ingestion Pipeline Integration

The backend communicates with an external ingestion pipeline service via HTTP. The pipeline URL defaults to the LlamaStack server's `/ingestion_pipeline/` path.

```python
# backend/app/api/v1/knowledge_bases.py (lines 154-161, 219-223)
async def create_ingestion_pipeline(kb: KnowledgeBaseCreate):
    add_pipeline = get_ingestion_pipeline_url() + "/add"
    data = kb.pipeline_model_dict()
    async with httpx.AsyncClient() as client:
        response = await client.post(add_pipeline, json=data)
        response.raise_for_status()

def get_ingestion_pipeline_url():
    try:
        return os.environ["INGESTION_PIPELINE_URL"]
    except KeyError:
        return "http://llamastack:8321/ingestion_pipeline/"
```

### Vector Store ID Synchronization

The backend synchronizes local knowledge base records with LlamaStack's vector store registry, mapping names to IDs so agents can reference the correct stores.

```python
# backend/app/api/v1/knowledge_bases.py (lines 174-199)
async def update_vector_store_ids(request: Request, db: AsyncSession):
    client = get_client_from_request(request)
    vector_stores = await client.vector_stores.list()
    vs_name_to_id = {vs.name: vs.id for vs in vector_stores.data}
    kbs = await knowledge_bases.get_multi(db)
    for kb in kbs:
        if kb.vector_store_name in vs_name_to_id:
            vs_id = vs_name_to_id[kb.vector_store_name]
            if kb.vector_store_id != vs_id:
                await knowledge_bases.update(
                    db, db_obj=kb, obj_in={"vector_store_id": vs_id}
                )
```

### RAG Tool Wiring into Responses API

At chat time, the runner converts the agent's vector store associations into OpenAI Responses API compatible `file_search` tools. The LlamaStack server handles the actual retrieval.

```python
# backend/app/services/runners/llamastack_runner.py (lines 408-465)
async def build_responses_tools(tools, vector_store_ids, request):
    responses_tools = []
    for tool_info in tools:
        tool_id = tool_info["toolgroup_id"]
        if tool_id == "builtin::rag":
            if vector_store_ids:
                responses_tools.append(
                    {"type": "file_search", "vector_store_ids": vector_store_ids}
                )
        elif "web_search" in tool_id or "search" in tool_id:
            responses_tools.append({"type": "web_search"})
        elif tool_id.startswith("mcp::"):
            # ... resolve MCP server URL from LlamaStack toolgroups
```

## Prompt / Chain Patterns

RAG is transparent to the prompt layer. The agent's system prompt (`agent.prompt`) is passed as `instructions` to the Responses API, and when `file_search` tools are attached, LlamaStack automatically embeds the user query, retrieves relevant chunks from the vector store, and injects them into the LLM context. The agent does not need RAG-specific prompt engineering -- retrieved content appears as tool results in the conversation.

## Gotchas

- The knowledge base metadata lives in two places: PostgreSQL (name, embedding model, status) and LlamaStack (vector store with actual embeddings). The `update_vector_store_ids()` function (called on every list operation) keeps them in sync, but a failed sync leaves stale `vector_store_id` values.
- Deleting a knowledge base requires checking that no virtual agents reference it (lines 107-122 of `knowledge_bases.py`), then cascading the delete across three systems: LlamaStack vector store, ingestion pipeline, and local database.
- The ingestion pipeline URL defaults to `http://llamastack:8321/ingestion_pipeline/` but is overridable via the `INGESTION_PIPELINE_URL` environment variable, allowing the pipeline service to run separately from the LlamaStack server.
- RAG only works with the LlamaStack runner via the `file_search` tool type. The LangGraph and CrewAI runners do not have equivalent built-in RAG integration -- they would need custom retriever tool implementations.

## Related Architectures

- [agent-orchestration](agent-orchestration.md) -- RAG tools are attached to agents and flow through the runner dispatch system
- [guardrails-layer](guardrails-layer.md) -- Input shields run before RAG retrieval in the LlamaStack runner

---

## Approach B: NVIDIA RAG Blueprint with NV-Ingest and vLLM (from aml-rag-nvidia)

### When to Use

Use this approach when deploying a RAG application using NVIDIA's pre-built RAG Blueprint server and NV-Ingest document processing pipeline, served by vLLM models on KServe. This approach requires no custom backend code -- all component wiring is done through Helm chart values and environment variables. It suits scenarios where the NVIDIA RAG server's built-in capabilities (query rewriting, reflection, multimodal VLM inference, filter expression generation, query decomposition) are sufficient and a custom application backend is not needed.

### Differences from Approach A

| Aspect | Approach A (LlamaStack) | Approach B (NVIDIA RAG Blueprint) |
|--------|------------------------|-----------------------------------|
| RAG server | Custom FastAPI backend with LlamaStack client | Pre-built NVIDIA RAG server (`nvcr.io/nvidia/blueprint/rag-server:2.4.0`) |
| Ingestion | External pipeline via LlamaStack `/ingestion_pipeline/` API | NV-Ingest 26.1.1 with Redis task queue + cloud-hosted NIMs for OCR/table/graphic detection |
| Vector DB | pgvector via LlamaStack vector stores | GPU-accelerated Milvus v2.6.5-gpu with GPU_CAGRA index |
| Model serving | LlamaStack server | vLLM via KServe ServingRuntime (4 separate InferenceServices) |
| Embedding/reranking | Direct LlamaStack embedding API | NIM-to-vLLM translation proxies (embedding-proxy, ranking-proxy) |
| RAG retrieval | file_search tool via Responses API (transparent to prompt) | Context injected directly into prompt templates (`{context}` placeholder) |
| Application code | Custom Python backend (FastAPI + SQLAlchemy + httpx) | No custom code -- Helm values configure pre-built containers |
| Object storage | Not used | ODF ObjectBucketClaim (NooBaa S3) for document/multimodal content storage |

### Data Flow

1. User submits a query via the React frontend (`rag-frontend` on port 3000)
2. Frontend sends the request to the NVIDIA RAG server (`rag-server` on port 8081) at `/v1` chat endpoint
3. RAG server embeds the query by calling the embedding proxy (`rag-server-embedding-proxy` on port 8080)
4. Embedding proxy strips NIM-specific fields (`input_type`, `truncate`, `dimensions`) and forwards to the vLLM embedding model (`nemoretriever-embedding-ms-predictor` on port 8080)
5. RAG server searches Milvus (`milvus` on port 19530) using GPU_CAGRA index with the query embedding, retrieving top-100 candidates with a score threshold of 0.25
6. RAG server reranks results by calling the ranking proxy (`rag-server-ranking-proxy` on port 8080), which translates NIM `/v1/ranking` format to vLLM `/v1/rerank` format and forwards to the reranking model (`nemoretriever-ranking-ms-predictor`)
7. RAG server injects the top-10 reranked chunks into the `rag_template` prompt as `{context}` and sends the completed prompt to the LLM (`nim-llm-predictor` on port 8080)
8. LLM generates a response grounded in the retrieved context; response is returned to the frontend

For document ingestion:

1. User uploads documents via the frontend, which sends them to the ingestor server (`ingestor-server` on port 8082)
2. Ingestor server submits documents to NV-Ingest (`nv-ingest` on port 7670) via Redis message queue (`ingest-redis-master` on port 6379)
3. NV-Ingest processes documents using cloud-hosted NVIDIA NIMs for page element detection, graphic element detection, table structure detection, OCR, and document parsing
4. NV-Ingest optionally captions images using the VLM model (`nim-vlm-predictor` on port 8080)
5. Processed chunks are embedded by calling the embedding model and indexed into Milvus with GPU-accelerated indexing
6. Document files are stored in ODF S3-compatible object storage via ObjectBucketClaim

### Component Wiring

| From | To | Protocol | Purpose |
|------|----|----------|---------|
| React frontend | rag-server | REST (port 8081) | Chat queries via `/v1` API |
| React frontend | ingestor-server | REST (port 8082) | Document upload and collection management via `/v1` |
| React frontend | Milvus | REST (port 19530) | Direct collection listing |
| rag-server | embedding-proxy | REST (port 8080) | Embed queries for vector search |
| embedding-proxy | nemoretriever-embedding-ms-predictor (vLLM) | REST (port 8080) | Translated NIM-to-vLLM embedding requests |
| rag-server | ranking-proxy | REST (port 8080) | Rerank search results |
| ranking-proxy | nemoretriever-ranking-ms-predictor (vLLM) | REST (port 8080) | Translated NIM `/v1/ranking` to vLLM `/v1/rerank` |
| rag-server | Milvus | REST (port 19530) | Vector similarity search with GPU_CAGRA |
| rag-server | nim-llm-predictor (vLLM) | REST (port 8080) | LLM inference for response generation |
| rag-server | Redis | TCP (port 6379) | Summary status tracking |
| ingestor-server | NV-Ingest | TCP (port 7670) | Document processing task submission |
| NV-Ingest | Redis | TCP (port 6379) | Task queue for ingest pipeline |
| NV-Ingest | NVIDIA cloud NIMs | HTTPS | OCR, page/graphic/table detection, document parsing |
| NV-Ingest | nim-vlm-predictor (vLLM) | REST (port 8080) | Image captioning during ingestion |
| NV-Ingest | nemoretriever-embedding-ms-predictor (vLLM) | HTTPS (NGC API) | Embedding during ingestion (cloud endpoint) |
| NV-Ingest | Milvus | REST (port 19530) | Index processed chunks |
| Milvus | ODF NooBaa S3 | HTTP (port 80) | Object storage backend for vector data |
| rag-server | ODF NooBaa S3 | HTTPS | Multimodal content retrieval |
| rag-server | OTEL Collector | HTTP/gRPC (ports 4318/4317) | Distributed tracing |

### Key Integration Points

#### NIM-to-vLLM Embedding Translation Proxy

The NVIDIA RAG server expects NIM-format embedding APIs, but models are served by vLLM which uses a slightly different OpenAI-compatible format. A lightweight Python proxy strips NIM-specific fields that vLLM rejects.

```python
# charts/rag-server/templates/embedding-proxy-configmap.yaml (lines 28-52)
NIM_ONLY_FIELDS = {"input_type", "truncate", "dimensions"}

def translate_nim_to_vllm(nim_body: dict) -> dict:
    """Strip NIM-specific fields that vLLM does not accept.

    Both NIM and vLLM use the OpenAI /v1/embeddings format, so only
    NIM-incompatible extras need to be removed:
      - input_type  (query vs passage -- not supported by vLLM)
      - truncate    (NONE / START / END -- not supported by vLLM)
      - dimensions  (vLLM rejects this for non-matryoshka models)
    """
    errors = []
    if "input" not in nim_body:
        errors.append("'input' field is required")
    if errors:
        raise ValueError("; ".join(errors))

    vllm_body = {k: v for k, v in nim_body.items() if k not in NIM_ONLY_FIELDS}
    return vllm_body
```

#### NIM-to-vLLM Ranking Translation Proxy

The ranking proxy performs a deeper structural translation -- converting the NIM `/v1/ranking` request format (with `query.text` and `passages[].text`) to vLLM's `/v1/rerank` format (flat `query` string and `documents[]` list), and translating the response back.

```python
# charts/rag-server/templates/ranking-proxy-configmap.yaml (lines 29-58)
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

#### Prompt Template Injection for RAG Context

Unlike Approach A where LlamaStack handles retrieval transparently via file_search tools, Approach B injects retrieved chunks directly into the prompt template. The RAG server uses a `{context}` placeholder in the `rag_template`.

```yaml
# charts/ingest/files/prompt.yaml (rag_template section)
rag_template:
  system: |
    /no_think

  human: |
    You are a helpful AI assistant named Envie.
    You must answer only using the information provided in the context.
    ...
    Context:
    {context}
```

The prompt includes the `/no_think` directive in the system message, which suppresses chain-of-thought reasoning in Nemotron models to produce cleaner responses.

#### Multi-Model KServe Serving with MIG Support

Four models are deployed as separate KServe InferenceService resources sharing a single ServingRuntime, with GPU resources specified as MIG slices rather than full GPUs.

```yaml
# charts/model-serving/values.yaml (lines 101-118)
models:
  nim-llm:
    id: nvidia/Llama-3_3-Nemotron-Super-49B-v1_5-FP8
    resources:
      limits:
        nvidia.com/mig-3g.47gb: "2"  # Tensor parallel across 2 MIG slices
    args:
      - --tensor-parallel-size=2
      - --max-num-seqs=32

  nemoretriever-embedding-ms:
    id: nvidia/llama-nemotron-embed-1b-v2
    resources:
      limits:
        nvidia.com/mig-1g.12gb: "1"  # Small MIG slice for embedding

  nemoretriever-ranking-ms:
    id: nvidia/llama-nemotron-rerank-1b-v2
    resources:
      limits:
        nvidia.com/mig-1g.12gb: "1"  # Small MIG slice for reranking
```

#### Cross-Chart ConfigMap Sharing

The rag-server chart mounts a prompt ConfigMap created by the ingest chart, coupling the two charts at the Kubernetes resource level.

```yaml
# charts/rag-server/templates/deployment.yaml (lines 69-82)
volumeMounts:
{{- if .Values.promptConfig.enabled }}
- name: prompt-config
  mountPath: /prompt.yaml
  subPath: prompt.yaml
  readOnly: true
{{- end }}
volumes:
{{- if .Values.promptConfig.enabled }}
- name: prompt-config
  configMap:
    name: ingestor-server-prompt  # Reference ConfigMap from ingest chart
{{- end }}
```

#### ODF ObjectBucketClaim for S3 Storage

The ingest chart provisions S3 storage via an OpenShift Data Foundation ObjectBucketClaim. The OBC creates a Secret and ConfigMap with AWS credentials and bucket details, which are injected into multiple components (ingestor-server, NV-Ingest, Milvus) via `envFrom`. An init container blocks the ingestor-server startup until the OBC resources are available.

```yaml
# charts/ingest/values.yaml (lines 10-17)
objectStorage:
  odf:
    objectBucketClaim:
      enabled: true
      name: &odf-bucket-name default-bucket
      bucketName: &odf-bucket default-bucket
      storageClassName: openshift-storage.noobaa.io
```

### Prompt / Chain Patterns

The NVIDIA RAG server supports multiple prompt templates configured via `prompt.yaml`, each for a different stage of the RAG pipeline:

- **`chat_template`**: Direct chat without retrieval (simple Q&A)
- **`rag_template`**: Core RAG template -- injects retrieved `{context}` into the prompt
- **`query_rewriter_prompt`**: Reformulates user questions using chat history for multi-turn conversations (disabled by default: `ENABLE_QUERYREWRITER: "False"`)
- **`vlm_template`**: Multimodal template for answering with text context and attached images
- **`document_summary_prompt`** / **`iterative_summary_prompt`** / **`shallow_summary_prompt`**: Document summarization during ingestion
- **`reflection_*` prompts** (relevance check, groundedness check, query rewriter, response regeneration): Self-correction loop that checks context relevance and response groundedness, rewriting queries or regenerating responses up to 3 iterations (disabled by default: `ENABLE_REFLECTION: "false"`)
- **`query_decomposition_*` prompts**: Breaks complex queries into sub-queries for better retrieval (disabled by default: `ENABLE_QUERY_DECOMPOSITION: "false"`)
- **`filter_expression_generator_prompt`**: Generates Milvus filter expressions from natural language (disabled by default: `ENABLE_FILTER_GENERATOR: "False"`)

All prompts include the `/no_think` system directive, which suppresses chain-of-thought reasoning in Nemotron models.

### Gotchas

- The rag-server and ingestor-server share a prompt ConfigMap (`ingestor-server-prompt`), meaning the ingest chart must be installed before the rag-server chart, or the rag-server pod will fail to start with a missing ConfigMap error. The README states "order does not matter, the deployments will resolve," but this relies on Kubernetes restart loops to eventually converge.
- The NV-Ingest `MESSAGE_CLIENT_HOST` must be hardcoded to `ingest-redis-master` because the NV-Ingest Helm subchart does not support Helm template expressions in its values. If the release name changes from `ingest`, this value goes stale and NV-Ingest cannot connect to Redis.
- NV-Ingest uses NVIDIA cloud-hosted NIMs for page element detection, graphic element detection, table structure detection, OCR, and document parsing. These require an NGC API key with appropriate entitlements and impose external network dependencies. The embedding endpoint in NV-Ingest (`EMBEDDING_NIM_ENDPOINT`) also points to the NGC cloud API (`https://integrate.api.nvidia.com/v1/embeddings`) rather than the local vLLM embedding model.
- Milvus disables its built-in MinIO (`minio.enabled: false`) and uses ODF S3 storage via `externalS3`, but forces HTTP port 80 (`MINIO_PORT: "80"`) to avoid TLS certificate verification issues with ODF.
- The embedding proxy strips `input_type` (query vs passage distinction), meaning the vLLM embedding model will not distinguish between query and passage embeddings. The proxy code notes this limitation and suggests configuring the distinction at the vLLM serving level if needed.
- The reranking model's vLLM args include `--enable-auto-tool-choice` and `--chat-template=/chat-templates/tool_chat_template_llama3.2_json.jinja`, which are tool-calling parameters not related to reranking -- these appear to be leftover configuration from a shared ServingRuntime template.
- The `anyuid` Security Context Constraint must be granted to three service accounts (`default`, `<release>-nv-ingest`, and `ingestor-server`) because NV-Ingest and its dependencies require running as specific non-root UIDs.

---

## Approach C: Standalone FAISS Microservice with PDF Knowledge Base (from ansible-log-analysis)

### When to Use

Use this approach when building a RAG system that serves as a "cheat sheet" or knowledge base lookup within an agent pipeline, rather than as a user-facing chat RAG. This approach is suited for scenarios where: the knowledge base is a curated set of PDF documents (e.g., known error patterns and resolutions), retrieval results feed into an agent graph as context enrichment rather than being returned directly to users, and the RAG system runs as an independent microservice with its own ingestion pipeline and index lifecycle managed via MinIO.

### Differences from Approach A and Approach B

| Aspect | Approach A (LlamaStack) | Approach B (NVIDIA RAG Blueprint) | Approach C (FAISS Microservice) |
|--------|------------------------|-----------------------------------|-------------------------------|
| RAG server | Custom FastAPI backend + LlamaStack client | Pre-built NVIDIA RAG server | Standalone FastAPI RAG microservice |
| Vector database | pgvector via LlamaStack vector stores | GPU-accelerated Milvus | FAISS (in-memory, loaded from MinIO) |
| Index storage | LlamaStack server (internal) | Milvus persistent volumes | MinIO object storage (index.faiss + metadata.pkl) |
| Ingestion | External pipeline via LlamaStack API | NV-Ingest with cloud NIMs | Custom PDF parser + embedder init job |
| Embedding | LlamaStack embedding API | NIM-to-vLLM translation proxies | HuggingFace TEI (Text Embeddings Inference) |
| RAG integration | Transparent via file_search tool in Responses API | Context injected via `{context}` prompt placeholder | RAG results returned to agent graph node as formatted text |
| Retrieval consumer | User-facing agent response | User-facing frontend | Internal agent pipeline (context enrichment for LLM) |
| Application code | Custom backend (FastAPI + SQLAlchemy + httpx) | No custom code (Helm-only) | Custom RAG service + custom init pipeline |
| Index lifecycle | Managed by LlamaStack (create/delete via API) | Managed by Milvus | Init job builds index → uploads to MinIO → RAG service polls and loads |
| Knowledge base source | User-uploaded documents | User-uploaded documents | Curated PDF files bundled with deployment |

### Data Flow

**Index Building (Init Job):**

1. RAG init pipeline (`rag_init_pipeline.py`) runs as a Kubernetes init job
2. Scans knowledge base directory for PDF files
3. `AnsibleErrorParser` extracts and chunks PDFs into structured error entries (title, description, symptoms, resolution, code)
4. `AnsibleErrorEmbedder` embeds chunks using TEI (nomic-ai/nomic-embed-text-v1.5) with `search_document:` task prefix
5. Builds a FAISS index (Inner Product / cosine similarity on L2-normalized vectors)
6. Uploads `index.faiss`, `metadata.pkl`, and `LATEST.json` pointer file to MinIO bucket
7. `LATEST.json` tracks index status (BUILDING/READY/FAILED), build ID, and model name

**RAG Service Startup:**

1. RAG service (`services/rag/main.py`) starts and attempts to load index from MinIO
2. If index not available, starts a background polling task that checks every 20 seconds
3. `RAGIndexLoader` downloads `index.faiss` and `metadata.pkl` from MinIO to temp files, loads FAISS index into memory
4. Service becomes ready when index is loaded (readiness probe checks `/ready` endpoint)

**Query Flow (within Agent Pipeline):**

1. Context agent subgraph calls `get_cheat_sheet_context(log_summary)` via the `RAGHandler` singleton
2. `RAGHandler` sends HTTP POST to RAG service at `/rag/query` with the log summary as query
3. RAG service embeds the query using TEI (`/embeddings` endpoint) with `search_query:` task prefix
4. FAISS similarity search returns top-K candidates
5. Results filtered by similarity threshold (default 0.6), top-N returned (default 1)
6. `RAGHandler._format_rag_results()` formats results as structured markdown (title, confidence score, description, symptoms, resolution, code)
7. Formatted context is passed as `cheat_sheet_context` to downstream agent nodes

### Component Wiring

| From | To | Protocol | Purpose |
|------|----|----------|---------|
| RAG init job | Knowledge base PDFs | Filesystem | Read and parse PDF documents |
| RAG init job (AnsibleErrorEmbedder) | TEI | HTTP (POST /embeddings) | Embed document chunks |
| RAG init job | MinIO | S3 API (minio Python SDK) | Upload FAISS index and metadata |
| RAG service | MinIO | S3 API (minio Python SDK) | Download FAISS index on startup |
| RAG service | TEI | HTTP (httpx POST /embeddings) | Embed query at search time |
| RAGHandler (in backend) | RAG service | HTTP (httpx POST /rag/query) | Query for relevant error solutions |
| Context agent node | RAGHandler | Python method call | Get cheat sheet context for log summary |

### Key Integration Points

#### RAG Service Query Endpoint

The RAG service exposes a `/rag/query` endpoint that embeds the query, searches FAISS, and returns structured error results.

```python
# services/rag/main.py (lines 215-268)
@app.post("/rag/query", response_model=QueryResponse)
async def query_rag(request: QueryRequest):
    # Step 1: Generate query embedding via TEI
    query_text = f"search_query: {request.query}"
    embedding_response = await embedding_client.post(
        "/embeddings",
        json={"input": [query_text], "model": "nomic-embed-text-v1.5"},
    )
    # ... extract and normalize embedding

    # Step 2: Similarity search in FAISS
    query_vector = query_embedding.reshape(1, -1)
    similarities, indices = index_loader.index.search(query_vector, request.top_k)

    # Step 3: Filter by threshold and format results
    results = []
    for idx, similarity in zip(indices, similarities):
        if similarity < request.similarity_threshold:
            continue
        error_id = index_loader.index_to_error_id[idx]
        error_data = index_loader.error_store[error_id]
        # ... build ErrorResult with sections (description, symptoms, resolution, code)
```

#### RAGHandler Integration into Agent Pipeline

The `RAGHandler` singleton communicates with the RAG service via HTTP and formats results as structured markdown for LLM consumption.

```python
# src/alm/utils/rag_handler.py (lines 137-200)
async def get_cheat_sheet_context(self, log_summary: str) -> str:
    if not self._initialize_rag_service():
        return ""

    response = await self._client.post(
        "/rag/query",
        json={
            "query": log_summary,
            "top_k": int(os.getenv("RAG_TOP_K", "3")),
            "top_n": int(os.getenv("RAG_TOP_N", "1")),
            "similarity_threshold": float(os.getenv("RAG_SIMILARITY_THRESHOLD", "0.6")),
        },
    )
    response.raise_for_status()
    return self._format_rag_results(response.json())
```

#### Index Lifecycle via MinIO Pointer File

The `LATEST.json` pointer file in MinIO tracks index state, enabling coordination between the init job (producer) and the RAG service (consumer).

```python
# services/rag/index_loader.py (lines 88-139)
def _load_index_sync(self):
    # Check status from LATEST.json
    response = self.minio_client.get_object(self.bucket_name, "LATEST.json")
    pointer = json.loads(response.read().decode())
    status = pointer.get("status")
    self.last_loaded_build_id = pointer.get("build_id")

    if status == "FAILED":
        raise ValueError(f"RAG index build failed: {pointer.get('error_message')}")
    if status != "READY":
        raise ValueError(f"RAG index is not ready (status: {status})")
```

#### Background Polling for Hot Index Reload

The RAG service polls MinIO every 20 seconds, supporting both initial index loading and hot reloads when a new build is detected.

```python
# services/rag/main.py (lines 103-152)
async def poll_for_index():
    while True:
        if index_loader is not None and index_loader.index is not None:
            force_rebuild = os.getenv("RAG_FORCE_REBUILD", "false").lower() == "true"
            if force_rebuild:
                response = index_loader.minio_client.get_object(
                    index_loader.bucket_name, "LATEST.json")
                pointer = json.loads(response.read().decode())
                latest_build_id = pointer.get("build_id")
                if latest_build_id and latest_build_id != index_loader.last_loaded_build_id:
                    await index_loader.reload_index()
        else:
            success = await load_index()
        await asyncio.sleep(poll_interval)
```

### Prompt / Chain Patterns

RAG results are injected into the agent pipeline as formatted markdown context. The `cheat_sheet_context_node` retrieves the context, and downstream nodes include it in their prompts:

- The `loki_router_node` receives both `log_summary` and `cheat_sheet_context` to decide if Loki log retrieval is needed
- The `suggest_step_by_step_solution_node` receives the combined context (cheat sheet + Loki logs) via a dedicated prompt template variant (`suggest_step_by_step_solution_with_context_user_message`) that includes an `{context}` placeholder

The nomic embedding model requires task-specific prefixes: `search_document:` for indexing and `search_query:` for queries.

### Gotchas

- The RAG service uses FAISS in-memory indexing, meaning the entire index must fit in RAM. The `RAGIndexLoader` downloads the index to temp files and loads it via `faiss.read_index()` (lines 160-165 of `index_loader.py`); FAISS requires file paths, not in-memory buffers.
- The `RAGHandler` is a singleton (`__new__` returns same instance) with lazy initialization. The `_initialize_rag_service()` method (lines 45-85 of `rag_handler.py`) is called on first use and checks the `RAG_ENABLED` environment variable. If RAG is disabled or the service is unavailable, all methods return empty strings rather than raising errors.
- The init pipeline (`backend_init_pipeline.py`) separates preparation steps (log loading, clustering) from processing steps (agent inference), waiting for the RAG service between them via `wait_for_rag_service()` which blocks up to 10 minutes (lines 14-85 of `rag_service.py`).
- The embedding client in the RAG service uses connection pooling (`httpx.AsyncClient` with `max_keepalive_connections=20`, `max_connections=100`) for high-throughput query handling (lines 172-181 of `rag/main.py`).
- The nomic embedding model requires different prefixes for documents (`search_document:`) vs. queries (`search_query:`) for optimal retrieval quality. The RAG service adds `search_query:` to queries (line 260 of `rag/main.py`), while the embedder adds `search_document:` during indexing.
- The index check for existing builds (`check_rag_index_exists`) allows skipping rebuilds for faster upgrades. Setting `RAG_FORCE_REBUILD=true` overrides this check (lines 76-88 of `rag_init_pipeline.py`).

---

## Approach D: Frontend-Driven LlamaStack RAG with Manual Context Injection (from f5-ai-guardrails)

### When to Use

Use this approach when building a RAG application where the frontend (Streamlit) orchestrates all RAG operations directly -- vector database creation, document ingestion, retrieval, and prompt context injection -- without a custom backend server. This approach suits scenarios where: the primary focus is demonstrating a different capability (e.g., AI guardrails) with RAG as a supporting feature, the application needs simple document management via a UI, LlamaStack's built-in rag_tool APIs are sufficient without custom retrieval logic, and minimal architectural complexity is preferred.

### Differences from Approaches A, B, and C

| Aspect | Approach A (LlamaStack) | Approach B (NVIDIA RAG Blueprint) | Approach C (FAISS Microservice) | Approach D (Frontend-Driven) |
|--------|------------------------|-----------------------------------|-------------------------------|------------------------------|
| RAG orchestration | Custom FastAPI backend | Pre-built NVIDIA RAG server | Standalone RAG microservice | Streamlit frontend (no backend) |
| Vector database | pgvector via LlamaStack vector stores | GPU-accelerated Milvus | FAISS in-memory | pgvector via LlamaStack vector stores |
| Document ingestion | External pipeline via LlamaStack API | NV-Ingest with cloud NIMs | Custom PDF parser + init job | Direct `rag_tool.insert` from Streamlit UI |
| Context injection | Transparent via file_search tool in Responses API | `{context}` placeholder in rag_template | HTTP API results formatted as markdown | Manual `CONTEXT: {text}` prepended to user prompt |
| Retrieval API | `build_responses_tools` maps builtin::rag to file_search | RAG server built-in | RAG service `/rag/query` endpoint | `rag_tool_query(client, content=..., vector_db_ids=...)` |
| Document management | FastAPI CRUD API with PostgreSQL metadata | Frontend + NV-Ingest APIs | Init job with curated PDFs | Streamlit UI with direct pgvector access (asyncpg) |
| Embedding model | LlamaStack embedding API | vLLM via NIM-to-vLLM proxies | TEI (nomic-embed-text-v1.5) | all-MiniLM-L6-v2 via LlamaStack |
| Application code | Custom backend (FastAPI + SQLAlchemy + httpx) | No custom code (Helm-only) | Custom RAG service + init pipeline | Streamlit frontend only (no backend) |
| Knowledge base type | Dynamic (user-uploaded via API) | Dynamic (user-uploaded via frontend) | Static (curated PDFs) | Dynamic (user-uploaded via Streamlit UI) |

### Data Flow

**Document Ingestion (via Streamlit UI):**

1. User navigates to the Vector Databases page in the Streamlit frontend
2. User creates a new vector database via `register_vector_db()`, specifying `all-MiniLM-L6-v2` as the embedding model with 384 dimensions, resolved against the LlamaStack `vector_io` provider
3. User uploads files (PDF, TXT, DOC/DOCX) through the Streamlit file uploader
4. Frontend converts files to base64 data URLs via `data_url_from_file()`
5. Frontend calls `rag_tool_insert()` with the vector_db_id, documents, and chunk_size_in_tokens=512
6. LlamaStack handles chunking, embedding, and indexing into the pgvector-backed vector store

**Query Flow (Chat with RAG):**

1. User selects one or more Document Collections (vector databases) in the chat sidebar
2. User submits a query via the chat input
3. Frontend resolves selected vector DB names to IDs via `get_vector_db_id()`
4. Frontend calls `rag_tool_query(client, content=prompt, vector_db_ids=vdb_ids)` via the LlamaStack client
5. LlamaStack embeds the query, searches the vector stores, and returns relevant chunks as `rag_resp.content`
6. Frontend builds an extended prompt: `"Please answer the following query using the context below.\n\nCONTEXT:\n{prompt_context}\n\nQUERY:\n{prompt}"`
7. Frontend sends `chat.completions.create` with the extended prompt to the LLM (via F5 Moderator or direct LlamaStack)
8. LLM generates a response grounded in the retrieved context

**Document Management (direct pgvector access):**

1. Frontend queries pgvector directly via asyncpg to list documents in a vector store (`_get_documents_from_pgvector`)
2. Table name is derived from the vector_db_id: `vs_{vector_db_id.replace('-', '_')}`
3. Documents are identified by `chunk_metadata.source` (the original filename) stored in the JSONB `document` column
4. Deletion removes all chunks matching the source filename directly from pgvector

### Component Wiring

| From | To | Protocol | Purpose |
|------|----|----------|---------|
| Streamlit frontend | LlamaStack | HTTP (LlamaStackClient) | Vector DB registration, RAG tool insert/query, model listing |
| Streamlit frontend | pgvector | TCP (asyncpg, port 5432) | Direct document listing and deletion |
| LlamaStack | pgvector | Internal | Vector store persistence, embedding storage, similarity search |
| Streamlit frontend | LLM (via LlamaStack or F5 Moderator) | HTTP (OpenAI SDK) | Chat completion with RAG context in prompt |

### Key Integration Points

#### RAG Tool Query via LlamaStack Client

The frontend retrieves context using LlamaStack's `rag_tool` API, falling back to a REST endpoint if the Python client lacks the `rag_tool` resource.

```python
# frontend/llama_stack_ui/distribution/ui/modules/api.py (lines 388-403)
def rag_tool_query(
    client: LlamaStackClient,
    *, content: str, vector_db_ids: List[str],
    query_config: Optional[Any] = None,
) -> Any:
    rag = getattr(getattr(client, "tool_runtime", None), "rag_tool", None)
    if rag is not None:
        return rag.query(content=content, vector_db_ids=vector_db_ids)
    body: dict[str, Any] = {"content": content, "vector_db_ids": vector_db_ids}
    raw = client.post("/v1/tool-runtime/rag-tool/query", body=body, cast_to=dict)
    return SimpleNamespace(content=raw.get("content"))
```

#### Manual Context Injection into Prompt

Unlike Approach A (transparent file_search) or Approach B (rag_template `{context}` placeholder), this approach manually prepends retrieved context to the user prompt in the frontend code.

```python
# frontend/llama_stack_ui/distribution/ui/page/playground/chat.py (lines 358-387)
# --- Shared RAG context ---
prompt_context = None
if selected_vector_dbs:
    all_vdbs = list_vector_catalog(client) or []
    vdb_ids = [get_vector_db_id(v) for v in all_vdbs if get_vector_db_name(v) in selected_vector_dbs]
    rag_resp = rag_tool_query(client, content=prompt, vector_db_ids=list(vdb_ids))
    prompt_context = rag_resp.content

if prompt_context:
    extended_prompt = (
        f"Please answer the following query using the context below.\n\n"
        f"CONTEXT:\n{prompt_context}\n\nQUERY:\n{prompt}"
    )
else:
    extended_prompt = f"Please answer the following query.\n\nQUERY:\n{prompt}"

messages_for_api = [
    {"role": "system", "content": system_prompt},
    {"role": "user", "content": extended_prompt},
]
```

#### Document Upload via RAG Tool Insert

The frontend converts uploaded files to base64 data URLs and inserts them into the vector store using LlamaStack's `rag_tool.insert` API.

```python
# frontend/llama_stack_ui/distribution/ui/page/distribution/vector_dbs.py (lines 326-344)
documents = [
    {
        "document_id": uploaded_file.name,
        "content": data_url_from_file(uploaded_file),
        "metadata": {"source": uploaded_file.name, "type": "uploaded_file"},
    }
    for uploaded_file in uploaded_files
]

rag_tool_insert(
    active_llama_stack_client(),
    vector_db_id=actual_db_id,
    documents=documents,
    chunk_size_in_tokens=512,
)
```

#### Direct pgvector Document Management

The frontend bypasses LlamaStack for document listing and deletion, querying pgvector directly via asyncpg. The table name convention is `vs_{vector_db_id}` with hyphens replaced by underscores.

```python
# frontend/llama_stack_ui/distribution/ui/page/distribution/vector_dbs.py (lines 377-431)
async def fetch_documents():
    conn = await asyncpg.connect(
        host=pg_host, port=pg_port, user=pg_user,
        password=pg_password, database=pg_database
    )
    table_name = f"vs_{vector_db_id.replace('-', '_')}"
    query = f"""
        SELECT DISTINCT
            COALESCE(
                NULLIF(document->'chunk_metadata'->>'source', 'null'),
                document->'metadata'->>'document_id'
            ) as document_id
        FROM {table_name}
        WHERE document->'metadata'->>'document_id' IS NOT NULL
        ORDER BY document_id
    """
    rows = await conn.fetch(query)
```

#### Vector Database Registration with Provider Resolution

The frontend discovers the `vector_io` provider from LlamaStack and uses it when registering new vector databases, with fallback to OpenAI-compatible `vector_stores.create` for LlamaStack 0.6+ distributions.

```python
# frontend/llama_stack_ui/distribution/ui/page/distribution/vector_dbs.py (lines 206-227)
providers = active_llama_stack_client().providers.list()
vector_io_provider = None
for provider in providers:
    if provider.api == "vector_io":
        vector_io_provider = provider.provider_id
        break

vector_db = register_vector_db(
    active_llama_stack_client(),
    vector_db_id=vdb_name,
    embedding_dimension=384,
    embedding_model="all-MiniLM-L6-v2",
    provider_id=vector_io_provider,
)
```

### Prompt / Chain Patterns

RAG context is injected as a single `CONTEXT:` block in the user message. The prompt structure is:

- **System message**: User-configurable via the sidebar (default: "You are a helpful AI assistant.")
- **User message**: `"Please answer the following query using the context below.\n\nCONTEXT:\n{retrieved_content}\n\nQUERY:\n{user_query}"`

When no RAG context is available (no vector DBs selected or retrieval returns empty), the prompt simplifies to: `"Please answer the following query.\n\nQUERY:\n{user_query}"`

The same RAG context and prompt are sent to both the F5 Guardrails panel and the LlamaStack Direct panel, enabling side-by-side comparison of guardrailed vs. unguardrailed responses with identical context.

### Gotchas

- The frontend uses direct pgvector access via asyncpg for document listing and deletion (`_get_documents_from_pgvector`, `_delete_document_from_pgvector` in vector_dbs.py). This bypasses LlamaStack's vector store API entirely, creating a tight coupling to the pgvector table naming convention (`vs_{id.replace('-', '_')}`). If LlamaStack changes its internal schema, the direct queries break.
- The pgvector connection details are read from environment variables (`PGVECTOR_HOST`, `PGVECTOR_PORT`, `PGVECTOR_USER`, `PGVECTOR_PASSWORD`, `PGVECTOR_DB`) with defaults that match the Helm chart values (`pgvector`, `5432`, `postgres`, `rag_password`, `rag_blueprint`). The Helm chart sets these on the frontend deployment (rag/values.yaml lines 27-35).
- The `register_vector_db` function in api.py uses a triple fallback strategy for LlamaStack API compatibility: first tries `client.vector_dbs.register()`, then falls back to `POST /v1/vector-dbs`, and finally falls back to `client.vector_stores.create()` for LlamaStack 0.6+ which uses OpenAI-compatible vector store APIs (api.py lines 304-340).
- Embedding dimension is hardcoded to 384 with `all-MiniLM-L6-v2` in the vector DB creation UI (vector_dbs.py line 224). This must match the embedding model configured in the LlamaStack distribution.
- The LlamaStack client URL normalization handles multiple legacy and current URL formats: stripping `/v1/openai/v1` suffixes, removing accidental `/v1/models` paste targets, and ensuring the base URL ends with `/v1` for OpenAI SDK compatibility (api.py lines 32-54). OpenShift route URLs require TLS verification disabled and redirect following (`httpx.Client(verify=False, follow_redirects=True)`).
- The file uploader tracks processed file sets in session state (`processed_files_{vector_db_name}`) using a frozenset of `name+size` to prevent re-uploading the same files on page rerun (vector_dbs.py lines 288-293). This deduplication is per-session only.

---

## Approach E: Startup-Time Knowledge Base Ingestion via LlamaStack OpenAI-Compatible API (from it-self-service-agent)

### When to Use

Use this approach when deploying a curated set of knowledge base documents that are bundled with the application (or mounted via ConfigMap) and ingested into LlamaStack vector stores at service startup. This approach suits scenarios where: the knowledge base is a fixed set of text files representing organizational policies or product catalogs, documents do not change frequently (updates require service restart or ConfigMap redeployment), no user-facing document management UI is needed, and retrieval should be transparent to the agent via LlamaStack's file_search tool in the Responses API.

### Differences from Approaches A, B, C, and D

| Aspect | Approach A (LlamaStack) | Approach B (NVIDIA RAG Blueprint) | Approach C (FAISS Microservice) | Approach D (Frontend-Driven) | Approach E (Startup Ingestion) |
|--------|------------------------|-----------------------------------|-------------------------------|------------------------------|-------------------------------|
| RAG orchestration | Custom FastAPI backend + external pipeline | Pre-built NVIDIA RAG server | Standalone RAG microservice | Streamlit frontend | Backend startup code (KnowledgeBaseManager) |
| Vector database | pgvector via LlamaStack vector stores | GPU-accelerated Milvus | FAISS in-memory | pgvector via LlamaStack vector stores | pgvector via LlamaStack vector stores |
| Document ingestion | External pipeline via LlamaStack `/ingestion_pipeline/` API | NV-Ingest with cloud NIMs | Custom PDF parser + init job | `rag_tool.insert` from Streamlit UI | Direct `files.create` + `vector_stores.files.create` at startup |
| Ingestion trigger | API call (user-initiated) | API call (user-initiated) | Init job (deploy-time) | UI upload (user-initiated) | Service startup (automatic) |
| Context injection | Transparent via file_search tool | `{context}` placeholder in rag_template | HTTP API results as markdown | Manual `CONTEXT:` prepend in frontend | Transparent via file_search tool |
| Document management | FastAPI CRUD API + PostgreSQL metadata | Frontend + NV-Ingest APIs | Init job (static) | Streamlit UI + direct pgvector | None (files bundled or ConfigMap-mounted) |
| Knowledge base source | User-uploaded documents | User-uploaded documents | Curated PDFs bundled with deployment | User-uploaded via Streamlit UI | Curated text files in config directory or ConfigMap |
| Dual metadata tracking | Yes (PostgreSQL + LlamaStack) | No (Milvus only) | No (MinIO + FAISS) | Yes (LlamaStack + direct pgvector) | No (LlamaStack only) |
| Vector store provider | Implicit (LlamaStack default) | Milvus | FAISS | Implicit (LlamaStack default) | Explicit (`extra_body={"provider_id": "pgvector"}`) |

### Data Flow

**Knowledge Base Ingestion (at service startup):**

1. Agent-service starts and `KnowledgeBaseManager.register_knowledge_bases()` scans the `config/knowledge_bases/` directory (and optional extra ConfigMap mount path)
2. For each subdirectory (e.g., `laptop-refresh/`), it calls `register_knowledge_base()`
3. A new vector store is created with a unique name via `self._llama_client.vector_stores.create(name=vector_store_name, extra_body={"provider_id": "pgvector"})`
4. All `.txt` files in the subdirectory are uploaded via `self._llama_client.files.create(file=f, purpose="assistants")`
5. Each uploaded file is attached to the vector store via `self._llama_client.vector_stores.files.create(vector_store_id=vector_store_id, file_id=file_id)`
6. LlamaStack handles chunking, embedding, and indexing into the pgvector-backed vector store

**RAG Retrieval (at query time):**

1. Agent configuration YAML specifies `knowledge_bases: ["laptop-refresh"]`
2. During `_get_mcp_tools_to_use()`, the agent calls `_get_vector_store_id(kb_name)` to find the matching vector store
3. `_get_vector_store_id()` lists all vector stores via `self.async_llama_client.vector_stores.list()` and finds the latest one matching the knowledge base name pattern
4. A `file_search` tool definition is added to the tools array: `{"type": "file_search", "vector_store_ids": [vector_store_id]}`
5. The LlamaStack Responses API transparently handles query embedding, vector search, and context injection when processing the agent's request

### Component Wiring

| From | To | Protocol | Purpose |
|------|----|----------|---------|
| KnowledgeBaseManager | LlamaStack (sync client) | HTTP (OpenAI-compatible) | Vector store creation, file upload, file attachment |
| Agent (responses_agent.py) | LlamaStack (async client) | HTTP (AsyncLlamaStackClient) | Vector store listing for ID resolution |
| Agent (responses_agent.py) | LlamaStack Responses API | HTTP (AsyncLlamaStackClient) | file_search tool execution during inference |
| LlamaStack server | pgvector | TCP | Vector store persistence, embedding storage, similarity search |
| Knowledge base files | Agent-service filesystem | Filesystem / ConfigMap mount | Source documents (`.txt` files) |

### Key Integration Points

#### KnowledgeBaseManager Startup Ingestion

The `KnowledgeBaseManager` scans directories at startup and registers each subdirectory as a separate knowledge base via LlamaStack's OpenAI-compatible vector store API.

```python
# agent-service/src/agent_service/knowledge/kb_manager.py (lines 73-121)
def register_knowledge_base(self, kb_directory: Path) -> Optional[str]:
    kb_name = kb_directory.name
    # Create vector store with explicit pgvector provider
    vector_store_name = f"{kb_name}-kb-{uuid.uuid4().hex[:8]}"
    vector_store = self._llama_client.vector_stores.create(
        name=vector_store_name, extra_body={"provider_id": "pgvector"}
    )
    vector_store_id = vector_store.id

    # Upload files to vector store
    uploaded_files = self._upload_files_to_vector_store(kb_directory, vector_store_id)
    return str(vector_store_id)
```

#### File Upload via OpenAI-Compatible API

Knowledge base text files are uploaded using the OpenAI-compatible files API and then attached to the vector store.

```python
# agent-service/src/agent_service/knowledge/kb_manager.py (lines 128-183)
def _upload_files_to_vector_store(self, directory: Path, vector_store_id: str) -> int:
    txt_files = list(directory.rglob("*.txt"))
    for file_path in txt_files:
        with open(file_path, "rb") as f:
            file_create_response = self._llama_client.files.create(
                file=f, purpose="assistants"
            )
        file_id = file_create_response.id
        self._llama_client.vector_stores.files.create(
            vector_store_id=vector_store_id, file_id=file_id
        )
        uploaded_count += 1
    return uploaded_count
```

#### Vector Store ID Resolution by Name Pattern

At query time, the agent resolves the knowledge base name to a vector store ID by listing all vector stores and finding the latest one matching the name pattern.

```python
# agent-service/src/agent_service/langgraph/responses_agent.py (lines 118-168)
async def _get_vector_store_id(self, kb_name: str) -> Optional[str]:
    vector_stores = await self.async_llama_client.vector_stores.list()
    matching_stores = []
    for vs in vector_stores.data:
        if vs.name and kb_name in vs.name:
            matching_stores.append(vs)
    if matching_stores:
        latest_store = max(matching_stores, key=lambda x: x.created_at)
        return str(latest_store.id) if latest_store.id is not None else None
    return None
```

#### Per-Agent Knowledge Base Configuration

Each agent YAML configuration lists the knowledge bases it should use. The agent resolves these names to vector store IDs at runtime.

```yaml
# agent-service/config/agents/laptop-refresh-agent.yaml (lines 15-16)
knowledge_bases: ["laptop-refresh"]
```

### Prompt / Chain Patterns

RAG is transparent to the prompt layer, identical to Approach A. The agent's system prompt and state machine prompts are passed through the LlamaStack Responses API, and when `file_search` tools are attached, LlamaStack automatically embeds the user query, retrieves relevant chunks from the vector store, and injects them into the LLM context.

The YAML state machine prompt explicitly instructs the LLM to use the knowledge base: "CRITICAL Query the laptop-refresh knowledge base to find the laptop refresh interval policy. CRITICAL You MUST use a knowledge base query tool to search for 'standard laptop refresh interval'" (lg-prompt-big.yaml, line 51). This ensures the LLM triggers the file_search tool rather than relying on its training data.

### Gotchas

- The `KnowledgeBaseManager` uses the synchronous LlamaStack client (`create_llamastack_client()`) for startup ingestion, while the `Agent` class uses the asynchronous client (`create_async_llamastack_client()`) for runtime operations. This is because startup runs before the async event loop is active.
- Each service restart creates a new vector store with a unique name (`{kb_name}-kb-{uuid_hex[:8]}`), meaning old vector stores accumulate in LlamaStack/pgvector. The `_get_vector_store_id()` method (line 134 of responses_agent.py) selects the latest store by `created_at` timestamp, so stale stores are ignored at query time but not cleaned up.
- The `extra_body={"provider_id": "pgvector"}` parameter (line 91 of kb_manager.py) is required in LlamaStack 0.3.3+ to associate the vector store with the pgvector provider. Without this, the vector store creation may fail or use an unexpected default provider.
- Only `.txt` files are supported for knowledge base ingestion (line 139 of kb_manager.py: `directory.rglob("*.txt")`). PDF, DOCX, and other formats are not handled. This is a deliberate simplification -- the knowledge base consists of curated policy documents in plain text format.
- The `register_knowledge_bases()` method accepts an optional `extra_path` parameter (line 26 of kb_manager.py) for scanning additional directories beyond the default `config/knowledge_bases/`. This is used for ConfigMap-mounted knowledge bases in Kubernetes deployments, enabling knowledge base updates without rebuilding the container image.
- The `_get_vector_store_id()` method returns `None` (not a fallback name) when no matching vector store is found (lines 153-168 of responses_agent.py). The `_get_mcp_tools_to_use()` method skips knowledge bases that return `None`, logging a warning but not failing the request. This means a missing or failed vector store results in the agent operating without RAG rather than crashing.
- Knowledge base files for the laptop-refresh agent include region-specific laptop catalogs (`APAC_laptop_offerings.txt`, `EMEA_laptop_offerings.txt`, `LATAM_laptop_offerings.txt`, `NA_laptop_offerings.txt`) and a `refresh_policy.txt`. All five files are uploaded to the same vector store, and the LLM uses the employee's location (from the MCP tool response) to query the correct region's offerings.

---

## Approach F: Dual-Mode Streamlit Frontend with Docling Ingestion Pipeline (from RAG)

### When to Use

Use this approach when building a self-contained RAG chatbot where the Streamlit frontend handles both user-facing chat and document management, with automated ingestion from multiple data sources (GitHub repositories, S3/MinIO, direct URLs) via a Kubeflow Pipelines-based pipeline and a local Docling-powered ingestion service. This approach suits scenarios where: users need a choice between Direct retrieval mode (manual context injection) and Agent-based mode (transparent file_search tool), document ingestion should be automated from external data sources at deploy time, users should also be able to upload documents via the UI, document management should use standard OpenAI-compatible APIs (no direct database access), and multiple device types (GPU, CPU, HPU, Xeon) need to be supported for model serving.

### Differences from Approaches A, B, C, D, and E

| Aspect | Approach A (LlamaStack) | Approach B (NVIDIA RAG Blueprint) | Approach C (FAISS Microservice) | Approach D (Frontend-Driven) | Approach E (Startup Ingestion) | Approach F (Dual-Mode + Docling) |
|--------|------------------------|-----------------------------------|-------------------------------|------------------------------|-------------------------------|-------------------------------|
| RAG orchestration | Custom FastAPI backend + external pipeline | Pre-built NVIDIA RAG server | Standalone RAG microservice | Streamlit frontend only | Backend startup code (KnowledgeBaseManager) | Streamlit frontend with dual mode (Direct + Agent-based) |
| Retrieval API | file_search tool via Responses API | Context via prompt template | HTTP POST /rag/query | `rag_tool_query` via LlamaStack client | file_search tool via Responses API | Direct mode: `vector_stores.search`; Agent mode: file_search via Responses API |
| Context injection | Transparent via file_search tool | `{context}` placeholder | Formatted markdown | Manual `CONTEXT:` prepend | Transparent via file_search tool | Direct mode: manual `CONTEXT:` prepend; Agent mode: transparent via file_search |
| Document ingestion | External pipeline via LlamaStack API | NV-Ingest with cloud NIMs | Custom PDF parser + init job | `rag_tool.insert` from Streamlit UI | `files.create` + `vector_stores.files.create` at startup | Docling ingestion service (GitHub/S3/URL sources) + UI upload via `files.create` + `vector_stores.files.create` |
| Document processing | LlamaStack internal | NV-Ingest (OCR, table detection) | Custom PyPDF parser | LlamaStack internal (base64 data URL) | LlamaStack internal | Docling (`DocumentConverter` + `HybridChunker`) for ingestion service; LlamaStack internal for UI uploads |
| Document management | FastAPI CRUD + PostgreSQL metadata | Frontend + NV-Ingest APIs | Init job (static) | Direct pgvector via asyncpg | None | OpenAI-compatible `vector_stores.files.list/delete` API (no direct DB access) |
| Vector store creation | LlamaStack internal | Milvus | FAISS | `register_vector_db` with triple fallback | `vector_stores.create` with explicit provider_id | `vector_stores.create` (no provider_id, no fallback) |
| Ingestion trigger | API call (user-initiated) | API call (user-initiated) | Init job (deploy-time) | UI upload (user-initiated) | Service startup (automatic) | Kubeflow Pipelines (deploy-time) + UI upload (user-initiated) |
| Data sources | User-uploaded documents | User-uploaded documents | Curated PDFs | User-uploaded via UI | Curated text files | GitHub repos, S3/MinIO, URLs (automated) + user-uploaded via UI |
| Guardrails | Per-agent shields (runner integration) | External proxy | Not built in | External F5 proxy | NeMo Guardrails | Frontend-integrated input/output shields via `safety.run_shield` |
| Application code | Custom backend (FastAPI + SQLAlchemy + httpx) | No custom code (Helm-only) | Custom RAG service | Streamlit frontend only | KnowledgeBaseManager + Agent | Streamlit frontend + separate ingestion service |
| Local development | Not supported | Not supported | Not supported | Not supported | Not supported | Podman Compose with Ollama on host |

### Data Flow

**Automated Ingestion (deploy-time via Kubeflow Pipelines or local Docling service):**

1. Helm chart defines multiple ingestion pipelines in `values.yaml` (e.g., `hr-pipeline`, `legal-pipeline`, `sales-pipeline`), each specifying a data source (GitHub, S3, URL), embedding model, and vector store name
2. For OpenShift deployment: Kubeflow Pipelines subchart (`ingestion-pipeline`) creates and runs pipeline jobs that process documents and store them in LlamaStack vector stores
3. For local deployment: the `IngestionService` container starts and waits for LlamaStack to be ready via `wait_for_llamastack()` (up to 30 retries at 5-second intervals)
4. The service iterates over enabled pipelines and fetches documents based on source type:
   - **GitHub**: Shallow git clone (`--depth 1`), walks the target path for PDF files
   - **S3**: Uses boto3 to list and download objects from the bucket with optional prefix filtering
   - **URL**: Downloads files via HTTP requests
5. `DocumentConverter` (Docling) converts PDFs with `PdfPipelineOptions(generate_picture_images=True)`
6. `HybridChunker` splits documents into chunks, filtering for `TEXT` and `PARAGRAPH` labels
7. Chunks are wrapped as `LlamaStackDocument` objects with `mime_type="text/plain"` and source metadata
8. `get_provider_id()` discovers the `vector_io` provider from LlamaStack's providers list
9. `client.vector_dbs.register()` creates the vector store with the discovered provider
10. `client.tool_runtime.rag_tool.insert()` inserts all chunks into the vector store with `chunk_size_in_tokens=512`

**User Upload (via Streamlit UI):**

1. User navigates to the Upload Documents page
2. User selects an existing vector store or creates a new one via `client.vector_stores.create(name=vdb_name)`
3. User selects extraction method: "LlamaStack Provider" (sends files directly) or "Docling" (client-side text extraction for .docx/.xlsx)
4. For Provider mode: uploaded file is sent directly via `client.files.create(file=uploaded_file, purpose="assistants")`
5. For Docling/local mode: `extract_text()` converts the file to plain text locally, then wraps it as a text file before uploading via `client.files.create()`, with `attributes={"source": original_filename}` to preserve the original filename
6. Each uploaded file is attached to the vector store via `client.vector_stores.files.create(vector_store_id=actual_db_id, file_id=file_response.id)`
7. LlamaStack handles chunking, embedding, and indexing internally

**Direct Mode Query Flow:**

1. User submits a query in the chat input
2. If input shields are configured, `run_input_shields()` calls `client.safety.run_shield()` for each shield; blocks with violation message if any shield triggers
3. For each selected vector store, `search_vector_store_direct()` calls `client.vector_stores.search(vector_store_id=vdb_id, query=prompt, max_num_results=top_k)`
4. Search results are extracted from the response (handles `data`, `chunks`, and `results` response formats for API compatibility)
5. Text content is extracted via `extract_text_from_search_result()` and formatted as `[Source: {source}]: {text}` context parts
6. `build_rag_messages()` constructs the prompt: system prompt + `"Please answer the following query using the context below.\n\nCONTEXT:\n{context}\n\nQUERY:\n{prompt}"`
7. `client.chat.completions.create()` sends the request with streaming enabled
8. Response streams through `stream_completions_direct()` which handles both `reasoning_content` (for models like R1) and regular `content` deltas
9. If output shields are configured, `run_output_shields()` validates the response; blocks if any shield triggers

**Agent-Based Mode Query Flow:**

1. User submits a query in the chat input
2. Input shields run identically to Direct mode
3. `build_response_tools()` converts selected toolgroups to Responses API format:
   - `builtin::rag` maps to `{"type": "file_search", "max_num_results": top_k, "vector_store_ids": [...]}`
   - `web_search` maps to `{"type": "web_search"}`
   - `mcp::*` toolgroups resolve their server URLs from LlamaStack toolgroups and map to `{"type": "mcp", "server_label": ..., "server_url": ...}`
4. `client.responses.create()` sends the request with `instructions` (system prompt), `input` (user message), `conversation` (conversation ID for multi-turn), `tools`, and streaming enabled
5. Chunks are processed by type: `response.file_search_call.in_progress`, `response.reasoning_text.delta`, `response.output_text.delta`, `response.output_item.done` (for file_search, web_search, function_call, mcp_call results), `response.done`
6. `strip_file_citations()` removes LlamaStack citation markers (`file<...>`, `<|file-...|>`, `【...†...】`) from the response text
7. `search_vector_stores_fallback()` explicitly searches vector stores after streaming completes to display retrieved chunks (since the Responses API stream does not always include file_search results)
8. Output shields run identically to Direct mode

### Component Wiring

| From | To | Protocol | Purpose |
|------|----|----------|---------|
| Streamlit frontend | LlamaStack server | HTTP (LlamaStackClient, port 8321) | Chat completions (Direct mode), Responses API (Agent mode), vector store CRUD, file upload, shield execution, model/toolgroup listing |
| Streamlit frontend | pgvector (via LlamaStack) | Indirect | Vector store persistence (managed by LlamaStack, no direct access) |
| Ingestion service | LlamaStack server | HTTP (LlamaStackClient) | Vector DB registration, rag_tool.insert for document ingestion |
| Ingestion service | GitHub | HTTPS (git clone) | Fetch PDF documents from repositories |
| Ingestion service | S3/MinIO | HTTP (boto3) | Fetch PDF documents from object storage |
| Ingestion service | URLs | HTTP (requests) | Fetch PDF documents from direct URLs |
| Kubeflow Pipelines | LlamaStack server | HTTP | Automated pipeline execution for document ingestion |
| Helm chart | ConfigMap | Kubernetes API | Suggested questions configuration injected as `RAG_QUESTION_SUGGESTIONS` env var |

### Key Integration Points

#### Dual-Mode Processing Architecture

The chat page supports switching between Direct and Agent-based modes via a sidebar radio button. Each mode uses a different LlamaStack API path for retrieval.

```python
# frontend/llama_stack_ui/distribution/ui/page/playground/chat.py (lines 634-650)
def process_prompt(prompt, config):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        state = ResponseState()

        if config.processing_mode == "Direct":
            direct_process_prompt(prompt, state, config)
        elif config.processing_mode == "Agent-based":
            agent_process_prompt(prompt, state, config)
```

#### Direct Mode: vector_stores.search API

Direct mode explicitly searches vector stores and injects results as context into the prompt, giving full control over retrieval and prompt construction.

```python
# frontend/llama_stack_ui/distribution/ui/page/playground/direct.py (lines 52-68)
def search_vector_store_direct(prompt, vector_db_id, vector_db_name, top_k, state):
    search_response = llama_stack_api.client.vector_stores.search(
        vector_store_id=vector_db_id,
        query=prompt,
        max_num_results=top_k,
    )

    search_results = []
    if hasattr(search_response, 'data') and search_response.data:
        search_results = search_response.data
    elif hasattr(search_response, 'chunks') and search_response.chunks:
        search_results = search_response.chunks
    elif hasattr(search_response, 'results') and search_response.results:
        search_results = search_response.results
```

#### Agent-Based Mode: Responses API with file_search Tool

Agent-based mode converts selected toolgroups (RAG, web search, MCP) into Responses API tool definitions, letting LlamaStack handle retrieval transparently.

```python
# frontend/llama_stack_ui/distribution/ui/page/playground/agent.py (lines 22-51)
def build_response_tools(toolgroup_selection, selected_vector_dbs, top_k, client):
    agent_tools = []
    for toolgroup_name in toolgroup_selection:
        if toolgroup_name == "builtin::rag":
            if len(selected_vector_dbs) > 0:
                vector_dbs = client.vector_stores.list() or []
                vector_db_ids = [
                    vector_db.id for vector_db in vector_dbs
                    if get_vector_db_name(vector_db) in selected_vector_dbs
                ]
                agent_tools.append({
                    "type": "file_search",
                    "max_num_results": top_k,
                    "vector_store_ids": list(vector_db_ids),
                })
        elif "web_search" in toolgroup_name or "search" in toolgroup_name.lower():
            agent_tools.append({"type": "web_search"})
        elif toolgroup_name.startswith("mcp::"):
            # ... resolve MCP server URL from LlamaStack toolgroups
```

#### Docling-Based Document Processing in Ingestion Service

The ingestion service uses Docling's `DocumentConverter` and `HybridChunker` for PDF processing, filtering for text and paragraph content items.

```python
# ingestion-service/ingest.py (lines 204-243)
def process_documents(self, pdf_files: List[str]) -> List[LlamaStackDocument]:
    llama_documents = []
    doc_id = 0
    for file_path in pdf_files:
        docling_doc = self.converter.convert(source=file_path).document
        chunks = self.chunker.chunk(docling_doc)
        for chunk in chunks:
            if any(
                c.label in [DocItemLabel.TEXT, DocItemLabel.PARAGRAPH]
                for c in chunk.meta.doc_items
            ):
                doc_id += 1
                llama_documents.append(
                    LlamaStackDocument(
                        document_id=f"doc-{doc_id}",
                        content=chunk.text,
                        mime_type="text/plain",
                        metadata={"source": os.path.basename(file_path)},
                    )
                )
```

#### Multi-Source Data Fetching

The ingestion service supports three data sources, each with its own fetch method, producing a list of PDF file paths for processing.

```python
# ingestion-service/ingest.py (lines 295-334)
def process_pipeline(self, pipeline_name: str, pipeline_config: Dict[str, Any]) -> bool:
    vector_store_name = pipeline_config['vector_store_name']
    source = pipeline_config['source']
    source_config = pipeline_config['config']

    with tempfile.TemporaryDirectory() as temp_dir:
        if source == 'GITHUB':
            pdf_files = self.fetch_from_github(source_config, temp_dir)
        elif source == 'S3':
            pdf_files = self.fetch_from_s3(source_config, temp_dir)
        elif source == 'URL':
            pdf_files = self.fetch_from_urls(source_config, temp_dir)

        documents = self.process_documents(pdf_files)
        return self.create_vector_db(vector_store_name, documents)
```

#### Document Upload via OpenAI-Compatible Files API

The UI upload page uses the standard OpenAI-compatible Files API for document management, with support for both server-side (LlamaStack Provider) and client-side (Docling) extraction methods.

```python
# frontend/llama_stack_ui/distribution/ui/page/upload/upload.py (lines 308-333)
for uploaded_file in uploaded_files:
    original_filename = uploaded_file.name

    if extraction_method == "local":
        text_content = extract_text(uploaded_file, original_filename)
        file_to_upload = create_text_file_from_extracted_content(
            text_content, original_filename
        )
    else:
        file_to_upload = uploaded_file

    file_response = llama_stack_api.client.files.create(
        file=file_to_upload,
        purpose="assistants"
    )

    vs_file_kwargs = {
        "vector_store_id": actual_db_id,
        "file_id": file_response.id,
    }
    if extraction_method == "local":
        vs_file_kwargs["attributes"] = {"source": original_filename}

    llama_stack_api.client.vector_stores.files.create(**vs_file_kwargs)
```

#### Frontend-Integrated Guardrails

Both Direct and Agent-based modes integrate input and output shields directly in the frontend, executing them via LlamaStack's `safety.run_shield` API before and after LLM inference.

```python
# frontend/llama_stack_ui/distribution/ui/modules/utils.py (lines 152-185)
def run_input_shields(client, shield_ids, user_message):
    for shield_id in shield_ids:
        shield_response = client.safety.run_shield(
            shield_id=shield_id,
            messages=[{"role": "user", "content": user_message}],
            params={},
        )
        if hasattr(shield_response, "violation") and shield_response.violation:
            violation_msg = getattr(
                shield_response.violation, "user_message", "Content blocked by safety guardrail"
            )
            return True, violation_msg, shield_id
    return False, None, None
```

#### File Citation Stripping

The frontend strips LlamaStack's file citation markers from streamed responses, including partial markers during streaming to prevent citation fragments from flashing in the UI.

```python
# frontend/llama_stack_ui/distribution/ui/modules/utils.py (lines 69-99)
def strip_file_citations(text):
    text = re.sub(r'file<[^>]+>', '', text)
    text = re.sub(r'<\|file-[^|]*\|>', '', text)
    text = re.sub(r'<\|[0-9a-fA-F-]{8,}\|>', '', text)
    text = re.sub(r'【[^】]*†[^】]*】', '', text)
    text = re.sub(r'  +', ' ', text)
    return text

def strip_file_citations_streaming(text):
    text = strip_file_citations(text)
    text = re.sub(r'<\|(?:f(?:i(?:l(?:e(?:-[^|]*)?)?)?)?)?\s*$', '', text)
    text = re.sub(r'<\|[0-9a-fA-F-]*$', '', text)
    text = re.sub(r'\bfile<[^>]*$', '', text)
    text = re.sub(r'【[^】]*$', '', text)
    return text
```

#### Suggested Questions from ConfigMap

The Helm chart renders suggested questions as a JSON ConfigMap, injected into the frontend as the `RAG_QUESTION_SUGGESTIONS` environment variable. Questions are keyed by vector store name and displayed when a matching database is selected.

```yaml
# deploy/helm/rag/values.yaml (lines 211-251)
suggestedQuestions:
  hr-vector-db-v1-0:
    - "What are the health insurance benefits offered?"
    - "How many vacation days do employees get?"
  sales-vector-db-v1-0:
    - "What is the sales process?"
    - "How do I qualify leads?"
```

```python
# frontend/llama_stack_ui/distribution/ui/modules/utils.py (lines 116-131)
def get_question_suggestions():
    suggestions_json = os.environ.get("RAG_QUESTION_SUGGESTIONS", "{}")
    suggestions = json.loads(suggestions_json)
    return suggestions
```

### Prompt / Chain Patterns

The RAG quickstart uses two distinct prompt patterns depending on the processing mode:

- **Direct mode**: The frontend builds the prompt explicitly with `CONTEXT:` and `QUERY:` sections. The system prompt is user-configurable (default: "You are a helpful AI assistant.") and sent as a separate system message. When no vector stores are selected, the prompt omits the context section entirely.

- **Agent-based mode**: The system prompt is passed as `instructions` to the Responses API, and the user message is passed as `input`. When `file_search` tools are attached, LlamaStack automatically embeds the user query, retrieves relevant chunks from the vector stores, and injects them into the LLM context. The agent does not need RAG-specific prompt engineering.

Both modes support `reasoning_content` deltas for models that expose chain-of-thought (e.g., DeepSeek R1), displaying reasoning in a collapsible expander before the final response.

### Gotchas

- The search response from `vector_stores.search` is handled with triple format fallback (`data`, `chunks`, `results` attributes at lines 75-80 of `direct.py`) because LlamaStack's response format varies across versions. This is a compatibility concern when upgrading LlamaStack.
- The `search_vector_stores_fallback()` function (lines 233-307 of `agent.py`) explicitly searches vector stores after the Agent-based response stream completes, because the Responses API stream does not consistently include file_search results in its chunks. This provides the user with visibility into what was retrieved, even though the LLM already used the retrieved context.
- The LlamaStackClient timeout defaults to 60 seconds but is configurable via `LLAMA_STACK_TIMEOUT` environment variable (default 600 seconds in `api.py` line 16), necessary for large document uploads that take longer than 60 seconds.
- The ingestion service uses `client.vector_dbs.register()` (line 263 of `ingest.py`) which is the legacy LlamaStack API, while the UI upload page uses `client.vector_stores.create()` (line 179 of `upload.py`) which is the newer OpenAI-compatible API. Both create vector stores in pgvector, but the ingestion service requires `provider_id` (discovered dynamically) while the UI does not.
- The ingestion service uses `client.tool_runtime.rag_tool.insert()` (line 283 of `ingest.py`) for document ingestion with `chunk_size_in_tokens=512`, while the UI upload uses `client.files.create()` + `client.vector_stores.files.create()` (lines 320-332 of `upload.py`). The former chunks documents before insertion; the latter delegates chunking to LlamaStack server-side.
- Docling's `HybridChunker` in the ingestion service filters only for `DocItemLabel.TEXT` and `DocItemLabel.PARAGRAPH` labels (lines 222-225 of `ingest.py`), discarding tables, images, and other content types extracted from PDFs.
- The file upload deduplication uses `f.name + str(f.size)` as a unique key in session state (line 258 of `upload.py`), preventing re-upload of the same file on Streamlit page reruns. This deduplication is per-session only.
- The podman-compose local deployment expects Ollama to run on the host machine rather than in a container, connecting via `host.docker.internal:11434` on macOS/Windows or `172.17.0.1:11434` on Linux (podman-compose.yml lines 5-13). The ingestion service container has `restart: "no"` to run once and exit after processing all pipelines.
- The `get_vector_db_name()` utility (line 113 of `utils.py`) falls back from `vector_db.name` to `vector_db.id`, which is important because LlamaStack may return vector stores without a `name` attribute depending on how they were created (registered vs created).
- The Helm chart depends on six subcharts from `rh-ai-quickstart/ai-architecture-charts`: `pgvector`, `llm-service`, `configure-pipeline`, `ingestion-pipeline`, `llama-stack`, and `mcp-servers`. The `configure-pipeline` subchart handles MinIO setup and sample file upload, while `ingestion-pipeline` handles Kubeflow Pipeline creation.
- The `llama-stack` subchart is configured with `fileProcessors.enabled: true` and `pypdf` provider (values.yaml lines 179-183), enabling LlamaStack's server-side PDF processing for files uploaded via the UI (complementing the Docling-based processing in the ingestion service).
- Input and output shield errors are caught and logged but do not crash the application (line 183 of `utils.py`). The shields execute sequentially; a failed shield check skips to the next shield rather than blocking. This is a fail-open design for shield execution errors (same as Approach A), though a successful violation detection does block the request.
- The suggested questions ConfigMap serializes the questions dictionary as JSON via Helm's `toJson` function (configmap-suggested-questions.yaml line 10). The frontend parses this from `RAG_QUESTION_SUGGESTIONS` environment variable, matching questions to vector stores by both name and ID (lines 246-264 of `utils.py`).

---

## Approach G: Helm-Only Dual-Frontend RAG with Kubernetes Job Seeding (from llm-cpu-serving)

### When to Use

Use this approach when deploying a complete RAG-enabled chat application with zero custom application code -- all component wiring is done through Helm templates and Kubernetes resources. This approach suits scenarios where: no GPUs are available (CPU-only inference), two independent chat interfaces are desired (AnythingLLM workbench for daily use + RHOAI Playground for exploration), documents are a fixed set of web-sourced content seeded at deploy time, and the goal is rapid prototyping or demonstration without writing any backend or frontend code.

### Differences from Approaches A through F

| Aspect | Approach A (LlamaStack) | Approach E (Startup Ingestion) | Approach F (Dual-Mode + Docling) | Approach G (Helm-Only Dual-Frontend) |
|--------|------------------------|-------------------------------|-------------------------------|-------------------------------|
| Application code | Custom FastAPI backend | KnowledgeBaseManager Python class | Streamlit frontend + Docling ingestion service | No custom code (Helm templates only) |
| RAG frontends | Custom React UI | Custom React UI | Streamlit UI (single) | AnythingLLM workbench + RHOAI Playground (two independent UIs) |
| Vector database | pgvector via LlamaStack | pgvector via LlamaStack | pgvector via LlamaStack | Inline Milvus (SQLite-backed) for Llama Stack; LanceDB (built-in) for AnythingLLM |
| Document ingestion | External pipeline via HTTP API | files.create + vector_stores.files.create at startup | Docling service + UI upload | Kubernetes Jobs: llama-stack-client SDK for Llama Stack, curl for AnythingLLM |
| Embedding model | LlamaStack embedding API | LlamaStack server | LlamaStack server | granite-embedding-125m-english (sentence-transformers) for Llama Stack; native for AnythingLLM |
| Llama Stack deployment | Manual pod/service | Manual pod/service | Helm subchart | LlamaStackDistribution CR (Kubernetes operator) |
| Model serving | LlamaStack server + vLLM | LlamaStack server + vLLM | LlamaStack server + vLLM | vLLM CPU via KServe (shared by both frontends) |
| GPU requirements | Lower (LlamaStack manages inference) | Lower (LlamaStack manages inference) | Configurable | None (CPU-only) |
| Document sources | User-uploaded | Curated text files | GitHub/S3/URLs + user uploads | Web URLs (fetched and HTML-stripped by seed job) |
| Document management | FastAPI CRUD API | None | Streamlit UI + OpenAI Files API | None (seed at deploy time, modify via AnythingLLM UI post-deploy) |

### Data Flow

**Llama Stack RAG (via RHOAI Playground):**

1. Helm installs the `LlamaStackDistribution` CR, which the Llama Stack operator reconciles into a running pod with the config from the `llama-stack-config` ConfigMap
2. Llama Stack config registers two inference providers: `sentence-transformers` (inline, for embeddings using `ibm-granite/granite-embedding-125m-english`) and `remote::vllm` (connecting to vLLM at `http://tinyllama-predictor.{namespace}.svc.cluster.local:8080/v1`)
3. Llama Stack config registers `inline::milvus` as the vector_io provider with a local SQLite-backed database
4. The `rag-seed` Kubernetes Job waits for Llama Stack to be ready (polls `/v1/version`), then discovers the namespace admin's username via Kubernetes RoleBindings API
5. The seed job creates or finds a vector store named with the SHA-256 hash of the admin username (matching the RHOAI Playground's auto-provisioning convention)
6. For each seed document URL, the job fetches the web page, strips HTML tags (script/style/nav/header/footer/aside elements), truncates to 60,000 chars, uploads via `client.files.create()`, and indexes via `client.vector_stores.files.create()`
7. User opens the RHOAI Playground, navigates to the Knowledge tab, enables RAG, and chats -- Llama Stack handles embedding, retrieval, and context injection transparently

**AnythingLLM RAG:**

1. Helm deploys AnythingLLM as a Kubeflow Notebook workbench with a SQLite sidecar container for API key setup
2. The SQLite sidecar waits for AnythingLLM's database to be created, then injects an API key (`sk-automation-workspace-setup`) directly into the `api_keys` table
3. The `anythingllm-seed` Kubernetes Job waits for AnythingLLM's API to be healthy (polls `/api/v1/system`)
4. The seed job creates a workspace named from `values.yaml` (`aiLifecoach.workspace.name`), sets the system prompt via `POST /api/v1/workspace/{slug}/update`, and uploads documents via `POST /api/v1/document/upload-link`
5. AnythingLLM processes each document URL internally using its built-in LanceDB vector store and native embedding engine
6. User opens the AnythingLLM workbench from the RHOAI dashboard, selects the pre-created workspace, and chats -- AnythingLLM handles RAG internally using LanceDB

### Component Wiring

| From | To | Protocol | Purpose |
|------|----|----------|---------|
| Llama Stack Distribution | vLLM predictor | REST (port 8080) | LLM inference via remote::vllm provider |
| Llama Stack Distribution | Inline Milvus | Embedded (SQLite file) | Vector storage and similarity search |
| Llama Stack Distribution | sentence-transformers | Inline | Query and document embedding (granite-embedding-125m-english) |
| rag-seed Job | Llama Stack Distribution | HTTP (port 8321, llama-stack-client SDK) | Vector store creation, file upload, file indexing |
| rag-seed Job | External web URLs | HTTPS | Fetch seed document content |
| rag-seed Job | Kubernetes API | HTTPS | Discover namespace admin username from RoleBindings |
| AnythingLLM | vLLM predictor | REST (port 8080) | LLM inference via LocalAI provider |
| AnythingLLM | LanceDB | Embedded | Built-in vector storage and RAG |
| anythingllm-seed Job | AnythingLLM API | REST (port 3001) | Workspace creation, system prompt, document upload-link |
| SQLite sidecar | AnythingLLM DB | Filesystem (shared PVC) | Inject API key into database |
| RHOAI Playground | Llama Stack Distribution | REST (port 8321) | Chat with RAG via Playground UI |

### Key Integration Points

#### LlamaStackDistribution CR for Operator-Managed Deployment

The Llama Stack server is deployed as a `LlamaStackDistribution` custom resource, managed by the Llama Stack Kubernetes operator rather than raw Deployments/Services.

```yaml
# helm/templates/playground.yaml (lines 133-180)
apiVersion: llamastack.io/v1alpha1
kind: LlamaStackDistribution
metadata:
  name: lsd-genai-playground
spec:
  network:
    allowedFrom:
      namespaces:
        - {{ .Release.Namespace }}
    exposeRoute: false
  replicas: 1
  server:
    containerSpec:
      command:
        - /bin/sh
        - -c
        - llama stack run /etc/llama-stack/config.yaml
      env:
        - name: VLLM_MAX_TOKENS
          value: "512"
        - name: VLLM_API_TOKEN_1
          value: fake
      port: 8321
    distribution:
      name: rh-dev
    userConfig:
      configMapName: llama-stack-config
```

#### Inline Milvus with Sentence-Transformers Embeddings

The Llama Stack config uses embedded Milvus (SQLite-backed, no external Milvus cluster) and inline sentence-transformers for embeddings, with the default embedding model set to `ibm-granite/granite-embedding-125m-english` at 768 dimensions.

```yaml
# helm/templates/playground.yaml (ConfigMap llama-stack-config, lines 34-41, 107-112)
vector_io:
- provider_id: milvus
  provider_type: inline::milvus
  config:
    db_path: /opt/app-root/src/.llama/distributions/rh/milvus.db

vector_stores:
  default_provider_id: milvus
  default_embedding_model:
    provider_id: sentence-transformers
    model_id: ibm-granite/granite-embedding-125m-english
```

#### Web Page Seeding via llama-stack-client SDK

The rag-seed Job fetches web pages, strips HTML to extract text, and uploads to the Llama Stack vector store using the OpenAI-compatible files API. It auto-discovers the admin username from Kubernetes RoleBindings to match the RHOAI Playground's auto-provisioned vector store naming convention.

```python
# helm/templates/rag-seed-job.yaml (ConfigMap rag-seed-script, lines 49-145)
from llama_stack_client import LlamaStackClient

client = LlamaStackClient(base_url=base_url, timeout=300)

# Auto-discover namespace admin username from Kubernetes RoleBindings
# ... (queries k8s API for admin RoleBinding subjects)
hashed = hashlib.sha256(username.encode()).hexdigest()[:32]

# Create or find the user's auto-provisioned vector store
vs = client.vector_stores.create(
    name=hashed,
    metadata={"created_by": "auto-provisioning", "username": username},
)

# For each seed document: fetch URL, strip HTML, upload file, index
for doc in seed_docs:
    text = fetch_text(url)  # strips script/style/nav/header/footer/aside tags
    f = client.files.create(
        file=(filename, io.BytesIO(text.encode("utf-8")), "text/plain"),
        purpose="assistants",
    )
    client.vector_stores.files.create(vector_store_id=vs_id, file_id=f.id)
```

#### AnythingLLM API Key Injection via SQLite Sidecar

The AnythingLLM workbench pod includes a SQLite sidecar container that waits for the database to be created, then directly inserts an API key so that the seed Job can authenticate against the AnythingLLM REST API.

```bash
# helm/templates/workbench.yaml (sidecar container args, lines 172-231)
DB_PATH="/opt/app-root/src/anythingllm/storage/anythingllm.db"

# Wait for AnythingLLM to create the database
for i in $(seq 1 120); do
  if [ -f "$DB_PATH" ]; then break; fi
  sleep 1
done

# Insert API key directly into SQLite
sqlite3 "$DB_PATH" << 'EOF'
INSERT OR REPLACE INTO api_keys (secret, createdBy, createdAt, lastUpdatedAt)
VALUES ('sk-automation-workspace-setup', 1, datetime('now'), datetime('now'));
EOF
```

#### AnythingLLM Workspace Seeding via curl

The anythingllm-seed Job uses curl to create a workspace, set its system prompt, and upload seed documents by URL -- all via the AnythingLLM REST API.

```bash
# helm/templates/init_job.yaml (lines 29-75)
SVC="anythingllm-api-internal.${NAMESPACE}.svc.cluster.local:3001"
BASE="http://${SVC}/api/v1"
AUTH="Authorization: Bearer ${ANYTHINGLLM_API_KEY}"

# Create workspace (idempotent)
curl -s -X POST "${BASE}/workspace/new" -H "${AUTH}" \
  -H "Content-Type: application/json" -d "{\"name\":\"${WS_NAME}\"}"

# Set system prompt on workspace
curl -s -X POST "${BASE}/workspace/${WS_SLUG}/update" -H "${AUTH}" \
  -H "Content-Type: application/json" -d '{"openAiPrompt": "..."}'

# Upload documents via link
for URL in ${SEED_URL}; do
  curl -s -X POST "${BASE}/document/upload-link" -H "${AUTH}" \
    -H "Content-Type: application/json" -d "{\"link\":\"${URL}\", \"addToWorkspaces\":\"${WS_SLUG}\"}"
done
```

### Prompt / Chain Patterns

This approach has no custom prompt chain code. Prompts are configured declaratively:

- **AnythingLLM**: The system prompt is set via the seed Job's `openAiPrompt` field, sourced from `values.yaml` (`aiLifecoach.workspace.systemPrompt`). It defines the HR assistant persona for U.S. financial services with instructions on domain context, key areas of expertise, response style, and escalation guidance.
- **RHOAI Playground**: Uses the Playground UI's built-in prompt configuration. RAG is enabled via the Knowledge tab, which activates Llama Stack's file_search tool for transparent retrieval.

Both RAG systems handle context injection internally -- neither requires custom prompt engineering for retrieval-augmented responses.

### Gotchas

- The rag-seed Job auto-discovers the namespace admin's username by querying Kubernetes RoleBindings (lines 57-80 of the seed script in `rag-seed-job.yaml`). It looks for a RoleBinding with `roleRef.name == 'admin'` and extracts the first `User` subject. If no admin RoleBinding exists in the namespace, the job fails with `RuntimeError("Could not find admin User in namespace RoleBindings")`.
- The vector store name uses `hashlib.sha256(username.encode()).hexdigest()[:32]` (line 86 of the seed script) to match the RHOAI Playground's auto-provisioning convention. If the Playground changes its hashing scheme, the pre-seeded vector store will not be discovered by the Playground UI.
- The AnythingLLM SQLite sidecar runs as a separate container (`keinos/sqlite3:latest`) sharing the same PVC as AnythingLLM. It waits up to 120 seconds for the database file to appear, then runs `sleep infinity` to keep the pod alive. This sidecar runs indefinitely and consumes minimal resources (50m CPU, 64Mi memory).
- The AnythingLLM API key (`sk-automation-workspace-setup`) is hardcoded in both the SQLite sidecar script (line 222 of `workbench.yaml`) and the Secret (line 18 of `anythingllm-api.yaml`, base64-encoded). This is a known automation key, not a security credential.
- The `fetch_text()` function in the rag-seed Job performs basic HTML stripping by removing `<script>`, `<style>`, `<nav>`, `<header>`, `<footer>`, `<aside>` elements and all remaining HTML tags (lines 120-128 of the seed script). It truncates extracted text to 60,000 characters. Complex HTML pages (JavaScript-rendered content, deeply nested structures) may produce low-quality text.
- The Milvus vector database in Llama Stack is embedded (SQLite-backed at `/opt/app-root/src/.llama/distributions/rh/milvus.db`), not an external cluster. Data persists only within the pod's filesystem. If the pod restarts without a PVC, the vector store and all indexed documents are lost.
- AnythingLLM uses `EMBEDDING_ENGINE: native` (line 15 of `anythingllm-secret.yaml`), meaning it uses its own built-in embedding engine rather than the vLLM endpoint. The vLLM connection via `LOCAL_AI_BASE_PATH` is used only for LLM inference, not embeddings.
- The anythingllm-seed Job uses `upload-link` (line 72 of `init_job.yaml`) which sends URLs to AnythingLLM for it to fetch and process. AnythingLLM handles the web scraping, chunking, and embedding internally. This contrasts with the rag-seed Job which fetches and processes content externally before uploading to Llama Stack.
- The `LlamaStackDistribution` CR spec includes `network.allowedFrom.namespaces` restricted to the release namespace (line 144 of `playground.yaml`), meaning only pods in the same namespace can reach the Llama Stack service. The `exposeRoute: false` setting prevents external access.

---

## Choosing Between Approaches

| Criteria | Approach A (LlamaStack) | Approach B (NVIDIA RAG Blueprint) | Approach C (FAISS Microservice) | Approach D (Frontend-Driven) | Approach E (Startup Ingestion) | Approach F (Dual-Mode + Docling) | Approach G (Helm-Only Dual-Frontend) |
|----------|------------------------|-----------------------------------|-------------------------------|------------------------------|-------------------------------|-------------------------------|-------------------------------|
| Custom backend logic needed | Yes -- build your own RAG pipeline with FastAPI | No -- use pre-built NVIDIA RAG server | Yes -- standalone RAG service + init pipeline | No -- frontend handles all RAG orchestration | Minimal -- startup ingestion code in KnowledgeBaseManager | Minimal -- Streamlit frontend + separate Docling ingestion service | No -- pure Helm templates and Kubernetes Jobs |
| RAG retrieval integration | Transparent via file_search tool (LlamaStack handles internally) | Explicit via prompt template context injection | HTTP API consumed by agent graph node | Manual context prepend in frontend code | Transparent via file_search tool (LlamaStack handles internally) | Both: Direct mode uses vector_stores.search + manual context prepend; Agent mode uses transparent file_search | Transparent via both AnythingLLM built-in RAG and RHOAI Playground file_search |
| Vector database | pgvector (integrated with LlamaStack) | GPU-accelerated Milvus (GPU_CAGRA index) | FAISS in-memory (loaded from MinIO) | pgvector (integrated with LlamaStack) | pgvector (integrated with LlamaStack, explicit provider_id) | pgvector (integrated with LlamaStack, no explicit provider_id for UI creation) | Inline Milvus (SQLite-backed) for Llama Stack; LanceDB (built-in) for AnythingLLM |
| Document processing | External ingestion pipeline via HTTP API | NV-Ingest with cloud NIMs (OCR, table/graphic detection) | Custom PDF parser (PyPDF-based) | LlamaStack rag_tool.insert (base64 data URL) | Direct files.create + vector_stores.files.create (text files only) | Docling (DocumentConverter + HybridChunker) for pipeline; LlamaStack pypdf provider for UI uploads | Web page fetch + HTML stripping (rag-seed Job); URL upload-link (AnythingLLM seed Job) |
| Model serving | LlamaStack server | vLLM via KServe with MIG-sliced GPUs | TEI for embeddings, separate LLM for inference | LlamaStack server + vLLM via KServe | LlamaStack server + vLLM via KServe | LlamaStack server + vLLM via KServe (GPU/CPU/HPU/Xeon) or Ollama for local dev | vLLM CPU via KServe (shared by both frontends, no GPU) |
| Multimodal support | Not built in | Built-in VLM inference for image captioning | Not built in | Not built in | Not built in | Not built in | Not built in |
| GPU requirements | Lower (LlamaStack manages inference) | Higher (4-5 GPUs or MIG-partitioned) | Minimal (TEI for embeddings, no GPU for FAISS) | Lower (LlamaStack manages inference) | Lower (LlamaStack manages inference) | Configurable (GPU, CPU, HPU, Xeon via device flag in Helm values) | None (CPU-only, designed for GPU-less environments) |
| External dependencies | Minimal (self-contained LlamaStack) | NVIDIA NGC cloud NIMs | MinIO for index storage, TEI for embeddings | Minimal (LlamaStack + pgvector) | Minimal (LlamaStack + pgvector) | Minimal (LlamaStack + pgvector); optional MinIO for configure-pipeline | Minimal (seed document URLs must be reachable from cluster) |
| Retrieval consumer | User-facing agent response | User-facing frontend | Internal agent pipeline (context enrichment) | User-facing frontend (dual-panel comparison) | Agent state machine via LlamaStack Responses API | User-facing frontend (selectable Direct or Agent mode) | Two independent UIs: AnythingLLM workbench + RHOAI Playground |
| Index lifecycle | Managed by LlamaStack API (with dual metadata) | Managed by Milvus | Init job + MinIO pointer file + polling | Managed by LlamaStack API (via frontend) | Created at startup, accumulates across restarts | Managed by LlamaStack API (via ingestion service and frontend) | Seeded at deploy time by Kubernetes Jobs; no lifecycle management |
| Knowledge base type | Dynamic (user-uploaded documents) | Dynamic (user-uploaded documents) | Static (curated PDFs bundled with deployment) | Dynamic (user-uploaded via Streamlit UI) | Static (curated text files bundled or ConfigMap-mounted) | Hybrid: automated from GitHub/S3/URLs at deploy time + dynamic user uploads via UI | Static (web URLs in values.yaml, seeded at deploy time); AnythingLLM allows post-deploy uploads via UI |
| Document management | FastAPI CRUD API + PostgreSQL metadata | Frontend + NV-Ingest APIs | Init job (static) | Streamlit UI + direct pgvector access | None (files deployed with application or via ConfigMap) | Streamlit UI + OpenAI-compatible vector_stores.files API (no direct DB access) | None (seed jobs only); AnythingLLM UI available post-deploy |
| Data sources | User-uploaded documents | User-uploaded documents | Curated PDFs | User-uploaded via UI | Curated text files | GitHub repos, S3/MinIO, URLs (automated) + user uploads via UI | Web URLs (defined in values.yaml) |
| Local development | Not supported | Not supported | Not supported | Not supported | Not supported | Podman Compose with Ollama on host | Not supported |
