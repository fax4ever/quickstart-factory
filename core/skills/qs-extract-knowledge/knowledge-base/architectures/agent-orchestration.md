---
name: agent-orchestration
description: Agent orchestration patterns from multi-runner dispatch to LangGraph DAGs to dual-provider factory
summary: "Enables pluggable multi-framework agent execution (Approach A) where a FastAPI ChatService endpoint dispatches to LlamaStack, LangGraph, or CrewAI runners based on VirtualAgent's runner_type in PostgreSQL, producing normalized SSE events (reasoning, response, tool_call, node_started/completed, error) for a React/PatternFly frontend; alternatively (Approach B) implements a hierarchical LangGraph DAG for automated event-driven processing with SentenceTransformer embedding + DBSCAN/HDBSCAN clustering, LLM structured-output routing via Command(goto=...), and nested subgraphs for RAG cheat-sheet and Loki tool-calling context retrieval; or (Approach C) a dual-provider factory selecting between backend-managed agentic loop (MCP-Direct with vLLM + Nemotron TOOLCALL tag auto-detection + hard-coded allowlist/Pydantic tool validation) and delegated orchestration (Llama Stack Agents API with toolgroup registration), both consuming the same pg-airman-mcp tool server with runtime governance policy injection. Use LlamaStack runner (default) for Responses API with built-in conversation history and auto-retry tool exclusion via AsyncLlamaStackClient; LangGraph for ReAct agents with MCP tools via MultiServerMCPClient or declarative DAG workflows (graph_config with typed nodes: llm, mcp_tool, mcp_tool_map, router and template substitution); CrewAI for multi-agent crews with persona/backstory mapping and LiteLLM OpenAI-compatible routing; Approach B for batch event-driven pipelines with fixed hierarchical subgraphs, dual LLM endpoints (default + tool-calling-capable), parallel processing of unique cluster representatives, and closure-bound Loki tools with result_id caching to reduce token usage; Approach C for interactive copilots needing deployment-time provider flexibility (COPILOT_PROVIDER_MODE env var) with single MCP tool server, where MCP-Direct gives full control over streaming/token management/model-specific parsing and Llama Stack simplifies architecture by delegating the agentic loop. All runners implement BaseRunner.stream() yielding SSE strings terminated by [DONE]; VirtualAgent model stores runner_type, model_name, prompt, tools, knowledge_base_ids, vector_store_ids, shields, and graph_config; LangGraph mode switches on graph_config presence (absent = create_react_agent, present = declarative StateGraph DAG with parallel node execution); Approach B graphs are compiled at module load time with a shared module-level LLM instance; Approach C's factory creates MCPDirectProvider or LlamaStackProvider based on COPILOT_PROVIDER_MODE, with MCP-Direct running a while loop (up to 100 iterations) auto-detecting Nemotron vs OpenAI tool call format, and Llama Stack registering pg-airman-mcp as a toolgroup with per-conversation sessions. Runners are lazily imported with _check_langgraph()/CREWAI_AVAILABLE guards to handle missing optional packages; CrewAI requires a _StreamDeduplicator to filter ReAct Thought/Action/Input noise; LangGraph's InMemorySaver must be swapped for PostgresSaver in multi-worker deployments; both LangGraph and CrewAI use LLM-based _extract_input_fields to parse structured fields from natural language when graph_config.input_fields are defined; Approach B's stream_with_fallback returns partial content on mid-stream interruption and its offline pipeline separates preparation (clustering) from processing to wait for RAG service readiness; Approach C's tool validation only applies in MCP-Direct mode (Llama Stack has no equivalent security layer), Llama Stack policy updates require full agent recreation clearing all sessions, conversation_store is in-memory (lost on pod restart), and MCP-Direct appends \"/mcp\" while Llama Stack appends \"/sse\" to the configured mcp_server_url."
metadata:
  type: architecture
tags:
  tech_stack: [fastapi, langchain, langgraph, crewai, llamastack, python, gradio, sentence-transformers, scikit-learn, sveltekit, openai-sdk, vega-lite]
  ai_pattern: [agents, prompt-chaining, model-serving, embeddings, data-governance]
  platform: [llamastack, vllm, rhoai, openshift, kserve]
  data_layer: [postgresql, pgvector]
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

## Choosing Between Approaches

| Criteria | Approach A (Multi-Runner Dispatch) | Approach B (Hierarchical LangGraph DAG) | Approach C (Dual-Provider Factory) |
|----------|-----------------------------------|----------------------------------------|-----------------------------------|
| Use case | Interactive chat with configurable AI agents | Automated event-driven data processing pipeline | Interactive copilot with deployment-mode flexibility |
| User interaction | Real-time chat with SSE streaming | No user interaction during processing; results viewed after | Real-time chat with SSE streaming |
| Agent framework | Pluggable (LlamaStack, LangGraph, CrewAI) | LangGraph only, with LangChain tool-calling agent | MCP-Direct (custom loop) or Llama Stack (delegated) |
| Graph definition | Configurable via database (runner_type, graph_config) | Fixed Python code, compiled at module load | Not applicable (simple tool-calling loop, no graph) |
| Framework selection | Runtime (per-agent, stored in database) | Hardcoded | Deployment-time (environment variable) |
| Context retrieval | RAG via file_search tool (transparent to prompt) | RAG as explicit graph node + Loki log retrieval subgraph | Not applicable (tools query database directly) |
| Processing model | One request at a time per chat session | Batch processing with log clustering for deduplication | One request at a time per chat session |
| LLM routing | Not used (dispatch is by runner_type config) | LLM structured output drives conditional graph edges | Not applicable (single sequential loop) |
| Tool security | Framework-managed tool registration | No explicit validation | Hard-coded allowlist + Pydantic schema validation (MCP-Direct only) |
| Model format support | Standard OpenAI tool calling | Standard OpenAI tool calling | Auto-detects Nemotron TOOLCALL tags vs OpenAI format |
| Policy management | Per-agent shields via LlamaStack safety API | Not applicable | Runtime policy injection into system prompt |
| Complexity | Higher (multi-framework, SSE normalization) | Moderate (single framework, hierarchical subgraphs) | Moderate (two providers, shared interface) |
