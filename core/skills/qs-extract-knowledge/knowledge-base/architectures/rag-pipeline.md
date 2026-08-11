---
name: rag-pipeline
description: RAG via LlamaStack vector stores with external ingestion pipelines and file_search tools
summary: "Implements retrieval-augmented generation by managing knowledge bases as LlamaStack vector stores, delegating document ingestion to an external pipeline service, and wiring retrieval into agent responses via the file_search tool type in the Responses API. Use when building RAG with the LlamaStack runner and builtin::rag toolgroup -- LangGraph and CrewAI runners lack built-in RAG integration and require custom retriever tool implementations. External ingestion pipeline URL defaults to http://llamastack:8321/ingestion_pipeline/ (override via INGESTION_PIPELINE_URL env var); the FastAPI backend coordinates metadata in PostgreSQL via async SQLAlchemy and vector store lifecycle via AsyncLlamaStackClient, with LlamaStackRunner.build_responses_tools mapping builtin::rag to file_search tools using vector_store_ids resolved from knowledge_base_ids. Dual-state metadata between PostgreSQL and LlamaStack requires update_vector_store_ids sync on every list operation; deleting a knowledge base must cascade across LlamaStack vector store, ingestion pipeline, and local database after verifying no agents reference it; stale vector_store_id values persist if sync fails."
metadata:
  type: architecture
tags:
  tech_stack: [fastapi, llamastack, python]
  ai_pattern: [rag, embeddings, vector-search]
  platform: [llamastack, rhoai, openshift, kubernetes]
  data_layer: [pgvector]
source_examples:
  - quickstart: "ai-virtual-agent"
    repo: "https://github.com/rh-ai-quickstart/ai-virtual-agent"
    notes: "RAG via LlamaStack vector stores with external ingestion pipeline API and file_search tool integration into agent responses"
    approach: "A"
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
