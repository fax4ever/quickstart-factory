---
name: mcp-risk-server
description: "Standalone FastMCP server exposing pure-computation risk assessment tools over Streamable HTTP for LangGraph agents"
summary: "Solves exposing stateless pure-computation risk tools (calculate_dti, calculate_ltv, evaluate_credit_risk, assess_income_stability, assess_asset_sufficiency, generate_risk_recommendation) as a standalone FastMCP server over Streamable HTTP on port 8081, consumed by LangGraph agents via langchain-mcp-adapters MultiServerMCPClient that converts MCP tools to LangChain StructuredTools merged with native tools. Use when LangGraph agents need to call pure-function tools accepting primitives and returning JSON, deployed as a separate process reusing the main API container image with entrypoint `python -m src.mcp_server` and a custom Helm Deployment template -- prefer the reusable mcp-servers subchart for standard MCP servers without custom templates. Critical config: custom `/health` GET route is mandatory (FastMCP's `/mcp` returns 406 on GET) for K8s probes, MCP_RISK_SERVER_URL (default `http://localhost:8081/mcp`) and optional PREDICTIVE_MODEL_MCP_URL with field_validator converting empty strings to None for graceful degradation; on OpenShift, Kagenti MCPServerRegistration CRD with `toolPrefix: risk_` wires an HTTPRoute through the MCP Gateway. Gotchas: risk threshold constants are duplicated between mcp_server.py and risk_tools.py, compose health check uses inline Python `urllib.request.urlopen` since the image lacks curl/wget, compose `service_healthy` dependency blocks API startup until MCP health passes, and the server runs via `__main__` not the FastAPI uvicorn process."
metadata:
  type: component
tags:
  tech_stack: [python, fastmcp, mcp, langchain-mcp-adapters, langgraph, fastapi]
  ai_pattern: [agents, mcp]
  platform: [openshift, kubernetes]
  data_layer: []
source_examples:
  - quickstart: "multi-agent-loan-origination"
    repo: "https://github.com/rh-ai-quickstart/multi-agent-loan-origination"
    notes: "Standalone MCP server with six risk-assessment tools consumed by the underwriter LangGraph agent via langchain-mcp-adapters MultiServerMCPClient"
    approach: "A"
---

# MCP Risk Server

## Overview

A standalone MCP server that exposes pure-computation risk assessment tools over the Streamable HTTP transport, designed to be called by LangGraph agents via `langchain-mcp-adapters`. The server runs as a separate process (port 8081) alongside the main FastAPI application, using the same container image but a different entrypoint command. It contains no database access -- all inputs are simple primitives passed by the LLM.

## Tech Stack & Dependencies

- **Runtime:** Python 3.11+
- **Container image:** Same image as the FastAPI API (`mortgage-ai-api`), launched with `python -m src.mcp_server`
- **Key dependencies:**
  - `mcp>=1.0.0,<2.0` -- FastMCP framework for building MCP servers
  - `langchain-mcp-adapters>=0.2.0,<1.0` -- client-side adapter converting MCP tools to LangChain StructuredTool instances
- **Helm subchart:** None (custom Helm Deployment template, not the reusable `mcp-servers` subchart)

## Key Patterns

### Separate Process, Same Image

The MCP risk server reuses the API container image but overrides the entrypoint command. This avoids building a separate image while keeping the MCP server isolated from the main FastAPI process.

```yaml
# From compose.yml
mcp-risk-server:
  build:
    context: .
    dockerfile: packages/api/Containerfile
  command: python -m src.mcp_server
  ports:
    - "8081:8081"
```

The Helm deployment uses the same pattern:

```yaml
# From deploy/helm/mortgage-ai/templates/mcp-risk-server.yaml
containers:
  - name: mcp-risk-server
    image: {{ include "mortgage-ai.image" (dict "name" .Values.mcpRiskServer.image.repository ...) }}
    command: ["python", "-m", "src.mcp_server"]
    ports:
      - name: http
        containerPort: 8081
```

### FastMCP Server with Custom Health Endpoint

The server uses `FastMCP` and adds a custom GET `/health` route for Kubernetes liveness/readiness probes, since the MCP `/mcp` endpoint only accepts POST and returns 406 on GET.

```python
# From packages/api/src/mcp_server.py
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("risk-assessment", host="0.0.0.0", port=8081)

@mcp.custom_route("/health", methods=["GET"])
async def health(request):
    from starlette.responses import JSONResponse
    return JSONResponse({"status": "healthy"})
```

### Pure-Computation Tools with JSON Return

All six MCP tools are stateless, pure functions with no database access. Each tool accepts primitive arguments from the LLM, computes a risk rating, and returns a JSON string. The tools are: `calculate_dti`, `calculate_ltv`, `evaluate_credit_risk`, `assess_income_stability`, `assess_asset_sufficiency`, and `generate_risk_recommendation`.

```python
# From packages/api/src/mcp_server.py
@mcp.tool()
def calculate_dti(monthly_income: float, monthly_debts: float) -> str:
    """Calculate Debt-to-Income ratio and risk rating.
    DTI = monthly_debts / monthly_income * 100.
    Ratings: <36% Low, 36-43% Medium, >43% High.
    """
    if monthly_income <= 0:
        return json.dumps({"value": None, "rating": None,
            "warning": "Missing or zero income -- DTI cannot be computed"})
    dti_pct = round(monthly_debts / monthly_income * 100, 1)
    # ... rating logic ...
    return json.dumps({"value": dti_pct, "rating": rating, "guidance": guidance})
```

### MultiServerMCPClient Integration (langchain-mcp-adapters)

The main FastAPI application connects to the MCP server at startup using `MultiServerMCPClient` from `langchain-mcp-adapters`, which converts MCP tools into LangChain `StructuredTool` instances. These tools are then mixed into the underwriter LangGraph agent's tool list alongside native tools.

```python
# From packages/api/src/agents/mcp_integration.py
from langchain_mcp_adapters.client import MultiServerMCPClient

async def init_mcp_client(url: str, *, predictive_model_url: str | None = None) -> None:
    servers: dict = {
        "risk-assessment": {
            "transport": "streamable_http",
            "url": url,
        },
    }
    _client = MultiServerMCPClient(servers)
    _tools = await _client.get_tools()
```

The underwriter agent merges MCP tools with native tools:

```python
# From packages/api/src/agents/underwriter_assistant.py
from .mcp_integration import get_mcp_tools

mcp_tools = get_mcp_tools()
all_tools = native_tools + mcp_tools
```

### Graceful Degradation for Optional MCP Servers

The MCP client supports an optional second MCP server (predictive model). If the predictive model server is unreachable, the client falls back to connecting only to the risk-assessment server rather than failing entirely.

```python
# From packages/api/src/agents/mcp_integration.py
except Exception as exc:
    if predictive_model_url:
        logger.warning("Predictive model MCP at %s unreachable, continuing without it",
                       predictive_model_url)
        _client = MultiServerMCPClient({
            "risk-assessment": {"transport": "streamable_http", "url": url},
        })
        _tools = await _client.get_tools()
        _predictive_model_connected = False
    else:
        raise
```

### Kagenti MCPServerRegistration for Gateway Routing

On OpenShift with Kagenti, the MCP server is registered via the `MCPServerRegistration` CRD. This wires an HTTPRoute through the MCP Gateway so Kagenti can discover and route to the MCP server. A `toolPrefix` of `risk_` namespaces the tools.

```yaml
# From deploy/helm/mortgage-ai/templates/mcp-server-registrations.yaml
apiVersion: mcp.kagenti.com/v1alpha1
kind: MCPServerRegistration
metadata:
  name: mcp-risk-server
  labels:
    "kagenti/mcp": "true"
spec:
  toolPrefix: risk_
  targetRef:
    group: gateway.networking.k8s.io
    kind: HTTPRoute
    name: mcp-risk-server-route
```

## Configuration

- **Environment variables:**
  - `MCP_RISK_SERVER_URL` -- URL of the MCP risk assessment server's Streamable HTTP endpoint (default: `http://localhost:8081/mcp`; in compose/Helm: `http://mcp-risk-server:8081/mcp`)
  - `PREDICTIVE_MODEL_MCP_URL` -- optional URL for external predictive model MCP server; empty string treated as unset via a field validator
- **Config files:** None (server is self-contained, no external config files)
- **Helm values:**
  - `mcpRiskServer.enabled` -- toggle the deployment (default: `true`)
  - `mcpRiskServer.name` -- service name (default: `mcp-risk-server`)
  - `mcpRiskServer.service.port` -- service port (default: `8081`)
  - `mcpRiskServer.replicas` -- replica count (default: `1`)
  - `mcpRiskServer.resources` -- resource requests/limits (default: 256Mi/512Mi memory, 100m/500m CPU)
  - `mcpRiskServer.healthCheck.enabled` -- enable K8s probes (default: `true`)

## Known Gotchas

- The MCP `/mcp` endpoint only accepts POST requests and returns HTTP 406 on GET. The custom `/health` route is required for K8s liveness/readiness probes because standard GET-based probes cannot hit `/mcp` directly. This is noted in a source comment: "Health endpoint for K8s probes (MCP's /mcp only accepts POST, returns 406 on GET)."
- The risk threshold constants are duplicated between `mcp_server.py` and `risk_tools.py`. The `mcp_server.py` mirrors the values with a comment: "Threshold constants (mirrored from risk_tools.py for tool descriptions)."
- The `PREDICTIVE_MODEL_MCP_URL` config setting uses a `field_validator` to convert empty strings to `None`, so deleting the env var value in a deployment disables the feature rather than causing a connection error.
- The compose health check uses an inline Python `urllib.request.urlopen` call rather than curl/wget since the container image may not include those utilities.
- The MCP server is started as a separate process via `if __name__ == "__main__": mcp.run(transport="streamable-http")`, not via the main FastAPI app's uvicorn process.

## Testing Notes

- Verify the MCP server is running by hitting its health endpoint: `curl http://localhost:8081/health`
- The API service in compose depends on `mcp-risk-server` with `condition: service_healthy`, so the API will not start until the MCP server's health check passes.
- The MCP tools can be tested independently since they are pure functions with no database access -- all inputs are primitives.

## Related Patterns

- See `mcp-common.md` for shared MCP server utilities (different approach: library-based shared code for multi-MCP-server monorepos)
- See `mcp-servers.md` for the reusable Helm subchart approach to deploying MCP servers (this quickstart uses a custom Deployment template instead)
