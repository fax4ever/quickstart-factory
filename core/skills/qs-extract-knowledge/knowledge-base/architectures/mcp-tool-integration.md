---
name: mcp-tool-integration
description: MCP tool integration from multi-framework registration and discovery to single-server transport layer
summary: "Integrates MCP tool servers into agent systems via two approaches: Approach A (ai-virtual-agent) provides multi-framework registration via LlamaStack toolgroups API (`POST /api/v1/mcp_servers/`, provider `model-context-protocol`), Kubernetes-native discovery from ToolHive MCPServer CRDs and Services labeled `app.kubernetes.io/component=mcp-server`, and four runtime paths (LlamaStack resolves `mcp::` prefixed toolgroup IDs into Responses API definitions, LangGraph ReAct uses `langchain-mcp-adapters` MultiServerMCPClient, GraphEngine calls MCP directly via JSON-RPC with deterministic non-LLM node invocation, CrewAI maps server names to hardcoded classes via `_TOOL_CLASS_BY_NAME`/`_SERVER_TOOL_NAME_HINTS`), while Approach B (ansible-log-analysis) hides MCP inside LangChain `@tool` functions as a transport layer for a single Loki server configured via `LOKI_MCP_SERVER_URL` env var with per-query httpx `MCPClient` session lifecycle and tool result caching via `_store_tool_result` returning lightweight `result_id` references. Choose Approach A for extensible multi-server platforms needing dynamic Kubernetes discovery, UI management, and multi-framework support producing `tool_call` SSE events; choose Approach B for single fixed-server integrations where MCP is invisible to the LLM, using `Mcp-Session-Id`-based sessions, `MAX_LOGS_PER_QUERY` (5000) caps, and closure-bound tool creation via `create_log_lines_above_tool`. MCP servers are registered with `mcp_endpoint={\"uri\": url}` and built with FastMCP using `transport=\"streamable-http\"`; Kubernetes discovery is namespace-scoped with transport type set by `mcp.transport` label (default streamable-http, appending `/mcp` to URL); Approach B wraps all MCP calls inside `execute_loki_query()` which creates a new `MCPClient` per invocation with JSON-RPC initialize handshake. GraphEngine maintains module-level `_MCP_SESSIONS` and `_TOOL_SCHEMAS` caches that refresh on 400/404 responses containing \"session\"; `_filter_args_to_schema` drops extra template-rendered arguments to prevent JSON-RPC -32602 (invalid params) errors; CrewAI MCP is not native and requires entries in both mapping tables for each new tool type; Approach B creates new `MCPClient` and `httpx.AsyncClient` per query with no connection pooling."
metadata:
  type: architecture
tags:
  tech_stack: [fastapi, llamastack, langchain, langgraph, python, httpx]
  ai_pattern: [agents, model-serving]
  platform: [llamastack, rhoai, openshift, kubernetes]
  data_layer: []
source_examples:
  - quickstart: "ai-virtual-agent"
    repo: "https://github.com/rh-ai-quickstart/ai-virtual-agent"
    notes: "MCP tool servers (travel research, hotel, flight) registered via LlamaStack toolgroups API, discovered from Kubernetes, and executed across LlamaStack, LangGraph, and CrewAI runners"
    approach: "A"
  - quickstart: "ansible-log-analysis"
    repo: "https://github.com/rh-ai-quickstart/ansible-log-analysis"
    notes: "Custom MCP client for Loki log queries, embedded inside LangChain tools as a query transport layer within a LangGraph agent subgraph"
    approach: "B"
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

## Choosing Between Approaches

| Criteria | Approach A (Multi-Framework MCP) | Approach B (MCP as Transport Layer) |
|----------|----------------------------------|-------------------------------------|
| Number of MCP servers | Multiple, dynamically added | Single, known at deploy time |
| Registration/discovery | LlamaStack API + Kubernetes CRDs/Services | Environment variable only |
| Agent framework | Multiple (LlamaStack, LangGraph, CrewAI) | LangChain tools inside LangGraph |
| MCP visibility to LLM | LLM sees MCP tools directly | MCP hidden behind LangChain tools |
| Session management | Framework-managed or cached at module level | Per-query (create, use, dispose) |
| Use case | Extensible tool platform with UI management | Fixed integration with specific backend service |
| Complexity | Higher (registration API, discovery, multi-framework) | Lower (single client, single server, no management layer) |
