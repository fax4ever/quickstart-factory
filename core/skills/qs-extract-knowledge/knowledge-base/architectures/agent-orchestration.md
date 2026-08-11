---
name: agent-orchestration
description: Multi-runner agent dispatch with pluggable frameworks and unified SSE streaming
summary: "Enables pluggable multi-framework agent execution where a single FastAPI ChatService endpoint dispatches chat requests to LlamaStack, LangGraph, or CrewAI runners based on a VirtualAgent's runner_type configuration in PostgreSQL, producing a normalized SSE event stream (reasoning, response, tool_call, node_started/completed, error) for a framework-agnostic React/PatternFly frontend. Use LlamaStack runner (default) for Responses API with built-in conversation history and auto-retry tool exclusion via AsyncLlamaStackClient; LangGraph for ReAct agents with MCP tools via MultiServerMCPClient or declarative DAG workflows (graph_config with typed nodes: llm, mcp_tool, mcp_tool_map, router and template substitution); CrewAI for multi-agent crews with persona/backstory mapping and LiteLLM OpenAI-compatible routing. All runners implement BaseRunner.stream() yielding SSE strings terminated by [DONE]; VirtualAgent model stores runner_type, model_name, prompt, tools, knowledge_base_ids, vector_store_ids, shields, and graph_config; LangGraph mode switches on graph_config presence (absent = create_react_agent, present = declarative StateGraph DAG with parallel node execution). Runners are lazily imported with _check_langgraph()/CREWAI_AVAILABLE guards to handle missing optional packages; CrewAI requires a _StreamDeduplicator to filter ReAct Thought/Action/Input noise from the stream; LangGraph's InMemorySaver checkpointer must be swapped for PostgresSaver in multi-worker deployments; both LangGraph and CrewAI use LLM-based _extract_input_fields to parse structured fields from natural language when graph_config.input_fields are defined."
metadata:
  type: architecture
tags:
  tech_stack: [fastapi, langchain, langgraph, crewai, llamastack, python]
  ai_pattern: [agents, prompt-chaining, model-serving]
  platform: [llamastack, vllm, rhoai, openshift]
  data_layer: [postgresql]
source_examples:
  - quickstart: "ai-virtual-agent"
    repo: "https://github.com/rh-ai-quickstart/ai-virtual-agent"
    notes: "Multi-runner agent orchestration with LlamaStack, LangGraph, and CrewAI runners behind a unified ChatService dispatcher"
    approach: "A"
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
