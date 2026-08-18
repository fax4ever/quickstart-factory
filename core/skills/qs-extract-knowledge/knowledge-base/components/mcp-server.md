---
name: mcp-server
description: "FastMCP-based observability MCP server exposing Prometheus, Tempo, Korrel8r, and vLLM tools over HTTP/SSE/stdio"
summary: "FastMCP-based MCP server exposing 30+ observability tools (Prometheus metrics, Tempo traces, Korrel8r correlations, vLLM analytics) over HTTP stateless JSON-RPC, SSE, and stdio transports, deployed on RHOAI with OpenShift serving-cert TLS (reencrypt Route termination) and Thanos ServiceAccount token auth. Use when building an AI-accessible observability layer needing multi-transport support — MCPServerAdapter implements ToolExecutor for zero-overhead in-process tool calls from synchronous chatbot code; stdio mode (for Claude Desktop/Cursor) requires suppressing builtins.print, stderr, and logging beyond FASTMCP_NO_BANNER=1; Helm RBAC grants cluster-monitoring-view, grafana-prometheus-reader, korrel8r-view, Loki tenant, and inferenceservice-viewer ClusterRoles. Critical patterns: imperative tool registration via self.mcp.tool() grouped by domain, MCP app mounted last at root with _enforce_no_routes_after_mount() route locking, eager 1877-metric catalog loaded at import, structured MCPException hierarchy with error codes and recovery suggestions, and pydantic-settings config with GPU metric prefix discovery at runtime. Gotchas: MCPServerAdapter async-to-sync bridge must spawn a new thread with its own event loop inside uvicorn's running loop or asyncio.run() raises RuntimeError; TRACE_FETCH_SAFETY_FACTOR (default 2) needs 3-5 for low error-rate workloads; FastMCP init overrides Python logging requiring force_reconfigure_all_loggers() post-init; uvicorn timeout_keep_alive=300 required for multi-minute LLM summarization requests."
metadata:
  type: component
tags:
  tech_stack: [fastapi, fastmcp, python, uvicorn, pydantic-settings, httpx, pandas, anthropic, openai, weasyprint]
  ai_pattern: [model-serving, agents, observability, prompt-chaining]
  platform: [openshift, rhoai, kserve, vllm, prometheus, tempo, korrel8r, loki]
  data_layer: []
source_examples:
  - quickstart: "openshift-ai-observability-summarizer"
    repo: "https://github.com/rh-ai-quickstart/openshift-ai-observability-summarizer"
    notes: "MCP server exposing 30+ observability tools for vLLM, OpenShift, Prometheus, Tempo, and Korrel8r"
    approach: "A"
---

# MCP Server

## Overview

This component is a Model Context Protocol (MCP) server built with FastMCP that exposes 30+ observability tools for querying Prometheus metrics, Tempo traces, Korrel8r correlations, and vLLM model analytics. It runs as a FastAPI application served by Uvicorn and supports three transport protocols: HTTP (stateless JSON-RPC), SSE, and stdio (for Claude Desktop/Cursor IDE integration). On RHOAI, it deploys with TLS via OpenShift serving certificates and authenticates to Thanos using a ServiceAccount token.

## Tech Stack & Dependencies

- **Runtime:** Python 3.11 on UBI9 (`registry.access.redhat.com/ubi9/python-311:latest`)
- **Container image:** `quay.io/ecosystem-appeng/aiobs-mcp-server:v3.2.0`
- **Key dependencies:** fastmcp 3.0.2, fastapi 0.135.1, uvicorn 0.41.0, pydantic-settings 2.13.1, httpx 0.28.1, pandas 2.3.1, anthropic 0.84.0, openai 2.24.0, google-generativeai 0.8.6, weasyprint 65.1
- **Helm subchart:** `deploy/helm/mcp-server` (standalone chart, version 0.1.0)

## Key Patterns

### FastMCP Tool Registration

Tools are registered imperatively by importing tool functions from domain-specific modules and calling `self.mcp.tool()` on each. The server groups tools by domain (vLLM, OpenShift, Prometheus, Tempo, Korrel8r, credentials, model config, chat).

```python
# From observability_mcp.py — imperative registration pattern
class ObservabilityMCPServer:
    def __init__(self) -> None:
        from fastmcp import FastMCP
        self.mcp = FastMCP("metrics-observability")
        self._register_mcp_tools()

    def _register_mcp_tools(self) -> None:
        from .tools.observability_vllm_tools import list_models, analyze_vllm
        from .tools.prometheus_tools import search_metrics, execute_promql
        self.mcp.tool()(list_models)
        self.mcp.tool()(analyze_vllm)
        self.mcp.tool()(search_metrics)
        self.mcp.tool()(execute_promql)
```

### Multi-Transport Protocol Support

The server supports three transports selectable via `MCP_TRANSPORT_PROTOCOL` env var. For HTTP mode it uses `stateless_http` with JSON responses for browser compatibility. SSE mode uses FastMCP's `create_sse_app`. A separate `stdio_server.py` entry point suppresses all stdout/logging to keep the JSON-RPC pipe clean for Claude Desktop.

```python
# From api.py — transport selection
if settings.MCP_TRANSPORT_PROTOCOL == "sse":
    from fastmcp.server.http import create_sse_app
    mcp_app = create_sse_app(server.mcp, message_path="/sse/message", sse_path="/sse")
else:
    mcp_app = server.mcp.http_app(path="/mcp", stateless_http=True, json_response=True)
```

### MCP App Mounted at Root with Route Lock

The MCP app is mounted at the root path `/` last, which catches all unmatched routes. A route-locking mechanism prevents accidental additions after the mount that would be silently ignored.

```python
# From api.py — mount MCP last and lock
app.mount("/", mcp_app)
def _enforce_no_routes_after_mount():
    def _blocked_route(*args, **kwargs):
        raise RuntimeError(
            "Cannot add routes after mounting MCP app at root. "
            "Move all route definitions before app.mount('/', mcp_app)"
        )
    app.add_route = _blocked_route
    app.add_api_route = _blocked_route
_enforce_no_routes_after_mount()
```

### Structured Exception Handling Framework

A custom exception hierarchy provides MCP-compliant error responses with error codes, context details, and recovery suggestions. A `handle_mcp_exception` decorator standardizes error handling for tool functions.

```python
# From exceptions.py
class MCPException(Exception):
    def __init__(self, message, error_code, details=None, recovery_suggestion=None):
        self.error_code = error_code
        self.recovery_suggestion = recovery_suggestion

    def to_mcp_response(self):
        content = f"Error ({self.error_code.value})\n\n{self.message}"
        if self.recovery_suggestion:
            content += f"\n\nSuggestion: {self.recovery_suggestion}"
        return [{"type": "text", "text": content}]
```

### MCPServerAdapter for In-Process Tool Execution

The `MCPServerAdapter` implements a `ToolExecutor` interface so chatbots running inside the same process can call MCP tools directly without network overhead. It handles the async-to-sync bridge by detecting whether an event loop is already running and spawning a new thread if needed.

```python
# From mcp_tools_adapter.py — async bridge pattern
class MCPServerAdapter(ToolExecutor):
    def call_tool(self, tool_name, arguments):
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            # Already in async context — run in separate thread with new event loop
            result_future = concurrent.futures.Future()
            def run_in_thread():
                new_loop = asyncio.new_event_loop()
                tool = new_loop.run_until_complete(self.mcp_server.mcp.get_tool(tool_name))
                result = new_loop.run_until_complete(tool.run(arguments))
                result_future.set_result(result)
            thread = threading.Thread(target=run_in_thread)
            thread.start(); thread.join()
            result = result_future.result()
        else:
            tool = asyncio.run(self.mcp_server.mcp.get_tool(tool_name))
            result = asyncio.run(tool.run(arguments))
```

### STDIO Server for Claude Desktop / Cursor IDE

A dedicated entry point (`stdio_server.py`) runs the MCP server over stdio for local AI IDE integration. It suppresses all print statements, disables logging, and redirects stderr to `/dev/null` to avoid corrupting the JSON-RPC pipe.

```python
# From stdio_server.py — print suppression for clean stdio
builtins.print = silent_print
sys.stderr = open(os.devnull, 'w')
logging.disable(logging.CRITICAL)
os.environ["FASTMCP_NO_BANNER"] = "1"
server = ObservabilityMCPServer()
sys.stdout = original_stdout  # restore for JSON-RPC
server.mcp.run(transport="stdio", show_banner=False)
```

### Eager Metrics Catalog Initialization

The metrics catalog (1877 OpenShift metrics from a base JSON catalog) is loaded eagerly at module import time in `api.py`, so GPU discovery and validation happen at startup rather than on first query.

```python
# From api.py
from core.metrics_catalog import get_metrics_catalog
_catalog = get_metrics_catalog()
_catalog.is_available()
```

## Configuration

- **Environment variables:**
  - `MCP_HOST` / `MCP_PORT`: Bind address (default `0.0.0.0:8085`)
  - `MCP_TRANSPORT_PROTOCOL`: `http` (default), `sse`, or `streamable-http`
  - `MCP_SSL_KEYFILE` / `MCP_SSL_CERTFILE`: TLS cert paths (auto-set by Helm when `tls.enabled`)
  - `PROMETHEUS_URL`: Thanos/Prometheus endpoint (default `https://thanos-querier.openshift-monitoring.svc.cluster.local:9091`)
  - `TEMPO_URL`: Tempo gateway URL, `TEMPO_TENANT_ID`: tenant (default `dev`)
  - `KORREL8R_URL`: Korrel8r correlation service URL
  - `THANOS_TOKEN`: ServiceAccount token for Prometheus/Thanos auth (injected from secret)
  - `MAX_TIME_RANGE_DAYS` / `DEFAULT_TIME_RANGE_DAYS`: Query time range limits (90 / 7)
  - `MAX_NUM_LOG_ROWS` / `MAX_NUM_TRACE_SPANS`: Result limits (10 / 10)
  - `TRACE_FETCH_SAFETY_FACTOR`: Multiplier for trace fetching (default 2, tune by error rate)
  - `MODEL_CONFIG`: JSON map of LLM provider configs (loaded from `model-config.json` or values override)
  - `LLAMA_STACK_URL`: Llama Stack inference endpoint
  - `DEV_MODE`: Enables browser-cached API keys
  - `GPU_METRICS_PREFIX_NVIDIA` / `_INTEL` / `_AMD`: Custom GPU metric prefixes
  - `MAAS_API_URL`: Model-as-a-Service endpoint
  - `CORS_ORIGINS`: Allowed CORS origins (default localhost:5173, localhost:3000)

- **Config files:**
  - `src/mcp_server/data/openshift-metrics-base.json`: Base catalog of 1877 OpenShift metrics (GPU metrics discovered at runtime)
  - `deploy/helm/mcp-server/model-config.json`: Default model provider configurations
  - `src/mcp_server/integrations/claude-desktop-config.json`: Template for Claude Desktop MCP config

- **Helm values:** Key overrides in `deploy/helm/mcp-server/values.yaml`:
  - `image.repository` / `image.tag`: Container image coordinates
  - `tls.enabled`: Enables OpenShift serving-cert TLS (default true)
  - `trustedCA.enabled`: Mounts OpenShift service CA bundle for HTTPS verification
  - `rbac.createGrafanaRole`: Creates ClusterRole for Prometheus/Alertmanager API access
  - `rbac.lokiReleaseName`: Loki release name for log tenant binding
  - `modelConfig`: Override model config JSON inline (null = read from chart file)

## Known Gotchas

- **MCP app must be mounted last at root:** All FastAPI route definitions (health, config, report endpoints) must appear before `app.mount("/", mcp_app)`. Routes added after the mount are silently swallowed. The codebase enforces this with `_enforce_no_routes_after_mount()` which replaces `app.add_route` with a function that raises `RuntimeError`.

- **Async-to-sync bridge in MCPServerAdapter:** When calling MCP tools from synchronous chatbot code inside an already-running event loop (uvicorn), the adapter must spawn a new thread with its own event loop. Using `asyncio.run()` inside a running loop raises `RuntimeError`.

- **STDIO mode requires aggressive output suppression:** The `stdio_server.py` replaces `builtins.print` with a no-op and redirects stderr to `/dev/null` because FastMCP and third-party libraries emit startup banners that corrupt the JSON-RPC pipe. The `FASTMCP_NO_BANNER=1` env var alone is insufficient.

- **TRACE_FETCH_SAFETY_FACTOR tuning:** The trace analyzer fetches `MAX_NUM_TRACE_SPANS * TRACE_FETCH_SAFETY_FACTOR` traces then filters for errors. Low error-rate workloads need a higher factor (3-5) or they may return zero error traces. This is documented in `values.yaml` comments.

- **Thanos token from ServiceAccount secret:** The deployment mounts the `mcp-analyzer` ServiceAccount token secret at `/var/run/secrets/kubernetes.io/serviceaccount` and injects it as `THANOS_TOKEN` env var. This is a long-lived token (not projected) created via the `kubernetes.io/service-account-token` type secret annotation.

- **TLS with `service.beta.openshift.io/serving-cert-secret-name`:** When `tls.enabled=true`, the Service annotation triggers automatic TLS cert generation by OpenShift. The Route must use `reencrypt` termination since the server runs HTTPS internally. The ConfigMap for the trusted CA bundle uses the `service.beta.openshift.io/inject-cabundle` annotation to get the service CA injected.

- **Force reconfigure loggers after FastMCP init:** FastMCP initialization overrides Python logging config. The code calls `force_reconfigure_all_loggers()` after `FastMCP()` init to restore the desired log configuration (from `observability_mcp.py`).

- **Uvicorn `timeout_keep_alive=300`:** Set to 5 minutes in `main.py` to accommodate long-running AI analysis requests that can take several minutes for LLM summarization.

## Testing Notes

- CLI provides `--test-config` to validate required env vars (`PROMETHEUS_URL` must be set)
- Health check endpoint: `GET /health` returns service status, transport protocol, and available endpoints
- `GET /config` returns runtime config including `devMode` flag
- Helm liveness probe: `curl -f -k https://0.0.0.0:8085/health` with 30s initial delay, 60s period, 6 failure threshold
- Helm readiness probe: same URL with 10s initial delay, 20s period, 5 failure threshold
- Console scripts installed via `setup.py`: `obs-mcp-server` (CLI/HTTP) and `obs-mcp-stdio` (stdio mode)

## Related Patterns

- `chatbots/tool_executor.py` defines the `ToolExecutor` interface that `MCPServerAdapter` implements
- `core/metrics_catalog.py` provides the metrics catalog loaded at startup
- `core/chat_with_prometheus.py` contains the Prometheus business logic called by tool functions
- RBAC setup in `crb.yaml` grants `cluster-monitoring-view`, `grafana-prometheus-reader`, `korrel8r-view`, Loki tenant log access, and `inferenceservice-viewer` ClusterRoles
