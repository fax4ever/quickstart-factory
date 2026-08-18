---
name: flight-mcp
description: "MCP server exposing IATA lookup and Google Flights search via SerpApi for agentic travel planning"
summary: "Exposes iata_lookup and google_flights_search as MCP tools via FastMCP streamable-http transport, enabling LangGraph/CrewAI agent pipelines in the ai-virtual-agent quickstart to integrate SerpApi-powered flight data into multi-step vacation planning workflows. Use when building agentic travel planning that needs flight search as an mcp_tool YAML node type with depends_on sequencing and args field mapping; follows the same FastMCP + streamable-http + Helm mcp-servers subchart pattern as sibling hotel_mcp and travel_research_mcp servers. IATA resolution uses three-tier fallback (hardcoded 30-city map, regex extraction, SerpApi locations API with progressive query refinement) and _coerce_list defensively parses LLM-generated tool arguments from JSON arrays, markdown bullets, or comma-separated strings; deployed as python:3.11-slim container via mcp-servers subchart with deploymentMode: deployment and SERPAPI_API_KEY injected from Kubernetes secret. Port mismatch between local compose (PORT=7003) and cluster Helm (8000) requires matching FLIGHT_MCP_URL, google_flights_search silently caps destinations to 2 (first and last from parsed list), SerpApi timeouts are hardcoded (10/20s locations, 10/30s flights), and raw-socket healthcheck can report false-positive readiness during startup."
metadata:
  type: component
tags:
  tech_stack: [python, mcp, requests, fastmcp]
  ai_pattern: [agents, mcp-tools]
  platform: [openshift]
  data_layer: []
source_examples:
  - quickstart: "ai-virtual-agent"
    repo: "https://github.com/rh-ai-quickstart/ai-virtual-agent"
    notes: "Flight MCP server providing IATA resolution and Google Flights search as tools for LangGraph/CrewAI vacation planner agents"
    approach: "A"
---

# Flight MCP Server

## Overview

A lightweight MCP (Model Context Protocol) server that exposes flight search capabilities as tools consumable by AI agents. It provides two tools -- `iata_lookup` for resolving city names to IATA airport codes, and `google_flights_search` for querying round-trip flight options via SerpApi's Google Flights engine. In the ai-virtual-agent quickstart, the backend's LangGraph and CrewAI agent pipelines connect to this server over streamable-http transport to integrate flight data into multi-step vacation planning workflows.

## Tech Stack & Dependencies

- **Runtime:** Python 3.11 (python:3.11-slim base image)
- **Container image:** `quay.io/rh-ai-quickstart/mcp-flight:latest`
- **Key dependencies:** `mcp>=1.26.0` (FastMCP framework), `requests` (HTTP client for SerpApi)
- **Helm subchart:** Deployed via `mcp-servers` subchart with `deploymentMode: deployment`

## Key Patterns

### FastMCP Server Bootstrap

The server uses the `FastMCP` class from the `mcp` library to register tools and run as a streamable-http endpoint. Host and port are configured via environment variables with sensible defaults.

```python
# mcp_servers/flight_mcp/server.py (lines 8, 13-17)
from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "flight_mcp",
    host=os.getenv("HOST", "0.0.0.0"),
    port=int(os.getenv("PORT", "8000")),
)
```

The server entrypoint explicitly selects the `streamable-http` transport:

```python
# mcp_servers/flight_mcp/server.py (lines 323-324)
if __name__ == "__main__":
    mcp.run(transport="streamable-http")
```

### IATA Resolution with Layered Fallback

Airport code resolution uses a three-tier strategy: first a hardcoded city-to-IATA map (30 major cities), then regex extraction for codes already in the input, and finally a SerpApi locations API lookup with progressive query refinement.

```python
# mcp_servers/flight_mcp/server.py (lines 133-170)
def _resolve_airport_code(value: str, api_key: str) -> str:
    value = _extract_first_location(value)
    known = _CITY_AIRPORT_MAP.get(value.lower().strip())
    if known:
        return known
    code = _extract_iata(value)
    if code:
        return code
    for query in (value, f"{value} airport", f"{value} international airport"):
        # ... SerpApi locations.json lookup with timeout handling
```

### Robust LLM Output Parsing

The `_coerce_list` function handles the variety of formats an LLM might produce when passing destination lists -- JSON arrays, markdown bullet lists, comma-separated strings, and embedded JSON within prose text. This defensive parsing is important because MCP tool arguments come from LLM-generated content.

```python
# mcp_servers/flight_mcp/server.py (lines 25-54)
def _coerce_list(value: str) -> list[str]:
    raw = value.strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    except json.JSONDecodeError:
        pass
    # Falls through to regex JSON extraction, newline splitting, comma splitting
```

### MCP Tool Integration in Agent Graphs

The flight MCP server is consumed by agent templates as an `mcp_tool` node type. The LangGraph template wires it as a graph node that depends on prior tasks and maps agent input fields to tool arguments:

```yaml
# backend/agent_templates/travel_vacation_planner.yaml (lines 68-80)
- id: flight_research_task
  type: mcp_tool
  depends_on:
    - itinerary_options_task
  server: flight
  tool: google_flights_search
  args:
    origin: "{inputs.origin}"
    destination: "{inputs.destination}"
    depart_date: "{inputs.start_date}"
    return_date: "{inputs.end_date}"
    passengers: 1
    cabin: "{inputs.cabin}"
```

The server reference (`flight`) maps to the MCP server URL configured in the graph's `mcp.servers` block:

```yaml
# backend/agent_templates/travel_vacation_planner.yaml (lines 20-27)
mcp:
  transport: streamable-http
  servers:
    flight:
      url: "${FLIGHT_MCP_URL:http://localhost:7003/mcp}"
```

## Configuration

- **Environment variables:**
  - `SERPAPI_API_KEY` -- Required. API key for SerpApi (Google Flights and locations lookup). Shared with hotel_mcp server.
  - `HOST` -- Server bind address (default: `0.0.0.0`)
  - `PORT` -- Server listen port (default: `8000`, overridden to `7003` in local compose)
  - `FLIGHT_MCP_URL` -- Set on the backend container to point at this server (default: `http://localhost:7003/mcp`)
- **Config files:** None; all configuration via environment variables
- **Helm values:**
  ```yaml
  # deploy/cluster/helm/values.yaml (lines 264-270)
  mcp-servers:
    mcp-servers:
      flight:
        enabled: true
        deploymentMode: deployment
        image:
          repository: quay.io/rh-ai-quickstart/mcp-flight
          tag: "latest"
        transport: streamable-http
        port: 8000
        targetPort: 8000
  ```
  The backend receives the MCP URL via Helm template:
  ```yaml
  # deploy/cluster/helm/values.yaml (line 139)
  mcp:
    flight_url: "http://mcp-flight:8000/mcp"
  ```
  On-cluster, the SERPAPI_API_KEY is injected from a Kubernetes secret:
  ```yaml
  # deploy/cluster/helm/templates/deployment.yaml (lines 178-183)
  - name: SERPAPI_API_KEY
    valueFrom:
      secretKeyRef:
        name: {{ include "ai-virtual-agent.fullname" $ }}-env
        key: SERPAPI_API_KEY
  ```

## Known Gotchas

- **Port mismatch between local and cluster:** The compose file sets `PORT=7003` for local dev, but the Helm chart uses port `8000` (the FastMCP default). The `FLIGHT_MCP_URL` on the backend must match whichever port the server actually listens on. In compose this is `http://flight-mcp:7003/mcp`; in Helm it is `http://mcp-flight:8000/mcp`.
- **Multi-destination capping:** `google_flights_search` silently caps destination lookups to 2 (`max_destinations = 2`) even if the LLM passes a longer list. Only the first and last items from the parsed list are searched (lines 229-235 of `server.py`).
- **SerpApi timeout tuning:** Separate connect and read timeouts are used -- `(10, 20)` for locations lookup and `(10, 30)` for flights search. These are hardcoded, not configurable via env vars.
- **Healthcheck uses raw socket, not HTTP:** The compose healthcheck (`python -c "import socket; s=socket.create_connection(('localhost',7003),2); s.close()"`) only verifies the port is open, not that the MCP server is accepting requests. This can cause false-positive health during startup.

## Testing Notes

- Verify the server starts and responds to MCP tool calls by hitting `http://<host>:<port>/mcp` with a valid MCP request
- The `iata_lookup` tool can be tested independently without flight search to validate SERPAPI_API_KEY is set correctly
- The hardcoded `_CITY_AIRPORT_MAP` covers 30 major cities; lookups for unlisted cities require a working SerpApi connection

## Related Patterns

- Other MCP servers in this quickstart follow the same FastMCP + Containerfile + streamable-http pattern (`hotel_mcp`, `travel_research_mcp`)
- Agent template integration via `mcp_tool` node type in LangGraph declarative graph configs
- Helm `mcp-servers` subchart handles deployment of all three MCP servers uniformly
