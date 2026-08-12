---
name: agent-orchestration
description: Agent orchestration patterns from multi-runner dispatch to LangGraph DAGs to dual-provider factory
summary: "Covers seven agent orchestration patterns for RHOAI quickstarts spanning multi-runner dispatch with LlamaStack/LangGraph/CrewAI behind a unified ChatService (A), hierarchical LangGraph DAG for batch log analysis with clustering deduplication (B), dual-provider factory with MCP-Direct vs Llama Stack (C), YAML-driven conversational state machines with CloudEvent microservices via Knative broker (D), multi-persona LangGraph agents with per-tool RBAC authorization nodes (E), vision-context-aware structured-output router for CV+SQL queries (F), and custom OpenAI SDK loop with HTTP tool discovery and two-phase pipeline-then-chat (G). Choose A for runtime-selectable frameworks with normalized SSE streaming (BaseRunner.stream()); B for event-driven batch processing with no user interaction and Command(goto=...) conditional routing; C for deployment-time provider selection via COPILOT_PROVIDER_MODE env var (backend agentic loop with Nemotron TOOLCALL tag parsing vs delegated Llama Stack); D for YAML-defined typed states (waiting/llm_processor/intent_classifier/llm_validator/terminal) with LlamaStack Responses API and multi-agent routing; E for regulated-industry per-tool allowed_roles enforced by a tool_auth graph node with AsyncPostgresSaver checkpointing and A2A protocol via Kagenti; F for multimodal apps routing between live CV context and SQL agent queries via RouteDecision structured output; G for deterministic pipeline before agentic chat with REST tool protocol (GET /tools, POST /tools/<name>) and PHASE2_TOOLS subset filtering. Critical patterns: ChatService._get_runner() dispatches by runner_type with lazy imports for optional packages (A); create_provider() factory selects MCPDirectProvider or LlamaStackProvider with hard-coded tool allowlist+Pydantic validation in MCP-Direct only (C); build_agent_graph() embeds NeMo Guardrails as input_shield/output_shield StateGraph nodes with tool_auth RBAC node using conditional edges (E); NeMo integration varies across approaches -- runner-level shields (A), graph nodes (E), Colang flows with jailbreak detection (D), HTTP client with fail-open degradation (G); session persistence ranges from in-memory InMemorySaver/dict (A/C/F) to PostgreSQL AsyncPostgresSaver (D/E). Common gotchas: dual LLM endpoints may be needed when the default model lacks tool-calling support (B); Nemotron streaming requires an 11-character buffer window to avoid splitting TOOLCALL/think tags and tool validation is absent in the Llama Stack provider path (C); the _consumed_this_invoke flag prevents multiple waiting states from consuming the same HumanMessage in a single graph invocation (D); output_shield re-sends full response for NeMo evaluation triggering a ~32s LLM call that can exceed the httpx 30s timeout (E); asyncio.run() inside synchronous Flask handlers creates a new event loop per request (F); tool schemas are rediscovered on every HTTP request with no cross-request caching (G)."
metadata:
  type: architecture
tags:
  tech_stack: [fastapi, flask, langchain, langgraph, crewai, llamastack, python, gradio, sentence-transformers, scikit-learn, sveltekit, openai-sdk, vega-lite, cloudevents, nemo-guardrails, zammad, react, tailwindcss, tanstack-router, keycloak, a2a-protocol, kagenti, opencv, yfinance, scipy, mlserver]
  ai_pattern: [agents, prompt-chaining, model-serving, embeddings, data-governance, guardrails, rag, multimodal]
  platform: [llamastack, vllm, rhoai, openshift, kserve, knative, openvino, triton, mlserver]
  data_layer: [postgresql, pgvector, minio]
source_examples:
  - quickstart: "ai-virtual-agent"
    repo: "https://github.com/rh-ai-quickstart/ai-virtual-agent"
    notes: "Multi-runner agent orchestration with LlamaStack, LangGraph, and CrewAI runners behind a unified ChatService dispatcher"
    approach: "A"
  - quickstart: "ansible-log-analysis"
    repo: "https://github.com/rh-ai-quickstart/ansible-log-analysis"
    notes: "Hierarchical LangGraph DAG with nested subgraphs for automated event-driven Ansible log analysis, LLM-based conditional routing, and tool-calling Loki agent"
    approach: "B"
  - quickstart: "data-governance-co-pilot"
    repo: "https://github.com/rh-ai-quickstart/data-governance-co-pilot"
    notes: "Dual-provider factory pattern selecting between backend-managed agentic loop (MCP-Direct with vLLM + MCP) and delegated orchestration (Llama Stack Agents API), both consuming the same pg-airman-mcp tool server"
    approach: "C"
  - quickstart: "it-self-service-agent"
    repo: "https://github.com/rh-ai-quickstart/it-self-service-agent"
    notes: "YAML-driven configurable state machine with LangGraph, multi-agent routing via CloudEvents, LlamaStack Responses API, and NeMo guardrails integration"
    approach: "D"
  - quickstart: "multi-agent-loan-origination"
    repo: "https://github.com/rh-ai-quickstart/multi-agent-loan-origination"
    notes: "Five persona-specific LangGraph agents with YAML-driven configs, registry-based hot-reloading, per-tool RBAC authorization node, NeMo Guardrails graph nodes, WebSocket streaming, and A2A protocol integration via Kagenti"
    approach: "E"
  - quickstart: "multimodal-compliance-monitor"
    repo: "https://github.com/rh-ai-quickstart/multimodal-compliance-monitor"
    notes: "Vision-context-aware LangGraph router with structured-output routing (context vs SQL path), ReAct SQL agents querying detection data via postgres-mcp, and a separate alert graph converting English rules to SQL"
    approach: "F"
  - quickstart: "portfolio-manager-agent"
    repo: "https://github.com/rh-ai-quickstart/portfolio-manager-agent"
    notes: "Custom OpenAI function-calling loop with HTTP tool discovery protocol, two-phase architecture (deterministic pipeline then agentic chat with tool filtering), context injection via system prompt, and NeMo Guardrails input/output checks"
    approach: "G"
---

# Agent Orchestration

## Overview

This architecture implements a pluggable agent orchestration layer where multiple AI agent frameworks (LlamaStack, LangGraph, CrewAI) run behind a unified dispatch service. A single FastAPI chat endpoint accepts user messages, resolves which runner framework to use based on the virtual agent's `runner_type` configuration, and delegates streaming to the selected runner. All runners produce a normalized SSE event stream consumed by the frontend, enabling framework-agnostic agent execution.

## Data Flow

1. User submits a chat message via the React/PatternFly frontend
2. `POST /api/v1/chat` receives the `ChatRequest` containing `virtualAgentId`, `sessionId`, and message content
3. The endpoint fetches the `VirtualAgent` from PostgreSQL (including its `runner_type`, `model_name`, `prompt`, `tools`, and `graph_config`)
4. `ChatService._get_runner()` resolves the runner implementation based on `runner_type` ("llamastack", "langgraph", or "crewai")
5. The selected runner streams SSE events back through a `StreamingResponse`
6. The frontend consumes normalized event types: `reasoning`, `response`, `tool_call`, `node_started`, `node_completed`, `token_usage`, `error`
7. The stream terminates with `data: [DONE]\n\n`

## Component Wiring

| From | To | Protocol | Purpose |
|------|----|----------|---------|
| React frontend | FastAPI backend | REST/SSE | Chat messages in, SSE event stream out |
| ChatService | BaseRunner subclass | Python method call | Dispatch to framework-specific runner |
| LlamaStackRunner | LlamaStack server | HTTP (AsyncLlamaStackClient) | Responses API with Conversations for inference + tool execution |
| LangGraphRunner | vLLM/LlamaStack | HTTP (ChatOpenAI) | OpenAI-compatible inference endpoint |
| LangGraphRunner | MCP servers | HTTP (MultiServerMCPClient) | Load MCP tools into LangGraph agent |
| CrewAIRunner | vLLM/LlamaStack | HTTP (LiteLLM) | OpenAI-compatible inference via LiteLLM routing |
| All runners | PostgreSQL | SQLAlchemy async | Session management, token tracking, title updates |

## Key Integration Points

### ChatService Dispatch

The `ChatService` is the single entry point for chat. It resolves which runner to use based on the agent's `runner_type` field, defaulting to LlamaStack when unset.

```python
# backend/app/services/chat.py (lines 43-75)
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
        else:
            raise ValueError(f"Unsupported runner type: '{runner_type}'.")
```

### BaseRunner Contract

All runners implement `BaseRunner.stream()` which yields SSE-formatted strings. The normalized event types ensure the frontend works unchanged regardless of which framework powers the agent.

```python
# backend/app/services/runners/base.py (lines 18-65)
class BaseRunner(ABC):
    @abstractmethod
    async def stream(
        self,
        agent: Any,
        session_id: str,
        prompt: Any,
    ) -> AsyncIterator[str]:
        """
        Must yield SSE-formatted strings using normalized event types:
        - reasoning: thinking/reasoning text
        - response: output text deltas
        - tool_call: tool invocations and results
        - error: error messages
        - node_started / node_completed: graph node lifecycle
        The stream must end with 'data: [DONE]\n\n'.
        """
        ...
```

### LangGraph Dual-Mode Dispatch

The LangGraph runner supports two execution modes selected by the presence of `agent.graph_config`: a prebuilt ReAct agent (using `create_react_agent`) and a declarative graph engine that executes a DAG of typed nodes (llm, mcp_tool, mcp_tool_map, router).

```python
# backend/app/services/runners/langgraph_runner.py (lines 538-589)
async def stream(self, agent, session_id, prompt):
    graph_config = getattr(agent, "graph_config", None)
    if graph_config:
        # Declarative graph mode: execute a DAG of typed nodes
        async for event in self._run_declarative_graph(agent, session_id, prompt):
            yield event
    else:
        # ReAct agent mode: create_react_agent with MCP tools
        mcp_configs = await self._resolve_mcp_servers(agent.tools)
        if mcp_configs:
            async with MultiServerMCPClient(mcp_configs) as mcp_client:
                tools = mcp_client.get_tools()
                async for event in self._run_graph(agent, tools, session_id, prompt):
                    yield event
```

### VirtualAgent Model

The `VirtualAgent` database model stores per-agent configuration including which runner to use, the model, system prompt, tools, knowledge bases, shields, and optional graph configuration for declarative workflows.

```python
# backend/app/models/agent.py (lines 14-57)
class VirtualAgent(Base):
    __tablename__ = "virtual_agents"
    id = Column(UUID(as_uuid=True), primary_key=True)
    name = Column(String(255), nullable=False, unique=True)
    runner_type = Column(String(50), server_default="llamastack")  # "llamastack" | "langgraph" | "crewai"
    model_name = Column(String(255), nullable=False)
    prompt = Column(String, nullable=True)
    tools = Column(JSON, nullable=True, default=list)
    knowledge_base_ids = Column(JSON, nullable=True, default=list)
    vector_store_ids = Column(JSON, nullable=True, default=list)
    input_shields = Column(JSON, nullable=True, default=list)
    output_shields = Column(JSON, nullable=True, default=list)
    graph_config = Column(JSON, nullable=True)
```

## Prompt / Chain Patterns

Each runner handles prompts differently:

- **LlamaStack**: Passes `agent.prompt` as `instructions` parameter to the Responses API alongside structured `input` messages. The LlamaStack server manages conversation history via conversation IDs.

- **LangGraph ReAct**: Passes `agent.prompt` as the system `prompt` parameter to `create_react_agent()`, which creates a ReAct-style agent with tool-calling capability. Session persistence uses an in-memory checkpointer keyed by `session_id`.

- **LangGraph Declarative**: Uses a `GraphEngine` that parses a `graph_config` dict defining a DAG of nodes. Prompts are rendered via template substitution (`{inputs.field}`, `{outputs.node_id}`), and the engine supports parallel node execution via LangGraph's `StateGraph`.

- **CrewAI**: Maps the agent's `prompt` to a CrewAI `Task.description`, with `persona` as role and `description` as backstory. Supports both single-agent and multi-agent crews defined via `graph_config.agents` and `graph_config.tasks`. A `_StreamDeduplicator` filters out ReAct noise (Thought/Action/Input lines) from the stream.

## Gotchas

- LangGraph and CrewAI runners are lazily imported inside `_get_runner()` (lines 63-64, 70) to avoid import errors when those optional packages are not installed. The runner checks availability with `_check_langgraph()` / `CREWAI_AVAILABLE` before executing.
- The LlamaStackRunner implements a retry loop (lines 660-714) that automatically excludes tools when LlamaStack returns "Tool not found" errors, retrying without the failed tool type.
- CrewAI's `_StreamDeduplicator` (lines 49-188 of `crewai_runner.py`) is necessary because CrewAI streams raw ReAct tokens including "Thought:", "Action:", "Action Input:" lines that are noise to end users.
- The LangGraph runner's `InMemorySaver` checkpointer (line 74) is sufficient for single-process development but the code comments note it should be swapped for `PostgresSaver` in multi-worker deployments.
- Both LangGraph and CrewAI runners include `_extract_input_fields` methods that use the LLM itself to extract structured fields (destination, num_days, origin) from natural-language user messages when `graph_config.input_fields` are defined.

## Related Architectures

- [guardrails-layer](guardrails-layer.md) -- Input/output shields are applied before runner dispatch in the LlamaStack runner
- [rag-pipeline](rag-pipeline.md) -- Knowledge bases are attached to agents via `vector_store_ids` and exposed as `file_search` tools
- [mcp-tool-integration](mcp-tool-integration.md) -- MCP servers provide external tool capabilities to all three runners

---

## Approach B: Hierarchical LangGraph DAG for Automated Log Analysis (from ansible-log-analysis)

### When to Use

Use this approach when building an event-driven AI pipeline that processes incoming data (e.g., log alerts) through a fixed sequence of LLM-powered analysis steps with conditional branching. Unlike Approach A's user-facing chat interface with pluggable runners, this approach defines a deterministic multi-level graph that automatically routes through summarization, classification, context retrieval, and remediation generation without user interaction during processing.

### Differences from Approach A

| Aspect | Approach A (Multi-Runner Dispatch) | Approach B (Hierarchical LangGraph DAG) |
|--------|-----------------------------------|----------------------------------------|
| Trigger | User chat message via frontend | Grafana alert or batch Loki query |
| Graph structure | Configurable per-agent (`runner_type`, `graph_config`) | Fixed hierarchical DAG with nested subgraphs |
| Runner framework | Selectable (LlamaStack, LangGraph, CrewAI) | LangGraph only, with LangChain `create_agent` for tool calling |
| Streaming | SSE event stream to frontend | No streaming; batch async processing |
| Agent configuration | Database-driven (`VirtualAgent` model) | Hardcoded graph definitions compiled at module load |
| Routing | Runtime dispatch based on `runner_type` | LLM-based conditional routing via `Command(goto=...)` |
| Context enrichment | RAG via `file_search` tool, MCP tools | RAG "cheat sheet" + Loki log retrieval subgraphs |
| Processing mode | Single request-response per chat message | Batch processing: cluster logs, then process unique representatives in parallel |

### Data Flow

1. Grafana alert fires or batch pipeline queries Loki for failed/fatal logs
2. Logs are embedded (SentenceTransformer or remote OpenAI-compatible endpoint) and clustered (DBSCAN/HDBSCAN/MeanShift/AgglomerativeClustering) to deduplicate similar errors
3. One representative log per cluster enters the main `inference_graph`:
   - `cluster_logs_node`: Assigns incoming log to a cluster via the clustering service
   - `no_clustering_graph_node`: Invokes the inner `graph_without_clustering` subgraph
4. Inner `graph_without_clustering` DAG:
   - `summarize_log_node`: LLM summarizes the raw log (structured output: `SummarySchema`)
   - `classify_log_node`: LLM classifies log into expert category (structured output: `ClassifySchema`)
   - `router_step_by_step_solution_node`: LLM decides if more context is needed (structured output: `RouterStepByStepSolutionSchema`)
   - If "Need More Context" -> `get_more_context_node` (invokes context agent subgraph)
   - If "No More Context Needed" -> `suggest_step_by_step_solution_node`
5. Context agent subgraph (`more_context_agent_graph`):
   - `cheat_sheet_context_node`: Queries RAG service for known error solutions
   - `loki_router_node`: LLM decides if additional Loki log context is needed
   - If needed -> `loki_sub_agent` (invokes Loki agent subgraph)
6. Loki agent subgraph (`loki_agent_graph`):
   - `identify_missing_log_data_node`: LLM generates a natural-language request for what log data is missing
   - `loki_execute_query_node`: LangChain `create_agent` with Loki tools executes LogQL queries via MCP
   - `summarize_loki_context_node`: LLM summarizes retrieved log context for root cause analysis
7. `suggest_step_by_step_solution_node`: LLM generates step-by-step remediation using all gathered context (cheat sheet + Loki logs)
8. Result is persisted to PostgreSQL as a `GrafanaAlert` record

### Component Wiring

| From | To | Protocol | Purpose |
|------|----|----------|---------|
| Grafana/Alloy | Loki | Log stream | Ansible log ingestion and storage |
| Grafana | FastAPI backend | REST (POST /grafana-alert/) | Alert notification triggers inference |
| FastAPI backend | LangGraph inference_graph | Python method call | Invoke the main agent DAG |
| Main graph | Context agent subgraph | LangGraph subgraph invocation | Retrieve additional context |
| Context agent | RAG service | HTTP (httpx POST /rag/query) | Cheat sheet lookup for known errors |
| Context agent | Loki agent subgraph | LangGraph subgraph invocation | Retrieve surrounding log context |
| Loki agent | Loki MCP server | HTTP (JSON-RPC via MCP client) | Execute LogQL queries |
| LLM nodes | vLLM/OpenAI-compatible endpoint | HTTP (ChatOpenAI) | All LLM inference (summarization, classification, routing, generation) |
| Backend | PostgreSQL | SQLAlchemy async | Persist GrafanaAlert results |
| Backend | Clustering service | HTTP (POST /cluster) | Predict log cluster assignment |
| Gradio UI | FastAPI backend | HTTP (httpx GET /grafana-alert/) | Display processed alerts with solutions |

### Key Integration Points

#### Hierarchical Graph Structure with Command-Based Routing

The main graph delegates to subgraphs using LangGraph's `Command` type for conditional routing. Each node returns a `Command` specifying which node to execute next.

```python
# src/alm/agents/graph.py (lines 68-78)
async def router_step_by_step_solution_node(
    state: GrafanaAlertState,
) -> Command:
    log_summary = state.logSummary
    classification = await router_step_by_step_solution(log_summary, llm)
    return Command(
        goto="suggest_step_by_step_solution_node"
        if classification == "No More Context Needed"
        else "get_more_context_node",
        update={"needMoreContext": classification == "Need More Context"},
    )
```

#### Subgraph Invocation via Direct Graph Execution

Subgraphs are compiled LangGraph `StateGraph` instances invoked via `.ainvoke()` from parent graph nodes, passing a subset of the parent state.

```python
# src/alm/agents/graph.py (lines 81-110)
async def get_more_context_node(
    state: GrafanaAlertState,
) -> Command:
    try:
        log_summary = state.logSummary
        subgraph_state = await more_context_agent_graph.ainvoke(
            ContextAgentState(
                log_summary=log_summary,
                log_entry=state.log_entry,
                expert_classification=state.expertClassification,
            )
        )
        context_agent_state = ContextAgentState.model_validate(subgraph_state)
        loki_context = context_agent_state.loki_context
        cheat_sheet_context = (
            f"Context from cheat sheet:\n{context_agent_state.cheat_sheet_context}"
        )
        context = (
            f"Context logs from loki:\n{loki_context}\n\n{cheat_sheet_context}"
            if loki_context
            else cheat_sheet_context
        )
```

#### LLM Structured Output for Graph Routing

Routing decisions are made by the LLM via structured output schemas. The LLM returns a typed response that drives `Command(goto=...)`.

```python
# src/alm/agents/output_scheme.py (lines 24-27)
class RouterStepByStepSolutionSchema(BaseModel):
    suggestion: Literal["No More Context Needed", "Need More Context"] = Field(
        description="The suggestion for the step by step solution"
    )
```

#### Tool-Calling Agent Within Subgraph

The Loki agent subgraph embeds a LangChain `create_agent` that uses tool calling for log queries. Tools are created with Python closures to bind log context (file name, message, timestamp) at creation time, avoiding LLM JSON serialization of complex values.

```python
# src/alm/agents/loki_agent/agent.py (lines 37-72)
class LokiQueryAgent:
    def __init__(self, file_name: str, log_message: str, log_timestamp: str):
        from alm.tools import LOKI_STATIC_TOOLS, create_log_lines_above_tool

        self.llm = get_llm_support_tool_calling()
        self.tools = [
            *LOKI_STATIC_TOOLS,
            create_log_lines_above_tool(file_name, log_message, log_timestamp),
        ]
        self.agent = self._initialize_agent()

    def _initialize_agent(self):
        with open(LOKI_AGENT_SYSTEM_PROMPT_PATH, "r") as f:
            system_prompt = f.read()
        return create_agent(
            model=self.llm,
            tools=self.tools,
            system_prompt=system_prompt,
        )
```

#### Batch Processing with Clustering

The offline pipeline deduplicates logs via embedding + clustering before running them through the graph, processing only unique cluster representatives in parallel.

```python
# src/alm/pipeline/offline.py (lines 86-92)
async def training_pipeline_process(
    log_entries, cluster_labels, unique_cluster,
):
    results = await asyncio.gather(
        *[
            _process_alert(label, log_entry)
            for label, log_entry in unique_cluster.items()
        ]
    )
```

#### Dual LLM Endpoints

The system uses two separate LLM endpoints: a default one for general inference (summarization, classification, routing) and a separate tool-calling-capable endpoint for the Loki agent, configured via separate environment variables.

```python
# src/alm/llm.py (lines 67-91)
def get_llm_support_tool_calling():
    API_KEY_WITH_TOOL_CALLING: str = os.getenv("OPENAI_API_TOKEN_WITH_TOOL_CALLING")
    BASE_URL_WITH_TOOL_CALLING: str = os.getenv("OPENAI_API_ENDPOINT_WITH_TOOL_CALLING")
    MODEL_WITH_TOOL_CALLING: str = os.getenv("OPENAI_MODEL_WITH_TOOL_CALLING")
    # ... falls back to default LLM if not configured
```

### Prompt / Chain Patterns

Each LLM call in the graph uses a distinct pattern:

- **Summarization**: System prompt loaded from `prompts/summarize_error_log.md`, user prompt templates with `{error_log}` placeholder, structured output via `SummarySchema`.
- **Classification**: System prompt loaded from `prompts/classifiy_log.md`, user prompt with `{log_summary}`, structured output via `ClassifySchema` with 8 expert categories (Cloud Infrastructure, Kubernetes, DevOps, Networking, System Admin, App Dev, IAM, Other).
- **Context routing**: System prompt loaded from `prompts/router_step_by_step_solution.md`, structured output via `RouterStepByStepSolutionSchema` ("No More Context Needed" / "Need More Context").
- **Loki routing**: System prompt from `prompts/loki_router.md`, user prompt includes both log summary and cheat sheet context, structured output via `LokiRouterSchema` ("need_more_context_from_loki_db" / "no_need_more_context_from_loki_db").
- **Missing data identification**: System prompt as inline string ("You are an Ansible expert..."), prompt loaded from `prompts/identify_missing_data.md` with `{log_summary}`, `{log_labels}`, `{log_timestamp}` substitution, structured output via `IdentifyMissingDataSchema`.
- **Loki log summarization**: System prompt as inline string, prompt loaded from `prompts/summarize_loki_logs.md` with multiple field substitutions, structured output via `LogSummarizationSchema`.
- **Step-by-step solution**: System prompt from `prompts/create_step_by_step_sol.md`, user prompt varies based on whether context is available (two template variants), uses `stream_with_fallback` for streaming with graceful degradation on mid-stream errors.

### Gotchas

- The system requires two LLM endpoints because the default RHOAI model may not support tool calling. The `get_llm_support_tool_calling()` function (lines 67-91 of `llm.py`) checks for separate `OPENAI_API_TOKEN_WITH_TOOL_CALLING`, `OPENAI_API_ENDPOINT_WITH_TOOL_CALLING`, and `OPENAI_MODEL_WITH_TOOL_CALLING` environment variables and falls back to the default LLM if not configured.
- The `get_more_context_node` (lines 81-110 of `graph.py`) wraps the entire subgraph invocation in a try-except, continuing without context if any part of the context retrieval chain fails. The `suggest_step_by_step_solution_node` has a similar fallback (lines 49-65), retrying without context if the contextualized call fails.
- LangGraph graphs are compiled once at module load time (`inference_graph()`, `more_context_agent_graph = build_graph()`, `loki_agent_graph = build_loki_agent_graph()`) and reused across requests. The module-level `llm = get_llm()` instance is shared across all graph nodes.
- The Loki agent creates a fresh `LokiQueryAgent` instance per invocation (line 83 of `loki_agent/graph.py`) because tools are bound via closure to specific log context (file name, message, timestamp). This avoids cross-request contamination.
- The `create_log_lines_above_tool` factory (lines 347-503 of `loki_tools.py`) uses Python closures to bind complex log context values, preventing the LLM from having to serialize them as JSON tool arguments. This is a deliberate design to avoid JSON serialization issues with complex log messages.
- The tool result caching mechanism (`_store_tool_result` / `_get_tool_result` in `loki_tool_cache.py`) stores the full `LogToolOutput` in a module-level cache and returns only a lightweight response (with a `result_id`) to the LLM, reducing token usage. The full result is retrieved from cache after the agent completes.
- The `stream_with_fallback` function (lines 48-64 of `llm.py`) collects streaming chunks and returns whatever was received even if the stream is interrupted mid-response, rather than failing entirely.
- The offline training pipeline (in `backend_init_pipeline.py`) separates preparation (clustering, which doesn't need RAG) from processing (which does), waiting for the RAG service to become ready between the two steps.

---

## Approach C: Dual-Provider Factory with MCP Tool Validation (from data-governance-co-pilot)

### When to Use

Use this approach when building an AI copilot that needs to support multiple deployment modes -- one where the backend fully manages the agentic tool-calling loop (for maximum control over streaming, token management, and model-specific parsing) and another where orchestration is delegated to an external agent service like Llama Stack (for simplified architecture). This is suited for scenarios where a single MCP tool server provides all agent capabilities (e.g., database analysis via pg-airman-mcp) and the choice between modes is an infrastructure decision, not a user-facing feature.

### Differences from Approach A and Approach B

| Aspect | Approach A (Multi-Runner Dispatch) | Approach B (Hierarchical LangGraph DAG) | Approach C (Dual-Provider Factory) |
|--------|-----------------------------------|----------------------------------------|-----------------------------------|
| Pattern | Multiple frameworks behind one dispatcher | Fixed multi-level graph DAG | Two provider modes behind a factory |
| Framework choice | Runtime (per-agent runner_type in DB) | Hardcoded (LangGraph only) | Deployment-time (COPILOT_PROVIDER_MODE env var) |
| Agentic loop owner | Each runner manages its own loop | LangGraph graph engine | MCP-Direct: backend while loop; Llama Stack: Llama Stack server |
| Tool server | Multiple MCP servers (travel, hotel, flight) | Single Loki MCP server inside LangChain tools | Single pg-airman-mcp server |
| Tool security | Framework-managed tool registration | No explicit validation | Hard-coded allowlist + Pydantic schema validation |
| Model format support | OpenAI standard tool calling | OpenAI standard tool calling | Auto-detects Nemotron custom TOOLCALL tags vs OpenAI format |
| Conversation state | Database-driven (VirtualAgent model) | Stateless batch processing | In-memory dict (MCP-Direct) or Llama Stack sessions |
| Policy management | Per-agent shields via LlamaStack safety API | Not applicable | Runtime policy injection into system prompt with provider-specific update behavior |
| Streaming | Normalized SSE from all runners | No streaming (batch) | Provider-specific streaming normalized to same SSE event types |

### Data Flow

**MCP-Direct Mode:**

1. User submits query via SvelteKit frontend to `POST /query/stream`
2. Service retrieves or creates conversation history from in-memory `conversation_store`
3. `DataGovernanceCopilot.process_query_stream()` delegates to `MCPDirectProvider`
4. Provider builds system prompt (including governance policy if active) and appends user message
5. Provider calls vLLM via AsyncOpenAI client with streaming enabled, tool definitions from MCP, and vLLM-specific `min_p` parameter via `extra_body`
6. Response is parsed for model-specific format: Nemotron `<TOOLCALL>` tags or OpenAI function calling deltas
7. If tool calls detected: each is validated against hard-coded allowlist + Pydantic schema, then executed via persistent MCP session
8. Tool results appended to messages; loop continues (up to 100 iterations)
9. When no more tool calls: cleaned response streamed as SSE events with timing summary

**Llama Stack Mode:**

1. User submits query via SvelteKit frontend to `POST /query/stream`
2. Service delegates to `LlamaStackProvider`
3. Provider resolves or creates a Llama Stack session (checking existing sessions by name for pod restart resilience)
4. Provider calls `client.alpha.agents.turn.create()` with user message and streaming enabled
5. Llama Stack manages the entire agentic loop -- tool calling, context, iteration
6. Provider maps Llama Stack events (step_start, step_progress, step_complete, turn_complete) to standardized SSE events
7. `turn_complete` event captured as internal marker; final_response emitted after stream loop

### Component Wiring

| From | To | Protocol | Purpose |
|------|----|----------|---------|
| SvelteKit frontend | FastAPI backend | REST/SSE (port 8080) | Chat queries, policy management, tool listing |
| FastAPI backend (MCP-Direct) | vLLM model server | HTTP (AsyncOpenAI, port 8000 via KServe route) | LLM inference with tool calling |
| FastAPI backend (MCP-Direct) | pg-airman-mcp | HTTP (MCP streamable-http, port 8000) | Tool execution via persistent MCP session |
| FastAPI backend (Llama Stack) | Llama Stack Distribution | HTTP (LlamaStackClient, port 8321) | Agent orchestration via Agents API |
| Llama Stack Distribution | vLLM model server | HTTP (OpenAI-compatible) | LLM inference (delegated) |
| Llama Stack Distribution | pg-airman-mcp | HTTP (MCP SSE, port 8000) | Tool execution via registered toolgroup |
| pg-airman-mcp | PostgreSQL+pgvector | TCP (port 5432) | Database queries via read-only user |

### Key Integration Points

#### Provider Factory Pattern

The factory creates the appropriate provider at startup based on environment configuration. Only one provider is active at a time.

```python
# packages/copilot/src/copilot/providers/factory.py (lines 18-99)
def create_provider(governance_policy: str | None = None) -> LLMProvider:
    provider_mode = os.getenv("COPILOT_PROVIDER_MODE", "mcp_direct").lower()

    if provider_mode == "mcp_direct":
        config = {
            "llm_base_url": os.getenv("LLM_BASE_URL", "http://nemotron-service:8000/v1"),
            "llm_model": os.getenv("LLM_MODEL", "nvidia/nemotron-nano-9b-v2"),
            "llm_tool_call_format": os.getenv("LLM_TOOL_CALL_FORMAT", "auto"),
            "mcp_server_url": os.getenv("PG_AIRMAN_MCP_SERVICE_PORT", "http://pg-airman-mcp-service:8000")
        }
        return MCPDirectProvider(config=config, governance_policy=governance_policy)
    elif provider_mode == "llama_stack":
        config = {
            "llama_stack_base_url": os.getenv("LLAMA_STACK_BASE_URL", "http://copilot-llama-stack:8000"),
            "llama_stack_model": os.getenv("LLAMA_STACK_MODEL", "vllm-inference/redhataillama-31-8b-instruct"),
            "mcp_server_url": os.getenv("PG_AIRMAN_MCP_SERVICE_URL", "http://pg-airman-mcp-service:8000")
        }
        return LlamaStackProvider(config=config, governance_policy=governance_policy)
```

#### Backend-Managed Agentic Loop (MCP-Direct)

The MCP-Direct provider runs its own while loop with up to 100 iterations, calling the LLM, parsing tool calls, executing them via MCP, and appending results to the conversation until the LLM responds without tool calls.

```python
# packages/copilot/src/copilot/providers/mcp_direct.py (lines 536-857)
while iteration < max_iterations:
    iteration += 1
    # Call LLM with streaming
    api_params = {
        "model": self.llm_model,
        "messages": messages,
        "tools": self.mcp_tools,
        "tool_choice": "auto",
        "max_tokens": 2048,
        "temperature": self.temperature,
        "stream": True,
        "extra_body": {"min_p": self.min_p}
    }
    stream = await self.llm_client.chat.completions.create(**api_params)
    # ... parse response for tool calls based on format
    if not tool_calls:
        # Final answer -- send timing_summary + final_response
        return
    # Execute tools and loop
```

#### Nemotron TOOLCALL Tag Parsing

The MCP-Direct provider auto-detects model format and parses Nemotron's custom `<TOOLCALL>` tags, converting them to the same structure as OpenAI function calling format for uniform downstream handling.

```python
# packages/copilot/src/copilot/providers/mcp_direct.py (lines 268-311)
def _parse_nemotron_tool_calls(self, content: str) -> list[dict[str, Any]]:
    toolcall_pattern = r'<TOOLCALL>(.*?)</TOOLCALL>'
    matches = re.findall(toolcall_pattern, content, re.DOTALL)
    tool_calls = []
    for match in matches:
        calls_data = json.loads(match.strip())
        if not isinstance(calls_data, list):
            calls_data = [calls_data]
        for call in calls_data:
            tool_call = {
                "id": f"call_{uuid.uuid4().hex[:24]}",
                "type": "function",
                "function": {
                    "name": call["name"],
                    "arguments": json.dumps(call["arguments"])
                }
            }
            tool_calls.append(tool_call)
```

#### Tool Validation Security Layer

Every tool call passes through a hard-coded allowlist check and Pydantic schema validation before execution, preventing prompt injection attacks from calling unauthorized MCP tools.

```python
# packages/copilot/src/copilot/providers/tool_validation.py (lines 93-107, 183-203)
TOOL_SCHEMAS: Dict[str, type[BaseModel]] = {
    "execute_sql": ExecuteSqlArgs,
    "list_schemas": ListSchemasArgs,
    "list_objects": ListObjectsArgs,
    "get_object_details": GetObjectDetailsArgs,
    "explain_query": ExplainQueryArgs,
    # ... 10 tools total
}
ALLOWED_TOOLS: Set[str] = set(TOOL_SCHEMAS.keys())

def validate_tool_call(tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
    validate_tool_name(tool_name)  # Reject if not in allowlist
    validated_args = validate_tool_arguments(tool_name, arguments)  # Pydantic validation
    return validated_args
```

#### Llama Stack Toolgroup Registration

The Llama Stack provider registers pg-airman-mcp as a toolgroup and creates an agent at initialization, then reuses the agent across queries with per-conversation sessions.

```python
# packages/copilot/src/copilot/providers/llama_stack.py (lines 106-143)
self.client.toolgroups.register(
    toolgroup_id=self.toolgroup_id,  # "mcp::pg_airman"
    provider_id=tool_provider.provider_id,
    mcp_endpoint={"uri": mcp_endpoint_uri}
)
agent = self.client.alpha.agents.create(
    agent_config={
        "model": self.llama_stack_model,
        "instructions": self.get_system_prompt(enable_reasoning=True),
        "toolgroups": [self.toolgroup_id],
        "tool_choice": "auto",
        "sampling_params": {
            "max_tokens": 2048,
            "temperature": self.temperature,
            "min_p": self.min_p,
        },
    }
)
```

#### Runtime Governance Policy Injection

Both providers support runtime policy updates via the `/policy/upload` endpoint, but differ in impact: MCP-Direct rebuilds prompts dynamically (no restart), while Llama Stack must recreate the agent (invalidates all sessions).

```python
# packages/copilot/src/copilot/providers/llama_stack.py (lines 687-738)
async def update_governance_policy(self, new_policy: str | None) -> None:
    self.governance_policy = new_policy
    if self._initialized and self.client:
        # Must recreate agent -- Llama Stack agent instructions are static
        agent = self.client.alpha.agents.create(
            agent_config={
                "model": self.llama_stack_model,
                "instructions": self.get_system_prompt(enable_reasoning=True),
                "toolgroups": [self.toolgroup_id],
                # ...
            }
        )
        self.agent_id = agent.agent_id
        self._session_store.clear()  # All existing sessions invalidated
```

### Prompt / Chain Patterns

Both providers use the same prompt structure with governance policy injection:

- **Base system prompt**: Defines the role as a PostgreSQL data analyst, establishes governance policy as highest priority, provides tool usage guidelines, database exploration strategies, formatting rules (Markdown tables, SQL code blocks), and Vega-Lite visualization instructions with chart type examples.
- **Policy injection**: When a governance policy is active, it is embedded into the system prompt between the base content and the guidelines section, with explicit instructions that policy rules override all user requests.
- **Nemotron reasoning control**: The MCP-Direct provider appends `/think` or `/no_think` directives to the system prompt based on the `enable_reasoning` flag, controlling Nemotron's chain-of-thought generation.
- **Llama Stack-specific rules**: The Llama Stack provider adds tool calling format rules (empty braces `{}` for no-parameter calls, single tool call per response) that are necessary because Llama Stack's tool calling format handling differs from direct vLLM.

### Gotchas

- The MCP-Direct provider's agentic loop runs up to 100 iterations (line 534 of `mcp_direct.py`), which is unusually high compared to typical agent loops. Each iteration makes at least one LLM call and potentially multiple MCP tool calls.
- The `_detect_tool_call_format` method (lines 131-154 of `mcp_direct.py`) auto-detects Nemotron models by checking if "nemotron" appears in the model name. This detection can be overridden via the `LLM_TOOL_CALL_FORMAT` environment variable (set to "auto", "nemotron", or "openai").
- Nemotron streaming requires careful buffer management: the provider maintains an 11-character buffer window (lines 713-715 of `mcp_direct.py`) to avoid splitting across `<TOOLCALL>` or `</think>` tag boundaries when streaming content character by character.
- The MCP session is persistent (created at startup, maintained for the lifetime of the backend process) but includes reconnection logic (lines 1013-1023 of `mcp_direct.py`) triggered when tool calls fail with "Session terminated", "404", or "ClosedResourceError". Reconnection calls `initialize()` which creates a new MCP session.
- The Llama Stack provider handles pod restarts by checking for existing sessions by name (`session-{conversation_id}`) via `client.alpha.agents.session.list()` (lines 216-224 of `llama_stack.py`) before creating new ones. This rebuilds the in-memory `_session_store` cache.
- The Llama Stack Agents API does not provide an update method for agent instructions. Updating the governance policy requires creating an entirely new agent and clearing all sessions (lines 710-734 of `llama_stack.py`), which is why the provider reports `requires_conversation_restart_on_policy_update() == True`.
- Conversation state is stored in an in-memory dict (`conversation_store` in `service.py`), meaning all conversations are lost on backend pod restart. The code comments note this should be replaced with Redis or a database in production (line 159 of `service.py`).
- The MCP-Direct provider appends `"/mcp"` to the configured `mcp_server_url` (line 114 of `mcp_direct.py`) because pg-airman-mcp serves MCP at the `/mcp` endpoint when using streamable-http transport. The Llama Stack provider instead appends `"/sse"` for SSE transport fallback (line 103 of `llama_stack.py`).
- Tool validation is only applied in MCP-Direct mode. The Llama Stack provider delegates all tool execution to Llama Stack, which does not perform the same allowlist or Pydantic validation (there is no equivalent security layer in the Llama Stack path).
- The copilot-backend Helm chart sets `failureThreshold: 30` on the liveness probe and `failureThreshold: 60` on the readiness probe (lines 114-124 of `copilot-backend/values.yaml`), allowing up to 5 minutes of health check failures before restart -- necessary because long-running multi-tool-call queries can block the event loop and make the `/health` endpoint unresponsive.

### Related Architectures

- [mcp-tool-integration](mcp-tool-integration.md) -- Both providers consume pg-airman-mcp tools, with MCP-Direct using a persistent session and Llama Stack using toolgroup registration

---

## Approach D: YAML-Driven State Machine with Multi-Agent Routing (from it-self-service-agent)

### When to Use

Use this approach when building a multi-agent IT service automation system where each specialist agent follows a structured conversational workflow defined entirely in YAML configuration. This approach is suited for scenarios where: conversation flows are deterministic state machines (collect info, validate, classify intent, process), multiple specialist agents handle different request types (laptop refresh, ticket review, general support), a routing agent dispatches to specialists based on user intent, and the entire system communicates via CloudEvent-driven microservices (request-manager, agent-service, integration-dispatcher) connected through a Knative eventing broker.

### Differences from Approaches A, B, and C

| Aspect | Approach A (Multi-Runner Dispatch) | Approach B (Hierarchical LangGraph DAG) | Approach C (Dual-Provider Factory) | Approach D (YAML State Machine) |
|--------|-----------------------------------|----------------------------------------|-----------------------------------|---------------------------------|
| Graph definition | Configurable via database (runner_type, graph_config) | Fixed Python code, compiled at module load | Not applicable (simple tool-calling loop) | YAML configuration files defining states, transitions, and prompts |
| State types | N/A (runner handles everything) | Typed LangGraph nodes (llm, router, tool) | N/A | 5 generic state types: `waiting`, `llm_processor`, `intent_classifier`, `llm_validator`, `terminal` |
| Agent framework | Pluggable (LlamaStack, LangGraph, CrewAI) | LangGraph only | MCP-Direct or Llama Stack | LangGraph execution engine + LlamaStack Responses API |
| Multi-agent routing | Not built in (single agent per session) | Not applicable (single pipeline) | Not applicable (single copilot) | Routing agent classifies intent and dispatches to specialist agents |
| Communication | Direct REST/SSE | Direct Python method calls | Direct REST/SSE | CloudEvent-driven microservices via Knative broker |
| State persistence | Database-driven (VirtualAgent model) | Stateless batch processing | In-memory dict | PostgreSQL-backed LangGraph checkpointer (AsyncPostgresSaver) |
| Prompt management | Database-stored prompt field | File-based system prompts | Environment-variable-based | YAML inline prompts with `{placeholder}` template substitution |
| LLM interaction | Framework-specific (LlamaStack/LangGraph/CrewAI) | LangChain ChatOpenAI | AsyncOpenAI or LlamaStack Agents API | LlamaStack Responses API with retry logic and empty response handling |
| Guardrails | Per-agent shields via LlamaStack safety API | Not applicable | Runtime policy injection | NeMo Guardrails service via HTTP `/v1/guardrail/checks` endpoint |
| External tools | MCP servers via framework-specific paths | LangChain tools wrapping MCP | MCP-Direct or Llama Stack toolgroup | MCP servers via LlamaStack Responses API native MCP tool type |
| Session management | Per-agent session in database | Stateless | In-memory dict | Per-session LangGraph thread with PostgreSQL checkpoint persistence |

### Data Flow

1. User submits a request via web UI, CLI, Slack, or Zammad ticketing system
2. Request-manager normalizes the request into a `NormalizedRequest` and publishes a `com.self-service-agent.request.created` CloudEvent to the Knative broker
3. Agent-service receives the CloudEvent, acquires a session lock, and creates a `ResponsesSessionManager`
4. `ResponsesSessionManager` loads agent configurations from YAML files and creates or resumes a `ConversationSession` with PostgreSQL-backed checkpointing
5. The routing agent's YAML state machine classifies user intent (e.g., `LAPTOP_REFRESH`) and sets `routing_decision` in LangGraph state
6. `SessionManager._handle_routing()` detects the routing decision and creates a new `ConversationSession` for the specialist agent (e.g., `laptop-refresh`)
7. The specialist agent's YAML state machine processes the request through states: waiting for input, LLM processing with tools (MCP + knowledge base), validation, and confirmation
8. LlamaStack Responses API handles LLM inference, MCP tool execution (ServiceNow, Zammad), and knowledge base retrieval (file_search) in a single call
9. Agent-service publishes the response as a `com.self-service-agent.agent.response-ready` CloudEvent
10. Integration-dispatcher delivers the response to the appropriate channel (web, Slack, email, Zammad)

### Component Wiring

| From | To | Protocol | Purpose |
|------|----|----------|---------|
| Web/CLI/Slack/Zammad | request-manager | REST/CloudEvents | Normalize and route incoming requests |
| request-manager | Knative broker | HTTP (CloudEvent) | Publish `request.created` events |
| Knative broker | agent-service | HTTP (CloudEvent) | Deliver request events for processing |
| agent-service (ResponsesSessionManager) | LangGraph ConversationSession | Python method call | State machine execution with checkpointing |
| agent-service (Agent) | LlamaStack server | HTTP (AsyncLlamaStackClient) | Responses API for inference + MCP tools + file_search |
| agent-service (Agent) | NeMo Guardrails service | HTTP (httpx) | Input/output guardrail checks via `/v1/guardrail/checks` |
| LlamaStack server | MCP servers (snow, zammad) | HTTP (streamable-http) | Tool execution (ServiceNow tickets, Zammad ticket management) |
| LlamaStack server | vLLM | HTTP (OpenAI-compatible) | LLM inference |
| LlamaStack server | pgvector | TCP | Knowledge base vector store queries |
| agent-service | Knative broker | HTTP (CloudEvent) | Publish `agent.response-ready` events |
| Knative broker | integration-dispatcher | HTTP (CloudEvent) | Deliver response events for channel delivery |
| integration-dispatcher | Slack/Email/Zammad | HTTP/SMTP | Deliver agent responses to end user |

### Key Integration Points

#### YAML-Driven State Machine Configuration

Each agent's conversation flow is defined in a YAML file with states, transitions, prompts, and response analysis rules. The `StateMachine` class reads this configuration and dynamically creates a LangGraph `StateGraph` with one node per YAML state.

```yaml
# agent-service/config/lg-prompts/routing.yaml (lines 1-43)
settings:
  initial_state: "greet_and_identify_need"
  terminal_state: "end"
  empty_response_retry_count: 5

state_schema:
  business_fields:
    routing_decision:
      type: "string"
      default: null

states:
  greet_and_identify_need:
    type: "llm_processor"
    temperature: 0.3
    prompt: |
      You are a routing agent. Greet the user and ask what they need help with.
    transitions:
      success: "waiting_user_need"

  waiting_user_need:
    type: "waiting"
    transitions:
      user_input: "classify_user_intent"

  classify_user_intent:
    type: "llm_processor"
    temperature: 0.1
    prompt: |
      The user said: "{last_user_message}"
      Respond with exactly one of: LAPTOP_REFRESH, EMAIL_CHANGE, or OTHER
    response_analysis:
      conditions:
        - name: "laptop_refresh"
          trigger_phrases: ["LAPTOP_REFRESH"]
          actions:
            - type: "set_field"
              field_name: "routing_decision"
              value: "laptop-refresh"
            - type: "transition"
              target: "end"
```

#### Dynamic LangGraph Construction from YAML

The `ConversationSession._create_graph()` method reads the YAML state definitions and creates a LangGraph `StateGraph` with a node for each state. Waiting states pause execution until a new `HumanMessage` arrives; other states invoke `StateMachine.process_state()` which dispatches to the appropriate state type handler.

```python
# agent-service/src/agent_service/langgraph/lg_flow_state_machine.py (lines 1238-1359)
def _create_graph(self) -> Any:
    workflow = StateGraph(self.state_machine.AgentState)
    states_config = self.state_machine.config.get("states", {})

    for state_name, state_config in states_config.items():
        state_type = state_config.get("type", "")

        def make_node_func(name, stype):
            async def node_func(state):
                state["current_state"] = name
                if stype == "terminal":
                    return state
                if stype == "waiting":
                    # Check for new HumanMessage to consume
                    human_count = sum(1 for msg in state.get("messages", [])
                                     if isinstance(msg, HumanMessage))
                    if human_count > state.get("_last_processed_human_count", 0)
                       and not state.get("_consumed_this_invoke", False):
                        state["_last_processed_human_count"] = human_count
                        state["_consumed_this_invoke"] = True
                        return Command(goto=next_node, update=state)
                    return state  # Pause execution
                else:
                    updated_state, next_node = await self.state_machine.process_state(
                        state, self.agent, self.authoritative_user_id)
                    return Command(goto=next_node, update=updated_state)
            return node_func

        workflow.add_node(state_name, make_node_func(state_name, state_type))
```

#### Multi-Agent Routing via State Field

The routing agent sets a `routing_decision` field in the LangGraph state via YAML-configured response analysis. The `SessionManager._handle_routing()` method reads this field and creates a new `ConversationSession` for the target specialist agent.

```python
# agent-service/src/agent_service/session_manager.py (lines 949-970)
# Check conversation state for routing decision from StateMachine
if self.conversation_session:
    current_state = await self.conversation_session.app.aget_state(
        self.conversation_session.thread_config)
    current_values = current_state.values
    routing_decision = current_values.get("routing_decision")

    if routing_decision and routing_decision in self.agents:
        routed_agent = routing_decision
```

#### CloudEvent-Driven Microservice Communication

Services communicate via CloudEvents published to a Knative broker. Event types are defined in `shared-models` and include `request.created`, `request.processing`, `agent.response-ready`, and `request.database-update`.

```python
# shared-models/src/shared_models/events.py (lines 35-46)
class EventTypes:
    REQUEST_CREATED = "com.self-service-agent.request.created"
    REQUEST_PROCESSING = "com.self-service-agent.request.processing"
    AGENT_RESPONSE_READY = "com.self-service-agent.agent.response-ready"
    DATABASE_UPDATE_REQUESTED = "com.self-service-agent.request.database-update"

# agent-service/src/agent_service/main.py (lines 378-403)
builder = CloudEventBuilder("agent-service")
event = builder.create_response_event(event_data, response.request_id,
                                       response.agent_id, response.session_id)
headers, body = to_structured(event)
response_http = await self.http_client.post(self.config.broker_url,
                                             headers=headers, content=body)
```

#### LlamaStack Responses API with MCP and Knowledge Base

The specialist agent uses LlamaStack's Responses API which natively supports MCP tool servers and knowledge base file_search in a single API call. MCP servers are configured per-agent in YAML and resolved to tool definitions at runtime.

```python
# agent-service/src/agent_service/langgraph/responses_agent.py (lines 230-265)
mcp_tool: Dict[str, Any] = {
    "type": "mcp",
    "server_label": server_name,
    "server_url": server_uri,
    "require_approval": server_config.get("require_approval", "never"),
}
# Add authorization headers
if authoritative_user_id:
    tool_headers["AUTHORITATIVE_USER_ID"] = authoritative_user_id
# Add tracing headers
if tracingIsActive():
    inject(tool_headers)
mcp_tool["headers"] = tool_headers
tools_to_use.append(mcp_tool)

# Knowledge base file_search tool
knowledge_base_tool = {
    "type": "file_search",
    "vector_store_ids": vector_store_ids,
}
tools_to_use.append(knowledge_base_tool)
```

### Prompt / Chain Patterns

Each state type has a distinct prompt handling pattern:

- **llm_processor**: Sends the YAML-configured `prompt` (with `{placeholder}` template substitution for state data like `{last_user_message}`, `{conversation_history}`, `{authoritative_user_id}`) to the LlamaStack Responses API. Supports conditional prompts that select different prompt text based on state field values. Temperature and tool usage (`uses_tools`, `uses_mcp_tools`) are per-state YAML settings.
- **intent_classifier**: Uses a low-temperature LLM call with a classification prompt, then matches the response against `intent_actions` entries to determine the next state and any data extraction actions.
- **llm_validator**: Sends conversation history plus a validation prompt, then uses a second LLM call with a `success_validation_prompt` to determine if the response was valid or needs correction.
- **waiting**: No prompt -- pauses the graph until a new `HumanMessage` arrives via `ConversationSession.send_message()`.

The `response_analysis` section in YAML-configured states enables conditional transitions based on `trigger_phrases` found in LLM responses, with actions including `set_field`, `add_message`, `transition`, `extract_data` (regex), `check_correction`, and `increment_field`.

### Gotchas

- The `StateMachine` class dynamically creates a `TypedDict` subclass (`AgentState`) from the YAML `state_schema.business_fields` section (lines 57-93 of `lg_flow_state_machine.py`). Field types are mapped from YAML strings ("string", "list", "dict", "boolean") to Python types. Unrecognized types default to `Optional[str]`.
- The `ConversationSession` uses a `__resume_dispatcher__` node as the LangGraph entry point (lines 1332-1343 of `lg_flow_state_machine.py`). This node checks `_last_waiting_node` in checkpointed state to resume from the correct waiting state after a process restart, rather than re-executing from the initial state.
- The `_consumed_this_invoke` flag (line 1295-1303) prevents multiple waiting states from consuming the same `HumanMessage` within a single graph invocation. It is reset to `False` at the start of each `send_message()` call. Without this, a graph with two consecutive waiting states would skip the second one.
- Agent configuration (model, system message, MCP servers, knowledge bases) is loaded from YAML files in `config/agents/` at startup. The LangGraph state machine config path is specified per-agent via `lg_state_machine_config` and can be overridden via environment variable `LG_PROMPT_<AGENT_NAME>` (lines 1130-1146).
- The `create_response_with_retry` method (lines 343-429 of `responses_agent.py`) implements exponential backoff (1s, 2s, 4s, 8s, 16s max) for empty responses and errors, with a configurable retry count set via `empty_response_retry_count` in the YAML settings. The default retry count is 3.
- Session locks (`acquire_agent_session_lock` / `release_agent_session_lock`) prevent concurrent CloudEvent processing for the same session. The lock timeout (`SESSION_LOCK_WAIT_TIMEOUT`, default 180s) must be >= the agent processing timeout to avoid dropping queued requests.
- The `FaultInjectingAsyncLlamaStackClient` wrapper (lines 46-227 of `fault_injector.py`) randomly injects failures into LlamaStack API calls for resilience testing, but exempts `vector_stores` namespace calls to avoid breaking knowledge base operations.
- The `_format_text` method (lines 224-310 of `lg_flow_state_machine.py`) supports dot notation in placeholders (e.g., `{laptop_eligibility.response}`) for nested state data access, and protects double braces (`{{` / `}}`) from being treated as placeholders, enabling JSON-like content in prompts.

### Related Architectures

- [guardrails-layer](guardrails-layer.md) -- NeMo Guardrails input/output shields are applied before/after agent response processing
- [rag-pipeline](rag-pipeline.md) -- Knowledge bases are uploaded at startup and wired as file_search tools via LlamaStack Responses API
- [mcp-tool-integration](mcp-tool-integration.md) -- MCP servers (ServiceNow, Zammad) are configured per-agent in YAML and invoked via LlamaStack Responses API native MCP tool type

---

## Approach E: Multi-Persona LangGraph Agents with RBAC Tool Authorization (from multi-agent-loan-origination)

### When to Use

Use Approach E when you need multiple persona-specific agents in a single backend application, each with its own tool set, RBAC rules, and system prompt, all sharing a common LangGraph graph structure with safety shields and tool authorization built into the graph itself. Best suited for regulated-industry applications where tool access must be scoped by user role and safety checks must be enforced at the graph level rather than as external middleware.

### Differences from Approach A

- **No framework abstraction layer**: All agents use LangGraph exclusively via a shared `build_agent_graph` factory function, rather than dispatching across multiple frameworks (LlamaStack, LangGraph, CrewAI).
- **YAML config drives tools and RBAC, not runner selection**: Each agent's YAML config specifies a system prompt, tool list with `allowed_roles` per tool, and model routing strategy -- not which framework to use.
- **Graph-level safety**: NeMo Guardrails are embedded as LangGraph StateGraph nodes (`input_shield`, `output_shield`) with conditional edges, rather than executed in runner code.
- **Tool-level RBAC as a graph node**: A `tool_auth` authorization node checks each pending tool call against the user's role before execution, injecting a denial message back to the agent when blocked.
- **WebSocket streaming with buffered response**: The full response is buffered during graph execution and sent as a single `done` message, rather than streaming token-by-token SSE events.
- **Registry with hot-reloading**: Agent graphs are cached and rebuilt when their YAML config file's mtime changes, checked at most every 5 seconds.
- **A2A protocol**: Agents are optionally exposed as A2A-compatible endpoints via Kagenti for agent-to-agent discovery and invocation.

### Data Flow

1. User connects via WebSocket at a persona-specific path (e.g., `/api/borrower/chat`, `/api/underwriter/chat`)
2. JWT authentication resolves the user's role (borrower, loan_officer, underwriter, ceo) or the public endpoint accepts unauthenticated users
3. The `create_authenticated_chat_router` factory builds a WebSocket handler that loads the appropriate agent graph via `get_agent(agent_name, checkpointer=checkpointer)`
4. The registry loads the agent's YAML config from `config/agents/<name>.yaml`, resolves `${ENV_VAR:-default}` placeholders, and calls the agent module's `build_graph()` function
5. Each agent module assembles its tool list (native tools + optional MCP tools) and calls `build_agent_graph(config, tools)` which creates a compiled LangGraph StateGraph: `input_shield -> agent -> tools <-> agent -> output_shield -> END`
6. The graph streams events via `astream_events(v2)`, the handler buffers the full response, strips think tags and markdown artifacts, and sends a single `{"type": "done", "content": ...}` WebSocket message
7. Conversation state is persisted via `langgraph-checkpoint-postgres` AsyncPostgresSaver with deterministic thread IDs (`user:{user_id}:agent:{agent_name}[:app:{app_id}]`)

### Component Wiring

| From | To | Protocol | Purpose |
|------|----|----------|---------|
| React frontend | FastAPI backend | WebSocket | Chat messages in, JSON events out |
| Chat handler | Agent registry | Python method call | Load/cache compiled LangGraph graph by agent name |
| Agent registry | YAML config files | Filesystem read | Load system prompt, tool config, RBAC rules with env var substitution |
| LangGraph agent node | vLLM/OpenAI-compatible endpoint | HTTP (ChatOpenAI) | LLM inference with tool binding |
| LangGraph input/output shield nodes | NeMo Guardrails server | HTTP (httpx) | Safety rail checks via `/v1/guardrail/checks` |
| LangGraph tools node | LangChain ToolNode | Python method call | Execute native tools and MCP tools |
| LangGraph tool_auth node | AgentState | Python method call | Check tool calls against `tool_allowed_roles` map |
| Chat handler | AsyncPostgresSaver | psycopg3 | Conversation checkpoint persistence |
| Chat handler | Audit service | SQLAlchemy async | Hash-chained audit event logging |
| A2A server (optional) | Agent registry | Python method call | Kagenti agent-to-agent invocation |

### Key Integration Points

#### Agent Registry with Hot-Reloading

The registry caches compiled graphs and rebuilds them when the YAML config file changes, with a 5-second mtime check interval to avoid excessive filesystem stat() calls.

```python
# packages/api/src/agents/registry.py (lines 43-49, 65-109)
_AGENT_MODULES: dict[str, str] = {
    "public-assistant": ".public_assistant",
    "borrower-assistant": ".borrower_assistant",
    "loan-officer-assistant": ".loan_officer_assistant",
    "underwriter-assistant": ".underwriter_assistant",
    "ceo-assistant": ".ceo_assistant",
}

def get_agent(agent_name: str, checkpointer=None):
    config_path = _AGENTS_CONFIG_DIR / f"{agent_name}.yaml"
    now = time.monotonic()
    if agent_name in _graphs and now - _last_check.get(agent_name, 0) < _MTIME_CHECK_INTERVAL:
        return _graphs[agent_name][0]
    _last_check[agent_name] = now
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

#### LangGraph Graph with Safety Shields and RBAC Tool Authorization

The shared factory builds a StateGraph with safety shields as nodes and an optional `tool_auth` node that checks each tool call against the user's role before execution.

```python
# packages/api/src/agents/base.py (lines 107-133, 170-175, 177-219, 301-333)
def build_agent_graph_compiled(
    *, system_prompt, tools, llm, tool_allowed_roles=None, checkpointer=None,
):
    async def input_shield(state: AgentState) -> dict:
        checker = get_safety_checker()
        if not checker:
            return {"safety_blocked": False}
        result = await checker.check_input(last_msg.content)
        if not result.is_safe:
            return {"safety_blocked": True, "messages": [AIMessage(content=SAFETY_REFUSAL_MESSAGE)]}
        return {"safety_blocked": False}

    def should_continue(state: AgentState) -> str:
        last = state["messages"][-1]
        if isinstance(last, AIMessage) and last.tool_calls:
            return "tool_auth" if tool_allowed_roles else "tools"
        return "output_shield"

    async def tool_auth(state: AgentState) -> dict:
        user_role = state.get("user_role", "")
        roles_map = dict(tool_allowed_roles or {})
        blocked = [tc["name"] for tc in last.tool_calls
                   if roles_map.get(tc["name"]) is not None and user_role not in roles_map.get(tc["name"])]
        if not blocked:
            return {}
        return {"messages": [AIMessage(content=f"Tool authorization denied: ...")]}

    graph = StateGraph(AgentState)
    graph.add_node("input_shield", input_shield)
    graph.add_node("agent", agent)
    graph.add_node("tools", tools_with_metrics)
    graph.add_node("output_shield", output_shield)
    graph.set_entry_point("input_shield")
    graph.add_conditional_edges("input_shield", after_input_shield, {END: END, "agent": "agent"})
    if tool_allowed_roles:
        graph.add_node("tool_auth", tool_auth)
        graph.add_conditional_edges("agent", should_continue,
            {"tool_auth": "tool_auth", "output_shield": "output_shield"})
        graph.add_conditional_edges("tool_auth", after_tool_auth,
            {"tools": "tools", "output_shield": "output_shield"})
    graph.add_edge("tools", "agent")
    graph.add_edge("output_shield", END)
    return graph.compile(checkpointer=checkpointer)
```

#### YAML-Driven Tool RBAC Configuration

Tool access is defined per-agent in YAML with `allowed_roles` lists. The `build_agent_graph` factory extracts these into a `tool_allowed_roles` dict that the `tool_auth` graph node uses at runtime.

```yaml
# config/agents/underwriter-assistant.yaml (lines 293-371)
tools:
  - name: current_date
    description: "Get today's date for due date calculations"
    allowed_roles: [borrower, loan_officer, underwriter, ceo, admin]
  - name: uw_queue_view
    description: "View the underwriting queue sorted by urgency"
    allowed_roles: [underwriter, admin]
  - name: calculate_dti
    description: "Calculate Debt-to-Income ratio"
    allowed_roles: [underwriter, admin]
  - name: kb_search
    description: "Search the compliance knowledge base"
    allowed_roles: [loan_officer, underwriter, admin]
```

#### WebSocket Chat Handler with Buffered Response

The chat handler buffers the full agent response during graph execution and sends a single `done` message, racing the agent task against a disconnect sentinel to cancel immediately if the client disconnects.

```python
# packages/api/src/routes/_chat_handler.py (lines 98-112, 161-207, 301-363)
async def run_agent_stream(ws, graph, *, thread_id, session_id, user_role, ...):
    async def _run_agent(user_text, input_messages):
        full_response = ""
        async for event in graph.astream_events(
            {"messages": input_messages, "user_role": user_role, "user_id": user_id, ...},
            config={"configurable": {"thread_id": thread_id}, "recursion_limit": 50},
            version="v2",
        ):
            kind = event.get("event")
            node = event.get("metadata", {}).get("langgraph_node")
            if kind == "on_chat_model_stream" and node in ("agent", "agent_fast", "agent_capable"):
                chunk = event.get("data", {}).get("chunk")
                if isinstance(chunk, AIMessageChunk) and chunk.content:
                    full_response += chunk.content
        return full_response

    agent_task = asyncio.create_task(_run_agent(user_text, input_messages))
    disconnect_task = asyncio.create_task(_wait_disconnect())
    done, pending = await asyncio.wait({agent_task, disconnect_task}, return_when=asyncio.FIRST_COMPLETED)
    if disconnect_task in done:
        agent_task.cancel()
        return
    full_response = re.sub(r"<think>.*?</think>", "", full_response, flags=re.DOTALL)
    await _send({"type": "done", "content": full_response})
```

#### A2A Protocol Integration via Kagenti

When `KAGENTI_ENABLED=true`, each agent is exposed as an A2A-compatible endpoint on sequential ports (8080+), enabling Kagenti to discover and invoke agents. Each `LoanAgentExecutor` bridges A2A requests to the existing LangGraph graph.

```python
# packages/api/src/a2a_server.py (lines 352-373, 470-501)
class LoanAgentExecutor(AgentExecutor):
    def __init__(self, agent_name: str) -> None:
        self._agent_name = agent_name
        self._checkpointer = MemorySaver()

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        query = context.get_user_input()
        graph = get_agent(self._agent_name, checkpointer=self._checkpointer)
        config = {"configurable": {"thread_id": context.context_id}}
        inputs = {"messages": [HumanMessage(content=query)], "user_role": default_role}
        result = await graph.ainvoke(inputs, config)
        response_text = self._extract_response(result)
        await updater.add_artifact([Part(text=response_text)], name="agent_response")
        await updater.complete()

async def run_all_a2a_servers(host="0.0.0.0"):
    for agent_name, config in AGENT_A2A_CONFIG.items():
        tasks.append(asyncio.create_task(run_a2a_server(agent_name, host, config["port"])))
    await asyncio.gather(*tasks)
```

### Prompt / Chain Patterns

Each agent's system prompt is defined in its YAML config file and supports `${ENV_VAR:-default}` placeholder substitution. The `AGENT_NAME` environment variable is optionally prepended as identity awareness. Prompts are domain-specific and contain structured workflow instructions -- for example, the underwriter assistant's system prompt defines a 5-step risk assessment workflow (application detail, five risk tools, ML prediction, recommendation generation, assessment persistence) that the agent must execute sequentially without intermediate responses.

### Gotchas

- The WebSocket handler buffers the entire response before sending, meaning the user sees no incremental output during agent execution. The `_run_agent` function accumulates tokens from `on_chat_model_stream` events for `agent`/`agent_fast`/`agent_capable` nodes, then sends a single `done` message. This simplifies the protocol but increases perceived latency for long responses.
- Think tags from reasoning models (e.g., `<think>...</think>`) and markdown bold markers (`**`) are stripped from the response via regex before sending to the client (lines 354-357 of `_chat_handler.py`). Stray inline tool-call text from small models is also removed.
- The `tool_auth` node uses graph-level `tool_allowed_roles` defaults only -- it never reads roles from the state to prevent state injection attacks (line 191 of `base.py`: "Use graph-level defaults only -- never allow state to override roles").
- Conversation thread IDs are deterministic (`user:{user_id}:agent:{agent_name}[:app:{app_id}]`) for authenticated users, enabling conversation resumption across sessions. The `verify_thread_ownership` check (line 135-150 of `conversation.py`) prevents users from reading other users' conversations by checking that the thread_id starts with the correct user prefix.
- The `output_shield` node re-sends the full assistant response as a new user message to NeMo Guardrails for evaluation, triggering a full LLM call (~32s+) that can exceed the httpx 30s timeout. The `OUTPUT_SHIELD_DISABLED` setting (lines 237-240 of `base.py`) exists as a workaround for this latency issue.
- Agent YAML configs support env var substitution with nested references: `${VISION_BASE_URL:-${LLM_BASE_URL:-default}}` is resolved via up to 3 substitution passes (lines 52-66 of `inference/config.py`).
- If a YAML config reload fails (bad YAML, missing fields), the registry keeps the last valid graph and logs a warning (lines 99-109 of `registry.py`), preventing a config typo from breaking a running system.
- The A2A integration uses in-memory `MemorySaver` for checkpointing (line 358 of `a2a_server.py`), not the PostgreSQL-backed AsyncPostgresSaver used by the WebSocket handler. A2A conversation state is lost on pod restart.
- PII masking is applied at the WebSocket level via the `pii_mask` parameter (controlled by user role data scope), not in the graph. The CEO assistant has `pii_mask=True` to redact PII from all responses, applied via the `PIIMaskingMiddleware` and a recursive JSON masking function.

### Related Architectures

- [guardrails-layer](guardrails-layer.md) -- NeMo Guardrails integrated as LangGraph StateGraph nodes for input/output safety checks
- [rag-pipeline](rag-pipeline.md) -- Compliance knowledge base with pgvector tier-based boosting, used as a LangGraph tool
- [mcp-tool-integration](mcp-tool-integration.md) -- MCP risk assessment tools loaded at startup via langchain-mcp-adapters and injected into the underwriter agent

---

## Approach F: Vision-Context-Aware LangGraph Router (from multimodal-compliance-monitor)

### When to Use

When the application combines real-time computer vision with LLM-powered analytics, and user questions must be routed between answering from live visual context (what the camera sees now) versus querying historical detection data in a database.

### Differences from Other Approaches

Unlike Approaches A-E which focus on interactive chat, configuration, or batch processing, Approach F routes between two fundamentally different data sources within a single graph: live CV detection context and historical SQL-queryable detection records. The graph uses structured-output classification (not intent-based routing or runner dispatch) to decide the path, and the SQL path employs a multi-node chain (planner -> agent -> answer) with a nested ReAct agent that generates and validates SQL queries.

### Key Integration Points

#### Structured-Output Router Node

The `router` node uses `llm.with_structured_output(RouteDecision)` to classify questions as `"context"` (present-tense visual questions) or `"sql"` (historical data queries). The current CV detection context and detection class information are injected into the routing prompt.

```python
# app/backend/chat/nodes.py (lines 75-91)
def make_router_node(llm: ChatOpenAI):
    structured_llm = llm.with_structured_output(RouteDecision)

    async def router_node(state: ChatState) -> dict:
        prompt = build_router_prompt(state.get("classes_info"))
        messages = [
            SystemMessage(content=prompt),
            SystemMessage(content=f"Current visual context:\n{state['context']}"),
            HumanMessage(content=state["question"]),
        ]
        decision: RouteDecision = await structured_llm.ainvoke(messages)
        return {"route": decision.route}

    return router_node
```

#### SQL Agent with Nested Tool-Calling ReAct Loop

The `sql_agent` node creates a dynamic `@tool`-decorated `query_metric` function that calls an inner LLM to generate SQL, then executes it via the `execute_sql` MCP tool. The outer `create_agent` ReAct loop handles retries when SQL execution fails (the error context is passed back to the generator).

```python
# app/backend/chat/nodes.py (lines 124-176)
def make_sql_agent_node(llm: ChatOpenAI, execute_sql_tool: StructuredTool):
    async def sql_agent_node(state: ChatState) -> dict:
        @tool
        async def query_metric(metric: str, error_context: str = "") -> str:
            """Generate and execute a SQL query for the given metric."""
            generator_prompt = build_sql_generator_prompt(
                metric=metric,
                app_config_id=app_config_id,
                classes_info=classes_info,
            )
            # ... LLM generates SQL, execute_sql_tool runs it ...

        agent = create_agent(llm, [query_metric], system_prompt=agent_prompt)
        result = await agent.ainvoke(
            {"messages": [HumanMessage(content=metrics_msg)]},
        )
        return {"sql_result": sql_result}

    return sql_agent_node
```

#### Dual LangGraph Graphs (Chat + Alert)

The application runs two separate LangGraph StateGraphs compiled independently. The chat graph (6 nodes with conditional routing) handles conversational queries with session memory via `MemorySaver`. The alert graph (2 nodes, linear) converts plain-English alert rules into SQL queries without session state.

```python
# app/backend/app.py (lines 68-69)
llm_alert = LLMAlert()
llm_chat = LLMChat()
```

The `LLMChat` class wraps the compiled graph with session management, using `MemorySaver` for per-session conversation history and a version counter for session reset without clearing the checkpointer:

```python
# app/backend/chat/graph.py (lines 83-86)
self._memory = MemorySaver()
graph = _build_graph(llm, execute_sql_tool)
self._app = graph.compile(checkpointer=self._memory)
self._session_versions: dict[str, int] = {}
```

### Prompt / Chain Patterns

Prompts are dynamically generated from detection class metadata. The `build_sql_generator_prompt` constructs worked SQL examples tailored to the specific trackable/non-trackable classes configured for the active app_config, including majority-vote query patterns for noisy observation data.

### Gotchas

- The `LLMChat` uses `asyncio.run()` inside synchronous Flask route handlers, creating a new event loop per request. This works because Flask runs in a threaded mode, but each request blocks a worker thread during the async graph execution.
- Session reset is implemented by incrementing a version counter appended to the thread_id (`f"{session_id}:{version}"`), which makes `MemorySaver` treat it as a new conversation without clearing old state from memory.
- The `ChatState` carries both `context` (live detection text) and `app_config_id` (for SQL scoping) as first-class state fields, making the graph inherently tied to the multimodal pipeline's data model.
- The SQL generator prompt explicitly instructs "Never alias detection_observations as 'do'" because `DO` is a PostgreSQL reserved keyword, which caused recurring SQL generation failures.
- The `context_answer` node receives visual context but no database access; the `sql_planner`/`sql_agent`/`sql_answer` chain receives database access but not visual context. The router decision is irreversible within a single invocation.

### Related Architectures

- [multimodal-video-analytics](multimodal-video-analytics.md) -- The CV pipeline that produces the visual context consumed by this graph
- [mcp-tool-integration](mcp-tool-integration.md) -- postgres-mcp provides the `execute_sql` tool used by the SQL agent nodes
- [evaluation-pipeline](evaluation-pipeline.md) -- LLM-as-judge framework for evaluating chat and alert output quality

---

## Approach G: HTTP Tool Discovery with Two-Phase Pipeline (from portfolio-manager-agent)

### When to Use

Use this approach when building a financial services or domain-specific AI agent that requires a deterministic pipeline phase (data ingestion, computation, validation) before entering an interactive agentic chat phase. This is suited for scenarios where: tool agents are simple HTTP microservices with self-describing JSON Schema interfaces (no MCP or framework-specific protocol needed), the LLM should only access a subset of tools during chat, and the orchestrator must maintain mutable domain state (e.g., portfolio holdings) across tool calls with automatic side-effects (e.g., recalculating VaR after any portfolio change).

### Differences from Other Approaches

| Aspect | Approach A (Multi-Runner Dispatch) | Approach G (HTTP Tool Discovery + Two-Phase) |
|--------|-----------------------------------|----------------------------------------------|
| Agent framework | Pluggable (LlamaStack, LangGraph, CrewAI) | None -- hand-written Orchestrator class with direct OpenAI SDK |
| Tool protocol | MCP servers via framework-specific adapters | Custom HTTP: `GET /tools` for discovery, `POST /tools/<name>` for invocation |
| Graph definition | Configurable via database (runner_type, graph_config) | Not applicable -- simple while loop with max 20 iterations |
| Pipeline structure | Single-phase agentic chat | Two-phase: deterministic pipeline (no LLM) then agentic chat with tool filtering |
| Tool filtering | All registered tools available | Phase 2 restricts tools to `PHASE2_TOOLS` subset |
| State management | Database-driven (VirtualAgent model) | Mutable context dict injected into system prompt, updated via `on_tool_result` callbacks |
| Streaming | SSE event stream | Synchronous REST (no streaming) |
| ML model integration | None (LLM-only) | scikit-learn MLP via KServe MLServer for guideline classification |
| Guardrails | Per-agent shields in runner code | Application-level NeMo Guardrails client with fail-open degradation |

### Data Flow

**Phase 1 -- Deterministic Pipeline (no LLM needed except for email generation):**

1. User configures investment parameters (guidelines URL, portfolio value, number of symbols, max VaR) via React frontend
2. `POST /pipeline` triggers `run_pipeline()` in the Flask orchestrator
3. `parse_guidelines()` calls the guidelines tool agent (`POST /tools/prohibited_symbols`), which fetches a PDF, splits it into sentences, classifies each via the scikit-learn MLP model (local or remote via MLServer), and extracts prohibited tickers from high-confidence prohibition sentences
4. `run_portfolio_var_loop()` iterates up to 10 times: calls `portfolio_equities` tool to build random portfolio excluding prohibited tickers, then calls `value_at_risk` tool to compute VaR -- retries until VaR <= max threshold
5. `generate_draft_email()` sends portfolio + VaR to the LLM (OpenAI-compatible endpoint) to compose a client-facing email
6. NeMo Guardrails output check validates the generated email for PII
7. `build_context_from_pipeline()` assembles the portfolio context dict for Phase 2

**Phase 2 -- Agentic Chat:**

1. User sends a chat message via `POST /chat`
2. NeMo Guardrails input check validates the user message
3. The orchestrator creates an `Orchestrator` instance with filtered tools (`PHASE2_TOOLS`)
4. Portfolio context is injected as a JSON block into the system prompt
5. `chat_with_context()` runs the agentic loop: LLM generates a response, if it includes `tool_calls`, the orchestrator executes them via HTTP tool agents and feeds results back
6. `on_tool_result` callback updates the mutable context (portfolio, VaR) after each tool call, including automatic VaR recalculation after portfolio mutations
7. NeMo Guardrails output check validates the LLM response
8. Updated context is returned to the frontend for display

### Component Wiring

| From | To | Protocol | Purpose |
|------|----|----------|---------|
| React frontend | Flask orchestrator | REST (port 5000) | Pipeline execution, chat messages |
| Flask orchestrator | Risk tool agent | REST (port 7001) | VaR calculation via `POST /tools/value_at_risk` |
| Flask orchestrator | Portfolio tool agent | REST (port 7002) | Portfolio construction via `POST /tools/portfolio_equities`, symbol replacement via `POST /tools/portfolio_replace_symbol` |
| Flask orchestrator | Guidelines tool agent | REST (port 7003) | Guideline parsing via `POST /tools/prohibited_symbols` |
| Guidelines tool agent | MLServer (KServe) | REST (V2 inference API, port 80) | Remote MLP inference via `POST /v2/models/guidelines-mlp/infer` |
| Guidelines tool agent | External URL | HTTPS | PDF download for investment guidelines |
| Flask orchestrator | NeMo Guardrails service | REST (port 8000) | Input/output validation via `POST /v1/guardrail/checks` |
| Flask orchestrator | OpenAI-compatible LLM | REST | Chat completions with function calling for email generation and agentic chat |
| MinIO | KServe MLServer | S3 | Model artifact storage for guidelines-mlp |

### Key Integration Points

#### HTTP Tool Discovery Protocol

Each tool agent exposes a `GET /tools` endpoint returning JSON Schema tool definitions, and a `POST /tools/<name>` endpoint for invocation. The `HttpToolServer` adapter discovers and invokes tools using this protocol.

```python
# orchestrator/src/orchestrator.py (lines 27-56)
class HttpToolServer:
    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout = timeout

    def discover(self) -> list[DiscoveredTool]:
        url = urljoin(self.base_url, "tools")
        resp = requests.get(url, timeout=self.timeout)
        resp.raise_for_status()
        tools = []
        for item in resp.json():
            tools.append(DiscoveredTool(
                name=item["name"],
                description=item.get("description", ""),
                parameters=item.get("parameters", {"type": "object", "properties": {}}),
                server_base=self.base_url,
            ))
        return tools

    def call(self, tool_name: str, arguments: dict) -> dict:
        url = urljoin(self.base_url, f"tools/{tool_name}")
        resp = requests.post(url, json=arguments, timeout=self.timeout)
        resp.raise_for_status()
        return resp.json()
```

#### Agentic Loop with Tool Filtering

The `Orchestrator._run_agentic_loop()` implements a while loop (max 20 iterations) that calls the LLM, executes any tool calls, and re-invokes the LLM with results until no more tool calls are requested. Phase 2 chat filters available tools to a subset via `refresh_tools_filtered()`.

```python
# orchestrator/src/orchestrator.py (lines 135-212)
def _run_agentic_loop(self, prompts, tools, temperature, on_tool_result=None):
    need_to_call_llm = True
    while need_to_call_llm and llm_count < 20:
        response = self.openai.chat.completions.create(
            model=self.model, messages=prompts, temperature=temperature,
            **({"tools": tools} if tools else {}),
        )
        need_to_call_llm = False
        tool_calls = response.choices[0].message.tool_calls or []
        for item in tool_calls:
            if item.type != "function":
                continue
            need_to_call_llm = True
            result = self._execute_tool_call(item.function.name, item.function.arguments)
            if on_tool_result and not (isinstance(result, dict) and result.get("error")):
                on_tool_result(item.function.name, result, json.loads(item.function.arguments))
            prompts.append({"role": "assistant", "content": response.choices[0].message.content,
                            "tool_calls": [item]})
            prompts.append({"role": "tool", "tool_call_id": item.id,
                            "name": item.function.name, "content": json.dumps(result)})
```

#### Two-Phase Pipeline with Context Handoff

Phase 1 runs deterministic tool calls without LLM involvement (except email generation). The pipeline result is converted to a context dict passed to Phase 2 chat via the system prompt.

```python
# orchestrator/src/pipeline.py (lines 151-189)
def run_pipeline(registry, llm_client, model, url_investment_guidelines,
                 portfolio_value, qty_symbols, max_var):
    guidelines = parse_guidelines(registry, url_investment_guidelines)
    prohibited = guidelines["prohibited_tickers"]
    portfolio, value_at_risk, attempts = run_portfolio_var_loop(
        registry, portfolio_value, qty_symbols, prohibited, max_var,
    )
    draft_email = generate_draft_email(llm_client, model, portfolio, value_at_risk)
    return {
        "prohibited_tickers": prohibited, "portfolio": portfolio,
        "valueAtRisk": value_at_risk, "draft_email": draft_email, ...
    }

# orchestrator/src/app.py (lines 256-261)
full_system = (
    f"{system_prompt}\n\n"
    f"Current portfolio context (authoritative; update via tools when the user "
    f"requests portfolio or risk changes):\n{json.dumps(context, indent=2)}"
)
```

#### Mutable Context with Automatic Side-Effects

After any portfolio mutation tool call in Phase 2, the orchestrator automatically recalculates VaR by calling the `value_at_risk` tool, keeping the context consistent without the LLM needing to request it.

```python
# orchestrator/src/pipeline.py (lines 238-263)
def apply_phase2_tool_result(context, tool_name, result, registry, tool_args=None):
    ctx = apply_tool_result_to_context(context, tool_name, result)
    if tool_name not in PORTFOLIO_MUTATION_TOOLS or _tool_result_failed(result):
        return ctx
    portfolio = ctx.get("portfolio")
    if not portfolio:
        return ctx
    try:
        var_result = calculate_var(registry, portfolio)
        return apply_tool_result_to_context(ctx, "value_at_risk", var_result)
    except Exception as e:
        logger.warning("Auto VaR after %s failed: %s", tool_name, e)
        return ctx
```

### Prompt / Chain Patterns

The system uses two distinct prompt patterns:

- **Phase 1 email generation**: A static system prompt (`DRAFT_EMAIL_SYSTEM` in `pipeline.py` line 20) defining the role as a portfolio manager, with the portfolio data and VaR sent as a JSON user message. Single LLM call, no tool calling.
- **Phase 2 agentic chat**: A configurable system prompt (`PHASE2_SYSTEM` in `app.py` line 39) defining conversational style and tool usage rules, with the full portfolio context appended as a JSON block. The prompt explicitly instructs: "Never paste JSON, code blocks, tool payloads" and "The UI already shows the full portfolio table" to prevent the LLM from echoing structured data. Tool calls are used for portfolio modifications and risk recalculation.

### Gotchas

- The `HttpToolServer.discover()` method calls `GET /tools` on each tool agent at the start of every HTTP request (via `get_tool_registry()` in Flask's `g` context at line 64-70 of `app.py`). There is no cross-request caching of tool schemas -- each request rediscovers all tools from all three servers.
- The `ToolRegistry` (in `pipeline.py` line 38) enforces tool name uniqueness across all servers. A duplicate tool name across different tool agents raises a `RuntimeError` at discovery time.
- The `disliked_symbol_in_message()` function (line 272 of `pipeline.py`) uses a regex pattern matching "do not like {SYMBOL} in this portfolio" to detect explicit symbol rejection. This is a hard-coded pattern designed for the integration test script, not a general NLP-based intent classifier.
- Phase 2 tool filtering uses a hard-coded set `PHASE2_TOOLS = {"portfolio_equities", "portfolio_replace_symbol", "value_at_risk"}` (line 37 of `app.py`). The `prohibited_symbols` tool is excluded from Phase 2 because guidelines should not be re-parsed during chat.
- The portfolio construction uses random selection from the S&P 100 universe (line 253 of `tools/portfolio/src/app.py`). The `run_portfolio_var_loop()` retries up to 10 times if the VaR exceeds the threshold, with each retry generating a completely new random portfolio.
- The guidelines tool agent can operate in two modes: local inference using a joblib-loaded scikit-learn model, or remote inference via MLServer's V2 API (controlled by `INFERENCE_URL` env var). When `INFERENCE_URL` is set, the local model is not loaded at startup (line 550-553 of `tools/guidelines/src/app.py`).
- The LLM endpoint configuration (URL, model name, API key) is sent by the frontend in every request payload (lines 73-81 of `app.py`), not stored in environment variables or backend config. This allows dynamic model switching from the UI.

### Related Architectures

- [guardrails-layer](guardrails-layer.md) -- NeMo Guardrails input/output checks are applied at the application level via a client module
- [model-serving-gateway](model-serving-gateway.md) -- The guidelines MLP model is served via KServe MLServer with scikit-learn runtime

---

## Choosing Between Approaches

| Criteria | Approach A (Multi-Runner Dispatch) | Approach B (Hierarchical LangGraph DAG) | Approach C (Dual-Provider Factory) | Approach D (YAML State Machine) | Approach E (Multi-Persona RBAC Agents) | Approach F (Vision-Context-Aware Router) | Approach G (HTTP Tool Discovery + Two-Phase) |
|----------|-----------------------------------|----------------------------------------|-----------------------------------|---------------------------------|----------------------------------------|------------------------------------------|----------------------------------------------|
| Use case | Interactive chat with configurable AI agents | Automated event-driven data processing pipeline | Interactive copilot with deployment-mode flexibility | Multi-agent IT service automation with structured conversational workflows | Multi-persona regulated-industry application with per-tool RBAC | Real-time multimodal analytics combining CV detections with conversational database queries | Deterministic domain pipeline followed by interactive agentic chat with tool filtering |
| User interaction | Real-time chat with SSE streaming | No user interaction during processing; results viewed after | Real-time chat with SSE streaming | Real-time chat via web, CLI, Slack, or ticketing system | Real-time chat via WebSocket with buffered response | Synchronous REST chat + MJPEG video feed; separate alert rule creation endpoint | Synchronous REST; pipeline results displayed then user enters agentic chat |
| Agent framework | Pluggable (LlamaStack, LangGraph, CrewAI) | LangGraph only, with LangChain tool-calling agent | MCP-Direct (custom loop) or Llama Stack (delegated) | LangGraph (execution engine) + LlamaStack Responses API (inference + tools) | LangGraph only via shared build_agent_graph factory | LangGraph only, two independent graphs (chat + alert) | None -- custom Orchestrator class with direct OpenAI SDK |
| Graph definition | Configurable via database (runner_type, graph_config) | Fixed Python code, compiled at module load | Not applicable (simple tool-calling loop, no graph) | YAML configuration files with typed states and declarative transitions | Shared graph structure per-agent, tools and RBAC from YAML config | Fixed Python code, two graphs compiled at startup with hardcoded node topology | Not applicable (while loop with max 20 iterations) |
| Framework selection | Runtime (per-agent, stored in database) | Hardcoded | Deployment-time (environment variable) | Startup (per-agent YAML config files, overridable via env vars) | Startup (per-agent YAML config, mtime-based hot-reload) | Hardcoded (chat graph selected by /api/chat, alert graph by /api/alerts) | Not applicable (single custom orchestrator) |
| Context retrieval | RAG via file_search tool (transparent to prompt) | RAG as explicit graph node + Loki log retrieval subgraph | Not applicable (tools query database directly) | RAG via file_search tool (transparent to prompt, knowledge bases in YAML) | RAG via pgvector compliance KB search tool (direct SQL, no LlamaStack) | Live CV detection context injected as state field; historical data via SQL through MCP | Deterministic pipeline produces domain context; injected as JSON into system prompt |
| Processing model | One request at a time per chat session | Batch processing with log clustering for deduplication | One request at a time per chat session | One request at a time per session, with session lock preventing concurrent processing | One request at a time per WebSocket, with asyncio.wait disconnect cancellation | One request at a time per Flask worker thread; asyncio.run() per request | Two phases: batch pipeline then one-at-a-time agentic chat per session |
| LLM routing | Not used (dispatch is by runner_type config) | LLM structured output drives conditional graph edges | Not applicable (single sequential loop) | LLM intent classification drives `routing_decision` field, session manager dispatches to specialist | Not used (single agent per persona, WebSocket path selects agent) | LLM structured output (RouteDecision) classifies "context" vs "sql" path within the chat graph | Not used (single orchestrator, tool filtering is programmatic) |
| Tool security | Framework-managed tool registration | No explicit validation | Hard-coded allowlist + Pydantic schema validation (MCP-Direct only) | LlamaStack-managed MCP tool execution with per-request AUTHORITATIVE_USER_ID header | YAML-configured per-tool allowed_roles checked by tool_auth graph node | SQL-level scoping wrapper using contextvars to enforce app_config_id filtering | Programmatic tool subset filtering (`PHASE2_TOOLS`) and duplicate name detection |
| Model format support | Standard OpenAI tool calling | Standard OpenAI tool calling | Auto-detects Nemotron TOOLCALL tags vs OpenAI format | Standard OpenAI tool calling via LlamaStack Responses API | Standard OpenAI tool calling via ChatOpenAI | Standard OpenAI tool calling via ChatOpenAI with structured output for routing/planning | Standard OpenAI tool calling via direct OpenAI SDK |
| Policy management | Per-agent shields via LlamaStack safety API | Not applicable | Runtime policy injection into system prompt | NeMo Guardrails service with custom Colang flows and jailbreak detection NIM | NeMo Guardrails as LangGraph graph nodes (input_shield, output_shield) | Not applicable (no guardrails; SQL scoping is the only security layer) | Application-level NeMo Guardrails client with fail-open degradation |
| Multi-agent support | Not built in (single agent per session) | Not applicable | Not applicable | Built-in routing agent + specialist agent dispatch with session state handoff | Five independent agents, each on its own WebSocket path; A2A protocol for cross-agent invocation | Two independent graphs (chat + alert) instantiated at startup, no inter-graph communication | Three independent HTTP tool agents behind single orchestrator |
| Communication model | Direct REST/SSE | Direct Python method calls | Direct REST/SSE | CloudEvent-driven microservices via Knative broker | Direct WebSocket with optional A2A (JSON-RPC) | Direct REST (synchronous Flask); MJPEG streaming for video feed | Direct REST with HTTP tool discovery protocol (GET /tools, POST /tools/<name>) |
| Complexity | Higher (multi-framework, SSE normalization) | Moderate (single framework, hierarchical subgraphs) | Moderate (two providers, shared interface) | Higher (multi-service, CloudEvents, YAML state machines, multi-agent routing) | Moderate (single framework, shared graph factory, YAML-driven config) | Lower (single framework, fixed graph topology, synchronous Flask, no streaming for chat) | Lower (no framework, simple while loop, HTTP-based tool protocol) |
