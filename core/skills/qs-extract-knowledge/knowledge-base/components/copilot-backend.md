---
name: copilot-backend
description: FastAPI backend with provider abstraction for LLM+MCP agentic orchestration and governance policy management
summary: "Provides a FastAPI backend orchestrating vLLM inference (via AsyncOpenAI client, 600s timeout) with MCP tool execution for data governance copilot use cases, streaming agentic loop progress to the UI via SSE with standardized event types (query_start through final_response) and supporting runtime governance policy injection via REST endpoints. Choose MCP-Direct mode (COPILOT_PROVIDER_MODE=mcp_direct) for direct agentic loop control with dual tool-call format detection (Nemotron XML <TOOLCALL> tags vs OpenAI function calling via LLM_TOOL_CALL_FORMAT), per-request dynamic system prompt rebuilds for policy updates without restart, and streamable-http MCP connection with exponential backoff retry; choose Llama Stack mode (llama_stack) to delegate orchestration to the Agents API with toolgroup registration, accepting that policy changes require full agent recreation and session invalidation. Critical pattern: provider factory in providers/factory.py selects implementation via env var, fail-closed tool validation layer in tool_validation.py enforces a hardcoded TOOL_SCHEMAS allowlist with Pydantic schema validation to block prompt-injection-driven unauthorized tool calls, and defaults are LLM_TEMPERATURE=0.1, LLM_MIN_P=0.1, LLM_MAX_CONTEXT_LENGTH=32768. Key gotchas: Uvicorn timeout_keep_alive=650s must exceed the 600s OpenShift Route timeout; health probes allow 5 minutes of failures (liveness failureThreshold:30 x periodSeconds:10) because the single-threaded handler blocks during long tool-calling loops; conversation_store is an in-memory dict (not production-ready); new MCP tools are silently rejected unless manually added to TOOL_SCHEMAS; and MCP URL env var names differ between providers (PG_AIRMAN_MCP_SERVICE_PORT vs PG_AIRMAN_MCP_SERVICE_URL)."
metadata:
  type: component
tags:
  tech_stack: [fastapi, python, openai, llama-stack-client, mcp, pydantic, uvicorn, httpx]
  ai_pattern: [agents, tool-calling, mcp, guardrails, prompt-chaining]
  platform: [openshift, vllm, kserve]
  data_layer: []
source_examples:
  - quickstart: "data-governance-co-pilot"
    repo: "https://github.com/rh-ai-quickstart/data-governance-co-pilot"
    notes: "FastAPI copilot backend with dual-provider architecture (MCP-Direct vs Llama Stack) for database governance with SSE streaming"
    approach: "A"
---

# Copilot Backend

## Overview

A FastAPI backend that orchestrates LLM inference with MCP (Model Context Protocol) tool execution for data governance use cases. It implements a provider abstraction layer supporting two deployment modes: MCP-Direct (backend manages the agentic loop with direct vLLM + MCP connections) and Llama Stack (delegates orchestration to the Llama Stack Agents API). The backend streams progress to the UI via Server-Sent Events and supports runtime governance policy injection.

## Tech Stack & Dependencies

- **Runtime:** Python 3.12, FastAPI, Uvicorn
- **Container image:** `quay.io/rh-ai-quickstart/copilot-backend:latest`
- **Key dependencies:** `fastapi>=0.115.0`, `openai>=1.57.0` (AsyncOpenAI client for vLLM), `llama-stack-client~=0.3.5`, `mcp[cli]>=1.23.1`, `pydantic>=2.10.0`, `httpx>=0.28.1`, `python-dotenv>=1.0.0`
- **Build system:** Hatchling with `uv` for dependency management (frozen lockfile in container build)
- **Helm subchart:** `helm/copilot-backend/` (standalone chart, not a subchart dependency)

## Key Patterns

### Provider Abstraction Layer

The backend uses an abstract `LLMProvider` base class with two concrete implementations selected at runtime via `COPILOT_PROVIDER_MODE` environment variable. A factory function in `providers/factory.py` instantiates the correct provider.

```python
# providers/factory.py - Provider selection
provider_mode = os.getenv("COPILOT_PROVIDER_MODE", "mcp_direct").lower()

if provider_mode == "mcp_direct":
    return MCPDirectProvider(config=config, governance_policy=governance_policy)
elif provider_mode == "llama_stack":
    return LlamaStackProvider(config=config, governance_policy=governance_policy)
else:
    raise ValueError(f"Invalid COPILOT_PROVIDER_MODE: {provider_mode}")
```

### MCP-Direct Provider (Agentic Loop)

In `mcp_direct` mode, the backend manages the complete agentic loop locally: it calls vLLM via the OpenAI-compatible API, parses tool calls from the response, executes them against the MCP server, appends results to the conversation, and repeats up to 100 iterations until the LLM produces a final answer with no tool calls.

```python
# providers/mcp_direct.py - Core agentic loop structure
while iteration < max_iterations:
    iteration += 1
    # Call LLM with streaming
    stream = await self.llm_client.chat.completions.create(
        model=self.llm_model, messages=messages, tools=self.mcp_tools,
        tool_choice="auto", max_tokens=2048, temperature=self.temperature,
        stream=True, extra_body={"min_p": self.min_p}
    )
    # Parse tool calls, execute via MCP, append results, loop
```

### MCP Connection with Streamable HTTP

The MCP client connects to the pg-airman-mcp server via the streamable-http transport. The connection contexts are stored as instance variables to keep the connection alive for the lifetime of the pod. Includes retry logic with exponential backoff (up to 5 retries, max 10s delay) and automatic reconnection on session termination.

```python
# providers/mcp_direct.py - MCP connection pattern
self._mcp_client_context = streamablehttp_client(self.mcp_server_url)
self._mcp_read, self._mcp_write, _ = await self._mcp_client_context.__aenter__()
self._mcp_session_context = ClientSession(self._mcp_read, self._mcp_write)
self.mcp_session = await self._mcp_session_context.__aenter__()
await self.mcp_session.initialize()
```

### Dual Tool Call Format Detection (Nemotron vs OpenAI)

The MCP-Direct provider auto-detects the tool calling format from the model name or explicit `LLM_TOOL_CALL_FORMAT` config. Nemotron models use custom `<TOOLCALL>` XML tags while other models (Llama, Qwen) use standard OpenAI function calling. This is parsed differently in the streaming response handler.

```python
# providers/mcp_direct.py - Format detection
def _detect_tool_call_format(self, config):
    explicit_format = config.get("llm_tool_call_format", "auto")
    if explicit_format and explicit_format != "auto":
        return explicit_format
    model_name = config.get("llm_model", "").lower()
    if "nemotron" in model_name:
        return "nemotron"
    return "openai"
```

### Tool Validation Security Layer

A fail-closed security layer validates every tool call before execution. It maintains a hard-coded allowlist of approved tool names and validates arguments against Pydantic schemas with type coercion. This defends against prompt injection attacks that could coerce the LLM into calling unauthorized tools.

```python
# providers/tool_validation.py - Allowlist + schema validation
TOOL_SCHEMAS: Dict[str, type[BaseModel]] = {
    "execute_sql": ExecuteSqlArgs,
    "list_schemas": ListSchemasArgs,
    "get_object_details": GetObjectDetailsArgs,
    # ... 10 tools total
}
ALLOWED_TOOLS: Set[str] = set(TOOL_SCHEMAS.keys())
```

### SSE Streaming Response Pattern

The backend streams events to the frontend using Server-Sent Events with a standardized event schema. Both providers emit the same event types: `query_start`, `iteration_start`, `llm_thinking`, `llm_content_delta`, `tool_call`, `tool_result`, `timing_summary`, `final_response`, and `error`.

```python
# service.py - SSE streaming endpoint
@app.post("/query/stream")
async def query_stream(request: QueryRequest):
    async def event_generator():
        async for event in copilot.process_query_stream(...):
            event_type = event.get("type", "unknown")
            yield f"data: {json.dumps(event)}\n\n"
    return StreamingResponse(event_generator(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
```

### Governance Policy Runtime Injection

Governance policies can be uploaded, replaced, or removed at runtime via REST endpoints (`POST /policy/upload`, `DELETE /policy`, `GET /policy/status`). The two providers handle policy updates differently: MCP-Direct builds system prompts dynamically per request (no restart needed), while Llama Stack must recreate its agent since instructions are static at creation time (invalidates all sessions).

```python
# providers/base.py - Policy update contract
@abstractmethod
def requires_conversation_restart_on_policy_update(self) -> bool:
    """MCP-Direct returns False, Llama Stack returns True"""
    pass
```

### Llama Stack Agents API Integration

The Llama Stack provider registers MCP tools as a "toolgroup" with the Llama Stack server, creates an agent with toolgroup bindings, and streams turn events. Session management maps conversation IDs to Llama Stack session IDs, with recovery logic for pod restarts (lists existing sessions by name).

```python
# providers/llama_stack.py - Agent creation with toolgroups
agent = self.client.alpha.agents.create(
    agent_config={
        "model": self.llama_stack_model,
        "instructions": self.get_system_prompt(enable_reasoning=True),
        "toolgroups": [self.toolgroup_id],
        "tool_choice": "auto",
        "sampling_params": {"max_tokens": 2048, "temperature": self.temperature, "min_p": self.min_p}
    }
)
```

## Configuration

- **Environment variables:**
  - `COPILOT_PROVIDER_MODE`: `mcp_direct` (default) or `llama_stack` -- selects provider implementation
  - `LLM_BASE_URL`: vLLM endpoint URL (default: `http://nemotron-service:8000/v1`)
  - `LLM_MODEL`: Model identifier (e.g., `nvidia/nemotron-nano-9b-v2`, `qwen3-14b`)
  - `LLM_API_KEY`: API key for LLM service (stored in Kubernetes Secret)
  - `LLM_MAX_CONTEXT_LENGTH`: Context window size in tokens (default: `32768`)
  - `LLM_TOOL_CALL_FORMAT`: `auto` (default), `nemotron`, or `openai`
  - `LLM_TEMPERATURE`: Sampling temperature 0.0-2.0 (default: `0.1`)
  - `LLM_MIN_P`: Min-P sampling threshold 0.0-1.0 (default: `0.1`)
  - `PG_AIRMAN_MCP_SERVICE_PORT` / `PG_AIRMAN_MCP_SERVICE_URL`: MCP server endpoint
  - `LLAMA_STACK_BASE_URL`: Llama Stack endpoint (default: `http://copilot-llama-stack:8000`)
  - `LLAMA_STACK_MODEL`: Llama Stack model identifier (auto-prefixed with `vllm-inference/`)
  - `COPILOT_UI_ORIGIN`: Comma-separated allowed CORS origins for CSRF protection
  - `LOG_LEVEL`: Python logging level (default: `INFO`)
- **Config files:** None (all config via env vars)
- **Helm values:** `helm/copilot-backend/values.yaml` controls provider mode, LLM settings, MCP URL, CORS, resource limits, health probe timings, route timeout, and replica count

## Known Gotchas

- **Uvicorn keep-alive set to 650s** (`__main__.py`): The `timeout_keep_alive=650` is intentionally higher than the 600s route timeout to keep connections alive during long multi-step LLM reasoning chains. The comment in code says "matches route timeout."
- **Health probe failure thresholds are very high**: Liveness probe allows up to 5 minutes of failures (`failureThreshold: 30, periodSeconds: 10`) and readiness probe the same (`failureThreshold: 60, periodSeconds: 5`). This is because during long LLM tool-calling loops, the single-threaded request handler may not respond to health checks promptly.
- **OpenShift Route session affinity via cookies**: The route template uses `haproxy.router.openshift.io/cookie_name: 'copilot-backend-route'` to pin SSE connections to the same pod when `replicaCount > 1` (default is 2 replicas).
- **Conversation store is in-memory**: `conversation_store` in `service.py` is a plain dict (`dict[str, list[dict[str, str]]]`). The code comments explicitly note "In production, this should be replaced with a persistent store (Redis, DB, etc.)."
- **MCP server URL env var naming inconsistency**: MCP-Direct uses `PG_AIRMAN_MCP_SERVICE_PORT` while Llama Stack uses `PG_AIRMAN_MCP_SERVICE_URL` for the same purpose. Both are set from `mcp.serviceUrl` in the Helm deployment template.
- **Nemotron thinking tag handling**: When `enable_reasoning=True`, the Nemotron provider adds `/think` to the system prompt and parses `<think>...</think>` tags from responses. When disabled, `/no_think` is appended. Orphan `</think>` close tags (without an opener) are handled by splitting on the tag and taking content after it.
- **Llama Stack agent recreation on policy update**: Since the Llama Stack agents API does not provide an update method, changing governance policy requires creating a new agent, which invalidates all existing sessions. The `_session_store` is cleared, and clients must restart their conversations.
- **OpenAI client timeout set to 600s**: The `AsyncOpenAI` client in MCP-Direct mode uses `timeout=600.0` (10 minutes) to accommodate long inference times during multi-step tool-calling chains.
- **MCP tool calls validated against hardcoded allowlist**: Even if the MCP server advertises new tools, they will be rejected by the validation layer unless manually added to `TOOL_SCHEMAS` in `tool_validation.py`. The `check_mcp_server_tools()` function logs warnings about mismatches at startup.

## Testing Notes

- Unit tests exist in `packages/copilot/tests/` for tool validation (`test_tool_validation.py`) covering allowlist enforcement, argument schema validation, type coercion, and MCP server tool list checks
- `test_mcp_explain.py` is a manual integration test script for the `explain_query` MCP tool (assumes port-forwarded MCP server at `localhost:8000`)
- Health check endpoint at `GET /health` returns provider health status, tool count, and provider mode
- Provider info at `GET /provider/info` returns whether policy updates require conversation restart
- `GET /tools` lists available MCP tools and count

## Related Patterns

- MCP server component (pg-airman-mcp) provides the database analysis tools consumed by this backend
- Llama Stack deployment (`helm/copilot-llama-stack/`) is an alternative orchestration layer
- Frontend (copilot-ui) consumes the SSE stream from `/query/stream`
