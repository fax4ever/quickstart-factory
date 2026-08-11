---
name: fastapi-backend
description: "FastAPI backend with multi-runner agent dispatch (LlamaStack, LangGraph, CrewAI), async PostgreSQL, and MCP tool integration"
summary: "Provides a pluggable multi-runner FastAPI backend (Python 3.12/UBI9) that dispatches AI agent chat requests to LlamaStack, LangGraph, or CrewAI frameworks via per-agent runner_type, with all runners streaming normalized SSE events (response, reasoning, tool_call, node_started/completed, error) and a declarative GraphEngine building LangGraph StateGraphs from YAML node configs with auto-detected data dependencies for parallel fan-out. Use when building a multi-framework agent backend needing pluggable runner dispatch, MCP tool integration via JSON-RPC with K8s MCPServer CRD discovery, YAML-defined agent templates by domain, and async PostgreSQL (SQLAlchemy/asyncpg) with Alembic migrations -- single approach from ai-virtual-agent. LLM resolution follows runner-specific env var (LANGGRAPH_LLM_API_BASE, CREWAI_LLM_API_BASE) > agent model_name > fallback default with __env_default__ sentinel; two main.py files where backend/main.py is production entry with pysqlite3 module swap (must execute before any imports for UBI9 SQLite 3.34 vs ChromaDB 3.35), SPA static files with dev proxy fallback, and deferred lifespan startup loading templates into the database. CrewAI auto-prefixes models with openai/ for LiteLLM routing and silently drops tools for small models (1B-3B); Alembic requires postgresql+asyncpg:// to postgresql:// URL conversion; MCP sessions cached at module level auto-refresh on 400/404 but LangGraph InMemorySaver must be swapped for PostgresSaver in multi-worker deployments; providers router must register before models router to prevent /{model_id:path} catch-all interception."
metadata:
  type: component
tags:
  tech_stack: [fastapi, python, postgresql, sqlalchemy, alembic, asyncpg, langchain, langgraph, crewai, litellm, httpx, pydantic]
  ai_pattern: [agents, model-serving, rag, guardrails, mcp, tool-use]
  platform: [llamastack, openshift, kubernetes]
  data_layer: [pgvector, postgresql]
source_examples:
  - quickstart: "ai-virtual-agent"
    repo: "https://github.com/rh-ai-quickstart/ai-virtual-agent"
    notes: "Multi-runner FastAPI backend dispatching to LlamaStack, LangGraph, and CrewAI agents with MCP tool integration and declarative graph engine"
    approach: "A"
---

# FastAPI Backend

## Overview

A FastAPI backend serving as the central API layer for the AI Virtual Agent quickstart. It provides a pluggable multi-runner architecture that dispatches chat requests to LlamaStack, LangGraph, or CrewAI agent frameworks based on per-agent configuration. The backend manages virtual agent definitions, chat sessions, knowledge bases, guardrails, and MCP tool integration, all backed by async PostgreSQL via SQLAlchemy.

## Tech Stack & Dependencies

- **Runtime:** Python 3.12 on `registry.access.redhat.com/ubi9/python-312:latest`
- **Container image:** Multi-stage Containerfile bundles built React frontend into FastAPI static files
- **Key dependencies:**
  - `fastapi`, `uvicorn[standard]` -- ASGI web framework and server
  - `sqlalchemy[asyncio]`, `asyncpg`, `alembic` -- async ORM, PostgreSQL driver, migrations
  - `llama-stack==0.6.1`, `llama_stack_client==0.6.1` -- LlamaStack Responses API
  - `langgraph`, `langchain-openai`, `langchain-mcp-adapters` -- LangGraph ReAct agent and MCP tool bridge
  - `crewai`, `crewai[tools]`, `litellm` -- CrewAI multi-agent framework with LiteLLM routing
  - `httpx` -- async HTTP for MCP JSON-RPC calls
  - `kubernetes` -- in-cluster MCP server discovery
  - `pysqlite3-binary` -- SQLite >= 3.35 shim for ChromaDB (CrewAI dependency) on UBI9
- **Helm subchart:** None (deployed via Containerfile + compose.yaml for local dev, single Containerfile for cluster)

## Key Patterns

### Multi-Runner Chat Dispatch

The `ChatService` resolves the agent's `runner_type` field and delegates to the matching runner. All runners implement `BaseRunner.stream()` and yield normalized SSE events (`response`, `reasoning`, `tool_call`, `node_started`, `node_completed`, `error`). The frontend consumes a single SSE protocol regardless of which agent framework runs underneath.

```python
# backend/app/services/chat.py
VALID_RUNNER_TYPES = {"llamastack", "langgraph", "crewai"}

class ChatService:
    def _get_runner(self, runner_type: str) -> BaseRunner:
        if runner_type == "llamastack" or not runner_type:
            return LlamaStackRunner(self.request, self.db, self.user_id)
        elif runner_type == "langgraph":
            from .runners.langgraph_runner import LangGraphRunner
            return LangGraphRunner(self.request, self.db, self.user_id)
        elif runner_type == "crewai" or runner_type == "crewai_react":
            from .runners.crewai_runner import CrewAIRunner
            return CrewAIRunner(self.request, self.db, self.user_id)
```

### Application Factory with Deferred Startup

The production entry point (`backend/main.py`) uses a lifespan context manager that schedules template population as a background task after the server starts accepting connections. This avoids blocking startup while ensuring agent templates are loaded from YAML files into the database.

```python
# backend/main.py
@asynccontextmanager
async def lifespan(app: FastAPI):
    async def run_startup_tasks():
        await asyncio.sleep(3)  # Wait for server readiness
        await startup_tasks()
    task = asyncio.create_task(run_startup_tasks())
    yield
    if not task.done():
        task.cancel()
```

### pysqlite3 Module Swap for UBI9

UBI9 ships SQLite 3.34, but ChromaDB (pulled in by CrewAI) requires >= 3.35. The root `backend/main.py` patches `sys.modules` before any other imports to swap in `pysqlite3`.

```python
# backend/main.py (must be first lines)
__import__("pysqlite3")
import sys
sys.modules["sqlite3"] = sys.modules.pop("pysqlite3")
```

### Declarative Graph Engine

The `GraphEngine` builds a LangGraph `StateGraph` from a YAML-style config dict defining typed nodes (`llm`, `mcp_tool`, `mcp_tool_map`, `router`). It auto-detects data dependencies between nodes via template references (`{outputs.node_id}`) and wires parallel fan-out edges accordingly, with no explicit edge definitions required.

```python
# backend/app/services/runners/graph_engine.py
class GraphEngine:
    def _build_graph(self):
        graph = StateGraph(GraphState)
        for step in self.nodes:
            graph.add_node(step_id, self._make_step_fn(step))
        # Auto-analyse data dependencies for parallel fan-out
        deps = {nid: _extract_output_deps(step) for nid, step in ...}
        for nid in node_ids:
            if deps[nid]:
                for dep in deps[nid]:
                    graph.add_edge(dep, nid)
            else:
                graph.add_edge(START, nid)
        return graph.compile()
```

### YAML Agent Templates with Suite Organization

Agent configurations are defined in YAML files under `backend/agent_templates/`, organized by domain (banking, legal, travel). Each file defines a template suite with category metadata and one or more agent templates including runner type, model, prompt, tools, and optional `graph_config` for declarative graph agents.

```yaml
# backend/agent_templates/travel_vacation_planner.yaml
name: "Travel Vacation Planner (LangGraph)"
category: "travel"
templates:
  vacation_planner:
    name: "Vacation Planner"
    runner_type: "langgraph"
    model_name: "meta-llama/Llama-3.1-8B-Instruct"
    graph_config:
      mcp:
        servers:
          travel_research:
            url: "${TRAVEL_RESEARCH_MCP_URL:http://localhost:7001/mcp}"
      nodes:
        - id: places_list_task
          type: llm
          internal: true
          prompt: "List 5 specific places..."
```

### Async Database Layer with Session Dependency

SQLAlchemy async engine and session factory using `asyncpg` driver. Database sessions are provided via FastAPI dependency injection through `get_db()`.

```python
# backend/app/database.py
engine = create_async_engine(settings.DATABASE_URL, echo=settings.DEBUG)
AsyncSessionLocal = sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False
)

async def get_db() -> Generator[AsyncSession, None, None]:
    async with AsyncSessionLocal() as session:
        yield session
```

### Alembic Migration with Async-to-Sync URL Conversion

Alembic runs synchronous migrations but the app uses `postgresql+asyncpg://`. The migration env.py automatically converts the async URL to synchronous format and seeds admin users after migrations.

```python
# backend/migrations/env.py
if db_url_from_env.startswith("postgresql+asyncpg://"):
    db_url_from_env = db_url_from_env.replace(
        "postgresql+asyncpg://", "postgresql://", 1
    )
```

### MCP Tool Integration via JSON-RPC

The graph engine calls MCP tools over HTTP using the JSON-RPC protocol with session management. It handles session initialization, tool discovery, input schema filtering (to prevent `-32602` errors from extra arguments), and SSE response parsing.

```python
# backend/app/services/runners/graph_engine.py
async def _call_mcp_tool(client, url, tool_name, arguments):
    session_id = await _get_mcp_session(client, url)
    payload = {
        "jsonrpc": "2.0", "id": 3,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    # ... handles session refresh on 400/404
```

### Kubernetes MCP Server Discovery

The `K8sMCPDiscovery` service discovers MCP servers in the cluster by querying `MCPServer` custom resources (from `toolhive.stacklok.dev/v1alpha1`) and Kubernetes Services with the label `app.kubernetes.io/component=mcp-server`.

```python
# backend/app/services/k8s_mcp_discovery.py
class K8sMCPDiscovery:
    def discover_mcp_servers(self):
        # 1. MCPServer CRDs with label app.kubernetes.io/component=mcp-server
        # 2. Service resources with same label
        # Constructs URLs based on mcp.transport label (sse vs streamable-http)
```

### LLM Model Resolution Chain

Each runner resolves the LLM model through a chain: runner-specific env var > agent's `model_name` > fallback default. A sentinel value `__env_default__` in agent configs triggers environment-based resolution, and `LOCAL_DEV_ENV_MODE` overrides to `DEFAULT_INFERENCE_MODEL`.

```python
# backend/app/services/runners/langgraph_runner.py
def _create_llm(self, agent):
    base_url = settings.LANGGRAPH_LLM_API_BASE
    if not base_url and settings.LLAMA_STACK_URL:
        base_url = f"{settings.LLAMA_STACK_URL}/v1"
    model_name = agent.model_name
    if not model_name or model_name == ENV_DEFAULT_MODEL_SENTINEL:
        model_name = settings.LANGGRAPH_DEFAULT_MODEL
```

### SPA Static Files with Dev Proxy

The production Containerfile bundles the React frontend build output into `backend/public/`. A custom `SPAStaticFiles` handler falls back to `index.html` for client-side routing (404 -> index.html), and in dev mode proxies requests to the React dev server.

```python
# backend/main.py
class SPAStaticFiles(StaticFiles):
    async def get_response(self, path, scope):
        if len(sys.argv) > 1 and sys.argv[1] == "dev":
            async with httpx.AsyncClient() as http_client:
                response = await http_client.get(f"http://localhost:8000/{path}")
            return Response(response.text, status_code=response.status_code)
        else:
            try:
                return await super().get_response(path, scope)
            except (HTTPException, StarletteHTTPException) as ex:
                if ex.status_code == 404:
                    return await super().get_response("index.html", scope)
```

## Configuration

- **Environment variables:**
  - `DATABASE_URL` -- async PostgreSQL connection string (default: `sqlite+aiosqlite:///:memory:`)
  - `LLAMA_STACK_URL` -- LlamaStack server endpoint
  - `DEFAULT_INFERENCE_MODEL` -- fallback model for local dev (e.g., `ollama/llama3.2:1b`)
  - `LANGGRAPH_LLM_API_BASE` / `LANGGRAPH_LLM_API_KEY` / `LANGGRAPH_DEFAULT_MODEL` -- LangGraph runner LLM config
  - `CREWAI_LLM_API_BASE` / `CREWAI_LLM_API_KEY` / `CREWAI_DEFAULT_MODEL` -- CrewAI runner LLM config (uses LiteLLM routing, model must be provider-prefixed e.g., `openai/llama-4-scout-17b`)
  - `LOCAL_DEV_ENV_MODE` -- bypasses OAuth auth, creates dev user with admin role
  - `DISABLE_ATTACHMENTS` -- toggle MinIO attachment features
  - `TRAVEL_RESEARCH_MCP_URL` / `HOTEL_MCP_URL` / `FLIGHT_MCP_URL` -- MCP server URLs for vacation planner graph
  - `ENABLE_COVERAGE` -- enables integration test coverage collection endpoint
- **Config files:**
  - `backend/app/config.py` -- centralized `Settings` class reading all env vars
  - `backend/agent_templates/*.yaml` -- agent template definitions by domain
  - `backend/migrations/` -- Alembic migration versions
- **Helm values:** N/A (uses compose.yaml for local, Containerfile for cluster deployment)

## Known Gotchas

- **pysqlite3 import order:** The `pysqlite3` module swap in `backend/main.py` must execute before any other import that touches `sqlite3`. This is specifically needed because CrewAI depends on ChromaDB, which requires SQLite >= 3.35, but UBI9 ships 3.34. The swap only appears in the production entry point, not in `backend/app/main.py` (the app factory used in tests).
- **Alembic async URL conversion:** Alembic migration `env.py` must convert `postgresql+asyncpg://` URLs to `postgresql://` because Alembic runs synchronous connections. Forgetting this causes connection errors during `alembic upgrade head`.
- **CrewAI LiteLLM model prefixing:** CrewAI routes through LiteLLM which requires provider-prefixed model names (e.g., `openai/model-name`). The `_to_litellm_model()` method auto-prefixes with `openai/` if no provider prefix is present. If `CREWAI_DEFAULT_MODEL` already has a prefix like `openai/`, it won't be double-prefixed.
- **MCP session invalidation:** The graph engine caches MCP sessions at module level (`_MCP_SESSIONS` dict). If a session becomes invalid (server restart), tool calls fail with 400/404. The engine handles this by detecting "session" in error responses and refreshing the session automatically.
- **Router registration order matters:** In `backend/app/api/v1/router.py`, the providers router is registered BEFORE the models router to prevent the `/{model_id:path}` catch-all from intercepting `/providers/` requests. A comment in the code warns about this.
- **InMemorySaver for LangGraph checkpoints:** The LangGraph runner uses `InMemorySaver` as the checkpointer singleton. A code comment notes this is sufficient for single-process dev but must be swapped for `PostgresSaver` in multi-worker production deployments.
- **Small model tool dropping:** The CrewAI runner detects models too small for reliable ReAct tool loops (1B, 2B, 3B parameter models) via regex and silently drops all tools, making the agent respond directly without tool use.
- **Two main.py files:** `backend/main.py` is the production entry point (with pysqlite3 swap, SPA static files, startup template population), while `backend/app/main.py` is a simpler app factory used for testing. The production entry point imports from the app factory's router.

## Testing Notes

- Health check available at `GET /api/v1/health` returning `{"status": "healthy"}`
- The compose.yaml healthcheck uses `curl -f http://localhost:8000/docs` (OpenAPI docs endpoint)
- Coverage collection endpoint at `GET /admin/coverage` when `ENABLE_COVERAGE=true`
- `LOCAL_DEV_ENV_MODE=true` creates a dev user with admin role and bypasses OAuth headers (`X-Forwarded-User`, `X-Forwarded-Email`)

## Related Patterns

- Deployment: compose.yaml orchestrates db, ollama, llamastack, backend, frontend, MCP servers, and optional MinIO
- MCP servers: separate Containerfiles under `mcp_servers/` (travel_research, hotel, flight)
- Agent templates define the agent configuration including runner_type that selects the execution framework
