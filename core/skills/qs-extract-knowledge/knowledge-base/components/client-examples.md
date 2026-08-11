---
name: client-examples
description: "Python client scripts demonstrating Llama Stack APIs: chat, RAG, shields, web search, and model listing"
summary: "Provides standalone Python scripts demonstrating Llama Stack Server APIs -- chat completions, model listing, agent-based web search (builtin::websearch via Tavily), safety shields (Llama-Guard-3-8B registration, standalone run_shield with threshold/categories params, agent-attached input_shields), and pgvector-backed RAG lifecycle (register, ingest, query, unregister) with provider discovery via client.providers.list(). Use as integration tests and learning tools for verifying a deployed Llama Stack Server; scripts use dual client libraries -- openai SDK for the OpenAI-compatible endpoint and llama-stack-client (pinned >=0.2.9,<0.2.23) for native features like agents, shields, RAG, and vector_io provider listing. Critical config: LLAMA_STACK_SERVER_OPENAI requires the double-v1 path ({server}/v1/openai/v1) with api_key=\"not applicable\" (SDK requires non-empty but server skips auth), and RAG vector DB must use embedding_dimension=384 matching all-MiniLM-L6-v2 with chunk_size_in_tokens=512. Gotchas: rag-delete uses startswith(\"ragged\") risking unintended deletions, dotenv loading is inconsistent across scripts (some use load_dotenv() while others call os.getenv directly), RAG scripts must execute in order (list->create->use->delete), and TAVILY_SEARCH_API_KEY must be configured in Helm values not client env."
metadata:
  type: component
tags:
  tech_stack: [python, openai, llama-stack-client, dotenv, rich]
  ai_pattern: [rag, guardrails, agents, model-serving, vector-search, embeddings]
  platform: [llama-stack, pgvector]
  data_layer: [pgvector]
source_examples:
  - quickstart: "RAG"
    repo: "https://github.com/rh-ai-quickstart/RAG"
    notes: "Standalone Python scripts exercising Llama Stack Server via both OpenAI-compatible and native client SDKs"
    approach: "A"
---

# Client Examples

## Overview

A collection of standalone Python scripts that demonstrate how to interact with a Llama Stack Server. The scripts cover chat completions, model listing, web search, safety shields, and RAG vector database operations. They serve as a learning tool and integration test suite for verifying that a deployed Llama Stack Server is working correctly.

## Tech Stack & Dependencies

- **Runtime:** Python 3.11
- **Key dependencies:** `openai`, `llama-stack-client>=0.2.9,<0.2.23`, `dotenv`, `rich`
- **Container image:** None (standalone scripts, not containerized)
- **Helm subchart:** None

## Key Patterns

### Dual Client Libraries

The examples use two distinct client libraries depending on the API surface being exercised. Scripts targeting the OpenAI-compatible endpoint use the `openai` SDK, while scripts using native Llama Stack features (agents, shields, RAG, tool groups) use `llama-stack-client`.

```python
# OpenAI-compatible client (chat-completions.py, list-models.py)
from openai import OpenAI
client = OpenAI(
    api_key="not applicable",
    base_url=LLAMA_STACK_SERVER_OPENAI,
)
```

```python
# Native Llama Stack client (web-search.py, rag-*.py, *-shield*.py)
from llama_stack_client import LlamaStackClient
client = LlamaStackClient(
    base_url=LLAMA_STACK_SERVER
)
```

The `api_key` is set to `"not applicable"` for the OpenAI client because Llama Stack Server does not require API key authentication.

### Agent-Based Web Search

Web search uses the Llama Stack Agent abstraction with the `builtin::websearch` tool, which requires a `TAVILY_SEARCH_API_KEY` configured in the Llama Stack Server Helm values.

```python
# web-search.py
agent = Agent(
    client,
    model=INFERENCE_MODEL,
    instructions="You are a helpful assistant.",
    tools=["builtin::websearch"],
    input_shields=[],
    output_shields=[],
    enable_session_persistence=False
)
session_id = agent.create_session(f"test-session-{uuid4()}")
response = agent.create_turn(
    messages=[{"role": "user", "content": "Who won the 2025 Super Bowl?"}],
    session_id=session_id,
)
```

### RAG Vector Database Lifecycle

The RAG examples demonstrate the full lifecycle of a pgvector-backed vector database: register, ingest documents, query, and unregister. The vector DB uses a specific embedding model and dimension.

```python
# rag-create-vector-db.py
vector_db = client.vector_dbs.register(
    vector_db_id="ragged-db",
    embedding_dimension=384,
    embedding_model="all-MiniLM-L6-v2",
    provider_id="pgvector"
)
client.tool_runtime.rag_tool.insert(
    documents=documents,
    vector_db_id=vector_db_id,
    chunk_size_in_tokens=512,
)
```

```python
# rag-use-vector-db.py — query and inject into prompt
rag_response = client.tool_runtime.rag_tool.query(
    content=user_query,
    vector_db_ids=[vector_db_id]
)
messages = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": f"""
        Answer the question based on the context provided.
        Context: {rag_response.content}
        Question: {user_query}
    """},
]
```

### Safety Shields

Shields provide input/output guardrails. Registration maps a shield ID to a guard model, then the shield can be used standalone or attached to an Agent.

```python
# register-shield.py
client.shields.register(
    shield_id="content_safety",
    provider_shield_id="meta-llama/Llama-Guard-3-8B"
)
```

```python
# test-shield.py — standalone shield check
response = client.safety.run_shield(
    shield_id="content_safety",
    messages=[{"role": "user", "content": user_message}],
    params={"threshold": 0.1, "categories": ["hate", "violence", "profanity"]}
)
if response.violation:
    print(f"Safety violation detected: {response.violation.user_message}")
```

```python
# test-shield.py — shield attached to an Agent
agent = Agent(
    client,
    model=INFERENCE_MODEL,
    instructions="You are a helpful assistant.",
    input_shields=["content_safety"],
    output_shields=[],
    enable_session_persistence=False
)
```

### Vector DB Provider Discovery

Scripts list both registered vector databases and available vector I/O providers, useful for determining which backends are configured.

```python
# rag-list-vector-db.py
providers = client.providers.list()
for provider in providers:
    if provider.api == "vector_io":
        pprint(f"Vector DB Provider: {provider.provider_id}")
```

## Configuration

- **Environment variables:**
  - `LLAMA_STACK_SERVER` -- base URL for Llama Stack Server (e.g., `http://localhost:8321`), used by the native `LlamaStackClient`
  - `LLAMA_STACK_SERVER_OPENAI` -- OpenAI-compatible endpoint, derived as `${LLAMA_STACK_SERVER}/v1/openai/v1`, used by the `openai` SDK
  - `INFERENCE_MODEL` -- model identifier for inference (e.g., `meta-llama/Llama-3.2-3B-Instruct`)
  - `TAVILY_SEARCH_API_KEY` -- required for web search, configured in Helm values not in the script env
- **Config files:** `.env` file supported via `dotenv` for local development
- **Helm values:** Web search requires `TAVILY_SEARCH_API_KEY` set under `llama-stack.secrets` in `deploy/helm/rag/values.yaml`

## Known Gotchas

- The OpenAI-compatible endpoint path is `{LLAMA_STACK_SERVER}/v1/openai/v1` -- note the double `v1` segments. The README explicitly sets `LLAMA_STACK_SERVER_OPENAI=$LLAMA_STACK_SERVER/v1/openai/v1` to construct this path.
- The `api_key` parameter for the OpenAI client is set to the literal string `"not applicable"` because the OpenAI SDK requires a non-empty value but Llama Stack Server does not enforce API key auth.
- The `llama-stack-client` library is pinned to `>=0.2.9,<0.2.23`, indicating potential breaking changes across minor versions.
- Not all scripts use `dotenv` consistently -- `list-shields.py` and `register-shield.py` read env vars directly via `os.getenv` without loading `.env`, while most others call `load_dotenv()`.
- The RAG vector DB uses `embedding_dimension=384` with `all-MiniLM-L6-v2` -- these must match. Using a different embedding model requires updating the dimension accordingly.
- The `rag-delete-vector-db.py` script deletes vector DBs whose identifier starts with `"ragged"` using `startswith()`, which could delete unintended databases if naming is not careful.

## Testing Notes

- Run `python list-models.py` first to verify connectivity to the Llama Stack Server and identify available model names
- The RAG scripts should be run in order: `rag-list-vector-db.py` -> `rag-create-vector-db.py` -> `rag-list-vector-db.py` -> `rag-use-vector-db.py` -> `rag-delete-vector-db.py`
- Shield registration (`register-shield.py`) must run before `test-shield.py`
- Web search requires the Tavily API key to be configured in the Llama Stack Server deployment, not in the client environment
- The PostgreSQL database `rag_blueprint` can be inspected directly via `psql` on the OpenShift console to verify vector store tables are created

## Related Patterns

- `llamastack.md` -- Llama Stack Server deployment and configuration
- `pgvector.md` -- PostgreSQL vector database used as the RAG backend
