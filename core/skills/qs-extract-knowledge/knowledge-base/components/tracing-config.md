---
name: tracing-config
description: Shared OpenTelemetry tracing/metrics library wired as a local Python package across all microservices
summary: "Centralizes OpenTelemetry tracing and metrics across Python microservices via a shared Hatchling-built package (Python >=3.12) distributed as a uv workspace local path dependency (`path = \"../tracing-config\"`), activated per-service with a single `auto_tracing_run(SERVICE_NAME, logger)` call that silently skips when `OTEL_EXPORTER_OTLP_ENDPOINT` is unset. Use this single-approach pattern when multiple services need unified distributed tracing without a package registry -- the library configures OTLPSpanExporter and OTLPMetricExporter over HTTP (appending `/v1/traces` and `/v1/metrics` to the base endpoint), sets W3C TraceContext propagation via `set_global_textmap(TraceContextTextMapPropagator())`, auto-instruments HTTPX clients, and pairs with a companion `@trace_mcp_tool()` decorator in mcp-common for MCP server span creation with parent context extraction. Critical config: Helm conditionally injects `OTEL_EXPORTER_OTLP_ENDPOINT` via the `otelExporter` value in deployment templates; the agent-service guards header injection with `tracingIsActive()` before calling `inject(tool_headers)` to propagate trace context to MCP servers. Gotchas: metrics export interval is hardcoded to 60s (`PeriodicExportingMetricReader` with `export_interval_millis=60000`) and not env-configurable, HTTPX auto-instrumentation cannot be selectively disabled producing high span volume, only mock-eventing-service and mock-servicenow Helm templates wire the `otelExporter` conditional (other services need manual env var injection), and mypy requires `disable_error_code = [\"attr-defined\"]` for OpenTelemetry's dynamic provider pattern."
metadata:
  type: component
tags:
  tech_stack: [python, opentelemetry, otlp, httpx]
  ai_pattern: [agents]
  platform: [openshift, kubernetes]
source_examples:
  - quickstart: "it-self-service-agent"
    repo: "https://github.com/rh-ai-quickstart/it-self-service-agent"
    notes: "Shared tracing-config package consumed by all services via local path dependencies"
    approach: "A"
---

# Tracing Config

## Overview

A shared Python package (`tracing-config`) that provides centralized OpenTelemetry tracing and metrics configuration for all microservices in the quickstart. It is distributed as a local path dependency rather than a published package, enabling every service to activate distributed tracing with a single function call. Tracing is opt-in: it only activates when the `OTEL_EXPORTER_OTLP_ENDPOINT` environment variable is set, so deployments without an OTLP collector work unaffected.

## Tech Stack & Dependencies

- **Runtime:** Python >= 3.12 (`.python-version` targets 3.13)
- **Build system:** Hatchling
- **Key dependencies:**
  - `opentelemetry-api` >= 1.37.0
  - `opentelemetry-sdk` >= 1.37.0
  - `opentelemetry-exporter-otlp-proto-http` >= 1.37.0
  - `opentelemetry-instrumentation-httpx` >= 0.58b0
  - `protobuf` >= 6.33.5
- **Helm subchart:** None (library only; OTLP endpoint injected via Helm `otelExporter` value)

## Key Patterns

### Opt-In Auto-Tracing via Environment Variable

The core pattern: each service calls `auto_tracing_run(SERVICE_NAME, logger)` at module level. If `OTEL_EXPORTER_OTLP_ENDPOINT` is unset, tracing is silently skipped.

```python
# From tracing-config/src/tracing_config/auto_tracing.py
def tracingIsActive() -> bool:
    return bool(os.environ.get(OTEL_EXPORTER_OTLP_ENDPOINT))

def run(service_name: str, logger: typing.Any) -> None:
    otel_exporter_endpoint = os.environ.get(OTEL_EXPORTER_OTLP_ENDPOINT)
    if not otel_exporter_endpoint:
        logger.info("OTEL exporter endpoint not provided -- skip auto tracing config.")
        return
```

### Service-Level Activation

Every service follows the same two-line pattern at module level, before any request handling:

```python
# From agent-service/src/agent_service/main.py
SERVICE_NAME = "agent-service"
logger = configure_logging(SERVICE_NAME)
auto_tracing_run(SERVICE_NAME, logger)
```

This is replicated across agent-service, integration-dispatcher, request-manager, mock-eventing-service, and both MCP servers (snow, zammad).

### Local Path Dependency Distribution

The package is consumed via `uv` workspace local path references in each service's `pyproject.toml`, avoiding the need for a package registry:

```toml
# From agent-service/pyproject.toml
[tool.uv.sources]
tracing-config = { path = "../tracing-config" }
```

The `mypy_path` is also extended to include the tracing-config source:

```toml
mypy_path = "../shared-models/src:../shared-clients/src:../tracing-config/src"
```

### OTLP HTTP Exporter with Separate Trace and Metric Endpoints

The library configures both tracing and metrics export over HTTP, appending `/v1/traces` and `/v1/metrics` to the base endpoint:

```python
# From tracing-config/src/tracing_config/auto_tracing.py
otlp_trace_exporter = OTLPSpanExporter(
    endpoint=f"{otel_exporter_endpoint}/v1/traces",
)
otlp_metric_exporter = OTLPMetricExporter(
    endpoint=f"{otel_exporter_endpoint}/v1/metrics",
)
metric_reader = PeriodicExportingMetricReader(
    exporter=otlp_metric_exporter,
    export_interval_millis=60000,  # Export every 60 seconds
)
```

### W3C Trace Context Propagation

The library sets the global propagator to W3C TraceContext, enabling distributed tracing across service boundaries:

```python
# From tracing-config/src/tracing_config/auto_tracing.py
set_global_textmap(TraceContextTextMapPropagator())
```

The agent-service injects trace headers when calling MCP servers:

```python
# From agent-service/src/agent_service/langgraph/responses_agent.py
if tracingIsActive():
    inject(tool_headers)
```

### MCP Tool Tracing Decorator

The companion `mcp-common` package builds on `tracing-config` to provide a `@trace_mcp_tool()` decorator that wraps MCP tool calls with OpenTelemetry spans, extracting parent context from HTTP headers:

```python
# From mcp-servers/mcp-common/src/mcp_common/tracing.py
@mcp.tool()
@trace_mcp_tool()
def open_laptop_refresh_ticket(employee_name: str, ...):
```

The decorator records tool arguments as span attributes and propagates parent context from incoming HTTP headers for cross-service trace correlation.

## Configuration

- **Environment variables:**
  - `OTEL_EXPORTER_OTLP_ENDPOINT` -- Base URL for the OTLP collector (e.g., `http://jaeger:4318`). When unset, tracing is completely disabled.
- **Helm values:**
  - `otelExporter` -- Conditionally injects `OTEL_EXPORTER_OTLP_ENDPOINT` into deployment pods:

```yaml
# From helm/templates/mock-eventing-service-deployment.yaml
{{- if .Values.otelExporter }}
- name: OTEL_EXPORTER_OTLP_ENDPOINT
  value: {{ .Values.otelExporter }}
{{- end }}
```

## Known Gotchas

- **Metrics export interval is hardcoded to 60 seconds** in `auto_tracing.py` (`export_interval_millis=60000`). This is not configurable via environment variable. Services needing faster export would need to modify the library.
- **HTTPX auto-instrumentation is always enabled** when tracing is active (`HTTPXClientInstrumentor().instrument()`). This means all outgoing HTTP calls from any service are traced automatically, which may produce high span volume.
- **mypy requires `disable_error_code = ["attr-defined"]`** for `tracing_config.*` due to the OpenTelemetry SDK's dynamic provider pattern (e.g., `trace.get_tracer_provider().add_span_processor(...)` where the returned type does not statically expose `add_span_processor`).
- **Only two Helm deployments wire the OTEL endpoint** -- `mock-eventing-service` and `mock-servicenow`. Other services (agent-service, request-manager, etc.) do not have the `otelExporter` conditional in their Helm templates, so they would need the env var set by other means (e.g., pod-level config or operator injection).

## Testing Notes

- Set `OTEL_EXPORTER_OTLP_ENDPOINT` to a local Jaeger or OTEL Collector instance to verify spans appear
- With the env var unset, confirm services start without tracing errors (the skip log message should appear)
- Check that cross-service traces show connected spans by verifying `traceparent` header propagation between agent-service and MCP servers

## Related Patterns

- `observability-stack.md` -- full observability deployment (collectors, dashboards)
- `mcp-servers.md` -- MCP server architecture that consumes the `@trace_mcp_tool()` decorator
