---
name: mcp-tool-integration
description: MCP tool integration from multi-framework registration to transport layer to persistent validated sessions
summary: "Integrates MCP tool servers into agent systems via five approaches: Approach A (ai-virtual-agent) provides multi-framework registration via LlamaStack toolgroups API (`POST /api/v1/mcp_servers/`, provider `model-context-protocol`), Kubernetes-native discovery from ToolHive MCPServer CRDs and Services labeled `app.kubernetes.io/component=mcp-server` with transport from `mcp.transport` label (default streamable-http), and four runtime paths (LlamaStack resolves `mcp::` prefixed toolgroup IDs, LangGraph ReAct uses `langchain-mcp-adapters` MultiServerMCPClient, GraphEngine calls MCP directly via JSON-RPC with `_MCP_SESSIONS`/`_TOOL_SCHEMAS` module-level caches refreshing on 400/404 containing \"session\" and `_filter_args_to_schema` preventing -32602 errors, CrewAI maps server names to hardcoded classes via `_TOOL_CLASS_BY_NAME`/`_SERVER_TOOL_NAME_HINTS`); Approach B (ansible-log-analysis) hides MCP inside LangChain `@tool` functions as transport for a single Loki server configured via `LOKI_MCP_SERVER_URL` with per-query httpx `MCPClient` using `Mcp-Session-Id` headers, tool result caching via `_store_tool_result` returning `result_id` references, `MAX_LOGS_PER_QUERY` (5000) cap, and closure-bound tool creation via `create_log_lines_above_tool`; Approach C (data-governance-co-pilot) maintains a persistent MCP session with pg-airman-mcp using MCP SDK `streamablehttp_client`+`ClientSession` with exponential backoff (5 retries, 1-10s), converts discovered tools to OpenAI format via `_convert_mcp_tools_to_openai`, validates calls via hard-coded `ALLOWED_TOOLS` set with Pydantic `TOOL_SCHEMAS`, auto-reconnects via `_reconnect_mcp()` on 404/\"Session terminated\"/ClosedResourceError, and supports dual consumption via MCP-Direct (custom agentic loop) or Llama Stack (toolgroup `mcp::pg_airman`); Approach D (it-self-service-agent) uses LlamaStack Responses API native MCP tool type with per-request `AUTHORITATIVE_USER_ID`/`traceparent`/`tracestate`/`SERVICE_NOW_TOKEN` headers injected at runtime, per-agent YAML config listing MCP server name+uri with `require_approval: \"never\"`, per-state tool toggling via `uses_mcp_tools` flag in the YAML state machine, FastMCP servers extracting auth via `mcp_common.headers.header_first` with `@trace_mcp_tool()` decorator for OpenTelemetry spans, and Zammad MCP delegating to a basher MCP client with `assert_ticket_customer_matches_basher` ticket ownership verification; Approach E (multi-agent-loan-origination) co-deploys a FastMCP server with stateless pure-computation risk assessment tools (DTI, LTV, credit risk, income stability, asset sufficiency, recommendation), caches tools at startup via `init_mcp_client()` using `langchain-mcp-adapters` MultiServerMCPClient in FastAPI lifespan as LangChain StructuredTool instances, supports optional predictive model MCP server with graceful degradation via `is_predictive_model_available()`, and exposes `/health` via `@mcp.custom_route` because MCP's `/mcp` endpoint returns 406 on GET. Choose Approach A for extensible multi-server platforms needing dynamic Kubernetes discovery, UI management, and multi-framework support; Approach B for single fixed-server integrations where MCP is invisible to the LLM with per-query session lifecycle; Approach C for security-first single-server scenarios needing persistent sessions with auto-reconnection, tool validation allowlist, and dual-mode consumption (MCP-Direct appends `/mcp` to URL, Llama Stack appends `/sse`); Approach D for multi-agent IT service automation needing per-user authorization headers, OpenTelemetry tracing propagation across MCP calls, per-agent YAML MCP server configuration, and LlamaStack-delegated MCP session lifecycle; Approach E for pure-computation MCP servers co-deployed with the agent where tools are cached at startup as LangChain StructuredTool instances with no per-request session overhead and optional secondary servers with graceful fallback. MCP servers are registered with `mcp_endpoint={\"uri\": url}` and built with FastMCP using `transport=\"streamable-http\"`; Kubernetes discovery is namespace-scoped with transport type set by `mcp.transport` label (default streamable-http); Approach B wraps all MCP calls inside `execute_loki_query()` creating a new `MCPClient` per invocation with JSON-RPC initialize handshake; Approach C's `check_mcp_server_tools()` logs warnings at startup for unrecognized tools without blocking; Approach D injects per-request headers into LlamaStack Responses API MCP tool definitions and supports `/health` endpoints via FastMCP `custom_route` for Kubernetes probes; Approach E initializes via `init_mcp_client()` in FastAPI lifespan with `MultiServerMCPClient` connecting to `MCP_RISK_SERVER_URL` and optionally `PREDICTIVE_MODEL_MCP_URL`, caching tools as module-level `_tools` list consumed by the underwriter agent's `get_mcp_tools()`. CrewAI MCP is not native, requiring entries in both `_TOOL_CLASS_BY_NAME` and `_SERVER_TOOL_NAME_HINTS` mapping tables; Approach B creates new `MCPClient` and `httpx.AsyncClient` per query with no connection pooling; Approach C's Pydantic tool validation is only active in MCP-Direct mode -- Llama Stack bypasses it, creating a prompt injection risk; pg-airman-mcp uses `mcp_readonly` user in `restricted` access mode with `allowCommentInRestricted: false` and supports multiple replicas requiring Service-level session affinity; Approach D's `AUTHORITATIVE_USER_ID` format varies -- ServiceNow strips `-{digits}` suffix via `re.sub(r\"-\\d+$\", \"\", raw)` while Zammad parses full `email-ticketid` format via `parse_email_and_ticket_id`, `dummy_parameter` exists in Zammad tools because MCP validation fails without at least one parameter, and LlamaStack manages the MCP session lifecycle internally so the agent has no control over session reuse, timeouts, or reconnection behavior; Approach E's cached tools become stale if the MCP server restarts post-initialization with no reconnection or health-check logic in `langchain-mcp-adapters`, and `get_predictive_tool()` searches by name `\"check_loan_approval\"` returning `None` silently if the tool name changes."
metadata:
  type: architecture
tags:
  tech_stack: [fastapi, llamastack, langchain, langgraph, python, httpx, openai-sdk, pydantic, zammad, servicenow, langchain-mcp-adapters]
  ai_pattern: [agents, model-serving, data-governance]
  platform: [llamastack, vllm, rhoai, openshift, kubernetes, kserve]
  data_layer: [postgresql, pgvector]
source_examples:
  - quickstart: "ai-virtual-agent"
    repo: "https://github.com/rh-ai-quickstart/ai-virtual-agent"
    notes: "MCP tool servers (travel research, hotel, flight) registered via LlamaStack toolgroups API, discovered from Kubernetes, and executed across LlamaStack, LangGraph, and CrewAI runners"
    approach: "A"
  - quickstart: "ansible-log-analysis"
    repo: "https://github.com/rh-ai-quickstart/ansible-log-analysis"
    notes: "Custom MCP client for Loki log queries, embedded inside LangChain tools as a query transport layer within a LangGraph agent subgraph"
    approach: "B"
  - quickstart: "data-governance-co-pilot"
    repo: "https://github.com/rh-ai-quickstart/data-governance-co-pilot"
    notes: "Persistent MCP session with pg-airman-mcp for PostgreSQL governance tools, tool validation allowlist with Pydantic schemas, dual consumption via MCP-Direct (backend agentic loop) and Llama Stack (toolgroup registration)"
    approach: "C"
  - quickstart: "it-self-service-agent"
    repo: "https://github.com/rh-ai-quickstart/it-self-service-agent"
    notes: "MCP servers (Zammad ticketing, ServiceNow) built with FastMCP, invoked via LlamaStack Responses API native MCP tool type with per-request AUTHORITATIVE_USER_ID and tracing headers"
    approach: "D"
  - quickstart: "multi-agent-loan-origination"
    repo: "https://github.com/rh-ai-quickstart/multi-agent-loan-origination"
    notes: "Co-deployed FastMCP server with pure-computation risk assessment tools, langchain-mcp-adapters MultiServerMCPClient startup initialization, tools cached as LangChain StructuredTool instances for LangGraph agent, optional predictive model server with graceful degradation"
    approach: "E"
---

# MCP Tool Integration

## Overview

This architecture wires Model Context Protocol (MCP) tool servers into the agent system at three levels: registration (CRUD via LlamaStack's toolgroups API), discovery (auto-detecting MCP servers from Kubernetes resources), and runtime execution (each agent framework invokes MCP tools differently). MCP servers are standalone HTTP services that expose tools via JSON-RPC. The backend manages their lifecycle through LlamaStack while providing Kubernetes-native discovery for cluster deployments. At runtime, each runner framework has its own mechanism for calling MCP tools, but all produce the same `tool_call` SSE events for the frontend.

## Data Flow

1. Admin registers an MCP server via `POST /api/v1/mcp_servers/`, providing a name, endpoint URL, and configuration
2. The backend registers the server as a LlamaStack toolgroup with provider `model-context-protocol`
3. Alternatively, the discover endpoint (`GET /api/v1/mcp_servers/discover`) auto-detects MCP servers from Kubernetes MCPServer CRDs and labeled Services
4. A virtual agent is configured with tools referencing MCP toolgroup IDs (e.g., `mcp::travel-research`)
5. At chat time, the runner resolves MCP server URLs from the agent's tool configuration
6. The runner calls MCP tools via JSON-RPC over HTTP (streamable-http transport)
7. Tool results are streamed back to the frontend as `tool_call` SSE events

## Component Wiring

| From | To | Protocol | Purpose |
|------|----|----------|---------|
| React frontend | FastAPI MCP API | REST | MCP server CRUD and discovery |
| FastAPI MCP API | LlamaStack server | HTTP (AsyncLlamaStackClient) | Toolgroup registration, listing, unregistration |
| FastAPI MCP API | Kubernetes API | kubernetes Python client | MCPServer CRD and Service discovery |
| LlamaStackRunner | LlamaStack server | HTTP | MCP tool execution via Responses API |
| LangGraphRunner (ReAct) | MCP servers | HTTP (MultiServerMCPClient) | MCP tools loaded as LangChain tools |
| LangGraphRunner (Declarative) | MCP servers | HTTP (httpx JSON-RPC) | Direct MCP tools/call via GraphEngine |
| CrewAIRunner | N/A (local wrappers) | Python | Maps MCP server names to local CrewAI tool classes |
| MCP servers | External APIs | HTTP | Tavily search, Google Hotels, Google Flights |

## Key Integration Points

### MCP Server Registration via LlamaStack

MCP servers are registered as LlamaStack toolgroups, storing endpoint URL and configuration centrally.

```python
# backend/app/api/v1/mcp_servers.py (lines 61-75)
await sync_client.toolgroups.register(
    toolgroup_id=server.toolgroup_id,
    provider_id="model-context-protocol",
    args={
        **server.configuration,
        "name": server.name,
        "description": server.description,
    },
    mcp_endpoint={"uri": server.endpoint_url},
)
```

### Kubernetes MCP Discovery

The backend auto-discovers MCP servers from two Kubernetes resource types: MCPServer custom resources (from ToolHive) and Services with the `app.kubernetes.io/component=mcp-server` label.

```python
# backend/app/services/k8s_mcp_discovery.py (lines 82-100, 167-217)
def _discover_mcpserver_resources(self) -> List[Dict[str, Any]]:
    label_selector = "app.kubernetes.io/component=mcp-server"
    resources = self.custom_api.list_namespaced_custom_object(
        group="toolhive.stacklok.dev",
        version="v1alpha1",
        namespace=self.namespace,
        plural="mcpservers",
        label_selector=label_selector,
    )
    # ... extract name, description, endpoint_url from status

def _discover_service_resources(self) -> List[Dict[str, Any]]:
    services = self.core_api.list_namespaced_service(
        namespace=self.namespace, label_selector=label_selector
    )
    # ... construct endpoint_url from service name, namespace, port
```

### LlamaStack Runner: MCP via Responses API

The LlamaStack runner converts MCP toolgroup references into Responses API tool definitions, letting LlamaStack handle MCP tool execution natively.

```python
# backend/app/services/runners/llamastack_runner.py (lines 439-457)
elif tool_id.startswith("mcp::"):
    if request:
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

### LangGraph Runner: MCP via MultiServerMCPClient

The LangGraph ReAct runner resolves MCP server URLs from LlamaStack toolgroups and loads them as LangChain-compatible tools via `langchain-mcp-adapters`.

```python
# backend/app/services/runners/langgraph_runner.py (lines 553-565)
if mcp_configs:
    from langchain_mcp_adapters.client import MultiServerMCPClient
    async with MultiServerMCPClient(mcp_configs) as mcp_client:
        tools = mcp_client.get_tools()
        async for event in self._run_graph(agent, tools, session_id, prompt):
            yield event
```

### GraphEngine: Direct MCP JSON-RPC

The declarative graph engine calls MCP tools directly via JSON-RPC over HTTP, including session management, tool schema discovery, and argument filtering.

```python
# backend/app/services/runners/graph_engine.py (lines 361-409)
async def _call_mcp_tool(client, url, tool_name, arguments):
    session_id = await _get_mcp_session(client, url)
    payload = {
        "jsonrpc": "2.0", "id": 3,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    headers = {"Accept": "application/json, text/event-stream",
               "Content-Type": "application/json"}
    if session_id:
        headers["Mcp-Session-Id"] = session_id
    resp = await client.post(url, json=payload, headers=headers, timeout=60)
    # ... handle session refresh on 400/404, parse result
```

### MCP Server Example: Travel Research

The quickstart includes purpose-built MCP servers as standalone FastMCP services using streamable-http transport.

```python
# mcp_servers/travel_research_mcp/server.py (lines 10-14, 17-18)
mcp = FastMCP(
    "travel_research_mcp",
    host=os.getenv("HOST", "0.0.0.0"),
    port=int(os.getenv("PORT", "8000")),
)

@mcp.tool()
def tavily_travel_search(query: str, max_results: int = 5) -> str:
    """Search the web for travel information about a destination or theme."""
```

### CrewAI Runner: Local Tool Wrappers

CrewAI does not call MCP servers directly. Instead, it maps MCP server names to local Python tool classes via a name-hint lookup table.

```python
# backend/app/services/runners/crewai_runner.py (lines 240-249)
_TOOL_CLASS_BY_NAME = {
    "tavily_travel_search": TavilySearchTool,
    "google_hotels_search": GoogleHotelsTool,
    "google_flights_search": GoogleFlightsTool,
}
_SERVER_TOOL_NAME_HINTS = (
    ("research", "tavily_travel_search"),
    ("hotel", "google_hotels_search"),
    ("flight", "google_flights_search"),
)
```

## Prompt / Chain Patterns

MCP tools are invoked by the LLM through function/tool calling. The LLM receives tool definitions (name, description, input schema) and decides when to call them based on the user's query. Tool results are injected back into the conversation as tool response messages, and the LLM synthesizes a final answer. In the declarative graph engine, MCP tools are called deterministically as graph nodes (not LLM-driven), with arguments rendered via template substitution.

## Gotchas

- The GraphEngine maintains module-level session caches (`_MCP_SESSIONS`, `_TOOL_SCHEMAS`) that persist across requests within a single process. Stale sessions are refreshed when the MCP server returns 400/404 with "session" in the response body (lines 391-396 of `graph_engine.py`).
- The GraphEngine's `_filter_args_to_schema` function (lines 342-358) discovers each MCP tool's input schema and drops arguments not in the schema to prevent JSON-RPC -32602 (invalid params) errors. This is necessary because template rendering can produce extra fields.
- CrewAI's MCP integration is a compatibility shim, not native MCP -- it maps server names to hard-coded local tool classes. Adding a new MCP server type requires adding a new entry to `_TOOL_CLASS_BY_NAME` and `_SERVER_TOOL_NAME_HINTS`.
- The Kubernetes discovery supports two resource types: ToolHive MCPServer CRDs (`toolhive.stacklok.dev/v1alpha1`) and standard Services. The transport type (SSE vs streamable-http) is determined by the `mcp.transport` label, with streamable-http as the default (appending `/mcp` to the URL).
- MCP servers in this quickstart use the `streamable-http` transport exclusively. The `FastMCP` library is used to build them, with `mcp.run(transport="streamable-http")`.

## Related Architectures

- [agent-orchestration](agent-orchestration.md) -- MCP tools are resolved and executed within each runner framework
- [rag-pipeline](rag-pipeline.md) -- Knowledge base tools (`builtin::rag`) and MCP tools are handled by the same `build_responses_tools` function

---

## Approach B: MCP Client as Log Query Transport Layer (from ansible-log-analysis)

### When to Use

Use this approach when MCP is used as a transport protocol for a single, known backend service (e.g., a Loki log database) rather than as a pluggable tool discovery and registration framework. This approach treats MCP as an implementation detail inside LangChain tools, not as a user-facing tool management system.

### Differences from Approach A

| Aspect | Approach A (Multi-Framework MCP) | Approach B (MCP as Transport Layer) |
|--------|----------------------------------|-------------------------------------|
| MCP server count | Multiple, dynamically registered | Single, hardcoded via environment variable |
| Registration | LlamaStack toolgroups API (`POST /api/v1/mcp_servers/`) | None -- URL configured via `LOKI_MCP_SERVER_URL` env var |
| Discovery | Kubernetes MCPServer CRDs + labeled Services | None -- single known server |
| Client library | LlamaStack native, langchain-mcp-adapters, httpx (GraphEngine), CrewAI shims | Custom `MCPClient` class using httpx |
| MCP consumer | Agent frameworks (LlamaStack, LangGraph, CrewAI) | LangChain `@tool` decorated functions |
| Tool visibility | LLM selects MCP tools from tool definitions | MCP is hidden from LLM -- LangChain tools wrap MCP calls |
| Session management | Framework-managed (MultiServerMCPClient) or manual (_MCP_SESSIONS cache) | Per-query: new client + initialize + call + cleanup |

### Data Flow

1. LangGraph Loki agent subgraph invokes `LokiQueryAgent.query_logs()` with a natural-language request
2. LangChain `create_agent` selects the appropriate LangChain tool (e.g., `get_logs_by_file_name`, `search_logs_by_text`, `get_play_recap`, `get_log_lines_above`)
3. The selected tool builds a LogQL query string from its parameters
4. Tool calls `execute_loki_query()` which creates a new `MCPClient` instance
5. `MCPClient.initialize()` sends a JSON-RPC `initialize` request to the Loki MCP server and captures the `Mcp-Session-Id` from the response header
6. `MCPClient.call_tool("loki_query", arguments)` sends a JSON-RPC `tools/call` request with LogQL query parameters
7. Loki MCP server executes the LogQL query against Loki and returns results
8. Tool parses the JSON response into `LogToolOutput`, stores in module-level cache, and returns a lightweight reference (result ID) to the LLM
9. MCP client is cleaned up after each query

### Component Wiring

| From | To | Protocol | Purpose |
|------|----|----------|---------|
| LangChain tools | MCPClient | Python method call | Execute LogQL queries via MCP |
| MCPClient | Loki MCP server | HTTP (JSON-RPC, streamable-http) | MCP protocol for tool execution |
| Loki MCP server | Loki | HTTP (Loki API) | Execute LogQL queries |
| LangChain agent | LangChain tools | LangChain tool calling | LLM selects and invokes tools |

### Key Integration Points

#### Custom MCP Client

A lightweight MCP client that manages session initialization and tool calling via JSON-RPC over HTTP.

```python
# src/alm/mcp/mcp_client.py (lines 14-121)
class MCPClient:
    def __init__(self, server_url):
        self.server_url = server_url
        self.session_id = None
        self.client: httpx.AsyncClient = None

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
        response = await self.client.post(self.server_url, json=payload,
            headers={"Content-Type": "application/json"})
        self.session_id = response.headers.get("Mcp-Session-Id")

    async def call_tool(self, tool_name, arguments):
        payload = {
            "jsonrpc": "2.0", "id": 3,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
        headers = {"Content-Type": "application/json",
                   "Mcp-Session-Id": self.session_id}
        response = await self.client.post(self.server_url, json=payload, headers=headers)
        data = response.json()
        return data["result"]["content"][0]["text"]
```

#### MCP Wrapped Inside LangChain Tools

LangChain tools hide the MCP transport from the LLM. The LLM sees tool names like `get_logs_by_file_name` and `search_logs_by_text` -- it never interacts with MCP directly.

```python
# src/alm/tools/loki_tools.py (lines 58-66, 171-226)
async def execute_loki_query(query, start, end, limit, reference_timestamp, direction):
    client = await create_mcp_client()
    arguments = {"query": query, "start": start_parsed, "end": end_parsed,
                 "limit": limit, "direction": direction, "format": "json"}
    result = await client.call_tool("loki_query", arguments)
    # ... parse result into LogToolOutput, store in cache

@tool(args_schema=FileLogSchema)
async def get_logs_by_file_name(file_name, log_timestamp, start_time, end_time,
                                 status_list, log_type_list, limit, direction):
    """Get logs for a specific file with time ranges relative to a reference timestamp."""
    # Build LogQL query from parameters
    query = "".join(selector_parts + query_parts)
    result = await execute_loki_query(query, start_time, end_time, limit, log_timestamp, direction)
    return result
```

#### Tool Result Caching to Reduce Token Usage

Full log results are stored in a module-level cache, and only a lightweight reference is returned to the LLM, preventing large log outputs from consuming the LLM context window.

```python
# src/alm/tools/loki_tools.py (lines 127-137)
full_output = LogToolOutput(
    status=ToolStatus.SUCCESS,
    message=message,
    logs=logs,
    number_of_logs=len(logs),
    query=query,
    execution_time_ms=parsed_result.get("stats", {}).get("summary", {}).get("execTime", 0),
)
return _store_tool_result(full_output)
# _store_tool_result saves full_output in cache, returns lightweight JSON with result_id
```

#### Closure-Bound Tool Creation

The `get_log_lines_above` tool is created dynamically with log context bound via Python closures, preventing the LLM from having to serialize complex log messages as JSON arguments.

```python
# src/alm/tools/loki_tools.py (lines 347-369)
def create_log_lines_above_tool(file_name, log_message, log_timestamp):
    @tool(args_schema=LogLinesAboveSchema)
    async def get_log_lines_above(lines_above: int = DEFAULT_LINE_ABOVE) -> str:
        """Get log lines that occurred before/above a specific log line in a file.
        This tool has log context (file_name, log_message, log_timestamp) bound
        via closure at creation time. The LLM only needs to specify how many lines
        to retrieve."""
        # Uses closure-captured file_name, log_message, log_timestamp
        # ... executes query via MCP
    return get_log_lines_above
```

### Prompt / Chain Patterns

The Loki agent uses a system prompt loaded from `src/alm/agents/loki_agent/prompts/loki_agent_system_prompt.md` that instructs the LLM how to use the available tools (get_logs_by_file_name, search_logs_by_text, get_play_recap, get_log_lines_above). The LLM receives tool definitions via LangChain's standard tool calling mechanism and selects tools based on the user request. MCP is invisible to the LLM -- it only sees the LangChain tool interfaces.

### Gotchas

- A new `MCPClient` instance is created for every query execution (line 81 of `loki_tools.py`). This means a new MCP session is initialized for each LogQL query, including the JSON-RPC handshake. This is simpler than maintaining a persistent session but adds per-query overhead.
- The MCP client creates a new `httpx.AsyncClient` on each `__aenter__` (line 22 of `mcp_client.py`) and closes it on `__aexit__`. There is no connection pooling across queries.
- The `MCPClient.initialize()` method expects an `Mcp-Session-Id` header in the response (line 51 of `mcp_client.py`). If the MCP server doesn't return this header, initialization fails with "No session ID received from server".
- The tool result caching mechanism (`_store_tool_result` / `_get_tool_result`) operates at the module level, meaning cache entries persist across requests within a single process. A cache miss (line 156 of `agent.py`) indicates a bug in the cache mechanism rather than an expected condition.
- The `MAX_LOGS_PER_QUERY` constant (5000) caps the number of logs returned per query (line 71 of `loki_tools.py`), even if the LLM requests more, to prevent excessive data transfer through the MCP layer.
- The Loki MCP server URL is configured via a single environment variable (`LOKI_MCP_SERVER_URL`, line 45 of `loki_tools.py`), with no fallback or discovery mechanism.

---

## Approach C: Persistent MCP Session with Tool Validation Allowlist (from data-governance-co-pilot)

### When to Use

Use this approach when integrating a single, known MCP server (e.g., EDB's pg-airman-mcp for PostgreSQL analysis) as the primary tool source for an AI copilot, where the MCP tools are visible to the LLM (unlike Approach B which hides MCP), security requires an application-level tool validation layer (unlike Approach A which relies on framework-managed registration), and the same MCP server must be consumed by two different provider modes (direct agentic loop vs delegated orchestration). This approach is suited for data governance scenarios where the LLM must use database tools under strict security controls.

### Differences from Approach A and Approach B

| Aspect | Approach A (Multi-Framework MCP) | Approach B (MCP as Transport Layer) | Approach C (Persistent Session + Validation) |
|--------|----------------------------------|-------------------------------------|---------------------------------------------|
| MCP server count | Multiple, dynamically registered | Single, hardcoded via env var | Single, hardcoded via env var |
| Registration | LlamaStack toolgroups API | None | MCP-Direct: none; Llama Stack: toolgroup registration |
| Discovery | Kubernetes MCPServer CRDs + labeled Services | None | None (known server at deploy time) |
| Client library | LlamaStack native, langchain-mcp-adapters, httpx, CrewAI shims | Custom MCPClient using httpx | MCP SDK (`streamablehttp_client` + `ClientSession`) and LlamaStackClient |
| Session lifecycle | Framework-managed or module-level cache | Per-query (create, use, dispose) | Persistent (startup to shutdown, with reconnection logic) |
| Tool visibility to LLM | LLM sees MCP tools directly | MCP hidden behind LangChain tools | LLM sees tools directly (converted to OpenAI format) |
| Tool security | Framework-managed tool registration | None | Hard-coded allowlist + Pydantic schema validation |
| Dual consumption | Each framework has its own MCP path | Single path (LangChain tools) | Two paths: backend loop (MCP-Direct) or delegated (Llama Stack) |

### Data Flow

**MCP-Direct Mode (Backend-Managed):**

1. On startup, `MCPDirectProvider.initialize()` connects to pg-airman-mcp via `streamablehttp_client` with retry logic (up to 5 retries with exponential backoff)
2. MCP session sends `initialize` handshake, then discovers tools via `session.list_tools()`
3. Discovered MCP tools are converted to OpenAI function calling format (`_convert_mcp_tools_to_openai`)
4. `check_mcp_server_tools()` compares advertised tools against the hard-coded `ALLOWED_TOOLS` set, logging warnings for mismatches
5. During query processing, the LLM receives tool definitions and may request tool calls
6. Each tool call is validated: `validate_tool_name()` checks against allowlist, `validate_tool_arguments()` runs Pydantic schema validation
7. Validated tool calls are executed via the persistent MCP session: `self.mcp_session.call_tool(tool_name, tool_args)` with 5-minute timeout and retry logic
8. If MCP session is lost (404, "Session terminated", ClosedResourceError), `_reconnect_mcp()` creates a new session and retries

**Llama Stack Mode (Delegated):**

1. On startup, `LlamaStackProvider.initialize()` discovers the tool_runtime provider from Llama Stack
2. Registers pg-airman-mcp as a toolgroup: `client.toolgroups.register(toolgroup_id="mcp::pg_airman", provider_id=..., mcp_endpoint={"uri": url})`
3. Creates an agent with the toolgroup: `client.alpha.agents.create(agent_config={"toolgroups": ["mcp::pg_airman"], ...})`
4. During query processing, Llama Stack handles all MCP tool execution internally via the registered toolgroup
5. The provider receives tool_call and tool_result events from the Llama Stack streaming response

### Component Wiring

| From | To | Protocol | Purpose |
|------|----|----------|---------|
| MCPDirectProvider | pg-airman-mcp | HTTP (MCP streamable-http via MCP SDK) | Persistent session for tool discovery and execution |
| MCPDirectProvider | vLLM model server | HTTP (AsyncOpenAI) | LLM inference with tool definitions |
| LlamaStackProvider | Llama Stack server | HTTP (LlamaStackClient) | Toolgroup registration + agent orchestration |
| Llama Stack server | pg-airman-mcp | HTTP (MCP, transport from provider config) | Tool execution via registered toolgroup |
| pg-airman-mcp | PostgreSQL | TCP (port 5432) | Read-only database queries (mcp_readonly user) |

### Key Integration Points

#### MCP Session Initialization with Retry

The MCP-Direct provider initializes the MCP session at startup with configurable retry logic to handle pod startup order in Kubernetes.

```python
# packages/copilot/src/copilot/providers/mcp_direct.py (lines 208-234)
async def initialize(self) -> None:
    async def connect_to_mcp():
        self._mcp_client_context = streamablehttp_client(self.mcp_server_url)
        self._mcp_read, self._mcp_write, _ = await self._mcp_client_context.__aenter__()
        self._mcp_session_context = ClientSession(self._mcp_read, self._mcp_write)
        self.mcp_session = await self._mcp_session_context.__aenter__()
        await self.mcp_session.initialize()
        tools_response = await self.mcp_session.list_tools()
        return tools_response

    tools_response = await self._retry_mcp_operation(
        connect_to_mcp, "connection", max_retries=5  # Up to ~31 seconds
    )
    self.mcp_tools = self._convert_mcp_tools_to_openai(tools_response.tools)
    advertised_tool_names = [tool["function"]["name"] for tool in self.mcp_tools]
    check_mcp_server_tools(advertised_tool_names)
```

#### MCP Tool Conversion to OpenAI Format

MCP tool definitions are converted to OpenAI function calling format so the LLM can select tools regardless of whether it uses Nemotron or OpenAI calling conventions.

```python
# packages/copilot/src/copilot/providers/mcp_direct.py (lines 243-266)
def _convert_mcp_tools_to_openai(self, mcp_tools) -> list[dict[str, Any]]:
    openai_tools = []
    for tool in mcp_tools:
        openai_tool = {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description or "",
                "parameters": tool.inputSchema if hasattr(tool, 'inputSchema') else {
                    "type": "object", "properties": {}
                }
            }
        }
        openai_tools.append(openai_tool)
    return openai_tools
```

#### Tool Allowlist and Schema Validation

A hard-coded allowlist with Pydantic schemas provides defense-in-depth against prompt injection attacks that attempt to coerce the LLM into calling unauthorized tools.

```python
# packages/copilot/src/copilot/providers/tool_validation.py (lines 26-107)
class ExecuteSqlArgs(BaseModel):
    sql: str = Field(default="all", description="SQL to run")

class ExplainQueryArgs(BaseModel):
    sql: str = Field(..., description="SQL query to explain")
    analyze: bool = Field(default=False, description="...")
    hypothetical_indexes: list[dict[str, Any]] = Field(default=[], description="...")

TOOL_SCHEMAS: Dict[str, type[BaseModel]] = {
    "execute_sql": ExecuteSqlArgs,
    "list_schemas": ListSchemasArgs,
    "list_objects": ListObjectsArgs,
    "get_object_details": GetObjectDetailsArgs,
    "explain_query": ExplainQueryArgs,
    "add_comment_to_object": AddCommentToObjectArgs,
    "analyze_workload_indexes": AnalyzeWorkloadIndexesArgs,
    "analyze_query_indexes": AnalyzeQueryIndexesArgs,
    "analyze_db_health": AnalyzeDbHealthArgs,
    "get_top_queries": GetTopQueriesArgs,
}
ALLOWED_TOOLS: Set[str] = set(TOOL_SCHEMAS.keys())
```

#### MCP Session Reconnection

The provider detects session failures during tool execution and automatically reconnects, creating a new MCP session.

```python
# packages/copilot/src/copilot/providers/mcp_direct.py (lines 954-968)
except Exception as e:
    error_msg = str(e)
    error_type = type(e).__name__
    if "Session terminated" in error_msg or "404" in error_msg or "ClosedResourceError" in error_type:
        logger.warning(f"MCP session terminated, attempting to reconnect and retry {tool_name}...")
        try:
            await self._reconnect_mcp()  # Calls initialize() to create new session
            tool_result = await asyncio.wait_for(
                self.mcp_session.call_tool(tool_name, tool_args),
                timeout=300.0
            )
        except Exception as reconnect_error:
            tool_result = {"error": f"Tool '{tool_name}' failed after reconnection: {str(reconnect_error)}"}
```

#### MCP Server Security Configuration

pg-airman-mcp runs in `restricted` access mode with a read-only PostgreSQL user, providing database-level defense-in-depth alongside the application-level tool validation.

```yaml
# helm/pg-airman-mcp/values.yaml (lines 5-18)
postgres:
  host: pgvector-0.pgvector-postgres-service
  port: 5432
  user: mcp_readonly  # Read-only user created by load_data.py
mcp:
  accessMode: restricted  # Read-only, suitable for production
  allowCommentInRestricted: false
  transport: streamable-http
  port: 8000
```

### Prompt / Chain Patterns

MCP tools are presented to the LLM as standard function definitions. The LLM selects tools based on the user's query and the tool descriptions discovered from the MCP server. In MCP-Direct mode, the system prompt includes explicit tool-specific guidelines (e.g., "explain_query: Pass ONLY the SELECT query, always use analyze=false"). In Llama Stack mode, the prompt adds Llama Stack-specific tool calling rules ("use empty braces {} for no-parameter calls", "only ONE tool call at a time").

### Gotchas

- The MCP-Direct provider appends `"/mcp"` to the configured URL (line 114 of `mcp_direct.py`) for streamable-http transport, while the Llama Stack provider appends `"/sse"` (line 103 of `llama_stack.py`) for SSE transport fallback. If the Llama Stack server's tool_runtime provider already has the MCP endpoint configured, the SSE fallback is not used.
- Tool validation via the allowlist and Pydantic schemas is only active in MCP-Direct mode. The Llama Stack mode delegates tool execution entirely to Llama Stack, which does not perform equivalent validation. This means a prompt injection attack could potentially call unauthorized tools when running in Llama Stack mode.
- The persistent MCP session uses the MCP SDK's `streamablehttp_client` and `ClientSession` context managers, but stores the context managers as instance attributes (lines 214-218 of `mcp_direct.py`) rather than using `async with` blocks. This is necessary to keep the connection alive across requests, but cleanup depends on the application shutdown handler calling `__aexit__` manually (lines 1025-1032).
- `check_mcp_server_tools()` (lines 206-239 of `tool_validation.py`) runs at startup and only logs warnings when the MCP server advertises tools not in the allowlist. It does not block startup or remove the unknown tools -- they are rejected at call time by `validate_tool_name()`.
- pg-airman-mcp uses a read-only PostgreSQL user (`mcp_readonly`) for defense-in-depth. Even if the tool validation is bypassed, the database user cannot modify data or schema. The `accessMode: restricted` configuration (line 14 of `pg-airman-mcp/values.yaml`) blocks `EXPLAIN ANALYZE` -- the system prompt instructs the LLM to always use `analyze=false`.
- The `_retry_mcp_operation` method (lines 156-206 of `mcp_direct.py`) uses exponential backoff (1s, 2s, 4s, 8s, 10s max) and is used both for initial connection (5 retries) and tool calls (2 retries). This handles Kubernetes pod startup ordering where pg-airman-mcp may not be ready when the backend starts.
- The pg-airman-mcp Helm chart supports multiple replicas (`replicas: 2` in `pg-airman-mcp/values.yaml`) but the MCP-Direct provider maintains a single persistent session to one pod. Session affinity is noted in the Helm chart comments but must be configured at the Kubernetes Service level.

---

## Approach D: LlamaStack Responses API Native MCP with Per-Request Auth Headers (from it-self-service-agent)

### When to Use

Use this approach when MCP servers are consumed via LlamaStack's Responses API native MCP tool type, where LlamaStack handles the MCP session lifecycle and tool execution internally. This approach suits scenarios where: multiple MCP servers wrap enterprise systems (ticketing, ITSM, HR), each request must carry per-user authorization headers (e.g., `AUTHORITATIVE_USER_ID` for user impersonation), the agent framework uses LlamaStack Responses API as the primary inference interface, MCP servers are configured per-agent in YAML rather than registered via an API, and OpenTelemetry tracing context needs to propagate across MCP tool calls.

### Differences from Approaches A, B, and C

| Aspect | Approach A (Multi-Framework MCP) | Approach B (MCP as Transport) | Approach C (Persistent Session) | Approach D (LlamaStack Native MCP) |
|--------|----------------------------------|-------------------------------|--------------------------------|-------------------------------------|
| MCP server count | Multiple, dynamically registered | Single, hardcoded via env var | Single, hardcoded via env var | Multiple, per-agent YAML config |
| Registration | LlamaStack toolgroups API | None | MCP-Direct: none; Llama Stack: toolgroup | None (MCP server URLs in agent YAML config) |
| Discovery | Kubernetes MCPServer CRDs + labeled Services | None | None | None (URLs configured per-agent in YAML) |
| Client library | LlamaStack native, langchain-mcp-adapters, httpx, CrewAI shims | Custom MCPClient (httpx) | MCP SDK (streamablehttp_client + ClientSession) | LlamaStack Responses API (delegates MCP to LlamaStack server) |
| Session lifecycle | Framework-managed or module-level cache | Per-query | Persistent (startup to shutdown) | Delegated to LlamaStack (per-request) |
| Tool visibility to LLM | LLM sees MCP tools directly | MCP hidden behind LangChain tools | LLM sees tools (converted to OpenAI format) | LLM sees MCP tools via LlamaStack Responses API |
| Tool security | Framework-managed registration | None | Hard-coded allowlist + Pydantic | LlamaStack-managed + per-request AUTHORITATIVE_USER_ID header |
| Auth propagation | Not built in | Not applicable | None (MCP-Direct has no auth headers) | Per-request headers: user ID, tracing context, service tokens |
| MCP server builder | External MCP servers | External Loki MCP server | External pg-airman-mcp | FastMCP with streamable-http transport |

### Data Flow

1. Agent configuration YAML lists MCP servers with `name` and `uri` (e.g., `snow` at `http://mcp-self-service-agent-snow:8000/mcp`)
2. During `create_response()`, the agent builds a tools array including MCP tool definitions with `type: "mcp"`, `server_label`, `server_url`, and per-request `headers`
3. Headers include `AUTHORITATIVE_USER_ID` (authenticated user's email), OpenTelemetry `traceparent`/`tracestate` (if tracing active), and `SERVICE_NOW_TOKEN` (if available)
4. The agent calls `self.async_llama_client.responses.create(input=messages, model=model, tools=tools_to_use)`
5. LlamaStack Responses API discovers available tools from the MCP server, presents them to the LLM, and executes tool calls as needed
6. MCP server receives tool call with headers, extracts user identity, and performs the operation (e.g., create ServiceNow ticket, get Zammad ticket info)
7. MCP server returns tool result to LlamaStack, which passes it back to the LLM for response synthesis

### Component Wiring

| From | To | Protocol | Purpose |
|------|----|----------|---------|
| Agent (responses_agent.py) | LlamaStack server | HTTP (AsyncLlamaStackClient) | Responses API with MCP tool definitions |
| LlamaStack server | MCP server (snow) | HTTP (streamable-http) | ServiceNow ticket operations |
| LlamaStack server | MCP server (zammad) | HTTP (streamable-http) | Zammad ticket management |
| MCP server (snow) | ServiceNow API / mock-service-now | HTTP | Laptop refresh ticket creation, employee lookup |
| MCP server (zammad) | Zammad REST API (via basher) | HTTP | Ticket tagging, state updates, customer lookup |

### Key Integration Points

#### Per-Agent MCP Server Configuration in YAML

Each agent's YAML configuration specifies which MCP servers are available, their URIs, and approval requirements.

```yaml
# agent-service/config/agents/laptop-refresh-agent.yaml (lines 8-16)
mcp_servers:
  - name: "snow"
    uri: "http://mcp-self-service-agent-snow:8000/mcp"
    require_approval: "never"
knowledge_bases: ["laptop-refresh"]
```

#### MCP Tool Definition with Per-Request Headers

The agent builds MCP tool definitions at runtime, injecting per-request headers for user authorization, tracing, and service token propagation.

```python
# agent-service/src/agent_service/langgraph/responses_agent.py (lines 216-265)
for server_config in mcp_server_configs:
    server_name = server_config.get("name")
    server_uri = server_config.get("uri")

    mcp_tool: Dict[str, Any] = {
        "type": "mcp",
        "server_label": server_name,
        "server_url": server_uri,
        "require_approval": server_config.get("require_approval", "never"),
    }

    tool_headers = {}
    if authoritative_user_id:
        tool_headers["AUTHORITATIVE_USER_ID"] = authoritative_user_id
    if tracingIsActive():
        inject(tool_headers)  # Inject traceparent/tracestate
    snow_api_key = os.environ.get("SERVICENOW_API_KEY")
    if snow_api_key:
        tool_headers["SERVICE_NOW_TOKEN"] = snow_api_key
    if tool_headers:
        mcp_tool["headers"] = tool_headers

    tools_to_use.append(mcp_tool)
```

#### Per-State MCP Tool Toggling

The YAML state machine configuration supports `uses_tools` and `uses_mcp_tools` flags per state, allowing states like intent classification to skip MCP tool calls (reducing latency) while processing states use full tool access.

```python
# agent-service/src/agent_service/langgraph/lg_flow_state_machine.py (lines 183-206)
if action_config:
    skip_all_tools = self._is_config_disabled(
        action_config.get("uses_tools", state_config.get("uses_tools", "yes")))
    skip_mcp_servers_only = self._is_config_disabled(
        action_config.get("uses_mcp_tools", state_config.get("uses_mcp_tools", "yes")))
```

#### FastMCP Server with Auth Header Extraction

MCP servers built with FastMCP extract the `AUTHORITATIVE_USER_ID` from request headers to perform user-scoped operations. The shared `mcp_common.headers.header_first` utility handles header extraction.

```python
# mcp-servers/snow/src/snow/server.py (lines 108-148)
@mcp.tool()
@trace_mcp_tool()
def open_laptop_refresh_ticket(
    employee_name: str, business_justification: str,
    servicenow_laptop_code: str, ctx: Context[Any, Any],
) -> str:
    """Open a ServiceNow laptop refresh ticket for an employee."""
    authoritative_user_id = _snow_authoritative_user_id_for_email(ctx)
    api_token = header_first(ctx, "SERVICE_NOW_TOKEN")
    # ... create ticket using ServiceNowClient with user's sys_id

# mcp-servers/zammad/src/zammad_mcp/server.py (lines 132-142)
def _authorize_ticket(ctx: Context[Any, Any]) -> tuple[str, int, int]:
    raw = header_first(ctx, "AUTHORITATIVE_USER_ID", "authoritative_user_id")
    email, ticket_id = parse_email_and_ticket_id(raw)
    cust_uid = assert_ticket_customer_matches_basher(ticket_id, email)
    return email, ticket_id, cust_uid
```

#### OpenTelemetry Tracing Propagation

Tracing context is propagated from the agent service to MCP servers via HTTP headers, enabling distributed tracing across the entire request path (agent -> LlamaStack -> MCP -> backend system).

```python
# agent-service/src/agent_service/langgraph/responses_agent.py (lines 246-255)
if tracingIsActive():
    inject(tool_headers)  # OpenTelemetry context propagation
    logger.debug("Injected tracing headers for MCP server",
                 server_name=server_name, header_keys=list(tool_headers.keys()))

# mcp-servers/mcp-common/src/mcp_common/tracing.py
# Shared tracing decorator for MCP tool functions
```

### Prompt / Chain Patterns

MCP tools are discovered and invoked by LlamaStack Responses API. The LLM receives tool definitions from the MCP servers (via LlamaStack's built-in MCP support) and decides when to call them based on the conversation context and the state machine prompt. The agent's YAML prompt explicitly instructs the LLM to use specific tools (e.g., "use the open_laptop_refresh_ticket tool to create the ticket", "use the get_employee_laptop_info tool to get the laptop information") and includes critical guardrails around tool usage (e.g., "CRITICAL: If an employee-info mcp server is unavailable, don't proceed").

The `allowed_tools` configuration in YAML states can restrict which tools are available in specific states, preventing tool calls during classification or validation states.

### Gotchas

- LlamaStack Responses API manages the MCP session lifecycle internally. The agent code never creates or manages MCP sessions directly -- it only provides the MCP server URL and headers in the tool definition. This simplifies the agent code but means the agent has no control over session reuse, timeouts, or reconnection behavior.
- The `AUTHORITATIVE_USER_ID` header format varies by MCP server: the ServiceNow MCP server strips a `-{digits}` suffix (for ticket flow format `email-ticketid`) via `re.sub(r"-\d+$", "", raw)` (line 28 of snow/server.py), while the Zammad MCP server parses the full `email-ticketid` format via `parse_email_and_ticket_id(raw)` (line 140 of zammad/server.py).
- MCP servers use the `@trace_mcp_tool()` decorator from `mcp_common.tracing` for OpenTelemetry span creation. This decorator reads the injected tracing headers to create child spans, enabling end-to-end distributed tracing from the agent service through LlamaStack to the MCP server.
- The ServiceNow MCP server supports request limits (`SERVICENOW_LAPTOP_REQUEST_LIMITS`) and duplicate avoidance (`SERVICENOW_LAPTOP_AVOID_DUPLICATES`) configured via environment variables (lines 40-71 of snow/server.py). These are validated at server startup and stored on the FastMCP app instance.
- The Zammad MCP server delegates actual ticket operations to a "basher" MCP client (`call_basher_tool` in basher_client.py), which calls a separate Zammad API wrapper. The `assert_ticket_customer_matches_basher` function (line 141 of zammad/server.py) verifies that the authenticated user owns the ticket before allowing operations.
- The `require_approval` field in MCP tool definitions is set to `"never"` in the agent YAML configs (line 15 of laptop-refresh-agent.yaml). LlamaStack Responses API uses this to determine whether to auto-execute tool calls or require user confirmation.
- Both MCP servers expose a `/health` endpoint (snow: line 102, zammad: line 127) for Kubernetes liveness/readiness probes. The FastMCP `custom_route` decorator is used for these non-MCP endpoints.
- The `dummy_parameter` argument in several Zammad MCP tools (e.g., `mark_as_agent_managed_laptop_refresh`, line 149 of zammad/server.py) exists because "validation fails unless there is at least one parameter" in the MCP tool definition.

---

## Approach E: Co-Deployed FastMCP with Startup Tool Caching (from multi-agent-loan-origination)

### When to Use

Use Approach E when MCP tools are pure-computation functions (no database access, no external API calls) co-deployed alongside the main application, and you want them cached at startup as LangChain StructuredTool instances for use in a single LangGraph agent. Best suited for cases where the MCP server is a functional boundary (separating risk calculations from agent logic) rather than an integration point with external systems. Supports optional secondary MCP servers (e.g., predictive ML model) with graceful degradation when unavailable.

### Differences from Approach A

- **Startup initialization, not dynamic registration**: The `MultiServerMCPClient` connects to MCP servers at app startup via `init_mcp_client()` in the FastAPI lifespan, not via a CRUD API or Kubernetes discovery.
- **Cached tools, not session-per-request**: Tools are loaded once via `get_tools()` and cached as a module-level list. All subsequent agent invocations use the same tool instances.
- **Single agent consumer**: Only the underwriter agent uses MCP tools, mixing them with native LangChain tools in one tool list. Other agents (public, borrower, loan officer, CEO) use only native tools.
- **Pure-computation MCP server**: The FastMCP server exposes risk assessment calculations (DTI, LTV, credit risk, income stability, asset sufficiency, recommendation) that take simple primitives and return JSON. No database access, no external API calls.
- **Graceful degradation for optional servers**: If the predictive model MCP server is unreachable, the client falls back to risk-assessment-only mode and logs a warning. The `is_predictive_model_available()` check lets the agent adapt its behavior.

### Data Flow

1. At FastAPI startup, `init_mcp_client()` creates a `MultiServerMCPClient` with the risk-assessment server URL (from `MCP_RISK_SERVER_URL`) and optionally the predictive model server URL (from `PREDICTIVE_MODEL_MCP_URL`)
2. The client connects to each MCP server via streamable-http transport and calls `get_tools()` to discover available tools
3. Tools are cached as LangChain `StructuredTool` instances in a module-level `_tools` list
4. When the underwriter agent graph is built, `get_mcp_tools()` returns the cached tools, which are combined with native tools and bound to the LLM via `llm.bind_tools(tools)`
5. During chat, the LLM emits tool calls for MCP tools (e.g., `calculate_dti`), LangGraph's `ToolNode` executes them via the cached StructuredTool instances, and results flow back to the agent
6. At shutdown, `shutdown_mcp_client()` clears the cached references

### Component Wiring

| From | To | Protocol | Purpose |
|------|----|----------|---------|
| FastAPI lifespan | MultiServerMCPClient | Python method call | Initialize MCP connections at startup |
| MultiServerMCPClient | FastMCP risk-assessment server | HTTP (streamable-http, port 8081) | Discover and load risk tools |
| MultiServerMCPClient | Predictive model MCP server (optional) | HTTP (streamable-http) | Discover and load ML prediction tool |
| Underwriter agent builder | mcp_integration module | Python method call | Get cached LangChain tools via `get_mcp_tools()` |
| LangGraph ToolNode | Cached StructuredTool instances | Python method call | Execute MCP tool calls from LLM |
| FastMCP server | risk_tools module | Python import | Reuse same computation logic as native tools |

### Key Integration Points

#### App-Startup MCP Client Initialization

The MCP client connects at app startup and caches tools. If the predictive model server is unreachable, it falls back to risk-assessment-only mode.

```python
# packages/api/src/agents/mcp_integration.py (lines 19-74)
_client: MultiServerMCPClient | None = None
_tools: list = []
_predictive_model_connected: bool = False

async def init_mcp_client(url, *, predictive_model_url=None):
    global _client, _tools, _predictive_model_connected
    servers = {"risk-assessment": {"transport": "streamable_http", "url": url}}
    if predictive_model_url:
        servers["predictive-model"] = {"transport": "streamable_http", "url": predictive_model_url}
    _client = MultiServerMCPClient(servers)
    try:
        _tools = await _client.get_tools()
        _predictive_model_connected = predictive_model_url is not None
    except Exception:
        if predictive_model_url:
            logger.warning("Predictive model MCP unreachable, continuing without it")
            _client = MultiServerMCPClient({"risk-assessment": {"transport": "streamable_http", "url": url}})
            _tools = await _client.get_tools()
            _predictive_model_connected = False
        else:
            raise

def get_mcp_tools() -> list:
    return list(_tools)
```

#### FastMCP Server with Pure-Computation Tools

The MCP server exposes six stateless risk assessment tools that take simple primitives and return JSON results. No database access -- all computation is self-contained.

```python
# packages/api/src/mcp_server.py (lines 11-22, 45-72)
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("risk-assessment", host="0.0.0.0", port=8081)

@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    return JSONResponse({"status": "healthy"})

@mcp.tool()
def calculate_dti(monthly_income: float, monthly_debts: float) -> str:
    """Calculate Debt-to-Income ratio and risk rating."""
    if monthly_income <= 0:
        return json.dumps({"value": None, "rating": None, "warning": "Missing or zero income"})
    dti_pct = round(monthly_debts / monthly_income * 100, 1)
    if dti_pct < 36:
        rating, guidance = "Low", "Well within conventional guidelines"
    elif dti_pct <= 43:
        rating, guidance = "Medium", "Within QM safe harbor limits"
    else:
        rating, guidance = "High", "Exceeds QM safe harbor; requires compensating factors"
    return json.dumps({"value": dti_pct, "rating": rating, "guidance": guidance})
```

#### Underwriter Agent Combining Native and MCP Tools

The underwriter agent builder loads MCP tools and concatenates them with native LangChain tools to form the complete tool list.

```python
# packages/api/src/agents/underwriter_assistant.py (lines 38-70)
def build_graph(config, checkpointer=None):
    native_tools = [
        current_date, product_info, affordability_calc,
        uw_queue_view, uw_application_detail, uw_save_risk_assessment,
        uw_predict_loan_approval, uw_preliminary_recommendation,
        compliance_check, kb_search,
        uw_issue_condition, uw_review_condition, uw_clear_condition,
        uw_waive_condition, uw_return_condition, uw_condition_summary,
        uw_render_decision, uw_draft_adverse_action,
        uw_generate_le, uw_generate_cd,
    ]
    mcp_tools = get_mcp_tools()
    all_tools = native_tools + mcp_tools
    return build_agent_graph(config, all_tools, checkpointer=checkpointer)
```

### Gotchas

- The MCP server and the main API server share the same codebase (the MCP server imports `risk_tools` from the agents package). The MCP server runs as a separate process (`mcp.run(transport="streamable-http")` in `__main__`) on port 8081, while the main API runs on port 8000. In container deployments, they run as separate containers.
- The `MultiServerMCPClient` from `langchain-mcp-adapters` connects at startup and caches tools. If the MCP server restarts after initial connection, the cached tools may become stale. There is no reconnection or health-check logic in the client.
- The `/health` endpoint on the MCP server uses `@mcp.custom_route("/health", methods=["GET"])` because MCP's `/mcp` endpoint only accepts POST and returns 406 on GET, making it unsuitable for Kubernetes liveness/readiness probes (line 25-26 of `mcp_server.py`).
- The `get_predictive_tool()` function searches the cached tools list by name (`"check_loan_approval"`) to return a specific tool instance. If the predictive model server changes its tool name, this lookup silently returns `None`.
- All six MCP tools return JSON strings (via `json.dumps()`), not structured objects. The LLM must parse the JSON from the tool result to extract values for downstream tool calls (e.g., passing `dti_rating` from `calculate_dti` to `generate_risk_recommendation`).
- The `generate_risk_recommendation` MCP tool is the integration point that aggregates all five individual risk assessments plus the optional ML prediction into a final recommendation (Approve, Approve with Conditions, Suspend, or Deny). The agent's system prompt instructs it to call all six tools in a specific sequence before presenting results.

### Related Architectures

- [agent-orchestration](agent-orchestration.md) -- The MCP tools are injected into the underwriter agent, which is one of five persona-specific LangGraph agents
- [guardrails-layer](guardrails-layer.md) -- Safety shields in the graph run before and after tool execution, including MCP tool calls

---

## Choosing Between Approaches

| Criteria | Approach A (Multi-Framework MCP) | Approach B (MCP as Transport Layer) | Approach C (Persistent Session + Validation) | Approach D (LlamaStack Native MCP) | Approach E (Co-Deployed FastMCP + Startup Cache) |
|----------|----------------------------------|-------------------------------------|---------------------------------------------|-------------------------------------|--------------------------------------------------|
| Number of MCP servers | Multiple, dynamically added | Single, known at deploy time | Single, known at deploy time | Multiple, per-agent YAML config | 1-2, known at deploy time (risk + optional prediction) |
| Registration/discovery | LlamaStack API + Kubernetes CRDs/Services | Environment variable only | Env var (MCP-Direct) or toolgroup registration (Llama Stack) | None (URLs in agent YAML config) | Environment variable only (MCP_RISK_SERVER_URL) |
| Agent framework | Multiple (LlamaStack, LangGraph, CrewAI) | LangChain tools inside LangGraph | MCP-Direct (custom loop) or Llama Stack (delegated) | LlamaStack Responses API (delegated) | LangGraph only (tools as LangChain StructuredTool) |
| MCP visibility to LLM | LLM sees MCP tools directly | MCP hidden behind LangChain tools | LLM sees MCP tools directly (converted to OpenAI format) | LLM sees MCP tools via LlamaStack Responses API | LLM sees MCP tools directly (as LangChain StructuredTool) |
| Session management | Framework-managed or cached at module level | Per-query (create, use, dispose) | Persistent (startup to shutdown) with auto-reconnection | Delegated to LlamaStack (per-request) | Startup initialization, cached for app lifetime |
| Tool security | Framework-managed registration | None | Hard-coded allowlist + Pydantic schema validation | LlamaStack-managed + per-request auth headers | YAML-configured per-tool allowed_roles (RBAC via graph node) |
| Auth propagation | Not built in | Not applicable | None | Per-request: AUTHORITATIVE_USER_ID, tracing headers, service tokens | Not applicable (tools are pure computation, no user context needed) |
| MCP client library | Various (LlamaStack native, langchain-mcp-adapters, httpx, CrewAI shims) | Custom MCPClient (httpx) | MCP SDK (streamablehttp_client + ClientSession) | None (LlamaStack handles MCP protocol) | langchain-mcp-adapters (MultiServerMCPClient) |
| Use case | Extensible tool platform with UI management | Fixed integration with specific backend service | Data governance copilot with security-first tool access | Multi-agent IT service automation with per-user tool authorization | Risk assessment computation separated from agent logic with optional ML model |
| Complexity | Higher (registration API, discovery, multi-framework) | Lower (single client, single server, no management layer) | Moderate (persistent session, validation layer, dual provider) | Lower (LlamaStack handles MCP, agent only provides URLs and headers) | Lower (startup init, cached tools, single consumer agent) |
