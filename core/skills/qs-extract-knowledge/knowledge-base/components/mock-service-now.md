---
name: mock-service-now
description: "FastAPI mock server emulating ServiceNow REST API for agent testing in IT self-service quickstarts"
summary: "Provides a FastAPI mock server emulating ServiceNow's Table API (sys_user email lookup, cmdb_ci_computer assigned_to lookup, sc_req_item always-empty) and Service Catalog order_now endpoint for developing and testing agentic IT self-service workflows without a real ServiceNow instance. Use when building agent-driven IT quickstarts needing ServiceNow integration during development and CI -- toggled via `mockServiceNow.enabled` Helm flag; the mock accepts optional `x-sn-apikey` via `APIKeyHeader(auto_error=False)` so agent code uses identical auth headers against mock and production. Built on UBI9 python-312 via shared `Containerfile.services-template` with `SERVICE_NAME`/`MODULE_NAME` build args; employee data loaded from `mock-employee-data` local dependency at import time, extendable via `TEST_USERS` comma-separated env var for CI injection; health check at `/health` returns `{\"status\":\"OK\",\"service\":\"mock-servicenow\"}`. Gotchas: `sysparm_query` parser uses simple prefix matching only (no compound `^`/`^OR` queries), `TEST_USERS` is cached at module level so runtime changes require process restart, and `SERVICENOW_INSTANCE_URL` must match the Helm-generated Service name (default `http://self-service-agent-mock-servicenow:8080`) for in-cluster agent resolution."
metadata:
  type: component
tags:
  tech_stack: [fastapi, python, uvicorn, pydantic]
  ai_pattern: [agents]
  platform: [openshift]
source_examples:
  - quickstart: "it-self-service-agent"
    repo: "https://github.com/rh-ai-quickstart/it-self-service-agent"
    notes: "Mock ServiceNow server providing Table API and Service Catalog endpoints for agentic laptop-refresh workflows"
    approach: "A"
---

# Mock ServiceNow Server

## Overview

A lightweight FastAPI server that emulates ServiceNow's REST API surface for testing and development of agentic IT self-service workflows. It provides mock endpoints for the Table API (`sys_user`, `cmdb_ci_computer`, `sc_req_item`) and the Service Catalog `order_now` endpoint, backed by an in-memory dataset of employee and asset records. This component allows the agent to be developed and tested without access to a real ServiceNow instance, and is toggled on/off via a Helm values flag.

## Tech Stack & Dependencies

- **Runtime:** Python 3.12 / FastAPI >= 0.100.0
- **Container image:** Built via shared `Containerfile.services-template` using `registry.access.redhat.com/ubi9/python-312:9.7` (builder) and `ubi9/python-312-minimal:9.7` (prod)
- **Key dependencies:**
  - `mock-employee-data` (local path dependency) -- provides the in-memory employee dataset
  - `self-service-agent-shared-models` (local path dependency) -- provides `configure_logging` (structlog-based)
  - `uvicorn[standard]` for ASGI serving
  - `pydantic >= 2.0.0` for request/response models
- **Helm subchart:** None -- deployed as a Deployment + ClusterIP Service via the parent `self-service-agent` Helm chart, gated by `mockServiceNow.enabled`

## Key Patterns

### ServiceNow Table API Emulation

The server mimics ServiceNow's Table API query parameter conventions. Queries use `sysparm_query` with simple `field=value` format, parsed by prefix-stripping rather than a full query parser.

```python
# server.py -- parsing sysparm_query for email lookup
sysparm_query = query_params.get("sysparm_query", "")
email = None
if sysparm_query.startswith("email="):
    email = sysparm_query[6:]  # Remove "email=" prefix
```

Endpoints exposed:
- `GET /api/now/table/sys_user` -- user lookup by email via `sysparm_query`
- `GET /api/now/table/cmdb_ci_computer` -- computer lookup by `assigned_to` user sys_id
- `GET /api/now/table/sc_req_item` -- always returns empty result set
- `POST /api/sn_sc/servicecatalog/items/{item_id}/order_now` -- laptop refresh ticket creation

### Optional API Key Authentication

The mock server accepts an optional `x-sn-apikey` header via FastAPI's `APIKeyHeader` security scheme but does not enforce validation. This allows the agent code to include the same authentication headers it would use against a real ServiceNow instance without blocking during development.

```python
# server.py -- API key is optional (auto_error=False)
api_key_header = APIKeyHeader(name="x-sn-apikey", auto_error=False)

def get_api_key(api_key: Optional[str] = Security(api_key_header)) -> Optional[str]:
    # For mock server, we accept any API key or no API key
    return api_key
```

### Shared Containerfile Template for Multi-Service Builds

All Python services in this quickstart share a single `Containerfile.services-template` that takes `SERVICE_NAME` and `MODULE_NAME` as build args. The Makefile wires this for mock-service-now:

```makefile
build-mock-servicenow-image: check-lockfile-mock-servicenow check-deps-services-template
	$(call build_template_image,$(MOCK_SERVICENOW_IMG),mock ServiceNow server image,\
	  Containerfile.services-template,mock-service-now,mock_servicenow.server,.)
```

### Dynamic Test User Injection via Environment Variable

The `mock-employee-data` library supports extending the in-memory dataset at startup through the `TEST_USERS` environment variable (comma-separated emails). This enables CI/E2E tests to inject custom user identities without rebuilding the image.

```python
# mock-employee-data/data.py -- TEST_USERS augmentation
test_users_env = os.getenv("TEST_USERS")
if not test_users_env:
    return result
test_emails = [email.strip() for email in test_users_env.split(",") if email.strip()]
for idx, email in enumerate(test_emails):
    if email.lower() in result:
        continue
    employee_id = 9001 + idx
    user_data = _generate_user_data_for_email(email, employee_id)
    result[email.lower()] = user_data
```

## Configuration

- **Environment variables:**
  - `PORT` -- server listen port (default `8080`)
  - `HOST` -- bind address (default `0.0.0.0`)
  - `LOG_LEVEL` -- logging verbosity (default `INFO`)
  - `TEST_USERS` -- comma-separated emails to dynamically add to mock data
  - `UVICORN_WORKERS` -- optional multi-worker concurrency
- **Config files:** None -- all configuration via env vars
- **Helm values:**
  - `mockServiceNow.enabled` -- toggle the entire deployment (default `true`)
  - `mockServiceNow.replicas` -- replica count (default `1`)
  - `mockServiceNow.logLevel` -- forwarded as `LOG_LEVEL` env var
  - `mockServiceNow.testUsers` -- forwarded as `TEST_USERS` env var
  - `mockServiceNow.uvicornWorkers` -- forwarded as `UVICORN_WORKERS` env var
  - `mockServiceNow.resources` -- Kubernetes resource requests/limits
  - `mockServiceNow.healthChecks` -- configurable liveness/readiness probe timings

## Known Gotchas

- The `sysparm_query` parser uses simple prefix matching (`startswith("email=")`, `startswith("assigned_to=")`) rather than supporting ServiceNow's full query syntax. Compound queries with `^` (AND) or `^OR` operators will not parse correctly -- only single-field lookups work.
- The `sc_req_item` endpoint always returns an empty result regardless of query parameters (by design, as noted in the source comment: "For simplicity, it always returns an empty result set").
- Employee data is cached at module level (`EMPLOYEE_DATA = get_employee_data()`) meaning `TEST_USERS` is only read once at import time. Changing the env var at runtime without restarting the process has no effect.
- The `SERVICENOW_INSTANCE_URL` Makefile variable defaults to `http://self-service-agent-mock-servicenow:8080` -- this must match the Helm-generated Service name to ensure agents resolve the mock correctly within the cluster.

## Testing Notes

- Tests use FastAPI's `TestClient` (backed by `httpx`) and run synchronously against the app without starting a real server.
- Health check: `GET /health` returns `{"status": "OK", "service": "mock-servicenow"}`.
- The test suite validates user lookup, computer lookup, ticket creation, missing variable error handling, and optional API key behavior.
- Run tests via `make test-mock-servicenow` or directly with `pytest` from the `mock-service-now/` directory.

## Related Patterns

- `components/mcp-servers.md` -- MCP server that wraps these mock endpoints for agent tool use
- `components/fastapi-backend.md` -- shared FastAPI patterns across quickstarts
