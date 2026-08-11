---
name: mcp-server-zammad
description: "MCP server wrapping Zammad ticket operations with AUTHORITATIVE_USER_ID auth and Basher sidecar delegation"
summary: "Python FastMCP server exposing Zammad ticket-management operations (tag, close, escalate, route, assign) as MCP tools for AI agents, delegating all mutations to a Basher MCP sidecar at 127.0.0.1:8001 via a sync-to-async ThreadPoolExecutor bridge while using a separate REST client only for custom user fields (current_laptop, manager_email) that Basher strips out. Use when an AI agent needs structured ticket lifecycle control with per-request authorization via AUTHORITATIVE_USER_ID header (format: email-ticket_id) cross-referenced against the ticket customer — tools employ a three-layer decorator stack (@mcp.tool, @_handle_tool_errors, @trace_mcp_tool for OpenTelemetry W3C propagation) and pool-queue routing that clears owner to \"-\" for unassigned escalation workflows. Deployed as Helm subchart under mcp-servers.mcp-servers.zammad-mcp with extraContainers for the Basher sidecar on UBI9 python-312-minimal; all config is environment-driven via a frozen dataclass singleton loaded at import — missing ZAMMAD_URL or ZAMMAD_HTTP_TOKEN raises ValueError at import time, MCP_TRANSPORT selects sse (default) or streamable-http, and 401 responses include operator remediation guidance. Basher URL must omit trailing slash (causes 307 redirects with streamable-http), FastMCP validation requires a dummy_parameter on every tool, _group_env preserves empty strings to intentionally disable groups/owners while _str_env treats empty as missing, REST fallback is a temporary workaround until Basher supports custom user attributes, and tests require conftest.py to os.environ.setdefault credentials before any zammad_mcp imports."
metadata:
  type: component
tags:
  tech_stack: [python, fastmcp, httpx, pydantic, uvicorn, opentelemetry]
  ai_pattern: [agents, mcp]
  platform: [openshift, kubernetes]
  data_layer: []
source_examples:
  - quickstart: "it-self-service-agent"
    repo: "https://github.com/rh-ai-quickstart/it-self-service-agent"
    notes: "Zammad MCP wrapper with sidecar Basher delegation, per-ticket AUTHORITATIVE_USER_ID authorization, and REST fallback for custom user fields"
    approach: "A"
---

# MCP Server Zammad

## Overview

A Python MCP server that exposes Zammad ticket-management operations (tag, close, escalate, route, assign) as MCP tools for AI agents. It does not talk to Zammad directly for ticket mutations; instead it delegates to a co-located Basher MCP sidecar container. A separate REST client is used only for Zammad custom user fields (e.g. `current_laptop`, `manager_email`) that the Basher MCP tools strip out. Every tool call is gated by an `AUTHORITATIVE_USER_ID` header that encodes the caller's email and ticket ID.

## Tech Stack & Dependencies

- **Runtime:** Python 3.12, FastMCP (from `mcp[cli]>=1.23`)
- **Container image:** Built via shared `Containerfile.mcp-template` on `registry.access.redhat.com/ubi9/python-312-minimal:9.7`
- **Key dependencies:** `httpx`, `mcp[cli]`, `pydantic`, `opentelemetry-*`, `cloudevents`, plus workspace packages `mcp-common`, `self-service-agent-shared-models`, `tracing-config`
- **Helm subchart:** Deployed as an entry under `mcp-servers.mcp-servers.zammad-mcp` in the parent Helm chart, with a Basher sidecar (`extraContainers`)

## Key Patterns

### Sidecar Basher MCP Delegation

The server does not call Zammad APIs for ticket mutations. It delegates to a third-party Basher MCP server (`ghcr.io/basher83/zammad-mcp`) running as a sidecar on `127.0.0.1:8001`. The `basher_client.py` bridges sync tool handlers to the async MCP client by running `asyncio.run` on a `ThreadPoolExecutor`.

```python
# basher_client.py — sync-to-async bridge
_executor = ThreadPoolExecutor(
    max_workers=ZAMMAD_MCP_SETTINGS.basher_mcp_max_workers,
    thread_name_prefix="zammad-basher-mcp",
)

def call_basher_tool(name: str, params: dict[str, Any]) -> str:
    url = ZAMMAD_MCP_SETTINGS.basher_mcp_url
    arguments: dict[str, Any] = {"params": params}
    def _run() -> str:
        return asyncio.run(_call_tool_async(url, name, arguments))
    return _executor.submit(_run).result(
        timeout=ZAMMAD_MCP_SETTINGS.mcp_timeout_seconds
    )
```

### AUTHORITATIVE_USER_ID Header Authorization

Every tool reads the `AUTHORITATIVE_USER_ID` MCP request header (format: `{email}-{ticket_id}`). The server parses this via `zammad_auth_id.parse_email_and_ticket_id`, then calls `assert_ticket_customer_matches_basher` to verify the ticket's customer matches the claimed email by fetching the ticket from Basher and cross-referencing.

```python
# server.py — authorization gate on every tool
def _authorize_ticket(ctx: Context[Any, Any]) -> tuple[str, int, int]:
    raw = header_first(ctx, "AUTHORITATIVE_USER_ID", "authoritative_user_id")
    if not raw:
        raise ValueError(
            "AUTHORITATIVE_USER_ID missing on the MCP request ..."
        )
    email, ticket_id = parse_email_and_ticket_id(raw)
    cust_uid = assert_ticket_customer_matches_basher(ticket_id, email)
    return email, ticket_id, cust_uid
```

### REST Fallback for Custom User Fields

Basher MCP tools strip custom Zammad user attributes. The `ZammadRestClient` makes direct `GET /api/v1/users/{id}` calls to read fields like `current_laptop` and `manager_email` that the Basher models omit.

```python
# zammad_rest_client.py — direct REST for custom fields only
class ZammadRestClient:
    """Zammad REST: GET /users/{id} only (custom fields not in Basher models)."""
    def get_user(self, user_id: int, timeout: float | None = None) -> Dict[str, Any]:
        with self._http_client(timeout=timeout) as client:
            r = client.get(f"{self._base}/users/{user_id}", headers=self._headers)
            _raise_for_zammad_response(r)
            return dict(r.json())
```

### Decorator Stack for Tools

Each MCP tool uses a three-layer decorator stack: `@mcp.tool()` for registration, `@_handle_tool_errors` for catching and logging exceptions (including `BaseExceptionGroup`), and `@trace_mcp_tool()` for OpenTelemetry span creation with W3C trace context propagation from HTTP headers.

```python
@mcp.tool()
@_handle_tool_errors
@trace_mcp_tool()
def close(ctx: Context[Any, Any], dummy_parameter: str = "") -> str:
    """Close the ticket."""
    ...
```

### Pool-Queue Routing with Owner Clearing

Escalation and routing tools use a shared helper that clears the ticket owner to `"-"` (Zammad's UI placeholder for unassigned) and optionally reassigns the Zammad group, enabling pool-queue workflows.

```python
# server.py
POOL_QUEUE_UNASSIGNED_OWNER = "-"

def _basher_pool_queue_ticket_update(
    ticket_id: int, *, group_name_stripped: str
) -> None:
    payload: dict[str, Any] = {
        "ticket_id": ticket_id,
        "owner": POOL_QUEUE_UNASSIGNED_OWNER,
    }
    if group_name_stripped:
        payload["group"] = group_name_stripped
    call_basher_tool("zammad_update_ticket", payload)
```

## Configuration

- **Environment variables:**
  - `ZAMMAD_URL` (required) — Zammad web origin, used for REST API calls
  - `ZAMMAD_HTTP_TOKEN` (required) — Zammad API token (from Kubernetes secret `zammad-credentials`)
  - `ZAMMAD_BASHER_MCP_URL` — Basher sidecar URL (default: `http://127.0.0.1:8001/mcp`)
  - `MCP_TRANSPORT` — Transport mode: `sse` or `streamable-http` (default: `sse`)
  - `SELF_SERVICE_AGENT_ZAMMAD_MCP_SERVICE_PORT_HTTP` — Listen port (default: `8002`)
  - `ZAMMAD_MCP_TIMEOUT_SECONDS` — Timeout for Basher and REST calls (default: `120`)
  - `ZAMMAD_BASHER_MCP_MAX_WORKERS` — Thread pool size for Basher calls (default: `8`, clamped 1-128)
  - `ZAMMAD_AGENT_MANAGED_TAG` — Tag for laptop-refresh flow (default: `agent-managed-laptop-refresh`)
  - `ZAMMAD_GENERAL_AGENT_MANAGED_TAG` — Tag for general support flow (default: `agent-managed-general-support`)
  - `ZAMMAD_STATE_CLOSED` — Zammad state name for closed tickets (default: `closed`)
  - `ZAMMAD_TAG_CLOSED_BY_AI` — Tag applied when AI closes a ticket (default: `closed-by-ai-agent`)
  - `ZAMMAD_TAG_ESCALATE_HUMAN` — Tag for human escalation (default: `escalated-human-review`)
  - `ZAMMAD_TAG_MANAGER_REVIEW` — Tag for manager review (default: `pending-manager-review`)
  - `ZAMMAD_GROUP_ESCALATED_LAPTOP` — Zammad group for escalated laptop tickets (default: `escalated_laptop_refresh_tickets`)
  - `ZAMMAD_GROUP_HUMAN_MANAGED` — Zammad group for human-managed queue (default: `human_managed_tickets`)
  - `ZAMMAD_LAPTOP_SPECIALIST_OWNER` — Email for laptop specialist assignment (default: `agent.laptop-specialist@example.com`)
  - `ZAMMAD_SPECIALIST_OWNER` — Email for general specialist assignment (default: `agent.general@example.com`)
  - `ZAMMAD_USER_MANAGER_FIELD` — Zammad user field containing manager email (default: `manager_email`)
  - `ZAMMAD_MANAGER_EMAIL` — Fallback manager email when user field is empty
  - `UVICORN_WORKERS` — Number of uvicorn workers (set to `2` in Helm values)
- **Config files:** All configuration is environment-driven via `settings.py` (frozen dataclass loaded once at import)
- **Helm values:** Deployed under `mcp-servers.mcp-servers.zammad-mcp` with `env`, `envSecrets`, and `extraContainers` for the Basher sidecar

## Known Gotchas

- **Basher URL trailing slash:** The `ZAMMAD_BASHER_MCP_URL` value must not have a trailing slash to avoid 307 redirect issues with the streamable-HTTP transport. The settings loader strips it: `basher_raw.rstrip("/")`. This is noted inline in `helm/values.yaml`: "No trailing slash: avoids some Basher/streamable-http 307 redirect quirks."
- **dummy_parameter on every tool:** FastMCP validation fails unless there is at least one parameter, so all tools accept a `dummy_parameter: str = ""` that is never used. The docstring on `get_employee_laptop_info` explains: "Optional parameter as validation fails unless there is at least one parameter."
- **Settings loaded at module import:** `ZAMMAD_MCP_SETTINGS` is a module-level singleton (`load_zammad_mcp_settings()` called at import time). If `ZAMMAD_URL` or `ZAMMAD_HTTP_TOKEN` is missing, the import itself raises `ValueError`. Tests use `conftest.py` to set these env vars via `os.environ.setdefault` before any `zammad_mcp.*` imports.
- **REST client exists only for custom user fields:** The docstring in `zammad_rest_client.py` explains: "Our goal is to avoid this and pass all requests through the MCP server, however that is not possible for custom attributes on the user (manager email and current laptop info) as all of the mcp server tools strips those out." This REST path should shrink if Basher adds custom-field support.
- **401 error message includes remediation:** The REST client catches `401 Unauthorized` specifically and returns a message telling the operator to check `ZAMMAD_HTTP_TOKEN` and restart the deployment, reducing debugging time.
- **_group_env vs _str_env:** Settings uses two distinct env helpers. `_str_env` treats empty the same as missing (returns default); `_group_env` preserves empty strings so callers can intentionally disable a group or owner by setting the env var to `""`.

## Testing Notes

- Tests mock both `call_basher_tool` and `assert_ticket_customer_matches_basher` to isolate tool logic from Basher and Zammad network calls
- `conftest.py` sets `ZAMMAD_URL` and `ZAMMAD_HTTP_TOKEN` via `os.environ.setdefault` before test module imports to prevent `ValueError` on settings load
- Tests verify the exact sequence and payload of Basher tool calls (e.g., `zammad_add_ticket_tag` before `zammad_update_ticket`)
- Authorization is tested: a tool called without the `AUTHORITATIVE_USER_ID` header returns an error message and never reaches Basher

## Related Patterns

- See `mcp-servers.md` for the shared MCP server deployment pattern and Containerfile template
- See `llm-service.md` for the agent orchestration layer that invokes these MCP tools
