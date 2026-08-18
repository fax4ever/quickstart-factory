---
name: mcp-common
description: "Shared Python library providing HTTP header helpers and OpenTelemetry tracing decorator for MCP servers"
summary: "Provides reusable HTTP header extraction and OpenTelemetry tracing utilities for FastMCP-based MCP servers in multi-server agentic monorepos, consumed as a Hatchling-built Python >= 3.12 path dependency via uv workspaces. Use when multiple sibling MCP servers (e.g., snow, zammad) need shared per-request credential extraction via `header_first` (AUTHORITATIVE_USER_ID, SERVICE_NOW_TOKEN) and distributed tracing that joins tool spans to the calling agent's trace via W3C TraceContext propagation -- not deployed independently (no Helm chart), tested indirectly through consuming servers. The `trace_mcp_tool` decorator is gated by the `OTEL_EXPORTER_OTLP_ENDPOINT` environment variable (no-op when unset) and depends on sibling path packages `tracing-config` (tracingIsActive guard) and `shared-models` (configure_logging), requiring explicit `[tool.uv.sources]` path entries. `mcp_http_headers` returns None silently on non-streamable-http transports (stdio), the tracing decorator records only primitive-type (str, int, float, bool) arguments as span attributes, and mypy_path must explicitly list sibling source directories with `follow_imports = \\\"skip\\\"` overrides."
metadata:
  type: component
tags:
  tech_stack: [python, mcp, opentelemetry, hatchling]
  ai_pattern: [agents]
  platform: []
  data_layer: []
source_examples:
  - quickstart: "it-self-service-agent"
    repo: "https://github.com/rh-ai-quickstart/it-self-service-agent"
    notes: "Shared utility library consumed by snow and zammad MCP servers for header extraction and distributed tracing"
    approach: "A"
---

# MCP Common

## Overview

`mcp-common` is a shared Python library that provides reusable utilities for MCP (Model Context Protocol) servers in multi-server agentic architectures. It supplies two modules: HTTP header extraction from FastMCP `Context` objects, and an OpenTelemetry decorator for tracing MCP tool calls. It is consumed as a path dependency by sibling MCP server packages (e.g., `snow`, `zammad`) within the same monorepo.

## Tech Stack & Dependencies

- **Runtime:** Python >= 3.12
- **Build system:** Hatchling (`hatchling.build`)
- **Key dependencies:**
  - `mcp[cli]>=1.23` — FastMCP framework providing `Context` and server primitives
  - `opentelemetry-exporter-otlp-proto-http>=1.37.0` — OTLP exporter for distributed tracing
  - `self-service-agent-shared-models` — sibling path dependency (`../../shared-models`) providing `configure_logging`
  - `tracing-config` — sibling path dependency (`../../tracing-config`) providing `tracingIsActive` guard
- **Helm subchart:** None (library package, not a deployed service)

## Key Patterns

### Path-Based Monorepo Dependencies

MCP servers in the same repo consume `mcp-common` as a local path dependency via `uv` workspaces, avoiding version management overhead for shared code.

```toml
# From mcp-servers/snow/pyproject.toml
[tool.uv.sources]
mcp-common = { path = "../mcp-common" }
```

The library itself also uses path dependencies for its own internal deps:

```toml
# From mcp-servers/mcp-common/pyproject.toml
[tool.uv.sources]
self-service-agent-shared-models = { path = "../../shared-models" }
tracing-config = { path = "../../tracing-config" }
```

### HTTP Header Extraction from MCP Context

The `headers` module navigates the FastMCP `Context` object hierarchy to reach Starlette-level HTTP headers from streamable-http transport. This provides case-insensitive header lookup to MCP tool handlers.

```python
# From mcp-servers/mcp-common/src/mcp_common/headers.py
def mcp_http_headers(ctx: Context[Any, Any]) -> Mapping[str, Any] | None:
    try:
        request_context = ctx.request_context
        if hasattr(request_context, "request") and request_context.request:
            request = request_context.request
            if hasattr(request, "headers"):
                return request.headers
    except Exception as e:
        logger.debug("Error reading MCP HTTP headers from context", ...)
    return None
```

Consumer MCP servers use `header_first` for per-request credential and identity extraction:

```python
# From mcp-servers/snow/src/snow/server.py
raw = header_first(ctx, "AUTHORITATIVE_USER_ID", "authoritative_user_id")
api_token = header_first(ctx, "SERVICE_NOW_TOKEN")
```

### OpenTelemetry Tracing Decorator

The `trace_mcp_tool` decorator wraps MCP tool functions with OpenTelemetry spans. It extracts W3C TraceContext propagation headers from the incoming MCP request so that MCP tool spans join the caller's distributed trace. Tracing is gated by the `OTEL_EXPORTER_OTLP_ENDPOINT` environment variable — when unset, the decorator is a no-op.

```python
# From mcp-servers/mcp-common/src/mcp_common/tracing.py
@trace_mcp_tool()
def open_laptop_refresh_ticket(
    employee_name: str,
    business_justification: str,
    servicenow_laptop_code: str,
    ctx: Context[Any, Any],
) -> str:
    ...
```

The decorator automatically sets span attributes for tool name, positional args (primitive types only), and keyword args:

```python
# From mcp-servers/mcp-common/src/mcp_common/tracing.py
span.set_attribute("mcp.tool.name", func.__name__)
for i, arg in enumerate(args):
    if not isinstance(arg, (str, int, float, bool)):
        continue
    span.set_attribute(f"mcp.tool.arg.{i}", str(arg))
```

### Trace Context Propagation from HTTP Headers

The tracing module extracts W3C TraceContext from the MCP request's HTTP headers so each MCP tool invocation appears as a child span of the calling agent's trace. Headers are lowercased before extraction to handle case variations.

```python
# From mcp-servers/mcp-common/src/mcp_common/tracing.py
headers = mcp_http_headers(ctx)
if headers is not None:
    carrier = {k.lower(): v for k, v in dict(headers).items()}
    extracted_context = extract(carrier)
```

## Configuration

- **Environment variables:**
  - `OTEL_EXPORTER_OTLP_ENDPOINT` — when set, enables OpenTelemetry tracing; when absent, `trace_mcp_tool` becomes a no-op passthrough
- **Config files:** None (configuration comes from consuming servers)
- **Helm values:** None (library package, not deployed independently)

## Known Gotchas

- The `mcp_http_headers` function relies on `hasattr` checks to navigate `ctx.request_context.request.headers` because the MCP `Context` object structure varies depending on the transport (streamable-http vs stdio). If the transport is not streamable-http, `None` is returned silently rather than raising an error.
- The `trace_mcp_tool` decorator only records primitive types (`str`, `int`, `float`, `bool`) as span attributes. Complex objects passed as tool arguments are silently skipped to avoid serialization issues.
- The `mypy_path` in `pyproject.toml` must explicitly list sibling package source directories (`../../tracing-config/src:../../shared-models/src`) and consumer servers must add `../mcp-common/src` as well, with `follow_imports = "skip"` overrides for those modules.

## Testing Notes

- This is a library, not a standalone service — it is tested indirectly through the MCP servers that consume it (snow, zammad).
- Verify tracing works by setting `OTEL_EXPORTER_OTLP_ENDPOINT` and confirming spans appear in the configured collector.
- Header extraction can be verified by checking that `AUTHORITATIVE_USER_ID` and service-specific tokens (e.g., `SERVICE_NOW_TOKEN`) reach the tool handlers.

## Related Patterns

- See `mcp-servers.md` for the overall MCP server architecture pattern
- Related to distributed tracing and observability patterns in agentic applications
