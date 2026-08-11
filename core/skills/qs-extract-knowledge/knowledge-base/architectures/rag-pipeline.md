---
name: rag-pipeline
description: RAG via LlamaStack vector stores with external ingestion pipelines and file_search tools
summary: "Implements retrieval-augmented generation via two approaches: (A) custom FastAPI backend coordinating PostgreSQL metadata (async SQLAlchemy) and LlamaStack vector stores (AsyncLlamaStackClient) with an external ingestion pipeline, wiring retrieval into agent responses via file_search tools in the Responses API; (B) NVIDIA's pre-built RAG Blueprint server with NV-Ingest document processing (cloud NIMs for OCR/table/graphic detection), GPU-accelerated Milvus (GPU_CAGRA index), 4 vLLM models on KServe with MIG-sliced GPUs, and NIM-to-vLLM translation proxies -- no custom backend code. Choose Approach A (builtin::rag toolgroup + LlamaStackRunner) for custom RAG logic with agent orchestration integration and lower GPU requirements -- LangGraph/CrewAI runners lack built-in RAG; choose Approach B when multimodal VLM inference, built-in reranking/query rewriting/reflection, and no-code Helm-only deployment are needed, accepting cloud NIM dependencies and 4-5 GPU or MIG-partitioned resource costs. A defaults ingestion pipeline URL to http://llamastack:8321/ingestion_pipeline/ (override via INGESTION_PIPELINE_URL), with build_responses_tools mapping builtin::rag to file_search using vector_store_ids resolved from knowledge_base_ids; B injects retrieved chunks via {context} placeholder in rag_template with /no_think directive for Nemotron models, provisions S3 via ODF ObjectBucketClaim, and uses embedding/ranking proxies to strip NIM-specific fields (input_type, truncate, dimensions, query.text/passages format) for vLLM compatibility. A's dual-state metadata (PostgreSQL + LlamaStack) requires update_vector_store_ids sync on every list operation (stale IDs persist on failure) with cascade deletes across three systems after verifying no agents reference the KB; B requires ingest chart before rag-server (cross-chart ConfigMap dependency), hardcodes NV-Ingest Redis hostname to ingest-redis-master (breaks on release rename), needs anyuid SCC for three service accounts, and embedding proxy strips input_type so vLLM cannot distinguish query vs passage embeddings."
metadata:
  type: architecture
tags:
  tech_stack: [fastapi, llamastack, python, vllm, nvidia-rag-blueprint]
  ai_pattern: [rag, embeddings, vector-search, reranking, multimodal]
  platform: [llamastack, rhoai, openshift, kubernetes, kserve, vllm]
  data_layer: [pgvector, milvus]
source_examples:
  - quickstart: "ai-virtual-agent"
    repo: "https://github.com/rh-ai-quickstart/ai-virtual-agent"
    notes: "RAG via LlamaStack vector stores with external ingestion pipeline API and file_search tool integration into agent responses"
    approach: "A"
  - quickstart: "aml-rag-nvidia"
    repo: "https://github.com/rh-ai-quickstart/aml-rag-nvidia"
    notes: "NVIDIA RAG Blueprint server with NV-Ingest document processing, GPU-accelerated Milvus, vLLM via KServe, and NIM-to-vLLM translation proxies -- no custom backend code"
    approach: "B"
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

## Choosing Between Approaches

| Criteria | Approach A (LlamaStack) | Approach B (NVIDIA RAG Blueprint) |
|----------|------------------------|-----------------------------------|
| Custom backend logic needed | Yes -- build your own RAG pipeline with FastAPI | No -- use pre-built NVIDIA RAG server |
| RAG retrieval integration | Transparent via file_search tool (LlamaStack handles internally) | Explicit via prompt template context injection |
| Vector database | pgvector (integrated with LlamaStack) | GPU-accelerated Milvus (GPU_CAGRA index) |
| Document processing | External ingestion pipeline via HTTP API | NV-Ingest with cloud NIMs (OCR, table/graphic detection) |
| Model serving | LlamaStack server | vLLM via KServe with MIG-sliced GPUs |
| Multimodal support | Not built in | Built-in VLM inference for image captioning and query answering |
| GPU requirements | Lower (LlamaStack manages inference) | Higher (4-5 GPUs or MIG-partitioned 2-3 GPUs) |
| External dependencies | Minimal (self-contained LlamaStack) | NVIDIA NGC cloud NIMs for document processing |
| Agent integration | Directly wired into agent orchestration via builtin::rag | Standalone RAG server, no agent framework |
| Customization level | Full control over RAG pipeline behavior | Limited to NVIDIA RAG server feature flags and prompt templates |
