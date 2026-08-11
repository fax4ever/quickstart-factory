---
name: mcp-tool-integration
description: MCP server registration, discovery, and runtime tool execution across agent frameworks
summary: "Integrates MCP tool servers into a multi-framework agent system through three layers: registration via LlamaStack toolgroups API (`POST /api/v1/mcp_servers/`, provider `model-context-protocol`), Kubernetes-native discovery from ToolHive MCPServer CRDs and labeled Services (`GET /api/v1/mcp_servers/discover`, label `app.kubernetes.io/component=mcp-server`), and per-runner execution that streams `tool_call` SSE events to the frontend. Four runtime paths -- LlamaStack runner resolves `mcp::` prefixed toolgroup IDs into Responses API definitions for native execution; LangGraph ReAct uses `langchain-mcp-adapters` MultiServerMCPClient; GraphEngine calls MCP directly via JSON-RPC with deterministic (non-LLM) node invocation; CrewAI is a local shim mapping server names to hardcoded tool classes via `_TOOL_CLASS_BY_NAME` and `_SERVER_TOOL_NAME_HINTS`, requiring code changes for new server types. MCP servers are registered with `mcp_endpoint={\"uri\": url}` and built with FastMCP using `transport=\"streamable-http\"`; Kubernetes discovery is namespace-scoped with transport type set by `mcp.transport` label (default streamable-http, appending `/mcp` to URL). GraphEngine maintains module-level `_MCP_SESSIONS` and `_TOOL_SCHEMAS` caches that refresh on 400/404 responses containing \"session\"; `_filter_args_to_schema` drops extra template-rendered arguments to prevent JSON-RPC -32602 (invalid params) errors; CrewAI MCP support is not native and requires entries in both mapping tables for each new tool type."
metadata:
  type: architecture
tags:
  tech_stack: [fastapi, llamastack, langchain, python, httpx]
  ai_pattern: [agents, model-serving]
  platform: [llamastack, rhoai, openshift, kubernetes]
  data_layer: []
source_examples:
  - quickstart: "ai-virtual-agent"
    repo: "https://github.com/rh-ai-quickstart/ai-virtual-agent"
    notes: "MCP tool servers (travel research, hotel, flight) registered via LlamaStack toolgroups API, discovered from Kubernetes, and executed across LlamaStack, LangGraph, and CrewAI runners"
    approach: "A"
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
