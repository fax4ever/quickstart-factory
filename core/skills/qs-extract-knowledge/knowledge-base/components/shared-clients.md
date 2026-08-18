---
name: shared-clients
description: Shared Python client library providing async HTTP clients for inter-service communication in agentic quickstarts
summary: "Centralizes async HTTP service-to-service communication for multi-service agentic quickstarts via a base ServiceClient (httpx[http2] with HTTP/2, 20-keepalive/100-max connection pooling, compression) with specialized clients for Request Manager, Integration Dispatcher, Zammad REST, CLI chat, and LlamaStack stream processing. Use when building multi-service agentic architectures that need shared HTTP clients with global singleton lifecycle management — consumed as a uv local path dependency built with hatchling and integrated into containers via PYTHONPATH (not pip install), depends on pydantic, structlog, and shared-models sibling package. Two distinct RequestManagerClient classes exist in the same package: standalone (request_manager_client.py, default http://localhost:8080, 180s timeout, x-user-id header) for CLI/tests vs internal (service_client.py, inherits ServiceClient, default http://self-service-agent-request-manager:80) for inter-service calls; global singletons initialized via initialize_service_clients() configured by REQUEST_MANAGER_URL, INTEGRATION_DISPATCHER_URL, and ZAMMAD_URL env vars. The two same-named RequestManagerClient classes in different modules cause import confusion despite __init__.py exporting both under distinct names; httpx logger is globally suppressed to WARNING at module import time; Zammad singleton recreates its client when ZAMMAD_URL changes at runtime; LlamaStackStreamProcessor handles both prompt_tokens/completion_tokens and input_tokens/output_tokens attribute names for cross-version compatibility."
metadata:
  type: component
tags:
  tech_stack: [python, httpx, pydantic, structlog, hatchling]
  ai_pattern: [agents]
  platform: [openshift]
  data_layer: []
source_examples:
  - quickstart: "it-self-service-agent"
    repo: "https://github.com/rh-ai-quickstart/it-self-service-agent"
    notes: "Shared client package providing ServiceClient base, RequestManagerClient, IntegrationDispatcherClient, CLIChatClient, and LlamaStack stream processor across a multi-service agentic architecture"
    approach: "A"
---

# Shared Clients

## Overview

Shared Clients is a local Python package that centralizes async HTTP client logic for service-to-service communication in multi-service agentic quickstarts. It provides a base `ServiceClient` with HTTP/2, connection pooling, and compression, plus specialized clients for the Request Manager, Integration Dispatcher, Zammad REST API, and a CLI chat harness. It also includes a unified stream processor for LlamaStack streaming responses with token usage tracking. The package is installed as a path dependency via `uv` and copied into container images alongside the services that consume it.

## Tech Stack & Dependencies

- **Runtime:** Python >= 3.12
- **Build system:** Hatchling (`hatch.build.targets.wheel`)
- **Key dependencies:**
  - `httpx[http2]>=0.25.0` (async HTTP with HTTP/2)
  - `structlog>=23.2.0` (structured logging)
  - `pydantic>=2.5.0` (data validation)
  - `self-service-agent-shared-models` (sibling local package)
- **Container image:** Not a standalone image; copied into service containers via `Containerfile.services-template`
- **Helm subchart:** None (library package, not a deployable service)

## Key Patterns

### Base ServiceClient with HTTP/2 and Connection Pooling

The `ServiceClient` class configures `httpx.AsyncClient` with HTTP/2, keepalive connection pooling, and compression by default. All specialized clients inherit from it.

```python
# shared-clients/src/shared_clients/service_client.py
class ServiceClient:
    def __init__(self, base_url: str, timeout: float = 30.0, verify_ssl: bool = True):
        self.base_url = base_url.rstrip("/")
        self.client = httpx.AsyncClient(
            timeout=timeout,
            verify=verify_ssl,
            follow_redirects=True,
            limits=httpx.Limits(max_keepalive_connections=20, max_connections=100),
            http2=True,
            headers={"Accept-Encoding": "gzip, deflate, br"},
        )
```

### Global Singleton Client Management

Service clients are managed as module-level singletons with explicit `initialize_service_clients()` and `cleanup_service_clients()` lifecycle functions. This avoids creating new HTTP connections per request.

```python
# shared-clients/src/shared_clients/service_client.py
_request_manager_client: Optional[RequestManagerClient] = None
_integration_dispatcher_client: Optional[IntegrationDispatcherClient] = None

def initialize_service_clients(
    request_manager_url: Optional[str] = None,
    integration_dispatcher_url: Optional[str] = None,
    integration_timeout: float = 30.0,
) -> None:
    global _request_manager_client, _integration_dispatcher_client
    _request_manager_client = RequestManagerClient(base_url=request_manager_url, timeout=integration_timeout)
    _integration_dispatcher_client = IntegrationDispatcherClient(base_url=integration_dispatcher_url, timeout=integration_timeout)
```

### Zammad REST Singleton with URL Change Detection

The Zammad REST client is a separate singleton that recreates itself when the `ZAMMAD_URL` env var changes, supporting test isolation without leaking connections.

```python
# shared-clients/src/shared_clients/service_client.py
_zammad_rest_client: Optional[ServiceClient] = None
_zammad_rest_client_canon: Optional[str] = None

async def get_zammad_rest_service_client() -> Optional[ServiceClient]:
    global _zammad_rest_client, _zammad_rest_client_canon
    raw = (os.getenv("ZAMMAD_URL") or "").strip()
    if not raw:
        return None
    canon = normalize_zammad_rest_api_base(raw)
    if _zammad_rest_client is not None and _zammad_rest_client_canon == canon:
        return _zammad_rest_client
    # Recreate if URL changed
    if _zammad_rest_client is not None:
        await _zammad_rest_client.close()
    _zammad_rest_client = ServiceClient(canon, timeout=30.0)
    _zammad_rest_client_canon = canon
    return _zammad_rest_client
```

### Two RequestManagerClient Classes with Different Roles

There are two distinct `RequestManagerClient` classes in separate modules, serving different roles:

1. **`request_manager_client.py`**: Standalone client for external consumers (CLI, tests). Uses `x-user-id` header, supports conversation queries, 180s default timeout.
2. **`service_client.py`**: Internal `RequestManagerClient(ServiceClient)` for service-to-service calls (e.g., integration-dispatcher forwarding web/cli requests). Defaults to in-cluster URL `http://self-service-agent-request-manager:80`.

### CLIChatClient with Test Mode

`CLIChatClient` extends the standalone `RequestManagerClient` with an interactive chat loop that supports both interactive terminal input and automated test mode (reading from stdin). It handles special commands like `**tokens**` for token usage reporting.

```python
# shared-clients/src/shared_clients/request_manager_client.py
class CLIChatClient(RequestManagerClient):
    async def chat_loop(
        self,
        initial_message: str | None = None,
        test_mode: bool = False,
    ) -> None:
        if test_mode:
            import sys
            for line in sys.stdin:
                message = line.strip()
                if not message:
                    continue
                should_continue = await self._process_message(message, test_mode=True)
                if not should_continue:
                    break
```

### LlamaStack Stream Processor

`LlamaStackStreamProcessor` provides a unified static method for processing LlamaStack streaming responses, handling both old (`chunk.event.payload`) and new (`chunk.event` with `event_type`) event structures. It extracts token usage from `turn_complete` events and supports content/error/tool-call callbacks.

```python
# shared-clients/src/shared_clients/stream_processor.py
class LlamaStackStreamProcessor:
    @staticmethod
    async def process_stream(
        response_stream: Any,
        on_content: Optional[Callable[[str], None]] = None,
        on_error: Optional[Callable[[str], None]] = None,
        on_tool_call: Optional[Callable[[str], None]] = None,
        collect_content: bool = True,
    ) -> Dict[str, Any]:
        # Returns dict with: content, tool_calls_made, errors, token_usage, stop_reason, etc.
```

### Monorepo Local Path Dependencies via uv

The package is consumed by other services as a local `uv` path dependency. Each consuming service's `pyproject.toml` declares the dependency and `[tool.uv.sources]` maps it to the relative path.

```toml
# agent-service/pyproject.toml
[project]
dependencies = [
    "self-service-agent-shared-clients",
]

[tool.uv.sources]
self-service-agent-shared-clients = { path = "../shared-clients" }
```

### Container PYTHONPATH Integration

The shared-clients package is copied into container images and made available via `PYTHONPATH` rather than pip-installed as a wheel.

```dockerfile
# Containerfile.services-template
COPY shared-clients ./shared-clients/
ENV PYTHONPATH="/usr/lib64/python3.12:${VIRTUAL_ENV}/lib/python3.12/site-packages:/app/agent-service/src:/app/shared-models/src:/app/shared-clients/src:/app/src:/app/tracing-config/src:$PYTHONPATH"
```

## Configuration

- **Environment variables:**
  - `REQUEST_MANAGER_URL`: URL of the Request Manager service (standalone client default: `http://localhost:8080`; service client default: `http://self-service-agent-request-manager:80`)
  - `INTEGRATION_DISPATCHER_URL`: URL of the Integration Dispatcher (default: `http://self-service-agent-integration-dispatcher:8080`)
  - `ZAMMAD_URL`: URL for Zammad REST API; when empty, the Zammad client returns `None`
  - `AGENT_MESSAGE_TERMINATOR`: Optional terminator string appended after agent responses in test mode
- **Config files:** None (configuration via environment variables and constructor args)
- **Helm values:** None (library package, not directly deployed via Helm)

## Known Gotchas

- **Two `RequestManagerClient` classes exist in the same package**: `request_manager_client.py` has a standalone version for CLI/test consumers, while `service_client.py` has an internal version inheriting from `ServiceClient`. They have different default URLs and different APIs. The `__init__.py` exports both under distinct names but the class name collision could cause confusion if importing from the wrong module.
- **Zammad client URL change detection**: The `get_zammad_rest_service_client()` function compares the current `ZAMMAD_URL` env var against a cached canonical URL on every call. If the env var changes at runtime (e.g., in tests), the old client is closed and a new one is created. This is by design per the docstring: "Recreates the client when ZAMMAD_URL changes (e.g. tests)."
- **httpx logging suppressed**: The standalone `RequestManagerClient` in `request_manager_client.py` explicitly sets `logging.getLogger("httpx").setLevel(logging.WARNING)` at module import time, which affects the global httpx logger for any code that imports this module.
- **Token usage extraction handles multiple attribute names**: The `_extract_token_usage` method tries both `prompt_tokens`/`completion_tokens` and `input_tokens`/`output_tokens` attribute names to handle different LlamaStack versions.

## Testing Notes

- The package includes a smoke test (`tests/test_import.py`) that verifies the package can be imported and `__all__` is populated.
- Integration tests live outside the package in `test/` directory (e.g., `test/chat-responses-request-mgr.py`, `test/get-conversations-request-mgr.py`) and use `CLIChatClient` and `RequestManagerClient` against a running Request Manager.
- `pytest.ini_options` in `pyproject.toml` sets `asyncio_mode = "auto"` for async test support.

## Related Patterns

- Sibling shared package: `shared-models` (provides `configure_logging`, `normalize_zammad_rest_api_base`, and other shared utilities)
- Consumers: `agent-service`, `integration-dispatcher`, `evaluations`, and integration test scripts
