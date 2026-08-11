---
name: rag-pipeline
description: RAG patterns from LlamaStack vector stores to NVIDIA Blueprints to standalone FAISS microservices
summary: "Implements retrieval-augmented generation across four approaches: (A) LlamaStack with external ingestion pipeline, pgvector vector stores, and transparent file_search retrieval via Responses API requiring no RAG-specific prompting; (B) NVIDIA RAG Blueprint with NV-Ingest document processing, GPU-accelerated Milvus GPU_CAGRA, vLLM on KServe with MIG-sliced GPUs, NIM-to-vLLM translation proxies for embedding/reranking, and optional query rewriting/reflection/decomposition with /no_think Nemotron directive; (C) standalone FAISS microservice with TEI nomic-embed-text-v1.5 (search_document:/search_query: prefixes), MinIO LATEST.json pointer file for init-job-to-service coordination, and results consumed as agent-internal context enrichment from static PDFs; (D) frontend-only Streamlit using LlamaStack rag_tool APIs with manual CONTEXT: prompt injection, direct pgvector access via asyncpg, all-MiniLM-L6-v2 at 384 dimensions, and triple-fallback vector DB registration. Choose A for custom FastAPI backends needing LlamaStack-integrated transparent retrieval; B for no-custom-code GPU-heavy deployments with pre-built NVIDIA RAG server and built-in multimodal/reranking capabilities; C for agent-pipeline context enrichment from curated PDF knowledge bases with minimal GPU requirements (TEI only); D for minimal-complexity frontend-only demos where RAG is a supporting feature alongside other capabilities like guardrails. Critical config: A requires update_vector_store_ids() to sync dual metadata (PostgreSQL + LlamaStack); B needs cross-chart ConfigMap (ingestor-server-prompt) installed before rag-server, anyuid SCC for three service accounts, and NV-Ingest MESSAGE_CLIENT_HOST hardcoded to ingest-redis-master; C requires TEI connection pooling and FAISS index files on disk (faiss.read_index needs file paths not buffers); D hardcodes embedding dimension 384 and uses direct pgvector queries with vs_{id.replace('-','_')} table naming. Common gotchas: A's dual metadata can desync if update_vector_store_ids fails and RAG only works with LlamaStack runner (not LangGraph/CrewAI); B depends on NVIDIA cloud NIMs for OCR/table/graphic detection (external network dependency) and embedding proxy strips input_type losing query-vs-passage distinction; C's FAISS index must fit entirely in RAM and RAGHandler singleton silently returns empty strings if RAG is disabled; D bypasses LlamaStack for document management via direct pgvector access that breaks if LlamaStack changes its internal schema."
metadata:
  type: architecture
tags:
  tech_stack: [fastapi, llamastack, python, vllm, nvidia-rag-blueprint, langchain, langgraph, gradio, streamlit]
  ai_pattern: [rag, embeddings, vector-search, reranking, multimodal]
  platform: [llamastack, rhoai, openshift, kubernetes, kserve, vllm, tei]
  data_layer: [pgvector, milvus, faiss, minio]
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

## Choosing Between Approaches

| Criteria | Approach A (LlamaStack) | Approach B (NVIDIA RAG Blueprint) | Approach C (FAISS Microservice) | Approach D (Frontend-Driven) |
|----------|------------------------|-----------------------------------|-------------------------------|------------------------------|
| Custom backend logic needed | Yes -- build your own RAG pipeline with FastAPI | No -- use pre-built NVIDIA RAG server | Yes -- standalone RAG service + init pipeline | No -- frontend handles all RAG orchestration |
| RAG retrieval integration | Transparent via file_search tool (LlamaStack handles internally) | Explicit via prompt template context injection | HTTP API consumed by agent graph node | Manual context prepend in frontend code |
| Vector database | pgvector (integrated with LlamaStack) | GPU-accelerated Milvus (GPU_CAGRA index) | FAISS in-memory (loaded from MinIO) | pgvector (integrated with LlamaStack) |
| Document processing | External ingestion pipeline via HTTP API | NV-Ingest with cloud NIMs (OCR, table/graphic detection) | Custom PDF parser (PyPDF-based) | LlamaStack rag_tool.insert (base64 data URL) |
| Model serving | LlamaStack server | vLLM via KServe with MIG-sliced GPUs | TEI for embeddings, separate LLM for inference | LlamaStack server + vLLM via KServe |
| Multimodal support | Not built in | Built-in VLM inference for image captioning | Not built in | Not built in |
| GPU requirements | Lower (LlamaStack manages inference) | Higher (4-5 GPUs or MIG-partitioned) | Minimal (TEI for embeddings, no GPU for FAISS) | Lower (LlamaStack manages inference) |
| External dependencies | Minimal (self-contained LlamaStack) | NVIDIA NGC cloud NIMs | MinIO for index storage, TEI for embeddings | Minimal (LlamaStack + pgvector) |
| Retrieval consumer | User-facing agent response | User-facing frontend | Internal agent pipeline (context enrichment) | User-facing frontend (dual-panel comparison) |
| Index lifecycle | Managed by LlamaStack API | Managed by Milvus | Init job + MinIO pointer file + polling | Managed by LlamaStack API (via frontend) |
| Knowledge base type | Dynamic (user-uploaded documents) | Dynamic (user-uploaded documents) | Static (curated PDFs bundled with deployment) | Dynamic (user-uploaded via Streamlit UI) |
| Document management | FastAPI CRUD API + PostgreSQL metadata | Frontend + NV-Ingest APIs | Init job (static) | Streamlit UI + direct pgvector access |
