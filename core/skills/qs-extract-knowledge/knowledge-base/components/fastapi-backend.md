---
name: fastapi-backend
description: "FastAPI backend with multi-runner agent dispatch (LlamaStack, LangGraph, CrewAI), async PostgreSQL, and MCP tool integration"
summary: "Covers two FastAPI backend approaches for AI quickstarts: Approach A (ai-virtual-agent, Python 3.12/UBI9) delivers pluggable multi-runner dispatch to LlamaStack, LangGraph, or CrewAI with normalized SSE streaming (response, reasoning, tool_call, node_started/completed, error) and a declarative GraphEngine building StateGraphs from YAML node configs with auto-detected data dependencies for parallel fan-out; Approach B (ansible-log-analysis, Python 3.12/UBI8) implements a single-purpose LangGraph pipeline for event-driven log analysis with cluster-summarize-classify-route-solve steps using Command-based routing, Pydantic structured output, and sklearn log clustering. Use Approach A for interactive multi-framework agent platforms needing per-agent runner_type selection, domain-organized YAML agent templates (banking/legal/travel), MCP tool integration via JSON-RPC with K8s MCPServer CRD discovery, and SQLAlchemy/asyncpg with Alembic migrations; use Approach B for fixed event-driven pipelines needing configurable clustering algorithms (DBSCAN/HDBSCAN/MeanShift/Agglomerative) with sentence embeddings, dual LLM endpoints (tool-calling workaround for RHOAI models), Phoenix/OTEL tracing, MinIO for ML artifacts, and uv packaging with PyTorch CPU-only index. Approach A LLM resolution follows runner-specific env var (LANGGRAPH_LLM_API_BASE, CREWAI_LLM_API_BASE) > agent model_name > fallback default with __env_default__ sentinel; two main.py files where backend/main.py is production entry with pysqlite3 module swap (must execute before any imports for UBI9 SQLite 3.34 vs ChromaDB 3.35), SPA static files with dev proxy fallback, and deferred lifespan startup loading domain templates into the database. CrewAI auto-prefixes models with openai/ for LiteLLM routing and silently drops tools for small models (1B-3B); Alembic requires postgresql+asyncpg:// to postgresql:// URL conversion; MCP sessions cached at module level auto-refresh on 400/404 but LangGraph InMemorySaver must be swapped for PostgresSaver in multi-worker deployments; providers router must register before models router to prevent /{model_id:path} catch-all interception; Approach B prompts load from disk at import time requiring repo-root working directory."
metadata:
  type: component
tags:
  tech_stack: [fastapi, python, postgresql, sqlalchemy, alembic, asyncpg, langchain, langgraph, crewai, litellm, httpx, pydantic, sqlmodel, uvicorn, scikit-learn, sentence-transformers, faiss, minio, phoenix, opentelemetry]
  ai_pattern: [agents, model-serving, rag, guardrails, mcp, tool-use, embeddings, clustering, log-analysis, structured-output]
  platform: [llamastack, openshift, kubernetes, grafana, loki]
  data_layer: [pgvector, postgresql, minio, faiss]
source_examples:
  - quickstart: "ai-virtual-agent"
    repo: "https://github.com/rh-ai-quickstart/ai-virtual-agent"
    notes: "Multi-runner FastAPI backend dispatching to LlamaStack, LangGraph, and CrewAI agents with MCP tool integration and declarative graph engine"
    approach: "A"
  - quickstart: "ansible-log-analysis"
    repo: "https://github.com/rh-ai-quickstart/ansible-log-analysis"
    notes: "Single-purpose LangGraph agentic pipeline for Ansible log analysis with clustering, RAG context retrieval, Loki integration, and Grafana alert processing"
    approach: "B"
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

---

## Approach B: Agentic Log Analysis Pipeline (from ansible-log-analysis)

### When to Use

When building a single-purpose agentic backend that processes incoming events (e.g., Grafana alerts, log entries) through a fixed LangGraph pipeline of summarize-classify-route-solve steps, with optional context enrichment from external services (Loki, RAG), log clustering via sklearn, and batch offline training capabilities. Suited for event-driven log analysis rather than interactive multi-framework agent dispatch.

### Differences from Approach A

- **Base image:** UBI8 (`registry.access.redhat.com/ubi8/python-312`) instead of UBI9
- **ORM:** SQLModel (Pydantic + SQLAlchemy hybrid) with `create_all` table initialization instead of raw SQLAlchemy + Alembic migrations
- **Architecture:** Single fixed LangGraph pipeline (summarize -> classify -> route -> solve) instead of multi-runner dispatch across frameworks
- **LLM access:** Single `ChatOpenAI` via OpenAI-compatible endpoint (RHOAI or external) with a separate tool-calling LLM workaround, instead of per-runner LLM resolution chains
- **Packaging:** `uv` with PyTorch CPU-only from custom index, instead of pip/Poetry
- **Agent style:** LangGraph `Command`-based node routing with Pydantic structured output schemas, instead of declarative YAML graph engine
- **Observability:** Phoenix/OTEL tracing for LangChain, instead of no built-in tracing
- **Storage:** MinIO for ML model artifacts (clustering models, RAG indexes), instead of MinIO for user attachments

### Tech Stack & Dependencies

- **Runtime:** Python 3.12 on `registry.access.redhat.com/ubi8/python-312`
- **Container image:** Multi-stage Containerfile using `uv sync` with PyTorch CPU-only index
- **Key dependencies:**
  - `fastapi`, `uvicorn` -- ASGI web framework and server
  - `sqlmodel`, `asyncpg`, `psycopg2-binary` -- SQLModel ORM with async PostgreSQL
  - `langchain`, `langchain-openai`, `langgraph` -- LangGraph pipeline and LLM integration
  - `scikit-learn`, `sentence-transformers`, `faiss-cpu` -- log clustering and embeddings
  - `minio` -- object storage for ML model artifacts
  - `arize-phoenix-otel`, `openinference-instrumentation-langchain` -- tracing
  - `httpx` -- async HTTP client for RAG service and MCP communication
  - `torch==2.9.0+cpu` -- PyTorch CPU-only (from custom index to avoid CUDA deps)

### Key Patterns

#### Dynamic Router Discovery

The app factory dynamically discovers and includes all `APIRouter` instances from the `routes/` package using `pkgutil.iter_modules`. Adding a new route module is automatic -- just define a module-level `router` variable.

```python
# src/alm/main_fastapi.py
def _include_route_modules(app: FastAPI) -> None:
    routes_dir = current_dir.parent / "routes"
    for module_info in pkgutil.iter_modules([str(routes_dir)]):
        module_name = f"{routes_package}.{module_info.name}"
        module = importlib.import_module(module_name)
        router = getattr(module, "router", None)
        if isinstance(router, APIRouter):
            app.include_router(router)
```

#### LangGraph Command-Based Pipeline

The inference graph chains nodes using LangGraph `Command` objects to explicitly route between steps. Each node returns a `Command` with `goto` (next node) and `update` (state mutations). The main pipeline is: cluster -> summarize -> classify -> route (need more context?) -> get context or solve.

```python
# src/alm/agents/graph.py
async def classify_log_node(state: GrafanaAlertState) -> Command:
    log_summary = state.logSummary
    log_category = await classify_log(log_summary, llm)
    return Command(
        goto="router_step_by_step_solution_node",
        update={"expertClassification": log_category},
    )
```

#### Structured Output with Pydantic Schemas

LLM calls use `with_structured_output()` to enforce Pydantic schemas on LLM responses. Classification uses `Literal` types to constrain the LLM to predefined expert categories.

```python
# src/alm/agents/output_scheme.py
class ClassifySchema(BaseModel):
    category: Literal[
        "Cloud Infrastructure / AWS Engineers",
        "Kubernetes / OpenShift Cluster Admins",
        "DevOps / CI/CD Engineers (Ansible + Automation Platform)",
        # ...
    ] = Field(description="Category of the log")

# src/alm/agents/node.py
llm_categorize = llm.with_structured_output(ClassifySchema)
log_category = await llm_categorize.ainvoke([...])
```

#### Dual LLM Configuration (Tool-Calling Workaround)

The backend supports a separate LLM endpoint for tool-calling operations, since not all RHOAI-served models support tool calling. The Loki agent uses this secondary endpoint when available.

```python
# src/alm/llm.py
def get_llm_support_tool_calling():
    """Workaround: uses litemaas endpoint which supports tool calling,
    while other agents use the default RHOAI model."""
    API_KEY_WITH_TOOL_CALLING = os.getenv("OPENAI_API_TOKEN_WITH_TOOL_CALLING")
    BASE_URL_WITH_TOOL_CALLING = os.getenv("OPENAI_API_ENDPOINT_WITH_TOOL_CALLING")
    MODEL_WITH_TOOL_CALLING = os.getenv("OPENAI_MODEL_WITH_TOOL_CALLING")
    if all([API_KEY_WITH_TOOL_CALLING, BASE_URL_WITH_TOOL_CALLING, MODEL_WITH_TOOL_CALLING]):
        return ChatOpenAI(api_key=..., base_url=..., model=..., temperature=TEMPERATURE)
    else:
        return get_llm()  # fallback to default
```

#### Streaming with Fallback

The `stream_with_fallback` function collects streamed LLM chunks and returns whatever was received even if the stream is interrupted mid-response, preventing total loss of partial results.

```python
# src/alm/llm.py
async def stream_with_fallback(llm, messages):
    collected_output = []
    try:
        async for chunk in llm.astream(messages):
            if chunk.content:
                collected_output.append(chunk.content)
    except Exception as e:
        logger.error(f"Stream interrupted: {e}")
        if len(collected_output) == 0:
            raise e
    return "".join(collected_output)
```

#### Log Clustering with Configurable Algorithms

Logs are clustered using sentence embeddings (local SentenceTransformer or remote OpenAI-compatible API) and configurable sklearn clustering algorithms (DBSCAN, HDBSCAN, MeanShift, AgglomerativeClustering). Trained models are persisted to MinIO or local disk.

```python
# src/alm/agents/node.py
def _cluster_logs(embeddings):
    algorithm = os.getenv("CLUSTERING_ALGORITHM")
    if algorithm.lower() == "dbscan":
        distance_matrix = cosine_distances(embeddings)
        cluster_model = DBSCAN(eps=0.3, min_samples=2, metric="precomputed")
    elif algorithm.lower() == "hdbscan":
        cluster_model = HDBSCAN(min_cluster_size=2, metric="cosine")
    # ...
    return cluster_model, cluster_labels
```

#### SQLModel Async Database with Auto-Create

Uses SQLModel (Pydantic-SQLAlchemy hybrid) for models and async engine creation. Tables are created with `metadata.create_all` -- no migration framework. The `DATABASE_URL` env var is automatically converted between sync and async driver formats.

```python
# src/alm/database.py
engine = create_async_engine(
    os.getenv("DATABASE_URL")
    .replace("+asyncpg", "")
    .replace("postgresql", "postgresql+asyncpg")
)

async def init_tables(delete_tables=False):
    async with engine.begin() as conn:
        if delete_tables:
            await conn.run_sync(GrafanaAlert.metadata.drop_all)
        await conn.run_sync(GrafanaAlert.metadata.create_all)
```

#### Singleton RAG Handler with Lazy Init

The `RAGHandler` uses singleton pattern and lazy initialization to communicate with a separate RAG microservice over HTTP. It gracefully degrades when RAG is disabled or unavailable.

```python
# src/alm/utils/rag_handler.py
class RAGHandler:
    _instance: Optional["RAGHandler"] = None
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def get_cheat_sheet_context(self, log_summary: str) -> str:
        if not self._initialize_rag_service():
            return ""
        response = await self._client.post("/rag/query", json={
            "query": log_summary,
            "top_k": int(os.getenv("RAG_TOP_K", "3")),
            # ...
        })
```

#### Phoenix/OTEL LangChain Tracing

Observability is wired via Arize Phoenix with OpenTelemetry. LangChain is explicitly instrumented at startup, and traces are sent to a configurable collector endpoint.

```python
# src/alm/utils/phoenix.py
def register_phoenix():
    phoenix_endpoint = os.getenv("COLLECTOR_ENDPOINT")
    tracer_provider = register(
        project_name="ansible-log-monitor",
        endpoint=phoenix_endpoint,
    )
    LangChainInstrumentor().instrument(tracer_provider=tracer_provider)
```

#### MCP Client for Loki Queries

A custom MCP client communicates with a Loki MCP server using JSON-RPC protocol for session management and tool calling. The Loki agent creates per-alert instances with log context bound via closures.

```python
# src/alm/mcp/mcp_client.py
class MCPClient:
    async def initialize(self):
        payload = {
            "jsonrpc": "2.0", "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "test-chat", "version": "1.0.0"},
            },
        }
        response = await self.client.post(self.server_url, json=payload, ...)
        self.session_id = response.headers.get("Mcp-Session-Id")
```

#### Containerfile with uv and PyTorch CPU-Only Index

Multi-stage build using UBI8 Python 3.12 base and `uv` package manager. PyTorch is installed from the CPU-only index to avoid pulling CUDA dependencies, which significantly reduces image size.

```dockerfile
# Containerfile
FROM registry.access.redhat.com/ubi8/python-312 AS builder
COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /uvx /bin/
RUN UV_HTTP_TIMEOUT=600 \
    TORCH_CUDA_ARCH_LIST="" \
    uv sync --frozen --no-install-project --no-dev
```

### Configuration

- **Environment variables:**
  - `OPENAI_API_TOKEN` / `OPENAI_API_ENDPOINT` / `OPENAI_MODEL` / `OPENAI_TEMPERATURE` -- primary LLM config (OpenAI-compatible endpoint, e.g., RHOAI model serving)
  - `OPENAI_API_TOKEN_WITH_TOOL_CALLING` / `OPENAI_API_ENDPOINT_WITH_TOOL_CALLING` / `OPENAI_MODEL_WITH_TOOL_CALLING` -- optional separate LLM for tool-calling operations
  - `DATABASE_URL` -- PostgreSQL connection string (default: `postgresql+asyncpg://user:password@localhost:5432/logsdb`)
  - `CLUSTERING_ALGORITHM` -- sklearn clustering algorithm: `dbscan`, `hdbscan`, `meanshift`, `agglomerative`
  - `SENTENCE_TRANSFORMER_MODEL_NAME` -- local embedding model (e.g., `Qwen/Qwen3-Embedding-0.6B`)
  - `EMBEDDINGS_LLM_URL` / `EMBEDDINGS_LLM_API_KEY` / `EMBEDDINGS_LLM_MODEL_NAME` -- optional remote embedding API
  - `RAG_ENABLED` / `RAG_SERVICE_URL` / `RAG_TOP_K` / `RAG_TOP_N` / `RAG_SIMILARITY_THRESHOLD` -- RAG microservice config
  - `MINIO_ENDPOINT` / `MINIO_PORT` / `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` / `MINIO_BUCKET_NAME` -- MinIO object storage
  - `COLLECTOR_ENDPOINT` -- Phoenix/OTEL trace collector URL
  - `LOKI_MCP_SERVER_URL` / `LOKI_URL` -- Loki MCP server and direct Loki endpoints
  - `LOG_LEVEL` / `LOG_FORMAT` -- logging config (`pretty` or `json` format)
  - `TMP_CLUSTER_MODEL_PATH` -- local path fallback for clustering model
- **Config files:**
  - `src/alm/config.py` -- `EmbeddingsConfig` and `StorageConfig` classes
  - `src/alm/agents/prompts/*.md` -- system prompt templates loaded at module import
  - `.env` / `.env.example` -- environment variable definitions
- **Helm values:** N/A (uses compose.yaml for local dev, Containerfile for cluster)

### Known Gotchas

- **DATABASE_URL driver format conversion:** The `database.py` module strips `+asyncpg` and re-adds `postgresql+asyncpg` to normalize the URL. This means the env var can use either `postgresql://` or `postgresql+asyncpg://` format, but the double-replace logic assumes the URL starts with `postgresql`.
- **Prompt files loaded at module import:** System prompts in `src/alm/agents/prompts/prompts.py` are read from disk with `open()` at import time (not at function call time). The file paths are relative (`src/alm/agents/prompts/*.md`), so the working directory must be the repo root when the application starts, or the prompts will fail to load.
- **PyTorch CPU-only index in pyproject.toml:** The `pyproject.toml` uses `[[tool.uv.index]]` with `explicit = true` for the PyTorch CPU index and `[tool.uv.sources]` to pin `torch` and `torchvision` to that index. Forgetting this when adding torch-dependent packages will pull CUDA builds and bloat the image.
- **Dual LLM endpoints for tool calling:** The code explicitly documents (in `llm.py`) that the default RHOAI model may not support tool calling. The `OPENAI_*_WITH_TOOL_CALLING` env vars are the workaround. If not set, it falls back to the default model, which may fail for the Loki agent.
- **Grafana test alerts silently dropped:** The `post_log_alert` route filters out messages matching `"Notification test"` or `"Grafana alert triggered"` and returns `None`. This is an intentional token-saving measure noted in a comment (`# tmp for grafana alert infernece to save tokens`).
- **MinIO `secure=False`:** The MinIO client is hardcoded to `secure=False` (HTTP) for internal service communication. This is appropriate for in-cluster use but would need to change for external MinIO endpoints.

### Testing Notes

- Health check at `GET /health` returning `{"status": "ok"}`
- Root endpoint at `GET /` returning `{"service": "alm", "status": "ok"}`
- The compose.yaml healthcheck uses `curl -f http://localhost:8000/health`
- Backend depends on `postgres` (healthy), `alm-embedding` (healthy), and `alm-rag` (started) in compose.yaml
- The `RAG_ENABLED=false` env var can disable RAG to run the backend without the RAG microservice

### Related Patterns

- Deployment: compose.yaml orchestrates postgres, loki, grafana, phoenix, promtail, aap-log-collector, aap-mock, backend, frontend, alm-embedding, minio, and alm-rag
- The RAG service (`services/rag/`) is a separate FastAPI microservice with its own Containerfile
- The clustering service (`services/clustering/`) can optionally serve cluster inference via HTTP
- Loki MCP server is a separate container (`quay.io/rh-ai-quickstart/alm-loki-mcp-server`)

---

## Choosing Between Approaches

| Criteria | Approach A (ai-virtual-agent) | Approach B (ansible-log-analysis) |
|----------|-------------------------------|-----------------------------------|
| **Use case** | Interactive multi-framework agent chat platform | Event-driven log analysis pipeline |
| **Agent frameworks** | LlamaStack, LangGraph, CrewAI (pluggable) | LangGraph only (fixed pipeline) |
| **LLM routing** | Per-runner env vars with sentinel-based resolution | Single OpenAI-compatible endpoint + optional tool-calling endpoint |
| **ORM / Migrations** | SQLAlchemy + Alembic | SQLModel + create_all (no migrations) |
| **Base image** | UBI9 | UBI8 |
| **Package manager** | pip | uv (with PyTorch CPU-only index) |
| **Graph definition** | Declarative YAML -> StateGraph | Imperative Python with Command routing |
| **Frontend bundling** | React SPA built into backend static files | Separate Gradio UI container |
| **Observability** | None built-in | Phoenix/OTEL with LangChain instrumentation |
| **ML workload** | None | Log clustering (sklearn) + sentence embeddings |
| **Object storage** | MinIO for attachments (optional) | MinIO for ML models and RAG indexes |
| **MCP usage** | Tool integration in graph engine + K8s CRD discovery | Loki log querying via dedicated MCP client |
