---
name: postgres-mcp
description: "MCP proxy exposing PostgreSQL as LangChain tools via SSE transport with app_config_id scoping guard"
summary: "Exposes PostgreSQL as LangChain-compatible agent tools via the pre-built crystaldba/postgres-mcp container running as a Kubernetes Deployment with --access-mode=restricted and --transport=sse, enabling LangGraph agent graphs to execute SQL without custom MCP server code. Use when agents need structured SQL access to PostgreSQL with per-request data isolation -- prefer this turnkey container over custom FastMCP servers when the standard execute_sql tool suffices and the contextvars.ContextVar app_config_id scoping-guard pattern meets multi-tenant filtering needs across shared LangGraph pipelines (chat and alert graphs). Backend connects via langchain-mcp-adapters MultiServerMCPClient to http://<release>-postgres-mcp:<port>/sse; load_execute_sql_tool() loads all MCP tools, keeps only execute_sql as a StructuredTool, and wraps it with a guard that rejects queries touching detection_classes/detection_tracks/detection_observations without exact \"app_config_id = {id}\" filter, using ContextVar token set/reset with try/finally around each graph invocation. Scoping guard uses substring matching so table names appearing as substrings of other identifiers trigger false rejections, only the exact = operator is accepted (LIKE/IN rejected even if semantically equivalent), busybox nc -z init containers must enforce startup ordering (PostgreSQL -> postgres-mcp -> backend), and the entire MCP layer is conditionally gated on postgresMcp.enabled in Helm values."
metadata:
  type: component
tags:
  tech_stack: [python, mcp, langchain, langchain-mcp-adapters, postgresql]
  ai_pattern: [agents, mcp-tools]
  platform: [openshift, kubernetes]
  data_layer: [postgresql]
source_examples:
  - quickstart: "multimodal-compliance-monitor"
    repo: "https://github.com/rh-ai-quickstart/multimodal-compliance-monitor"
    notes: "Pre-built postgres-mcp container deployed as sidecar proxy, consumed by LangGraph chat and alert agents via langchain-mcp-adapters SSE client with SQL scoping guard"
    approach: "A"
---

# Postgres MCP

## Overview

A pre-built MCP (Model Context Protocol) server that exposes PostgreSQL database operations as tools consumable by AI agents over SSE transport. In the multimodal-compliance-monitor quickstart, it runs as a separate Deployment alongside a PostgreSQL instance and is consumed by the backend's LangGraph agent graphs (chat and alert pipelines) through the `langchain-mcp-adapters` library. The backend wraps the `execute_sql` tool with an `app_config_id` scoping guard to enforce per-request data isolation at the SQL level.

## Tech Stack & Dependencies

- **Runtime:** Pre-built container image (`docker.io/crystaldba/postgres-mcp:latest`)
- **Container image:** `docker.io/crystaldba/postgres-mcp`
- **Key dependencies:**
  - PostgreSQL instance (the MCP server connects to it via `DATABASE_URI`)
  - `langchain-mcp-adapters>=0.2.1` on the backend side for consuming MCP tools as LangChain tools
- **Helm subchart:** None (deployed as a Helm template within the parent chart)

## Key Patterns

### Pre-Built Container as MCP Proxy

Rather than implementing a custom MCP server, this quickstart uses the third-party `crystaldba/postgres-mcp` container image as a turnkey proxy that translates MCP tool calls into PostgreSQL queries. The server is configured with `--access-mode=restricted` and `--transport=sse` via container args.

```yaml
# deploy/helm/ppe-compliance-monitor/templates/postgres-mcp.yaml (lines 36-44)
containers:
  - name: postgres-mcp
    image: "{{ .Values.postgresMcp.image.repository }}:{{ .Values.postgresMcp.image.tag }}"
    imagePullPolicy: {{ .Values.postgresMcp.image.pullPolicy }}
    args:
      - "--access-mode={{ .Values.postgresMcp.accessMode }}"
      - "--transport=sse"
    ports:
      - containerPort: {{ .Values.postgresMcp.port }}
        name: sse
```

### Init Container Wait-for-Dependency Pattern

Both the postgres-mcp Deployment and the backend Deployment use busybox init containers with `nc -z` to wait for their upstream dependencies before starting. The postgres-mcp waits for PostgreSQL; the backend waits for postgres-mcp.

```yaml
# deploy/helm/ppe-compliance-monitor/templates/postgres-mcp.yaml (lines 22-34)
initContainers:
  - name: wait-for-postgresql
    image: "{{ .Values.initUtils.busybox.repository }}:{{ .Values.initUtils.busybox.tag }}"
    command:
      - /bin/sh
      - -c
      - |
        echo "Waiting for PostgreSQL..."
        until nc -z {{ .Values.postgresql.host | ... }} {{ .Values.postgresql.port }}; do
          echo "PostgreSQL not ready, retrying in 2s..."
          sleep 2
        done
        echo "PostgreSQL is ready"
```

The backend has a matching init container that waits for the postgres-mcp service:

```yaml
# deploy/helm/ppe-compliance-monitor/templates/backend-deployment.yaml (lines 39-51)
- name: wait-for-postgres-mcp
  image: "{{ .Values.initUtils.busybox.repository }}:{{ .Values.initUtils.busybox.tag }}"
  command:
    - /bin/sh
    - -c
    - |
      echo "Waiting for postgres-mcp on port {{ .Values.postgresMcp.port }}..."
      until nc -z {{ include "ppe-compliance-monitor.fullname" . }}-postgres-mcp {{ .Values.postgresMcp.port }}; do
        echo "postgres-mcp not ready, retrying in 2s..."
        sleep 2
      done
      echo "postgres-mcp is ready"
```

### LangChain MCP Adapters SSE Client

The backend connects to the postgres-mcp server using `langchain-mcp-adapters`' `MultiServerMCPClient` with SSE transport, which converts MCP tools into LangChain `StructuredTool` instances usable in LangGraph agent nodes.

```python
# app/backend/tools/mcp_tools.py (lines 21-30)
POSTGRES_MCP_URL = os.getenv("POSTGRES_MCP_URL")

_mcp_client = MultiServerMCPClient(
    {
        "postgres": {
            "url": POSTGRES_MCP_URL,
            "transport": "sse",
        }
    }
)
```

### SQL Scoping Guard via ContextVar

The `execute_sql` tool from the MCP server is wrapped with a scoping guard that enforces `app_config_id` filtering on detection tables. A `contextvars.ContextVar` carries the per-request config ID, and the wrapper rejects SQL queries that touch scoped tables without the required filter.

```python
# app/backend/tools/mcp_tools.py (lines 32-36, 43-55)
_SCOPED_TABLES = {"detection_classes", "detection_tracks", "detection_observations"}

async def _scoped_execute(sql: str) -> str:
    config_id = current_app_config_id.get()
    if config_id is not None:
        sql_lower = sql.lower()
        touches_scoped = any(t in sql_lower for t in _SCOPED_TABLES)
        has_filter = f"app_config_id = {config_id}" in sql_lower
        if touches_scoped and not has_filter:
            return (
                f"ERROR: Query rejected. You MUST include "
                f"'detection_classes.app_config_id = {config_id}' "
                f"when querying detection tables. Rewrite your query and retry."
            )
    return await original_tool.ainvoke({"sql": sql})
```

The caller (LangGraph graph) sets and resets the context var around each invocation:

```python
# app/backend/chat/graph.py (lines 138, 152)
token = current_app_config_id.set(app_config_id)
try:
    # ... invoke graph ...
finally:
    current_app_config_id.reset(token)
```

### Dual Agent Graph Consumption

The wrapped `execute_sql` tool is loaded once and shared across two LangGraph pipelines: the chat graph (router -> sql_planner -> sql_agent -> sql_answer) and the alert graph (clarifier_planner -> sql_agent). Both use `load_execute_sql_tool()` which loads all MCP tools, wraps `execute_sql`, and discards the rest.

```python
# app/backend/tools/mcp_tools.py (lines 83-92)
async def load_execute_sql_tool() -> StructuredTool:
    """Load only the wrapped ``execute_sql`` tool, dropping all others."""
    all_tools = await load_tools()
    sql_tools = [t for t in all_tools if t.name == "execute_sql"]
    if not sql_tools:
        raise RuntimeError("execute_sql tool not found in postgres-mcp tools")
    return sql_tools[0]
```

## Configuration

- **Environment variables:**
  - `DATABASE_URI` -- On the postgres-mcp container. Constructed from Helm values: `postgresql://{{ user }}:{{ password }}@{{ host }}:{{ port }}/{{ database }}`
  - `POSTGRES_MCP_URL` -- On the backend container. Points to the postgres-mcp SSE endpoint: `http://<release>-postgres-mcp:<port>/sse`
- **Config files:** None; all configuration via Helm values and environment variables
- **Helm values:**
  ```yaml
  # deploy/helm/ppe-compliance-monitor/values.yaml (lines 211-218)
  postgresMcp:
    enabled: true
    image:
      repository: docker.io/crystaldba/postgres-mcp
      tag: latest
      pullPolicy: IfNotPresent
    port: 8000
    accessMode: "restricted"
  ```
  The backend receives the MCP URL via Helm template:
  ```yaml
  # deploy/helm/ppe-compliance-monitor/templates/backend-deployment.yaml (lines 136-138)
  {{- if .Values.postgresMcp.enabled }}
  - name: POSTGRES_MCP_URL
    value: "http://{{ include "ppe-compliance-monitor.fullname" . }}-postgres-mcp:{{ .Values.postgresMcp.port }}/sse"
  {{- end }}
  ```

## Known Gotchas

- The SQL scoping guard uses simple `in` substring matching (e.g., `any(t in sql_lower for t in _SCOPED_TABLES)`), which means table names that appear as substrings of other identifiers will trigger the guard. A test in `test_mcp_scoping.py` (line 89-92) explicitly documents this as known behavior: querying `my_detection_tracks_backup` triggers the scoping rejection.
- The scoping guard checks for an exact string match of `app_config_id = {config_id}` in the lowercased SQL. Using `LIKE`, `IN`, or any other comparison operator instead of `=` will be rejected even if semantically equivalent (tested in `test_mcp_scoping.py` lines 85-87).
- The `POSTGRES_MCP_URL` in CI tests is set to a dummy value (`http://localhost:9999/sse` in `.github/workflows/test-backend.yml` line 70) since unit tests mock the MCP client rather than running the actual server.
- The postgres-mcp Deployment and Service are both gated behind `{{- if .Values.postgresMcp.enabled }}`, and the backend's `POSTGRES_MCP_URL` env var and init container are similarly conditional, so the entire MCP layer can be disabled by setting `postgresMcp.enabled: false`.

## Testing Notes

- Unit tests for the scoping guard are in `app/backend/tests/unit/test_mcp_scoping.py` -- they test the `_wrap_execute_sql` function in isolation using a `_FakeTool` mock, covering both scoped (config_id set) and unscoped (config_id None) scenarios.
- The tests use `contextvars.ContextVar` reset patterns with pytest fixtures to ensure clean state between tests.
- To verify the full integration, deploy the postgres-mcp container alongside PostgreSQL and confirm the backend can reach `POSTGRES_MCP_URL` and execute queries through the LangGraph agent.

## Related Patterns

- Uses the same MCP-as-tool pattern seen in other quickstart MCP servers (flight-mcp, hotel-mcp), but with a pre-built third-party container instead of a custom FastMCP server
- The init container wait-for-dependency pattern (`nc -z` polling) is used across multiple components in this quickstart
- The `langchain-mcp-adapters` SSE client pattern is the consumer-side counterpart to FastMCP server implementations
