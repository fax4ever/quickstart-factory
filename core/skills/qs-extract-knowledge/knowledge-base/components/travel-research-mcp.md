---
name: travel-research-mcp
description: "MCP server wrapping Tavily web search API for travel research, used by agentic vacation planner"
summary: "Wraps Tavily web search API as a FastMCP streamable-http MCP server (`/mcp` endpoint) exposing `tavily_travel_search` to LangGraph (via `mcp_tool_map` fan-out node) and CrewAI agent orchestrators in the ai-virtual-agent quickstart. Use when an agentic vacation planner needs web research via MCP protocol -- follows the identical FastMCP pattern as sibling hotel_mcp and flight_mcp servers, all deployed via the `mcp-servers` Helm subchart from ai-architecture-charts with `mcp>=1.26.0`. Critical config: TAVILY_API_KEY injected via Kubernetes secret on-cluster, port defaults to 8000 (Helm) but overridden to 7001 in compose with env-var fallback `${TRAVEL_RESEARCH_MCP_URL:http://localhost:7001/mcp}`, and external API calls use tuple-style timeout `(10, 30)`. Gotchas: `raise_for_status()` runs outside try/except so non-timeout HTTP errors (e.g. 401) raise unhandled HTTPError instead of a user-friendly string, no Containerfile HEALTHCHECK (compose compensates with socket check), image name `mcp-travel-research` is derived from directory `travel_research_mcp` by stripping `_mcp` suffix and must match Helm `image.repository`, and tool returns structured text not JSON so downstream agents parse as natural language."
metadata:
  type: component
tags:
  tech_stack: [python, fastmcp, requests]
  ai_pattern: [agents, mcp]
  platform: [openshift, rhoai]
source_examples:
  - quickstart: "ai-virtual-agent"
    repo: "https://github.com/rh-ai-quickstart/ai-virtual-agent"
    notes: "Streamable-HTTP MCP server exposing Tavily web search as a tool for LangGraph and CrewAI vacation planner agents"
    approach: "A"
---

# Travel Research MCP Server

## Overview

A lightweight MCP (Model Context Protocol) server that wraps the Tavily web search API, exposing a `tavily_travel_search` tool to AI agents. In the ai-virtual-agent quickstart it serves as one of three MCP servers (alongside hotel and flight) consumed by both LangGraph and CrewAI agent orchestrators. It uses the `streamable-http` transport and runs as a standalone container deployed via the `mcp-servers` Helm subchart from ai-architecture-charts.

## Tech Stack & Dependencies

- **Runtime:** Python 3.11 (python:3.11-slim base image)
- **Container image:** `quay.io/rh-ai-quickstart/mcp-travel-research`
- **Key dependencies:** `mcp>=1.26.0` (FastMCP framework), `requests` (HTTP client for Tavily API)
- **Helm subchart:** `mcp-servers` v0.5.15 from `https://rh-ai-quickstart.github.io/ai-architecture-charts`

## Key Patterns

### FastMCP Server Initialization

The server uses FastMCP with host/port configurable via environment variables, defaulting to `0.0.0.0:8000`:

```python
# mcp_servers/travel_research_mcp/server.py
mcp = FastMCP(
    "travel_research_mcp",
    host=os.getenv("HOST", "0.0.0.0"),
    port=int(os.getenv("PORT", "8000")),
)
```

### Tool Registration via Decorator

Tools are registered with the `@mcp.tool()` decorator. The tool gracefully handles a missing API key by returning a user-friendly string rather than raising an exception:

```python
# mcp_servers/travel_research_mcp/server.py
@mcp.tool()
def tavily_travel_search(query: str, max_results: int = 5) -> str:
    """Search the web for travel information about a destination or theme."""
    api_key = os.getenv("TAVILY_API_KEY")
    if not api_key:
        return "TAVILY_API_KEY is not set. Provide it to enable web research."
```

### Streamable-HTTP Transport

The server runs with `streamable-http` transport (not SSE), which is the newer MCP transport mode:

```python
# mcp_servers/travel_research_mcp/server.py
if __name__ == "__main__":
    mcp.run(transport="streamable-http")
```

### Explicit Timeout Tuning on External API Calls

The Tavily API call uses a tuple-style timeout with separate connect and read timeouts, and wraps both `Timeout` and generic `RequestException` errors:

```python
# mcp_servers/travel_research_mcp/server.py
response = requests.post(
    "https://api.tavily.com/search",
    json={...},
    timeout=(10, 30),  # (connect_timeout, read_timeout)
)
```

### Agent Template Integration (LangGraph)

The backend agent templates reference this MCP server by name and wire the tool into an `mcp_tool_map` node that fans out queries across a list of places:

```yaml
# backend/agent_templates/travel_vacation_planner.yaml
- id: destination_research_task
  type: mcp_tool_map
  server: travel_research
  tool: tavily_travel_search
  items_path: outputs.places_list_task
  max_items: 5
  query_template: "Research {item} in {inputs.destination}..."
```

### Agent Template Integration (CrewAI)

In the CrewAI variant, the same MCP server is assigned as a tool to the `destination_researcher` agent role:

```yaml
# backend/agent_templates/travel_vacation_planner_crewai.yaml
agents:
  destination_researcher:
    role: Travel Research Specialist
    tools:
      - travel_research
```

## Configuration

- **Environment variables:**
  - `TAVILY_API_KEY` -- Required. The API key for Tavily search. Gracefully returns an error string if unset.
  - `HOST` -- Listen address (default: `0.0.0.0`)
  - `PORT` -- Listen port (default: `8000`, overridden to `7001` in local compose)
- **Helm values:** The backend pod receives the MCP URL via `mcp.travel_research_url` which defaults to `http://mcp-travel-research:8000/mcp`. On the cluster, the API key is injected via a Kubernetes secret (`TAVILY_API_KEY` in `secretKeyRef`).
- **Compose config:** In local dev, the service runs on port `7001` and the backend connects via `TRAVEL_RESEARCH_MCP_URL` environment variable defaulting to `http://localhost:7001/mcp`.

## Known Gotchas

- **Port mismatch between local and cluster:** The Helm subchart defaults to port `8000` while the compose file overrides to `7001`. The agent templates use env-var expansion with a localhost fallback (`${TRAVEL_RESEARCH_MCP_URL:http://localhost:7001/mcp}`), so the local port must match the compose port assignment.
- **`raise_for_status()` after exception handling:** The code catches `Timeout` and `RequestException` early with graceful returns, but `response.raise_for_status()` on line 43 runs outside those try/except blocks. A non-timeout HTTP error (e.g., 401 from a bad API key) would raise an unhandled `HTTPError` instead of returning a user-friendly string.
- **Minimal Containerfile -- no healthcheck:** The Containerfile has no `HEALTHCHECK` instruction; the compose file compensates with a socket-based healthcheck (`python -c "import socket; s=socket.create_connection(('localhost',7001),2); s.close()"`).
- **Image naming convention:** The Makefile build target transforms the directory name `travel_research_mcp` into the image name `mcp-travel-research` by stripping the `_mcp` suffix and replacing underscores with hyphens. This naming must stay consistent with the Helm values `image.repository`.

## Testing Notes

- Verify the MCP server responds on its `/mcp` endpoint (the `streamable-http` transport path).
- The compose healthcheck uses a raw TCP socket check rather than an HTTP check -- confirming the port is open does not confirm the MCP protocol handler is functioning.
- The tool returns structured text (formatted list of results), not JSON -- downstream agents parse it as natural language.

## Related Patterns

- Other MCP servers in this quickstart follow the identical FastMCP pattern (hotel_mcp, flight_mcp) but wrap different external APIs (SerpAPI for hotels, SerpAPI for flights).
- The `mcp-servers` Helm subchart from ai-architecture-charts handles Deployment, Service, and optional Secret creation for each MCP server.
