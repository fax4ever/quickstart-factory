---
name: fastapi-backend
description: "FastAPI backend patterns for AI quickstarts: multi-runner dispatch, agentic pipelines, persona-based systems, recommendation serving, and transaction monitoring"
summary: "Covers 5 FastAPI backend architectures for AI quickstarts: multi-runner dispatch (A: LlamaStack/LangGraph/CrewAI with declarative YAML graph engine and MCP JSON-RPC), event-driven log analysis (B: LangGraph Command routing with sklearn clustering and Phoenix/OTEL tracing), multi-agent persona-scoped system (C: 5 LangGraph agents with NeMo Guardrails safety shields, 3-layer RBAC, PII masking, MLflow+Prometheus), recommendation serving (D: Feast feature store with hybrid SQL+semantic search, in-process PyTorch CLIP inference, pgvector Helm subchart), and transaction monitoring (E: LangGraph NL-to-SQL alert pipelines, async job queue with ThreadPoolExecutor, background scheduler). Choose A for pluggable multi-framework agent platforms with K8s MCPServer CRD discovery; B for single-purpose pipelines with dual LLM endpoints (tool-calling workaround) and SQLModel create_all; C for regulated-industry apps needing Keycloak OIDC, langchain-mcp-adapters MultiServerMCPClient, and Kagenti A2A protocol; D for e-commerce with Feast+pgvector from ai-architecture-charts and K8s Job DB init; E for financial monitoring with multi-provider LLM/embedding factories (OpenAI-compatible/LlamaStack/sentence-transformers), Keycloak dual-URL pattern, and WebSocket push notifications. All share async PostgreSQL via asyncpg, lifespan context managers, and SPA static files with dev proxy; base images vary (UBI9/UBI8/python:3.11-slim/custom); build tools span pip, uv+hatchling, and Turborepo monorepos; conversation persistence ranges from InMemorySaver (A) to langgraph-checkpoint-postgres (C); YAML agent configs support mtime-based hot-reload (C) and ${VAR:-default} env-var substitution. Critical gotchas: pysqlite3 module swap must be first import for CrewAI+UBI9 (ChromaDB needs SQLite>=3.35), Alembic env.py must convert postgresql+asyncpg:// URLs, DATABASE_URL string-replace can double-prefix asyncpg driver, MODEL_ENDPOINT assert at module import crashes the entire app if unset, MinIO secure=False and httpx verify=False are hardcoded for in-cluster use, Containerfile must chmod HuggingFace cache for OpenShift restricted SCC, and router registration order prevents path catch-all conflicts."
metadata:
  type: component
tags:
  tech_stack: [fastapi, python, postgresql, sqlalchemy, alembic, asyncpg, langchain, langgraph, crewai, litellm, httpx, pydantic, pydantic-settings, sqlmodel, uvicorn, scikit-learn, sentence-transformers, faiss, minio, phoenix, opentelemetry, keycloak, mlflow, prometheus, boto3, a2a-sdk, feast, torch, transformers, numpy, bcrypt, pillow, python-jose, llama-stack-client, twilio, pandas, hatchling, uv]
  ai_pattern: [agents, model-serving, rag, guardrails, mcp, tool-use, embeddings, clustering, log-analysis, structured-output, multi-agent, safety-shields, recommendations, hybrid-search, vector-search, background-jobs, scheduled-tasks]
  platform: [llamastack, openshift, kubernetes, grafana, loki, rhoai, kserve, vllm]
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
  - quickstart: "multi-agent-loan-origination"
    repo: "https://github.com/rh-ai-quickstart/multi-agent-loan-origination"
    notes: "Multi-agent FastAPI backend with 5 persona-scoped LangGraph agents, NeMo Guardrails safety shields, Keycloak OIDC, RBAC, PII masking, MLflow tracing, Prometheus metrics, MCP tool integration, and Kagenti A2A protocol support"
    approach: "C"
  - quickstart: "product-recommender-system"
    repo: "https://github.com/rh-ai-quickstart/product-recommender-system"
    notes: "E-commerce recommendation backend with Feast feature store, CLIP/user encoder model serving, hybrid search (SQL + semantic), JWT auth, Helm with pgvector subchart from ai-architecture-charts, and LLM-powered review summarization"
    approach: "D"
  - quickstart: "spending-transaction-monitor"
    repo: "https://github.com/rh-ai-quickstart/spending-transaction-monitor"
    notes: "Transaction monitoring backend with LangGraph alert processing pipelines, async job queue for ML recommendations, background scheduler, multi-provider LLM/embedding abstraction, Keycloak OIDC with dual URL pattern, and WebSocket push notifications"
    approach: "E"
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

---

## Approach C: Multi-Agent Persona-Scoped System (from multi-agent-loan-origination)

### When to Use

When building a multi-agent backend where each persona (role) has its own dedicated LangGraph agent with role-scoped tools, safety shields (NeMo Guardrails), RBAC-controlled tool access, WebSocket streaming, conversation persistence, audit trails, and Prometheus observability. Suited for regulated-industry applications (financial services, healthcare) requiring per-role data isolation, PII masking, compliance knowledge bases, and Keycloak OIDC authentication.

### Differences from Approach A

- **Agent architecture:** 5 persona-specific LangGraph agents (public, borrower, loan officer, underwriter, CEO) loaded from YAML configs with mtime-based hot-reload, instead of a single multi-runner dispatch across frameworks
- **Safety:** NeMo Guardrails input/output shields integrated into the LangGraph graph as nodes (`input_shield -> agent -> tools -> output_shield`), instead of no built-in safety
- **Communication:** WebSocket streaming with buffered-until-done delivery, instead of SSE streaming
- **Auth:** Keycloak OIDC with JWT validation and role-based data scoping, instead of OAuth header forwarding
- **RBAC:** 3-layer authorization (route-level `require_roles`, graph-level `tool_auth` node, data-level `DataScope`), instead of basic user/admin checks
- **Observability:** MLflow autolog for LangChain/LangGraph tracing + Prometheus custom metrics (token usage, inference latency, tool calls, agent routing), instead of no observability
- **Base image:** `python:3.11-slim` with multi-stage build, instead of UBI9
- **Package manager:** `uv` with hatchling build system in a Turborepo monorepo, instead of pip
- **MCP integration:** `langchain-mcp-adapters` MultiServerMCPClient with Streamable HTTP transport, instead of raw JSON-RPC
- **Deployment:** Helm chart with init containers (wait-for-db, run-migrations), Kagenti A2A sidecar support, SPIRE identity for mTLS, instead of compose-only

### Tech Stack & Dependencies

- **Runtime:** Python 3.11 on `python:3.11-slim`
- **Container image:** Multi-stage Containerfile using `uv` with CPU-only PyTorch index for embedding model
- **Key dependencies:**
  - `fastapi`, `uvicorn[standard]` -- ASGI web framework and server
  - `sqlalchemy[asyncio]`, `asyncpg`, `alembic` -- async ORM, PostgreSQL driver, migrations (shared `packages/db` package)
  - `langgraph`, `langchain-openai`, `langchain-core` -- LangGraph agent graphs with safety shield nodes
  - `langgraph-checkpoint-postgres`, `psycopg[binary]` -- PostgreSQL-backed conversation persistence
  - `langchain-mcp-adapters` -- MCP tool integration via Streamable HTTP
  - `mcp>=1.0.0,<2.0` -- MCP protocol SDK
  - `a2a-sdk[http-server]>=0.2.0` -- A2A protocol for Kagenti agent discovery
  - `PyJWT[crypto]` -- JWT validation for Keycloak OIDC
  - `prometheus-fastapi-instrumentator` -- automatic HTTP metrics + custom agent metrics
  - `mlflow>=3.1.0` -- LangChain/LangGraph autolog tracing
  - `sentence-transformers` -- local embedding model (nomic-embed-text-v1.5) for compliance KB
  - `boto3` -- S3/MinIO document storage
  - `pymupdf` -- PDF document extraction
  - `sqladmin` -- admin dashboard
  - `httpx` -- async HTTP client for NeMo Guardrails and MCP servers
- **Helm subchart:** Custom Helm chart at `deploy/helm/mortgage-ai/` with api-deployment, api-service templates

### Key Patterns

#### LangGraph Agent with Safety Shield Nodes

Each agent graph follows: `input_shield -> agent -> tools <-> agent -> output_shield -> END`. Safety shields call NeMo Guardrails `/v1/guardrail/checks` endpoint (runs only rails, no full LLM call). Shields fail-closed in regulated domains.

```python
# packages/api/src/agents/base.py
graph = StateGraph(AgentState)
graph.add_node("input_shield", input_shield)
graph.add_node("agent", agent)
graph.add_node("tools", tools_with_metrics)
graph.add_node("output_shield", output_shield)
graph.set_entry_point("input_shield")
graph.add_conditional_edges("input_shield", after_input_shield,
    {END: END, "agent": "agent"})
graph.add_edge("tools", "agent")
graph.add_edge("output_shield", END)
```

#### YAML-Driven Agent Registry with Hot-Reload

Agent configs live in `config/agents/<name>.yaml` with system prompts, tool definitions, and RBAC rules. The registry caches compiled graphs and rebuilds them when the YAML file's mtime changes (checked at most every 5 seconds). Failed reloads keep the last valid graph.

```python
# packages/api/src/agents/registry.py
def get_agent(agent_name: str, checkpointer=None):
    config_path = _AGENTS_CONFIG_DIR / f"{agent_name}.yaml"
    current_mtime = config_path.stat().st_mtime
    if agent_name in _graphs:
        cached_graph, cached_mtime = _graphs[agent_name]
        if current_mtime <= cached_mtime:
            return cached_graph
    config = load_agent_config(agent_name)
    graph = _build_graph(agent_name, config, checkpointer=checkpointer)
    _graphs[agent_name] = (graph, current_mtime)
    return graph
```

#### 3-Layer RBAC with Per-Tool Authorization

Layer 1: Route-level `require_roles()` dependency. Layer 2: `tool_auth` graph node checks each pending tool call against `tool_allowed_roles` from agent YAML config. Layer 3: `DataScope` object restricts query results per role (borrower sees own data, CEO gets PII-masked aggregates).

```python
# packages/api/src/core/auth.py
def build_data_scope(role: UserRole, user_id: str) -> DataScope:
    if role == UserRole.BORROWER:
        return DataScope(own_data_only=True, user_id=user_id)
    if role == UserRole.CEO:
        return DataScope(pii_mask=True, document_metadata_only=True,
                         full_pipeline=True)
    if role == UserRole.UNDERWRITER:
        return DataScope(full_pipeline=True)
    return DataScope()
```

#### WebSocket Chat with Disconnect Cancellation

Chat endpoints use WebSocket with a race pattern: the agent task runs against a disconnect sentinel. If the client disconnects mid-stream, the agent task is cancelled immediately, freeing the LLM slot.

```python
# packages/api/src/routes/_chat_handler.py
agent_task = asyncio.create_task(_run_agent(user_text, input_messages))
disconnect_task = asyncio.create_task(_wait_disconnect())
done, pending = await asyncio.wait(
    {agent_task, disconnect_task},
    return_when=asyncio.FIRST_COMPLETED,
)
if disconnect_task in done:
    agent_task.cancel()
    return
```

#### YAML Model Config with Env Var Substitution and Hot-Reload

A `config/models.yaml` file defines LLM tiers (llm, vision, embedding) with `${VAR:-default}` placeholders. The config supports nested env var references and is hot-reloaded on mtime change.

```yaml
# config/models.yaml
models:
  llm:
    provider: openai_compatible
    model_name: "${LLM_MODEL:-gpt-4o-mini}"
    endpoint: "${LLM_BASE_URL:-https://api.openai.com/v1}"
    api_key: "${LLM_API_KEY:-not-needed}"
  vision:
    model_name: "${VISION_MODEL:-${LLM_MODEL:-gpt-4o-mini}}"
    endpoint: "${VISION_BASE_URL:-${LLM_BASE_URL:-https://api.openai.com/v1}}"
```

#### Prometheus Custom Metrics for Agent Observability

Custom Prometheus metrics track LLM token usage (input/output by model and persona), inference latency, tool call counts/duration, agent routing decisions, and active WebSocket sessions. These complement automatic HTTP metrics from `prometheus-fastapi-instrumentator`.

```python
# packages/api/src/core/metrics.py
llm_tokens_total = Counter("llm_tokens_total",
    "Total LLM tokens used",
    ["model", "direction", "persona"])
llm_inference_duration_seconds = Histogram("llm_inference_duration_seconds",
    "LLM inference duration in seconds",
    ["model", "persona"],
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0])
```

#### MLflow Tracing with RHOAI Kubernetes Auth

MLflow autolog traces all LangChain/LangGraph operations. Auth supports three modes: RHOAI 3.4+ Kubernetes plugin (reads mounted ServiceAccount token automatically), explicit bearer token, or legacy SA token file. Initialization runs in a background thread to avoid blocking startup.

```python
# packages/api/src/observability.py
def _configure_auth() -> None:
    if os.environ.get("MLFLOW_TRACKING_AUTH") == "kubernetes":
        # RHOAI 3.4+ plugin -- reads SA token and namespace automatically
        if not settings.MLFLOW_WORKSPACE and _SA_NAMESPACE_PATH.is_file():
            namespace = _SA_NAMESPACE_PATH.read_text().strip()
            os.environ["MLFLOW_WORKSPACE"] = namespace
        return
    if settings.MLFLOW_TRACKING_TOKEN:
        os.environ["MLFLOW_TRACKING_TOKEN"] = settings.MLFLOW_TRACKING_TOKEN
        return
    # Legacy: read mounted SA token file directly
```

#### PII Masking Middleware

A Starlette middleware intercepts JSON responses and recursively masks sensitive fields (SSN, DOB, account numbers) when the authenticated user's data scope has `pii_mask=True`. Coverage is automatic across all endpoints.

```python
# packages/api/src/middleware/pii.py
class PIIMaskingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if not getattr(request.state, "pii_mask", False):
            return response
        # Read body, mask PII fields, return new response
        data = json.loads(body_bytes)
        masked = _mask_pii_recursive(data)
        return Response(content=json.dumps(masked).encode("utf-8"), ...)
```

#### MCP Tool Integration via langchain-mcp-adapters

Uses `MultiServerMCPClient` with Streamable HTTP transport to connect to MCP servers at startup. Tools are cached and injected into agent graphs. Supports multiple MCP servers (risk-assessment, predictive-model) with graceful degradation when optional servers are unreachable.

```python
# packages/api/src/agents/mcp_integration.py
_client = MultiServerMCPClient({
    "risk-assessment": {
        "transport": "streamable_http",
        "url": url,
    },
})
_tools = await _client.get_tools()
```

#### Kagenti A2A Protocol for Agent Discovery

Each LangGraph agent is exposed as an A2A-compatible endpoint for Kagenti multi-agent orchestration. Agents register with skills, capabilities, and SPIRE identity for mTLS. Feature-gated by `KAGENTI_ENABLED` env var.

```python
# packages/api/src/a2a_server.py
class LoanAgentExecutor(AgentExecutor):
    async def execute(self, context, event_queue):
        graph = get_agent(self._agent_name, checkpointer=self._checkpointer)
        result = await graph.ainvoke(inputs, config)
        tag_trace_with_spire()  # Attach SPIRE identity to MLflow trace
```

### Configuration

- **Environment variables:**
  - `DATABASE_URL` -- async PostgreSQL connection string (`postgresql+asyncpg://...`)
  - `COMPLIANCE_DATABASE_URL` -- separate connection for HMDA compliance schema with dedicated `compliance_app` role
  - `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` -- primary LLM config (any OpenAI-compatible endpoint)
  - `VISION_MODEL` / `VISION_BASE_URL` / `VISION_API_KEY` -- optional vision-capable model (falls back to main LLM)
  - `KEYCLOAK_URL` / `KEYCLOAK_REALM` / `KEYCLOAK_CLIENT_ID` / `KEYCLOAK_ISSUER` -- Keycloak OIDC config
  - `AUTH_DISABLED` -- bypass JWT validation for dev/tests
  - `NEMO_GUARDRAILS_ENDPOINT` -- NeMo Guardrails server for safety shields
  - `MCP_RISK_SERVER_URL` -- MCP risk assessment server (Streamable HTTP)
  - `PREDICTIVE_MODEL_MCP_URL` -- optional external predictive model MCP server
  - `MLFLOW_TRACKING_URI` / `MLFLOW_EXPERIMENT_NAME` / `MLFLOW_TRACKING_AUTH` -- MLflow tracing config
  - `S3_ENDPOINT` / `S3_ACCESS_KEY` / `S3_SECRET_KEY` / `S3_BUCKET` -- MinIO document storage
  - `KAGENTI_ENABLED` / `KAGENTI_SERVICE_NAME` -- enable A2A protocol servers
  - `COMPANY_NAME` / `AGENT_NAME` -- branding and agent name injection
- **Config files:**
  - `packages/api/src/core/config.py` -- centralized `Settings` class via pydantic-settings
  - `config/models.yaml` -- model tier definitions with env var substitution and hot-reload
  - `config/agents/*.yaml` -- per-agent system prompts, tool configs, and RBAC rules with hot-reload
  - `config/keycloak/` -- Keycloak realm export
- **Helm values:** `deploy/helm/mortgage-ai/values.yaml` with `api.enabled`, `api.replicas`, `api.image`, `api.healthCheck`, `api.resources`

### Known Gotchas

- **OpenShift restricted SCC and HuggingFace cache:** The Containerfile sets `chown -R appuser:0 /app && chmod -R g+w /app/.cache` because OpenShift's restricted SCC assigns arbitrary UIDs in group 0. Without `g+w` on the cache directory, the sentence-transformers model download fails at runtime.
- **CPU-only PyTorch in Containerfile:** The embedding model runs on CPU in the container. The Containerfile uses `--extra-index-url https://download.pytorch.org/whl/cpu` to avoid shipping ~25GB of unused CUDA libraries. A comment in the Containerfile documents this choice.
- **MLflow init in background thread:** MLflow initialization may block on HTTP calls to the tracking server. The `init_mlflow_tracing()` function runs `_do_mlflow_init()` in a daemon thread to prevent blocking app startup if the MLflow server is slow or unreachable.
- **Output shield timeout workaround:** The NeMo Guardrails output check previously re-sent the full assistant response as a new user message, triggering a full LLM call (32s+) that exceeded the httpx 30s timeout. The code now uses `/v1/guardrail/checks` which runs only the rails (<5s). The `OUTPUT_SHIELD_DISABLED` setting remains as a fallback toggle.
- **PREDICTIVE_MODEL_MCP_URL empty string handling:** A Pydantic field_validator converts empty strings to `None` so that deleting the env var value properly disables the predictive model feature, rather than leaving an empty URL that would cause connection errors.
- **Monorepo editable install for DB package:** The `pyproject.toml` uses `[tool.uv.sources]` with `path = "../db", editable = true` to link the shared `packages/db` package. Both the Containerfile and the Helm init container must set `PYTHONPATH` to include both packages.
- **Think tag stripping in chat handler:** Small models (e.g., Llama) sometimes emit `<think>` tags and inline tool-call text instead of using structured tool-calling format. The chat handler strips these with regex before sending the response to the client.

### Testing Notes

- Health check at `GET /health/` with structured response including database, storage, and LLM connectivity status
- Auth bypass with `AUTH_DISABLED=true` for local dev and testing
- 1083+ pytest tests with `pytest-asyncio` (`asyncio_mode = "auto"`)
- Three test tiers: unit tests, functional tests (real FastAPI app with middleware), integration tests (real PostgreSQL + MinIO via testcontainers)
- `Prometheus /metrics` endpoint auto-exposed by `prometheus-fastapi-instrumentator`
- Containerfile includes a built-in HEALTHCHECK using Python urllib

### Related Patterns

- Deployment: Helm chart at `deploy/helm/mortgage-ai/` with init containers for db-wait and migrations, Kagenti sidecar annotations, SPIRE SVID volume mounts
- Database: shared `packages/db` package with SQLAlchemy models, Alembic migrations, HMDA schema isolation
- Frontend: separate `packages/ui` React app communicating via WebSocket and REST
- MCP servers: external risk-assessment and predictive-model MCP servers consumed via Streamable HTTP

---

## Choosing Between Approaches

| Criteria | Approach A (ai-virtual-agent) | Approach B (ansible-log-analysis) | Approach C (multi-agent-loan-origination) |
|----------|-------------------------------|-----------------------------------|-------------------------------------------|
| **Use case** | Interactive multi-framework agent chat platform | Event-driven log analysis pipeline | Multi-agent regulated-industry application |
| **Agent frameworks** | LlamaStack, LangGraph, CrewAI (pluggable) | LangGraph only (fixed pipeline) | LangGraph only (5 persona-specific agents) |
| **Agent count** | 1 (dynamically configured) | 1 (fixed pipeline) | 5 (public, borrower, LO, underwriter, CEO) |
| **LLM routing** | Per-runner env vars with sentinel-based resolution | Single endpoint + optional tool-calling endpoint | YAML model tiers (llm, vision, embedding) with hot-reload |
| **Safety** | None built-in | None built-in | NeMo Guardrails input/output shield nodes (fail-closed) |
| **Auth / RBAC** | OAuth header forwarding | None | Keycloak OIDC + 3-layer RBAC (route, tool_auth node, DataScope) |
| **Communication** | SSE streaming | REST endpoints | WebSocket streaming with disconnect cancellation |
| **ORM / Migrations** | SQLAlchemy + Alembic | SQLModel + create_all (no migrations) | SQLAlchemy + Alembic (shared db package in monorepo) |
| **Base image** | UBI9 | UBI8 | python:3.11-slim |
| **Package manager** | pip | uv (with PyTorch CPU-only index) | uv + hatchling (Turborepo monorepo) |
| **Observability** | None built-in | Phoenix/OTEL with LangChain instrumentation | MLflow autolog + Prometheus custom metrics |
| **PII handling** | None | None | Middleware-based recursive PII masking per role |
| **MCP usage** | Tool integration in graph engine + K8s CRD discovery | Loki log querying via dedicated MCP client | langchain-mcp-adapters MultiServerMCPClient (Streamable HTTP) |
| **Conversation persistence** | InMemorySaver | None | langgraph-checkpoint-postgres (per-user threads) |
| **Multi-agent protocol** | None | None | Kagenti A2A with SPIRE mTLS |
| **Deployment** | compose.yaml | compose.yaml | Helm chart + compose.yml (init containers, Kagenti sidecar) |

---

## Approach D: E-Commerce Recommendation Serving Backend (from product-recommender-system)

### When to Use

When building an e-commerce or product recommendation backend that serves pre-trained model predictions via a Feast feature store, combines deterministic SQL search with semantic vector search, bundles a React frontend as static files in the same container, and deploys via Helm with the `pgvector` subchart from `ai-architecture-charts`. Suited for recommendation-serving applications with user onboarding flows, product catalogs, review generation, and LLM-powered review summarization -- rather than interactive agent chat or log analysis pipelines.

### Differences from Approach A

- **AI pattern:** Recommendation serving (Feast feature store + PyTorch user encoder + CLIP search) instead of agentic multi-runner dispatch
- **No agent frameworks:** No LangGraph, CrewAI, or LlamaStack -- the LLM is used only for review generation and summarization via OpenAI-compatible chat completions API
- **Auth:** Simple JWT auth with bcrypt/passlib and `python-jose`, not OAuth header forwarding or Keycloak OIDC
- **Database init:** Kubernetes Job runs `init_backend.py` which uses `drop_all` + `create_all`, not Alembic migrations
- **Deployment:** Helm chart with `pgvector` subchart from `ai-architecture-charts`, Feast TLS secret volume mounts, and init containers waiting for db-init Job completion
- **Base image:** Multi-stage: UBI9 NodeJS 22 for frontend build, then `recommendation-core:latest` (custom base with ML dependencies) for backend
- **Feature store:** Feast with remote registry and PostgreSQL online store (vector-enabled) for both recommendation serving and vector search
- **Model serving:** In-process PyTorch inference (user encoder tower loaded from MinIO, CLIP model pre-downloaded in Containerfile) rather than external KServe/vLLM endpoints

### Tech Stack & Dependencies

- **Runtime:** Python 3.12 on `quay.io/rh-ai-quickstart/recommendation-core:latest` (custom base)
- **Container image:** Multi-stage Containerfile: UBI9 NodeJS 22 builds React frontend, recommendation-core base runs backend with bundled frontend in `/public`
- **Key dependencies:**
  - `fastapi==0.110.0`, `uvicorn[standard]` -- ASGI web framework and server
  - `sqlalchemy==2.0.30`, `asyncpg==0.29.0` -- async ORM and PostgreSQL driver
  - `feast[postgres]==0.49.0` -- feature store with PostgreSQL online store and vector search
  - `torch`, `transformers` -- PyTorch user encoder inference and CLIP model
  - `minio` -- object storage for trained model artifacts (user encoder weights)
  - `httpx` -- async HTTP for dev proxy and LLM API calls
  - `python-jose`, `passlib[bcrypt]`, `bcrypt` -- JWT auth and password hashing
  - `recommendation_core` -- local package (uv path source from `../recommendation-core`)
  - `Pillow` -- image processing for image-based product search
  - `kafka-python` -- listed as dependency (interaction logging originally used Kafka, now replaced with direct DB writes)
  - `alembic` -- listed as dependency but not used in practice; init uses `create_all`
- **Helm subchart:** `pgvector` v0.1.0 from `https://rh-ai-quickstart.github.io/ai-architecture-charts`

### Key Patterns

#### Feast Feature Store Singleton with MinIO Model Loading

The `FeastService` singleton initializes the Feast `FeatureStore`, downloads the user encoder model from MinIO (versioned via a `model_version` database table), and sets up CLIP encoder and search services. All recommendation serving flows through this singleton.

```python
# backend/src/services/feast/feast_service.py
class FeastService:
    _instance = None
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(FeastService, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if not self._initialized:
            path = Path("/app/recommendation-core/src/recommendation_core/feature_repo")
            self.store = FeatureStore(str(path))
            self._initialized = True
            self.user_encoder = self._load_user_encoder()
            self.clip_encoder = ClipEncoder()
            self.search_by_image_service = SearchByImageService(self.store, self.clip_encoder)
```

#### Hybrid Search: Deterministic SQL + Semantic Vector Search

Product search combines deterministic PostgreSQL name matching (exact > prefix > substring with normalized text) with Feast semantic vector search as a fallback. If deterministic results fill the requested `k`, semantic search is skipped entirely.

```python
# backend/src/services/feast/feast_service.py
def search_item_by_text(self, text: str, k=5):
    # 1. Deterministic: exact, prefix, contains via SQL
    norm_expr = "regexp_replace(lower(name), '[^a-z0-9]', '', 'g')"
    exact_ids = _query_item_ids(f"{norm_expr} = :qn", {"qn": qn}, exact_limit)
    prefix_ids = _query_item_ids(f"{norm_expr} LIKE :prefix", {"prefix": f"{qn}%"}, ...)
    contains_ids = _query_item_ids(f"{norm_expr} LIKE :contains", {"contains": f"%{qn}%"}, ...)
    # Merge with priority and dedupe
    if len(merged) >= k:
        return self._item_ids_to_product_list(merged[:k])
    # 2. Semantic fallback via Feast
    semantic_df = search_service.search_by_text(text, semantic_k)
```

#### Kubernetes Job for Database Initialization

Database setup runs as a Helm post-install/post-upgrade Job (`db-init`). The Job uses an init container that waits for the `model_version` table (populated by the training pipeline) before running `init_backend.py`. The backend Deployment itself has its own init container waiting for the db-init Job to complete.

```yaml
# helm/product-recommender-system/templates/backend.yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: {{ include "product-recommender-system.fullname" . }}-db-init
  annotations:
    "helm.sh/hook": "post-install,post-upgrade"
    "helm.sh/hook-weight": "1"
    "helm.sh/hook-delete-policy": "before-hook-creation"
spec:
  template:
    spec:
      initContainers:
        - name: wait-until-model-training-workflow
          image: postgres:15-alpine
          command: ["/bin/sh", "-c", |
            until PGPASSWORD=$DB_PASSWORD psql -h $DB_HOST -U $DB_USER -d $DB_NAME \
              -c "SELECT 1 FROM model_version LIMIT 1" > /dev/null 2>&1; do
              echo "Waiting for model_version table..."
              sleep 10
            done]
```

#### Liveness and Readiness Health Checks

Separate liveness and readiness endpoints. Readiness verifies database connectivity with a `SELECT 1` query, returning 503 if the database is unreachable.

```python
# backend/src/routes/health.py
@router.get("/health/live")
async def liveness_check():
    return {"status": "alive"}

@router.get("/health/ready")
async def readiness_check(db: AsyncSession = Depends(get_db)):
    try:
        await db.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception:
        return Response(status_code=503)
```

#### LLM-Powered Review Summarization with Stratified Sampling

The review summarization endpoint sends product reviews to an OpenAI-compatible LLM for analysis. Reviews are stratified-sampled by rating bucket (1-5 stars) to ensure balanced representation, with proportional quota allocation and redistribution.

```python
# backend/src/routes/reviews.py
MODEL_ENDPOINT = os.getenv("MODEL_ENDPOINT")
MODEL_NAME = os.getenv("MODEL_NAME")
assert MODEL_ENDPOINT is not None, "Must assign value to model endpoint"

response = requests.post(
    MODEL_ENDPOINT,
    json={
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": "You are a helpful, smart shopper..."},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
    },
    headers=headers,
)
```

#### SPA Static Files with Dev Proxy

Identical pattern to Approach A but with a different dev server port (9000 instead of 8000). The production Containerfile copies React build output into `../public` and serves it via a custom `SPAStaticFiles` handler mounted at root.

```python
# backend/src/main.py
class SPAStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        if len(sys.argv) > 1 and sys.argv[1] == "dev":
            async with httpx.AsyncClient() as client:
                response = await client.get(f"http://localhost:9000/{path}")
            return Response(response.text, status_code=response.status_code)
        else:
            try:
                return await super().get_response(path, scope)
            except (HTTPException, StarletteHTTPException) as ex:
                if ex.status_code == 404:
                    return await super().get_response("index.html", scope)
```

#### Feast Feature Store Config with Env Var Placeholders

The feature store configuration uses environment variable placeholders for deployment flexibility. The online store is PostgreSQL with `vector_enabled: true` for vector similarity search. The registry uses a remote gRPC service with TLS cert mounted from a Kubernetes secret.

```yaml
# backend/src/services/feast/feature_store.yaml
project: ${FEAST_PROJECT_NAME}
provider: local
registry:
  registry_type: remote
  path: ${FEAST_REGISTRY_URL}
  cert: /app/feature_repo/secrets/tls.crt
online_store:
  type: postgres
  host: ${DB_HOST}
  port: ${DB_PORT}
  database: ${DB_NAME}
  user: ${DB_USER}
  password: ${DB_PASSWORD}
  vector_enabled: true
```

#### Containerfile with Pre-Downloaded HuggingFace Models

The multi-stage Containerfile pre-downloads the CLIP model during build to avoid runtime downloads. It uses `chmod -R 777 /hf_cache` for OpenShift compatibility (arbitrary UID in group 0). Product images from the recommendation-core data directory are copied into the static files.

```dockerfile
# Containerfile
FROM registry.access.redhat.com/ubi9/nodejs-22 AS frontend-builder
# ... builds React frontend ...

FROM quay.io/rh-ai-quickstart/recommendation-core:latest
ENV HF_HOME=/hf_cache
RUN pip install --upgrade pip && pip3 install uv && uv pip install -r pyproject.toml && \
    mkdir -p /hf_cache && \
    python3 -c "from transformers import CLIPProcessor, CLIPModel; \
                CLIPProcessor.from_pretrained('openai/clip-vit-base-patch32'); \
                CLIPModel.from_pretrained('openai/clip-vit-base-patch32')" && \
    chmod -R 777 /hf_cache && chmod -R +r .
```

#### Singleton DatabaseService Replacing Kafka

User interactions (views, cart adds, purchases) are logged via a `DatabaseService` singleton that writes directly to the `stream_interaction` table. Code comments indicate this replaced a previous Kafka-based implementation.

```python
# backend/src/services/database_service.py
class DatabaseService:
    _instance = None
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DatabaseService, cls).__new__(cls)
        return cls._instance

    async def log_interaction(self, db: AsyncSession, user_id, item_id,
                               interaction_type, rating=None, quantity=None, ...):
        interaction_id = f"{user_id}-{item_id}-{datetime.now(timezone.utc).timestamp()}"
        interaction = StreamInteraction(...)
        db.add(interaction)
        await db.commit()
```

### Configuration

- **Environment variables:**
  - `DATABASE_URL` -- PostgreSQL connection string (auto-converted from `postgresql://` to `postgresql+asyncpg://` in `db.py`)
  - `MODEL_ENDPOINT` -- LLM endpoint URL for review summarization (OpenAI-compatible `/v1/chat/completions`; asserted at module import time)
  - `MODEL_NAME` -- LLM model name for review summarization (asserted at module import time)
  - `SECRET_KEY` -- JWT signing key (default: `supersecret`)
  - `MINIO_HOST` / `MINIO_PORT` / `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY` -- MinIO for user encoder model artifacts
  - `FEAST_PROJECT_NAME` / `FEAST_REGISTRY_URL` / `FEAST_SECRET_NAME` -- Feast feature store config (injected via Helm helper template)
  - `DB_HOST` / `DB_PORT` / `DB_USER` / `DB_PASSWORD` / `DB_NAME` -- database credentials for Feast online store and init job (from `pgvector` Kubernetes secret)
  - `USE_LLM_FOR_REVIEWS` -- enable LLM-generated synthetic reviews during DB init (default: `false`)
  - `LLM_API_BASE` / `LLM_API_KEY` / `LLM_MODEL` / `LLM_TIMEOUT` -- LLM config for review generation during init
  - `SUMMARY_LLM_API_KEY` -- API key for the review summarization LLM endpoint
  - `SUMMARIZE_MAX_REVIEWS` -- max reviews to include in summarization prompt (default: `200`)
  - `HF_HOME` -- HuggingFace cache directory (set to `/hf_cache` in Containerfile)
  - `PYTHONPATH` -- must include `/app/backend:/app/backend/src:/app/recommendation-core/src`
- **Config files:**
  - `backend/src/services/feast/feature_store.yaml` -- Feast feature store config with env var placeholders
  - `backend/src/config/test_users.yaml` -- test user definitions for DB seeding
  - `backend/feature_store.yaml` -- hardcoded Feast config with cluster-internal FQDNs (fallback)
- **Helm values:** `helm/product-recommender-system/values.yaml` with `backend.service`, `backend.resources`, `backend.additionalEnv`, `frontendBackendImage`, `llmModel.ollamaModel`, `llmModel.modelEndpoint`, `feast.*`, `minio.env`, `route.*`, `autoscaling.*`

### Known Gotchas

- **DATABASE_URL driver conversion is fragile:** `db.py` uses `.replace("postgresql://", "postgresql+asyncpg://")` which means the env var must use the `postgresql://` scheme. If `postgresql+asyncpg://` is provided directly, the replace produces `postgresql+asyncpg+asyncpg://`.
- **MODEL_ENDPOINT and MODEL_NAME asserted at module import time:** `reviews.py` has `assert MODEL_ENDPOINT is not None` at module level. If these env vars are missing, the entire application fails to start -- not just the review routes.
- **init_backend.py uses drop_all + create_all:** The DB initialization script drops all tables before recreating them (`Base.metadata.drop_all` followed by `Base.metadata.create_all`). This is destructive and intended for fresh deployments only. The Helm hook `before-hook-creation` deletes the previous Job before re-running.
- **HuggingFace cache permissions for OpenShift:** The Containerfile runs `chmod -R 777 /hf_cache` because OpenShift's restricted SCC assigns arbitrary UIDs. Without this, the CLIP model (pre-downloaded during build) cannot be read at runtime.
- **Feast feature store has hardcoded cluster FQDNs as fallback:** `backend/feature_store.yaml` contains hardcoded `feast-feast-edb-recommendation-registry.recommendation.svc.cluster.local` and `cluster-sample-rw.recommendation.svc.cluster.local`. The env-var-templated version in `services/feast/feature_store.yaml` is used in production, but the wrong file could be picked up if `FEAST_PROJECT_NAME` is not set.
- **GET recommendations endpoint is synchronous:** The `GET /recommendations/{user_id}` handler is a regular `def` (not `async def`), while all other route handlers are async. This blocks the event loop during Feast feature retrieval for existing users.
- **MinIO secure=False:** The MinIO client in `feast_service.py` is hardcoded to `secure=False` for in-cluster HTTP communication. This must be changed for external MinIO endpoints with TLS.
- **kafka-python is a dependency but unused:** The `pyproject.toml` lists `kafka-python>=2.2.11` but the `DatabaseService` singleton replaced Kafka for interaction logging. The dependency remains for potential future use or backward compatibility.
- **Backend Deployment init container uses ose-cli:** The backend Deployment's init container (`wait-for-db-init`) uses `registry.redhat.io/openshift4/ose-cli:latest` to poll the db-init Job status via `oc get job`. This requires the `job-viewer` ServiceAccount with RBAC to read Jobs in the namespace.

### Testing Notes

- Liveness check at `GET /health/live` returning `{"status": "alive"}`
- Readiness check at `GET /health/ready` returning `{"status": "ready"}` or 503 if DB unreachable
- The backend starts with `uvicorn main:app --host 0.0.0.0 --port 8000 --reload`
- DB initialization runs as a separate Kubernetes Job, not inline at app startup
- Dev mode: pass `dev` as CLI argument to proxy frontend requests to `localhost:9000`

### Related Patterns

- Deployment: Helm chart at `helm/product-recommender-system/` with pgvector subchart from ai-architecture-charts, OpenShift Route, and HPA support
- Training: separate `recommendation-training` component runs Kubeflow pipelines for model training
- Core library: `recommendation-core` package shared between backend and training (user encoder, CLIP encoder, dataset provider)
- Feature store: Feast with remote registry (gRPC + TLS), PostgreSQL online store with vector search enabled

---

## Approach E: Transaction Monitoring with Async Job Queue (from spending-transaction-monitor)

### When to Use

When building a transaction monitoring or financial alerting backend that uses LangGraph for alert rule processing (parse natural language to SQL, execute, evaluate), schedules ML-powered recommendations via background job queues, provides real-time WebSocket push notifications, and abstracts LLM/embedding providers behind factory patterns. Suited for applications requiring Keycloak OIDC authentication with dual internal/external URL handling, in-process ML model training at startup, and multi-provider LLM/embedding support (LlamaStack, OpenAI-compatible, local sentence-transformers).

### Differences from Approach A

- **AI pattern:** LangGraph for alert rule processing (natural language to SQL query pipelines), not for general agent chat dispatch across frameworks
- **Background processing:** Async job queue with thread pool executor for CPU-intensive recommendation generation, not synchronous request/response
- **Scheduling:** Background recommendation scheduler pre-generates recommendations for active users on configurable intervals (6 hours default)
- **ML:** In-process scikit-learn KNN recommender with startup training (heuristic fallback when no alert data), not external model serving
- **LLM abstraction:** Factory pattern with multiple providers (OpenAI-compatible via langchain-openai ChatOpenAI, LlamaStack via llama-stack-client) selectable via env var
- **Embedding abstraction:** Multi-provider embedding service (local sentence-transformers default, OpenAI, LlamaStack, Ollama deprecated) with abstract base class and factory function
- **Auth:** Keycloak OIDC with python-jose JWT validation, dual URL pattern (internal for API-to-Keycloak, external for token issuer validation), OIDC discovery with hardcoded fallback, and `BYPASS_AUTH` dev mode with test user header support
- **Communication:** WebSocket for push notifications (recommendation-ready events), not for chat streaming
- **Monorepo:** pnpm + Turborepo with `packages/api` and `packages/db` as separate workspaces, dotenv-cli for env loading in dev scripts
- **Build:** UBI9 with `TORCH_VARIANT` build arg (cpu or cuda) for PyTorch variant selection
- **Notifications:** Twilio SMS and SMTP email notification services

### Tech Stack & Dependencies

- **Runtime:** Python 3.12 on `registry.access.redhat.com/ubi9/python-312:latest`
- **Container image:** Single-stage Containerfile with `TORCH_VARIANT` build arg, copies `packages/api`, `packages/db`, and `data/`
- **Key dependencies:**
  - `fastapi>=0.104.0`, `uvicorn[standard]>=0.24.0` -- ASGI web framework and server
  - `sqlalchemy>=2.0.0`, `asyncpg>=0.29.0`, `alembic>=1.13.0` -- async ORM, PostgreSQL driver, migrations (shared `packages/db`)
  - `langchain>=0.1.0`, `langchain-openai>=0.1.0`, `langgraph>=0.2.0` -- LangGraph alert processing pipeline
  - `llama-stack-client>=0.5.0,<0.6.0` -- LlamaStack LLM client
  - `sentence-transformers>=3.0.0`, `torch>=2.0.0` -- local embedding model
  - `scikit-learn>=1.3.0`, `pandas>=2.0.0`, `numpy>=1.24.0` -- ML recommendation model
  - `python-jose[cryptography]>=3.3.0` -- JWT validation for Keycloak OIDC
  - `pydantic-settings>=2.1.0` -- settings management with env file priority
  - `twilio>=9.0.0` -- SMS notification delivery
  - `kafka-python>=2.0.0` -- listed dependency (for message queue integration)
  - `spending-monitor-db` -- shared database package (editable path source from `../db`)
- **Helm subchart:** N/A (deployed via Containerfile; uses `Makefile` at repo root)
- **Build system:** hatchling with `[tool.uv.sources]` for editable local dependency

### Key Patterns

#### Lifespan-Managed Background Services

The FastAPI lifespan context manager initializes and tears down four background services in order: ML system training, LLM thread pool, recommendation job queue, alert job queue, and recommendation scheduler. Each service has explicit `start()`/`stop()` lifecycle methods.

```python
# packages/api/src/main.py
@asynccontextmanager
async def lifespan(app: FastAPI):
    await initialize_ml_system()
    await llm_thread_pool.start()
    await recommendation_job_queue.start()
    await alert_job_queue.start()
    await recommendation_scheduler.start()
    yield
    await alert_job_queue.stop()
    await recommendation_job_queue.stop()
    await recommendation_scheduler.stop()
    await llm_thread_pool.stop()
```

#### Async Job Queue with Thread Pool for CPU-Intensive Work

The `RecommendationJobQueue` uses `asyncio.Queue` with a dedicated worker thread. CPU-intensive LLM/ML operations run in a `ThreadPoolExecutor` (4 workers). After job completion, WebSocket notifications are scheduled on the main event loop using `asyncio.run_coroutine_threadsafe`.

```python
# packages/api/src/services/recommendations/recommendation_job_queue.py
class RecommendationJobQueue:
    def __init__(self):
        self._queue: asyncio.Queue = asyncio.Queue()
        self._thread_pool = ThreadPoolExecutor(
            max_workers=4, thread_name_prefix='rec-worker'
        )
        self._worker_thread: threading.Thread | None = None

    async def start(self):
        self._worker_thread = threading.Thread(
            target=self._run_worker_in_thread,
            name='recommendation-job-worker',
            daemon=True,
        )
        self._worker_thread.start()
```

#### LangGraph Alert Processing Pipeline with Conditional SQL Routing

Alert rules are processed via two compiled LangGraph `StateGraph` instances: `app` for validation (creates rule then parses alert to SQL) and `trigger_app` for evaluation (routes based on saved SQL). The `should_use_saved_sql` conditional edge skips SQL generation when a cached query exists.

```python
# packages/api/src/services/alerts/generate_alert_graph.py
graph = StateGraph(AppState)
graph.add_node('route_sql_generation', RunnableLambda(lambda state: state))
graph.add_node('parse_alert', RunnableLambda(...))
graph.add_node('substitute_timestamp', RunnableLambda(substitute_timestamp))
graph.add_node('execute_sql', RunnableLambda(...))
graph.add_node('create_alert', RunnableLambda(generate_alert))
graph.add_node('generate_alert_message', RunnableLambda(generate_alert_message_node))

graph.add_conditional_edges(
    'route_sql_generation',
    should_use_saved_sql,
    {'substitute_timestamp': 'substitute_timestamp', 'parse_alert': 'parse_alert'},
)
```

#### Multi-Provider LLM Abstraction

Two LLM client implementations behind a common interface: `LLMClient` wraps `langchain-openai`'s `ChatOpenAI` for any OpenAI-compatible endpoint (including RHOAI model serving), while `LlamastackClient` uses the native `llama-stack-client` SDK. Provider is selected via the `LLM_PROVIDER` setting.

```python
# packages/api/src/services/llms/llm.py
class LLMClient:
    def __init__(self, max_tokens=8192, temperature=0.1, top_p=1):
        self.llm = ChatOpenAI(
            api_key=settings.API_KEY,
            model=settings.MODEL,
            base_url=settings.BASE_URL,
            async_client=async_client,
            http_client=http_client,
            max_tokens=max_tokens,
        )

# packages/api/src/services/llms/llamastack.py
class LlamastackClient:
    def __init__(self, max_tokens=8192, temperature=0.1, top_p=1):
        self.client = LlamaStackClient(base_url=settings.LLAMASTACK_BASE_URL)
```

#### Multi-Provider Embedding Service with Abstract Base

An abstract `EmbeddingProvider` base class with four implementations: `SentenceTransformerEmbeddingProvider` (default, local, no external dependencies), `OpenAIEmbeddingProvider`, `LlamaStackEmbeddingProvider`, and `OllamaEmbeddingProvider` (deprecated). A `get_embedding_client()` factory function selects the provider based on `EMBEDDING_PROVIDER` env var.

```python
# packages/api/src/services/embeddings/embedding_service.py
class EmbeddingProvider(ABC):
    @abstractmethod
    async def get_embedding(self, text: str) -> list[float]: ...
    @abstractmethod
    def get_dimensions(self) -> int: ...

def get_embedding_client() -> EmbeddingProvider:
    provider = os.getenv('EMBEDDING_PROVIDER', settings.EMBEDDING_PROVIDER)
    if provider == 'local' or provider == 'sentence-transformers':
        return SentenceTransformerEmbeddingProvider()
    elif provider == 'llamastack':
        return LlamaStackEmbeddingProvider()
    elif provider == 'openai':
        return OpenAIEmbeddingProvider()
```

#### Keycloak OIDC with Dual URL Pattern

The auth middleware uses two Keycloak URLs: `KEYCLOAK_URL` (internal, for API-to-Keycloak HTTP calls like JWKS and OIDC discovery) and `KEYCLOAK_FRONTEND_URL` (external, for token issuer validation since browsers obtain tokens via the external URL). The OIDC discovery response's issuer is overridden to match the frontend URL.

```python
# packages/api/src/auth/middleware.py
class KeycloakJWTBearer:
    async def get_oidc_config(self) -> dict:
        discovery_url = f'{KEYCLOAK_URL}/realms/{REALM}/.well-known/openid-configuration'
        response = requests.get(discovery_url, timeout=10.0)
        _oidc_config_cache = response.json()
        # Override issuer to use browser-accessible URL
        _oidc_config_cache['issuer'] = f'{KEYCLOAK_FRONTEND_URL}/realms/{REALM}'

    async def get_jwks(self) -> dict:
        # Fix JWKS URI to use internal URL instead of external
        parsed = urlparse(jwks_uri)
        jwks_uri = f'{KEYCLOAK_URL}{parsed.path}'
```

#### WebSocket Push Notifications for Recommendations

A `ConnectionManager` tracks active WebSocket connections per user (max 3 per user). When background recommendation jobs complete, notifications are pushed to connected clients via `notify_recommendations_ready`. Connection cleanup handles state checking via `WebSocketState.CONNECTED`.

```python
# packages/api/src/routes/websocket.py
class ConnectionManager:
    def __init__(self) -> None:
        self.active_connections: dict[str, set[WebSocket]] = {}
        self.max_connections_per_user = 3

    async def send_personal_message(self, message: dict, user_id: str) -> None:
        connections = self.active_connections[user_id].copy()
        for connection in connections:
            if connection.client_state == WebSocketState.CONNECTED:
                await connection.send_text(json.dumps(message))
```

#### Scheduled Recommendation Pre-Generation

The `RecommendationScheduler` runs as an asyncio background task, waiting for the database to have transaction data before first run. It identifies active users who lack recent cached recommendations (stale cutoff: 12 hours) and generates fresh recommendations in a thread pool.

```python
# packages/api/src/services/recommendations/recommendation_scheduler.py
class RecommendationScheduler:
    async def _wait_for_database_ready(self, max_wait_seconds: int = 60):
        while asyncio.get_event_loop().time() - start_time < max_wait_seconds:
            result = await session.execute(
                text('SELECT COUNT(*) FROM transactions')
            )
            count = result.scalar()
            if count and count > 0:
                return

    async def _get_users_needing_recommendations(self, session):
        active_cutoff = datetime.now(UTC) - timedelta(days=self.active_user_days)
        stale_cutoff = datetime.now(UTC) - timedelta(hours=12)
        # Query active users without recent cached recommendations
```

#### ML System Initialization at Startup

The ML recommendation system initializes during lifespan startup. It supports two modes: external inference service (verifies connectivity to OpenShift AI) or local model (trains scikit-learn KNN recommender from database alert data with heuristic-based fallback when no real alerts exist).

```python
# packages/api/src/services/ml_startup.py
async def initialize_ml_system():
    use_inference_service = (
        os.getenv('USE_ML_INFERENCE_SERVICE', 'false').lower() == 'true'
    )
    if use_inference_service:
        await verify_inference_service()
    else:
        await load_sample_alerts_if_needed()
        await train_ml_model_if_needed()
```

#### Pydantic Settings with Env File Priority Chain

The `Settings` class uses `pydantic-settings` with a 3-level env file priority: root `.env.development`, root `.env`, then `packages/api/.env`. The `model_post_init` hook auto-enables `BYPASS_AUTH` in development mode unless explicitly set via environment.

```python
# packages/api/src/core/config.py
class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=[
            Path(__file__).resolve().parents[4] / '.env.development',
            Path(__file__).resolve().parents[4] / '.env',
            Path(__file__).resolve().parents[2] / '.env',
        ],
        extra='ignore',
    )

    def model_post_init(self, __context):
        if self.ENVIRONMENT == 'development' and 'BYPASS_AUTH' not in os.environ:
            self.BYPASS_AUTH = True
```

#### Containerfile with PyTorch CPU/CUDA Variant Selection

The Containerfile uses a `TORCH_VARIANT` build arg to select between CPU (lightweight, ~176MB) and CUDA (GPU-enabled, ~800MB) PyTorch installations. It also handles UBI9 vs Debian base image detection for system dependency installation.

```dockerfile
# packages/api/Containerfile
ARG BASE_IMAGE=registry.access.redhat.com/ubi9/python-312:latest
ARG TORCH_VARIANT=cpu
RUN if [ "$TORCH_VARIANT" = "cpu" ]; then \
        uv pip install --python $(which python3) --system --no-cache \
            --index-url https://download.pytorch.org/whl/cpu torch; \
    else \
        uv pip install --python $(which python3) --system --no-cache torch; \
    fi
```

### Configuration

- **Environment variables:**
  - `DATABASE_URL` -- async PostgreSQL connection string (`postgresql+asyncpg://...`)
  - `LLM_PROVIDER` -- LLM provider selection: `openai` (default) or `llamastack`
  - `BASE_URL` / `API_KEY` / `MODEL` -- OpenAI-compatible LLM config
  - `LLAMASTACK_BASE_URL` / `LLAMASTACK_MODEL` -- LlamaStack LLM config
  - `EMBEDDING_PROVIDER` -- embedding provider: `local` (default), `openai`, `llamastack`, `ollama` (deprecated)
  - `EMBEDDING_MODEL` / `EMBEDDING_DIMENSIONS` -- embedding model config (default: `all-minilm`, 384 dims)
  - `KEYCLOAK_URL` -- internal URL for API-to-Keycloak communication (container/cluster network)
  - `KEYCLOAK_FRONTEND_URL` -- external URL for browser access and token issuer validation
  - `KEYCLOAK_REALM` / `KEYCLOAK_CLIENT_ID` -- Keycloak realm and client config
  - `BYPASS_AUTH` -- skip JWT validation (auto-enabled in development mode)
  - `JWT_CLOCK_SKEW_LEEWAY_SECONDS` -- clock skew tolerance for JWT validation (default: 120)
  - `ENVIRONMENT` -- environment mode: `development`, `production`, `staging`, `test`, `ci`
  - `ALLOWED_HOSTS` -- CORS origins list (default: `http://localhost:5173`)
  - `USE_ML_INFERENCE_SERVICE` -- use external OpenShift AI inference vs local model (default: `false`)
  - `SMTP_HOST` / `SMTP_PORT` / `SMTP_USERNAME` / `SMTP_PASSWORD` / `SMTP_FROM_EMAIL` -- email notification config
  - `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` / `TWILIO_PHONE_NUMBER` -- SMS notification config
  - `RECOMMENDATION_*` -- prefixed env vars for recommendation config (thread pool workers, batch size, cache duration, scheduler interval)
- **Config files:**
  - `packages/api/src/core/config.py` -- centralized `Settings` class via pydantic-settings with env file priority chain
  - `packages/api/src/core/recommendation_config.py` -- `RecommendationConfig` class with `RECOMMENDATION_` env prefix
  - `packages/api/pyproject.toml` -- hatchling build system, uv sources, ruff config, mypy overrides, pytest config
  - `packages/api/package.json` -- pnpm scripts for dev/start/test/lint/format/type-check via uv
- **Helm values:** N/A (uses Makefile at repo root)

### Known Gotchas

- **Keycloak dual URL pattern is required:** The auth middleware must use `KEYCLOAK_URL` (internal) for JWKS and OIDC discovery HTTP calls, but override the issuer to `KEYCLOAK_FRONTEND_URL` (external) for JWT validation. Without this override, token validation fails because browsers obtain tokens via the external URL whose issuer claim differs from the internal discovery endpoint's issuer. The JWKS URI is also re-written to use the internal URL. Both the override and the rewrite are documented in inline comments in `middleware.py`.
- **OIDC discovery fallback to hardcoded endpoints:** If the Keycloak OIDC discovery endpoint is unreachable (common during startup before Keycloak is ready), the middleware falls back to hardcoded endpoint paths. The fallback is logged with a warning and cached for 1 hour.
- **JWT clock skew leeway defaults to 120 seconds:** The `JWT_CLOCK_SKEW_LEEWAY_SECONDS` setting defaults to 120 to handle Keycloak-to-API pod clock drift. This is notably high and documented in a config comment as being specifically for Keycloak integration.
- **Development bypass auto-enables without explicit env var:** `model_post_init` in `Settings` sets `BYPASS_AUTH = True` in development mode unless `BYPASS_AUTH` is explicitly set in `os.environ`. This means the auth bypass only occurs when the environment variable is absent, not when it is set to any value.
- **Monorepo editable install for DB package:** `pyproject.toml` uses `[tool.uv.sources]` with `path = "../db", editable = true` for the shared `spending-monitor-db` package. The Containerfile copies both `packages/api/` and `packages/db/` and installs the DB package first with `uv pip install -e`.
- **httpx clients created with `verify=False`:** Both `LLMClient` and `LlamastackClient` create `httpx.AsyncClient(verify=False)` and `httpx.Client(verify=False)` at module level. This disables TLS certificate verification for all LLM API calls, which is appropriate for self-signed certs on internal RHOAI endpoints but should not be used in production with external providers.
- **Recommendation job queue WebSocket notification uses `asyncio.get_event_loop()`:** The worker thread schedules WebSocket notifications via `asyncio.run_coroutine_threadsafe(notify_recommendations_ready(...), asyncio.get_event_loop())`, which relies on the deprecated `get_event_loop()` to cross thread boundaries. This works but may break in future Python versions.
- **Health check database check is disabled:** The health check route in `routes/health.py` has the database connectivity check commented out with a note: "Temporarily disable database health check to fix hanging issue". Only the API status is reported.
- **ML model trains synchronously during startup:** `initialize_ml_system()` runs during lifespan startup (before the server accepts connections). If training takes long, the application startup is delayed. Unlike Approach A which uses deferred background tasks, this blocks until complete.
- **Containerfile UBI9/Debian detection for system deps:** The Containerfile uses `echo "${BASE_IMAGE}" | grep -q "ubi"` to detect whether to use `dnf` (UBI) or `apt-get` (Debian) for system dependencies. The subscription-manager removal (`rm -f /etc/rhsm-host`) prevents host RHEL subscriptions from leaking into the container build.

### Testing Notes

- Health check at `GET /health/` returning a list of `HealthResponse` objects (currently only API status, DB check disabled)
- Root endpoint at `GET /` returning `{"message": "Welcome to spending-monitor API"}`
- Dev mode: `pnpm dev` runs uvicorn with `--reload` via dotenv-cli loading root `.env`
- Tests run with `ENVIRONMENT=test uv run pytest` with coverage threshold of 40%
- Test user header support: set `X-Test-User-Email` header to authenticate as a specific user in dev mode
- pytest markers: `integration` and `slow` for selective test execution

### Related Patterns

- Database: shared `packages/db` package with SQLAlchemy models, Alembic migrations, async session factory
- Frontend: separate `packages/ui` React app communicating via REST and WebSocket
- Monorepo: pnpm workspaces with Turborepo, shared root `.env` loaded via dotenv-cli
- LangGraph: used for alert rule processing (not general agent chat) with separate validation and trigger graph compilations

---

## Choosing Between Approaches

| Criteria | Approach A (ai-virtual-agent) | Approach B (ansible-log-analysis) | Approach C (multi-agent-loan-origination) | Approach D (product-recommender-system) | Approach E (spending-transaction-monitor) |
|----------|-------------------------------|-----------------------------------|-------------------------------------------|------------------------------------------|-------------------------------------------|
| **Use case** | Interactive multi-framework agent chat platform | Event-driven log analysis pipeline | Multi-agent regulated-industry application | E-commerce product recommendation serving | Financial transaction monitoring with ML alerts |
| **Agent frameworks** | LlamaStack, LangGraph, CrewAI (pluggable) | LangGraph only (fixed pipeline) | LangGraph only (5 persona-specific agents) | None (Feast + PyTorch in-process inference) | LangGraph for alert pipelines + scikit-learn ML |
| **Agent count** | 1 (dynamically configured) | 1 (fixed pipeline) | 5 (public, borrower, LO, underwriter, CEO) | N/A (no agents) | 2 LangGraph graphs (validation + trigger) |
| **LLM routing** | Per-runner env vars with sentinel-based resolution | Single endpoint + optional tool-calling endpoint | YAML model tiers (llm, vision, embedding) with hot-reload | Single endpoint for review summarization only | Multi-provider factory (OpenAI-compatible + LlamaStack) |
| **Safety** | None built-in | None built-in | NeMo Guardrails input/output shield nodes (fail-closed) | None built-in | None built-in |
| **Auth / RBAC** | OAuth header forwarding | None | Keycloak OIDC + 3-layer RBAC (route, tool_auth node, DataScope) | JWT with bcrypt/passlib (simple token auth) | Keycloak OIDC + python-jose (dual URL pattern) |
| **Communication** | SSE streaming | REST endpoints | WebSocket streaming with disconnect cancellation | REST endpoints | REST + WebSocket push notifications |
| **Background processing** | Deferred startup tasks | None | None | K8s Job for DB init | Async job queue + thread pool + scheduled pre-generation |
| **ORM / Migrations** | SQLAlchemy + Alembic | SQLModel + create_all (no migrations) | SQLAlchemy + Alembic (shared db package in monorepo) | SQLAlchemy + create_all via K8s Job (no migrations) | SQLAlchemy + Alembic (shared db package in monorepo) |
| **Base image** | UBI9 | UBI8 | python:3.11-slim | recommendation-core (custom base with ML deps) | UBI9 (with CPU/CUDA PyTorch variant selection) |
| **Package manager** | pip | uv (with PyTorch CPU-only index) | uv + hatchling (Turborepo monorepo) | uv pip install (in Containerfile) | uv + hatchling (pnpm/Turborepo monorepo) |
| **Observability** | None built-in | Phoenix/OTEL with LangChain instrumentation | MLflow autolog + Prometheus custom metrics | None built-in | None built-in |
| **PII handling** | None | None | Middleware-based recursive PII masking per role | None | None |
| **Feature store** | None | None | None | Feast with PostgreSQL online store + vector search | None |
| **Model serving** | External (LlamaStack, vLLM endpoints) | External (OpenAI-compatible endpoint) | External (OpenAI-compatible endpoint) | In-process PyTorch (user encoder + CLIP) | In-process scikit-learn + optional external inference |
| **Embeddings** | None | SentenceTransformer (local or remote) | sentence-transformers (local) | None | Multi-provider (local sentence-transformers default) |
| **Conversation persistence** | InMemorySaver | None | langgraph-checkpoint-postgres (per-user threads) | N/A | N/A (alert rules persisted, not conversations) |
| **Deployment** | compose.yaml | compose.yaml | Helm chart + compose.yml (init containers, Kagenti sidecar) | Helm chart with pgvector subchart (ai-architecture-charts) + K8s Job for DB init | Containerfile + Makefile |
