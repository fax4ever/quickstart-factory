---
name: llamastack
description: "LlamaStack distribution server providing inference, agents, safety, tool runtime, and vector I/O APIs"
summary: "LlamaStack provides a unified AI orchestration server exposing inference, agents, safety, tool runtime, vector I/O, and files APIs between a FastAPI backend and Ollama, acting as the default runner in a pluggable multi-runner dispatch system (LlamaStack/LangGraph/CrewAI) for the ai-virtual-agent quickstart. Use as a single-server orchestration layer when you need combined model inference, input safety shields (inline::llama-guard), MCP tool integration resolved from toolgroups, and Responses API streaming with Conversations -- choose LangGraph or CrewAI runners when their specific agent frameworks are required. Configured via llamastack-run.yaml mounted at RUN_CONFIG_PATH declaring providers (remote::ollama for inference, inline::llama-guard for safety), consumed through llama_stack_client==0.6.1 AsyncLlamaStackClient with 180s default timeout and K8s SA token plus X-Forwarded-User/X-Forwarded-Email auth header forwarding for RBAC. Container runs as root (user 0:0) with 90s healthcheck start_period, SDK attribute names changed between 0.3.x and 0.6.1 (identifier to id, api_model_type to model_type) requiring _get_model_type/_get_model_id version-compatibility helpers, SQLite storage is dev-only not production, platform linux/amd64 causes ARM emulation perf hit, and regex-based tool retry error parsing (Tool '(\\w+)' not found) is fragile if LlamaStack changes its error message format."
metadata:
  type: component
tags:
  tech_stack: [llamastack, ollama, python, fastapi, llama-stack-client]
  ai_pattern: [agents, model-serving, guardrails, rag, vector-search]
  platform: [openshift, kubernetes]
  data_layer: [sqlite]
source_examples:
  - quickstart: "ai-virtual-agent"
    repo: "https://github.com/rh-ai-quickstart/ai-virtual-agent"
    notes: "LlamaStack as unified AI orchestration layer with Ollama backend, Responses API streaming, MCP tool integration, and safety shields"
    approach: "A"
---

# LlamaStack

## Overview

LlamaStack serves as a unified AI orchestration layer in the ai-virtual-agent quickstart, providing a single server that exposes inference, agents, safety, tool runtime, vector I/O, and files APIs. It sits between the FastAPI backend and the underlying model provider (Ollama in local dev) and is consumed through the `llama_stack_client` Python SDK. The backend uses the LlamaStack Responses API with Conversations for streaming chat, MCP tool execution, input shield validation, and model/resource enumeration.

## Tech Stack & Dependencies

- **Runtime:** LlamaStack distribution server v0.6.1
- **Container image:** `docker.io/ogxai/distribution-starter:0.6.1`
- **Key dependencies:** `llama_stack_client==0.6.1` (Python SDK), Ollama as inference provider, SQLite for internal state
- **Helm subchart:** None (deployed as a compose service in local dev)

## Key Patterns

### Distribution Run Configuration

LlamaStack is configured via a YAML run config (`llamastack-run.yaml`) that declares which APIs to expose and wires each API to a specific provider. The config is mounted into the container at runtime.

```yaml
version: 2
image_name: ollama
apis:
- agents
- inference
- safety
- tool_runtime
- vector_io
- files
providers:
  inference:
  - provider_id: ollama
    provider_type: remote::ollama
    config:
      base_url: http://ollama:11434/v1
  safety:
  - provider_id: llama-guard
    provider_type: inline::llama-guard
    config:
      excluded_categories: []
```

The config mounts into the container via a volume bind:

```yaml
# compose.yaml
volumes:
  - ./llamastack-run.yaml:/app-config/config.yaml:Z
environment:
  - RUN_CONFIG_PATH=/app-config/config.yaml
```

### Async Client Factory with Auth Forwarding

The backend creates `AsyncLlamaStackClient` instances that forward Kubernetes service account tokens and user identity headers (`X-Forwarded-User`, `X-Forwarded-Email`) to LlamaStack for RBAC-aware requests.

```python
# backend/app/api/llamastack.py
LLAMASTACK_URL = os.getenv("LLAMASTACK_URL", "http://localhost:8321")
LLAMASTACK_TIMEOUT = float(os.getenv("LLAMASTACK_TIMEOUT", "180.0"))

def get_llamastack_client(
    api_key: Optional[str], headers: Optional[dict[str, str]] = None
) -> AsyncLlamaStackClient:
    client = AsyncLlamaStackClient(
        base_url=LLAMASTACK_URL,
        default_headers=headers or {},
        timeout=httpx.Timeout(LLAMASTACK_TIMEOUT),
    )
    if api_key:
        client.api_key = api_key
    return client
```

A request-scoped factory extracts the SA token from `/var/run/secrets/kubernetes.io/serviceaccount/token` and merges user headers from the incoming HTTP request, while a sync factory adds the `ADMIN_USERNAME` env var for background operations.

### Responses API Streaming with StreamAggregator

The `LlamaStackRunner` uses the LlamaStack Responses API (`client.responses.create`) with Conversations for message history. A `StreamAggregator` class accumulates raw streaming events into simplified SSE events the frontend consumes. It handles reasoning deltas, output text deltas, tool calls (MCP, function, web search, file search), refusal detection, and token usage reporting.

```python
# backend/app/services/runners/llamastack_runner.py
response_params = {
    "model": model_for_request,
    "input": openai_input,
    "stream": True,
}
if tools:
    response_params["tools"] = tools

response_params["conversation"] = conversation_id

async for chunk in await client.responses.create(**response_params):
    chunk_dict = jsonable_encoder(chunk)
    async for simplified_event in aggregator.process_chunk(chunk_dict):
        yield f"data: {json.dumps(simplified_event)}\n\n"
```

### Tool Retry with Automatic Exclusion

When a tool is not found on the LlamaStack server, the runner automatically retries the request with that tool excluded, up to the total number of tools configured.

```python
# backend/app/services/runners/llamastack_runner.py
excluded_tools: set = set()
max_retries = len(tools) if tools else 0

for attempt in range(max_retries + 1):
    current_tools = [
        t for t in (tools or []) if t.get("type") not in excluded_tools
    ]
    # ... stream response ...
    match = re.search(r"Tool '(\w+)' not found", error_obj.get("message", ""))
    if match and attempt < max_retries:
        failed_tool = match.group(1)
        excluded_tools.add(failed_tool)
        retry = True
        break
```

### Input Shield Validation

Before streaming a response, the runner can invoke LlamaStack safety shields to check user input for policy violations. Shields are called via `client.safety.run_shield()` and a violation short-circuits the stream with an error event.

```python
# backend/app/services/runners/llamastack_runner.py
for shield_id in shield_ids:
    shield_response = await client.safety.run_shield(
        shield_id=shield_id,
        messages=[{"role": "user", "content": text_content}],
        params={},
    )
    if hasattr(shield_response, "violation") and shield_response.violation:
        violation_msg = shield_response.violation.user_message
        return {"type": "error", "message": violation_msg}
```

### MCP Tool Integration via Responses API

Tools from virtual agent config are converted to OpenAI Responses API format. MCP tools resolve their `server_url` by querying LlamaStack's toolgroups endpoint at runtime.

```python
# backend/app/services/runners/llamastack_runner.py
elif tool_id.startswith("mcp::"):
    client = get_llamastack_client_from_request(request)
    toolgroups = await client.toolgroups.list()
    for toolgroup in toolgroups:
        if str(toolgroup.identifier) == tool_id:
            responses_tools.append({
                "type": "mcp",
                "server_label": toolgroup.args.get("name", str(toolgroup.identifier)),
                "server_url": toolgroup.mcp_endpoint.uri,
            })
```

### Runner Abstraction (Multi-Framework Support)

LlamaStack is the default runner in a pluggable runner system. The `ChatService` dispatches to `LlamaStackRunner`, `LangGraphRunner`, or `CrewAIRunner` based on the agent's `runner_type` field (defaults to `"llamastack"`).

```python
# backend/app/services/chat.py
if runner_type == "llamastack" or not runner_type:
    return LlamaStackRunner(self.request, self.db, self.user_id)
```

### Resource Enumeration Endpoints

The backend exposes API endpoints that proxy LlamaStack resource listing with version-compatibility helpers that handle attribute name changes between LlamaStack 0.3.x and 0.6.1 (`identifier` vs `id`, `api_model_type` vs `model_type`).

```python
# backend/app/api/v1/llama_stack.py
def _get_model_type(model):
    """Get model type from various API versions"""
    for attr in ("api_model_type", "model_type"):
        val = getattr(model, attr, None)
        if val is not None:
            return val
    meta = getattr(model, "custom_metadata", None) or {}
    return meta.get("model_type")
```

## Configuration

- **Environment variables:**
  - `LLAMASTACK_URL` -- LlamaStack server URL (default: `http://localhost:8321`)
  - `LLAMASTACK_TIMEOUT` -- Client timeout in seconds (default: `180.0`)
  - `LLAMASTACK_PORT` -- Exposed port for LlamaStack server (default: `8321`)
  - `DEFAULT_INFERENCE_MODEL` -- Override model for local dev (e.g., `ollama/llama3.2:1b`)
  - `ADMIN_USERNAME` -- Username for `X-Forwarded-User` header in sync client
  - `TAVILY_API_KEY` -- API key for Tavily web search tool runtime provider
  - `RUN_CONFIG_PATH` -- Path inside container to the distribution run config YAML
- **Config files:**
  - `deploy/local/llamastack-run.yaml` -- Distribution run config defining APIs, providers, storage, registered models, and tool groups
- **Helm values:** N/A (compose-based local deployment)

## Known Gotchas

- The LlamaStack container runs as `user: "0:0"` (root) in compose to avoid permission issues with the `.llama` volume mounts (see `compose.yaml` line 72).
- The `platform: linux/amd64` is explicitly set in compose, meaning ARM-based dev machines (e.g., Apple Silicon) will use emulation, which impacts performance.
- The healthcheck uses a 90-second `start_period` because LlamaStack needs time to initialize providers and download model metadata after Ollama becomes healthy (`compose.yaml` lines 88-90).
- The LlamaStack SDK changed attribute names between versions 0.3.x and 0.6.1 (e.g., `identifier` to `id`, `api_model_type` to `model_type`). The backend has version-compatibility helpers to handle both (`_get_model_type`, `_get_model_id`, `_get_provider_resource_id` in `backend/app/api/v1/llama_stack.py`).
- Storage backends use SQLite by default (`kv_sqlite` and `sql_sqlite` in the run config), which stores state inside the container volume at `/.llama/distributions/ollama/`. This is fine for dev but not for production persistence.
- When `has_output_text` is False after stream completion (e.g., the model only emitted tool calls with no text), the `StreamAggregator` emits an error event telling the user to retry -- this is by design to prevent silent empty responses (`llamastack_runner.py` lines 365-370).
- The tool retry mechanism parses error messages with regex (`Tool '(\w+)' not found`) which is fragile if LlamaStack changes its error message format.

## Testing Notes

- Unit tests mock the LlamaStack client using `_MockLlamaClient` stubs that expose `.models.list()`, `.vector_stores.list()`, and `.toolgroups.list()` as async coroutines returning Pydantic models (see `tests/unit/test_llamastack_endpoints.py`).
- The mock pattern uses a `_Proxy(list)` subclass that adds an async `list()` method returning itself, enabling `await client.models.list()` to work on a plain list.
- Healthcheck endpoint: `curl -f http://localhost:8321/v1/health`
- After deployment, verify model registration: the compose entrypoint runs `ollama run llama3.2:1b --keepalive 60m hi` to ensure the model is pulled and warm before LlamaStack starts.

## Related Patterns

- Architecture: agent orchestration, multi-runner framework dispatch
- Deployment: compose-based local dev with service dependency chains
- Components: ollama (inference backend), postgresql (session/agent storage)
