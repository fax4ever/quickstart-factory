---
name: hotel-mcp
description: "MCP server wrapping SerpApi Google Hotels for agent-driven hotel search in agentic travel apps"
summary: "MCP server (Python 3.11, FastMCP, streamable-http transport) wrapping SerpApi Google Hotels API as a google_hotels_search tool for agent-driven hotel search, running alongside sibling flight-mcp and travel-research-mcp in the ai-virtual-agent quickstart. Dual implementation exists: MCP server with retry logic (appends \"hotels\" to empty queries) and timeout tuning (10, 30) vs. CrewAI BaseTool (GoogleHotelsTool) with budget field and richer markdown formatting -- use MCP when consumed via URL by agent orchestration templates, CrewAI when embedded directly. Deployed via mcp-servers Helm subchart (deploymentMode: deployment); SERPAPI_API_KEY required, backend discovers server via HOTEL_MCP_URL env var substituted into agent templates, results capped at 6 properties via properties[:6] to keep LLM context manageable. Port mismatch between local compose (7002) and cluster Helm (8000) requires correct HOTEL_MCP_URL; SerpApi response key varies between \"properties\" and \"hotels\" needing defensive dual-key lookup; healthcheck uses raw socket since streamable-http lacks an HTTP health route."
metadata:
  type: component
tags:
  tech_stack: [python, mcp, fastmcp, serpapi, requests]
  ai_pattern: [agents, mcp-server]
  platform: [openshift]
  data_layer: []
source_examples:
  - quickstart: "ai-virtual-agent"
    repo: "https://github.com/rh-ai-quickstart/ai-virtual-agent"
    notes: "Standalone MCP server exposing google_hotels_search tool via streamable-http transport"
    approach: "A"
---

# Hotel MCP Server

## Overview

A lightweight MCP (Model Context Protocol) server that wraps the SerpApi Google Hotels API, exposing a `google_hotels_search` tool for agent-driven hotel search. In the ai-virtual-agent quickstart it runs as a standalone containerized service alongside sibling MCP servers (flight, travel research) and is consumed by the backend's agent orchestration layer via streamable-http transport.

## Tech Stack & Dependencies

- **Runtime:** Python 3.11 (python:3.11-slim base image)
- **Container image:** `quay.io/rh-ai-quickstart/mcp-hotel`
- **Key dependencies:** `mcp>=1.26.0` (FastMCP framework), `requests` (HTTP client for SerpApi)
- **Helm subchart:** Deployed via an `mcp-servers` subchart entry in the main Helm chart

## Key Patterns

### FastMCP Server Initialization

The server uses `FastMCP` from the `mcp` library, binding host and port from environment variables with sensible defaults:

```python
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "hotel_mcp",
    host=os.getenv("HOST", "0.0.0.0"),
    port=int(os.getenv("PORT", "8000")),
)
```

Source: `mcp_servers/hotel_mcp/server.py`, lines 11-15.

### MCP Tool Registration

A single tool `google_hotels_search` is registered using the `@mcp.tool()` decorator, following a convention shared with the sibling flight and travel research MCP servers:

```python
@mcp.tool()
def google_hotels_search(
    destination: str,
    start_date: str,
    end_date: str,
    adults: int = 2,
    preferences: str = "",
) -> str:
    """Find hotel options for a destination and date range using SerpApi Google Hotels."""
```

Source: `mcp_servers/hotel_mcp/server.py`, lines 18-26.

### Streamable-HTTP Transport

The server runs with `streamable-http` transport (not SSE or stdio), which is a consistent choice across all three MCP servers in this quickstart:

```python
if __name__ == "__main__":
    mcp.run(transport="streamable-http")
```

Source: `mcp_servers/hotel_mcp/server.py`, lines 102-103.

### SerpApi Retry with Query Augmentation

When the initial query returns no hotel properties, the server retries by appending "hotels" to the search query. It also handles the SerpApi response key inconsistency (`properties` vs `hotels`):

```python
properties = data.get("properties") or data.get("hotels") or []
if not properties:
    retry_params = dict(params)
    retry_params["q"] = f"{query} hotels"
    try:
        data = _fetch(retry_params)
    except RuntimeError as exc:
        return str(exc)
    properties = data.get("properties") or data.get("hotels") or []
```

Source: `mcp_servers/hotel_mcp/server.py`, lines 76-84.

### Dual Implementation: MCP Tool and CrewAI Tool

The hotel search functionality exists in two forms: (1) as the MCP server tool shown above, and (2) as a `GoogleHotelsTool` CrewAI `BaseTool` in the backend at `backend/app/lib/agent_tools/google_hotel_tool.py`. The CrewAI version includes an additional `budget` field and slightly richer formatting (markdown bold, amenities) but shares the same SerpApi integration. The MCP version adds timeout tuning `(10, 30)` and retry logic that the CrewAI version lacks.

Source: `backend/app/lib/agent_tools/google_hotel_tool.py`, lines 20-86.

## Configuration

- **Environment variables:**
  - `SERPAPI_API_KEY` — Required. SerpApi key for Google Hotels engine. Gracefully returns an error string if unset.
  - `HOST` — Bind address, defaults to `0.0.0.0`.
  - `PORT` — Listen port, defaults to `8000` in code. Overridden to `7002` in local compose, `8000` in cluster Helm.
  - `HOTEL_MCP_URL` — Set on the backend pod (not on hotel-mcp itself) to wire agent templates to this server. Defaults to `http://localhost:7002/mcp` locally, `http://mcp-hotel:8000/mcp` in cluster.
- **Config files:** None; all configuration is via environment variables.
- **Helm values:**
  ```yaml
  mcp:
    hotel_url: "http://mcp-hotel:8000/mcp"
  # Under mcp-servers subchart:
  servers:
    hotel:
      enabled: true
      deploymentMode: deployment
      image:
        repository: quay.io/rh-ai-quickstart/mcp-hotel
        tag: "latest"
      transport: streamable-http
      port: 8000
      targetPort: 8000
  ```
  Source: `deploy/cluster/helm/values.yaml`, lines 136-263.

## Known Gotchas

- **SerpApi response key varies:** The API returns hotel results under either `properties` or `hotels` depending on the query. The code defensively checks both: `data.get("properties") or data.get("hotels") or []`. This is found in both the MCP server and the CrewAI tool. (Source: `mcp_servers/hotel_mcp/server.py`, line 76)
- **Port mismatch between local and cluster:** The compose file assigns port `7002` for local dev, while the Helm chart uses port `8000`. The `HOTEL_MCP_URL` env var on the backend must match accordingly. (Source: `deploy/local/compose.yaml` vs `deploy/cluster/helm/values.yaml`)
- **Results capped at 6:** Both the MCP and CrewAI implementations hard-limit output to 6 hotel properties via `properties[:6]`, which is a design choice to keep LLM context manageable. (Source: `mcp_servers/hotel_mcp/server.py`, line 92)
- **Healthcheck uses raw socket, not HTTP:** The compose healthcheck uses a Python socket connection test rather than an HTTP health endpoint, because the MCP streamable-http transport does not expose a standard HTTP health route. (Source: `deploy/local/compose.yaml`)

## Testing Notes

- Verify the server starts by checking the socket-based healthcheck passes (port `7002` locally, `8000` in cluster).
- Requires a valid `SERPAPI_API_KEY` for functional testing; without it, the tool returns a descriptive error string rather than failing.
- Test the retry logic by searching for a generic destination that may not return results on the first query.

## Related Patterns

- Sibling MCP servers (`flight-mcp`, `travel-research-mcp`) follow the same FastMCP + streamable-http pattern.
- The backend wires MCP server URLs into agent templates via environment variable substitution (e.g., `${HOTEL_MCP_URL:http://localhost:7002/mcp}` in `backend/agent_templates/travel_vacation_planner.yaml`).
