---
name: mcp-server-snow
description: "FastMCP server exposing ServiceNow laptop refresh tools via MCP protocol with API key auth and request guardrails"
summary: "Wraps ServiceNow Table and Service Catalog REST APIs (sys_user, cmdb_ci_computer, servicecatalog order_now) as two FastMCP tools (open_laptop_refresh_ticket, get_employee_laptop_info) consumable by an AI agent in the it-self-service-agent quickstart for laptop-refresh ticket workflows. Use when building an MCP server that proxies enterprise ITSM APIs with per-request auth propagation via HTTP headers (AUTHORITATIVE_USER_ID, SERVICE_NOW_TOKEN) for multi-tenant scenarios -- the FastMCP lifespan pattern validates required config at startup while AuthManager injects API keys into a configurable header (default x-sn-apikey); supports stdio/sse/streamable-http transports via MCP_TRANSPORT (default sse). Requires SERVICENOW_INSTANCE_URL and SERVICENOW_LAPTOP_REFRESH_ID env vars, provides two independent guardrails -- duplicate avoidance (SERVICENOW_LAPTOP_AVOID_DUPLICATES) and request limits (SERVICENOW_LAPTOP_REQUEST_LIMITS) that skip API calls when disabled -- and uses @trace_mcp_tool() from mcp-common for W3C traceparent OpenTelemetry tracing with shared Containerfile.mcp-template on UBI9 Python 3.12/uvicorn. MCP validation fails for zero-parameter tools requiring a dummy_parameter workaround, app-level state uses setattr/getattr on the FastMCP instance since it lacks typed custom attributes, a new ServiceNowClient is instantiated per request (not reusable across calls), and ServiceNow's tokenbased_auth plugin (com.glide.tokenbased_auth) must be manually activated with separate API Access Policies for Service Catalog and Table APIs."
metadata:
  type: component
tags:
  tech_stack: [fastmcp, python, pydantic, httpx, requests, opentelemetry, uvicorn]
  ai_pattern: [agents, mcp]
  platform: [openshift, rhoai]
  data_layer: []
source_examples:
  - quickstart: "it-self-service-agent"
    repo: "https://github.com/rh-ai-quickstart/it-self-service-agent"
    notes: "MCP server wrapping ServiceNow Table and Service Catalog APIs for laptop refresh ticket workflows"
    approach: "A"
---

# MCP Server — ServiceNow (Snow)

## Overview

The Snow MCP server is a FastMCP-based backend that exposes ServiceNow laptop-refresh operations as MCP tools consumable by an AI agent. It wraps the ServiceNow Table API and Service Catalog API behind two tools (`open_laptop_refresh_ticket`, `get_employee_laptop_info`) with built-in request-limit enforcement, duplicate-avoidance guardrails, and OpenTelemetry tracing. The server runs as a standalone microservice inside the `it-self-service-agent` quickstart, communicating over SSE or streamable-HTTP transport.

## Tech Stack & Dependencies

- **Runtime:** Python 3.12, FastMCP (`mcp[cli]>=1.23`)
- **Container image:** Built via shared `Containerfile.mcp-template` with `SERVICE_NAME=mcp-servers/snow`, `MODULE_NAME=snow.server`; base image `registry.access.redhat.com/ubi9/python-312-minimal:9.7`
- **Key dependencies:** `requests` (ServiceNow HTTP calls), `pydantic` (config/model validation), `opentelemetry-*` (distributed tracing), `httpx` (async HTTP), internal packages `mcp-common`, `self-service-agent-shared-models`, `tracing-config`
- **Helm subchart:** No dedicated Helm subchart; deployed as part of the monorepo Makefile targets (`build-mcp-snow-image`, `push-mcp-snow-image`)

## Key Patterns

### FastMCP Lifespan for Configuration Validation

The server uses FastMCP's `lifespan` context manager to validate required ServiceNow configuration at startup, failing fast if `SERVICENOW_LAPTOP_REFRESH_ID` is missing. Configuration values are stored as attributes on the `mcp` app instance.

```python
@asynccontextmanager
async def lifespan(app: FastMCP) -> AsyncGenerator[None, None]:
    laptop_refresh_id = os.getenv("SERVICENOW_LAPTOP_REFRESH_ID")
    if not laptop_refresh_id:
        raise ValueError(
            "SERVICENOW_LAPTOP_REFRESH_ID environment variable is required but not set."
        )
    laptop_request_limits_env = os.getenv("SERVICENOW_LAPTOP_REQUEST_LIMITS")
    laptop_request_limits = (
        int(laptop_request_limits_env) if laptop_request_limits_env else None
    )
    setattr(app, "laptop_refresh_id", laptop_refresh_id)
    setattr(app, "laptop_request_limits", laptop_request_limits)
    # ...
    yield
```

### MCP Transport Selection

The server supports multiple MCP transports (`stdio`, `sse`, `streamable-http`) via environment variable, defaulting to `sse`. For `streamable-http`, it exposes an ASGI app for `uvicorn`.

```python
MCP_TRANSPORT: Literal["stdio", "sse", "streamable-http"] = cast(
    Literal["stdio", "sse", "streamable-http"],
    os.environ.get("MCP_TRANSPORT", "sse") or "sse",
)
mcp = FastMCP(
    "Snow Server",
    host=MCP_HOST,
    stateless_http=(MCP_TRANSPORT == "streamable-http"),
    lifespan=lifespan,
)
# Expose ASGI app for uvicorn
app = mcp.streamable_http_app()
```

### Header-Based Auth Propagation

Per-request authentication tokens and user identity are extracted from HTTP headers using the shared `mcp-common` library, not from environment variables. The `AUTHORITATIVE_USER_ID` header carries the caller's email; `SERVICE_NOW_TOKEN` carries the ServiceNow API key. A regex strips trailing `-{digits}` suffixes from the user ID to handle ticket-flow naming patterns.

```python
def _snow_authoritative_user_id_for_email(ctx: Context[Any, Any]) -> str | None:
    raw = header_first(ctx, "AUTHORITATIVE_USER_ID", "authoritative_user_id")
    if raw is None:
        return None
    return re.sub(r"-\d+$", "", str(raw).strip())
```

### Request Guardrails: Duplicate Avoidance and Limits

Before creating a new laptop request, the client checks existing open requests via the `sc_req_item` table. Two independent guardrails are configurable:

1. **Duplicate avoidance** (`SERVICENOW_LAPTOP_AVOID_DUPLICATES`): prevents opening a second request for the same laptop model.
2. **Request limits** (`SERVICENOW_LAPTOP_REQUEST_LIMITS`): caps the total number of open requests per user.

Both checks are skipped entirely when their respective settings are disabled, avoiding unnecessary API calls.

```python
# Only fetch existing requests if guardrails are enabled
if self.laptop_avoid_duplicates or self.laptop_request_limits is not None:
    existing_requests_result = self.get_open_laptop_requests_for_user(user_sys_id)
    # ...

# Duplicate check
existing_request = self._has_existing_request_for_laptop_model(
    existing_requests, current_laptop_model
)
if existing_request:
    return {"success": True, "existing_ticket": True, ...}

# Limit check
if self._would_exceed_request_limit(existing_requests):
    return {"success": False, ...}
```

### ServiceNow API Client with API Key Auth

The `ServiceNowClient` loads configuration from environment variables and uses an `AuthManager` that injects the API key into a configurable HTTP header (default: `x-sn-apikey`). The client wraps three ServiceNow REST endpoints:

- `GET /api/now/table/sys_user` -- user lookup by email
- `GET /api/now/table/cmdb_ci_computer` -- laptop info by assigned user
- `POST /api/sn_sc/servicecatalog/items/{id}/order_now` -- catalog item ordering

```python
auth_config = AuthConfig(
    type=AuthType.API_KEY,
    api_key=ApiKeyConfig(
        api_key=api_token,
        header_name=os.getenv("SERVICENOW_API_KEY_HEADER", "x-sn-apikey"),
    ),
)
```

### OpenTelemetry Tracing via Decorator

Each MCP tool is wrapped with the shared `@trace_mcp_tool()` decorator from `mcp-common`. The decorator extracts the parent trace context from HTTP headers (W3C `traceparent`), creates a child span, and records tool arguments and outcomes. Tracing is gated by a `tracingIsActive()` check so it adds zero overhead when disabled.

```python
@mcp.tool()
@trace_mcp_tool()
def open_laptop_refresh_ticket(
    employee_name: str,
    business_justification: str,
    servicenow_laptop_code: str,
    ctx: Context[Any, Any],
) -> str:
```

### Shared Containerfile Template

All MCP servers in the monorepo share `Containerfile.mcp-template`, a multi-stage build using UBI9 Python 3.12 images. The template accepts build args (`SERVICE_NAME`, `MODULE_NAME`) and supports both `uv sync` (default) and `pip install --require-hashes` (for QEMU/Mac M1 builds). The final stage runs `uvicorn` with optional `UVICORN_WORKERS` for multi-process concurrency.

```dockerfile
FROM registry.access.redhat.com/ubi9/python-312:9.7 as builder
# ...
ARG SERVICE_NAME
ARG MODULE_NAME
# ...
CMD if [ -n "$UVICORN_WORKERS" ]; then \
      python3 -m uvicorn $MODULE_NAME:app --host 0.0.0.0 --port 8000 --workers $UVICORN_WORKERS; \
    else \
      python3 -m uvicorn $MODULE_NAME:app --host 0.0.0.0 --port 8000; \
    fi
```

## Configuration

- **Environment variables:**
  - `SERVICENOW_INSTANCE_URL` (required): ServiceNow instance base URL
  - `SERVICENOW_LAPTOP_REFRESH_ID` (required): Catalog item sys_id for laptop refresh
  - `SERVICENOW_API_KEY_HEADER` (default: `x-sn-apikey`): HTTP header name for API key
  - `SERVICENOW_LAPTOP_REQUEST_LIMITS` (optional): Max open requests per user; no limit if unset
  - `SERVICENOW_LAPTOP_AVOID_DUPLICATES` (default: `false`): Prevent duplicate laptop model requests
  - `SERVICENOW_DEBUG` (default: `false`): Enable debug logging
  - `SERVICENOW_TIMEOUT` (default: `30`): HTTP request timeout in seconds
  - `MCP_TRANSPORT` (default: `sse`): MCP transport protocol (`stdio`, `sse`, `streamable-http`)
  - `MCP_HOST` (default: `0.0.0.0`): Server bind host
  - `SELF_SERVICE_AGENT_SNOW_SERVER_SERVICE_PORT_HTTP` (default: `8001`): Server port
  - `OTEL_EXPORTER_OTLP_ENDPOINT`: OpenTelemetry collector endpoint
- **Config files:** `pyproject.toml` defines project metadata, dependencies, and tool config (black, isort, pytest, mypy)
- **Helm values:** No dedicated chart; environment variables passed via top-level Helm `--set` in Makefile (e.g., `--set-string security.apiKeys.snowIntegration`)

## Known Gotchas

- **`dummy_parameter` workaround in `get_employee_laptop_info`:** The tool accepts a `dummy_parameter: str = ""` argument because MCP validation fails for tools with zero parameters (only the `ctx` argument). The docstring notes this explicitly: "Optional parameter as validation fails unless there is at least one parameter." (source: `server.py`, line 228)
- **User ID suffix stripping:** The `_snow_authoritative_user_id_for_email` helper strips trailing `-{digits}` from the user ID header using `re.sub(r"-\d+$", "", ...)`. This handles a ticket-flow naming convention where user IDs arrive as `alice@company.com-42`. If upstream systems change this pattern, the regex must be updated. (source: `server.py`, line 31)
- **API key is per-request, not per-server:** Unlike typical patterns where the API key is an env var read at startup, here `SERVICE_NOW_TOKEN` comes from the HTTP request header. A new `ServiceNowClient` is instantiated on every tool call with the per-request token. This supports multi-tenant scenarios but means the client cannot be reused across requests. (source: `server.py`, lines 158-163, 274-279)
- **`setattr` for app-level state:** Configuration is stored on the FastMCP app instance via `setattr(app, "laptop_refresh_id", ...)` and retrieved with `getattr(mcp, "laptop_refresh_id")`. This is a FastMCP-specific pattern since the app object does not have typed attributes for custom data. (source: `server.py`, lines 69-71, 160-163)
- **`conftest.py` sets default ServiceNow URL:** The test `conftest.py` uses `os.environ.setdefault` to set `SERVICENOW_INSTANCE_URL` to `http://self-service-agent-mock-servicenow:8080`, pointing to the mock ServiceNow service. This means tests depend on the mock server's URL pattern even though tests mock the HTTP layer. (source: `tests/conftest.py`, line 9)
- **ServiceNow API key setup requires plugin activation:** The README documents that the "API Key and HMAC Authentication" plugin (`com.glide.tokenbased_auth`) must be manually activated in ServiceNow before API keys can be created. Two separate API Access Policies are needed: one for Service Catalog API and one for Table API. (source: `README.md`, lines 149-246)

## Testing Notes

- Tests use `unittest.mock` with `@patch` decorators to mock the `ServiceNowClient` and `mcp` app attributes
- A custom `MockContext` class simulates the MCP `Context` with HTTP headers for `AUTHORITATIVE_USER_ID`
- Test coverage includes: successful ticket creation, empty-parameter validation, duplicate-avoidance behavior (enabled/disabled), request limit enforcement, API failure handling, and laptop info retrieval
- Run tests with: `cd mcp-servers/snow/ && uv run pytest`

## Related Patterns

- `components/mcp-servers.md` -- general MCP server component patterns in AI Quickstarts
- `components/fastapi-backend.md` -- shared patterns with FastAPI-based backends (uvicorn, OpenTelemetry, UBI9 images)
