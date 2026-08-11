---
name: mcp-servers
description: "Reusable Helm subchart for deploying MCP servers with dual-mode support (Toolhive CRD or standard Deployment)"
summary: "The mcp-servers Helm subchart (v0.5.7/v0.5.18, ai-architecture-charts) provides a data-driven way to deploy one or more MCP servers on OpenShift/Kubernetes with dual-mode support -- Toolhive MCPServer CRDs with permissionProfile/proxyMode (auto-detected via CRD + toolhive-system namespace lookup) or standard Deployments with ClusterIP Services prefixed mcp-<key>. Two consumption approaches: Approach A uses a raw JSON-RPC 2.0 httpx MCPClient over streamable-HTTP with per-query lifecycle managing Mcp-Session-Id headers for programmatic backend-only access (connects via LOKI_MCP_SERVER_URL, local dev compose on port 8081:8080); Approach B registers servers as LlamaStack toolgroups (mcp:: prefix) auto-discovered by Streamlit frontend pills and agent-invoked via Responses API with mcp_call streaming output -- choose A when the backend calls MCP directly, B when using LlamaStack orchestration with user-selectable tools. Server entries live under double-nested mcp-servers.mcp-servers values key with fields for deploymentMode (auto|mcpserver|deployment), transport, image, env, resources, securityContext, volumes, and envSecrets; Approach B configures servers through global.mcp-servers merge and toggles the subchart via mcp-servers.enabled. The double-nested values key silently produces no resources if misconfigured, service names differ between Deployment (mcp-<key>) and Toolhive (mcp-<key>-proxy) modes breaking URL references when switching, the chart ships a default weather server that must be explicitly disabled, default global.mcp-servers: {} means no servers deploy out-of-the-box in Approach B, E2E tests disable MCP entirely, and image tags may use branch names instead of semver."
metadata:
  type: component
tags:
  tech_stack: [python, httpx, helm, streamlit, fastmcp, llama-stack]
  ai_pattern: [mcp, agents, rag]
  platform: [openshift, kubernetes, toolhive]
source_examples:
  - quickstart: "ansible-log-analysis"
    repo: "https://github.com/rh-ai-quickstart/ansible-log-analysis"
    notes: "Deploys a Loki MCP server via the mcp-servers subchart; backend consumes it through a raw JSON-RPC MCP client over streamable-HTTP"
    approach: "A"
  - quickstart: "RAG"
    repo: "https://github.com/rh-ai-quickstart/RAG"
    notes: "Deploys MCP servers via the subchart and registers them as LlamaStack toolgroups; frontend auto-discovers and agents invoke them through the LlamaStack Responses API"
    approach: "B"
---

# MCP Servers

## Overview

A reusable Helm subchart from `ai-architecture-charts` that deploys one or more MCP (Model Context Protocol) servers with a data-driven values-based configuration. The chart supports dual deployment modes: Toolhive operator MCPServer CRDs when the operator is installed, or standard Kubernetes Deployments as a fallback. In the ansible-log-analysis quickstart it deploys a Loki MCP server that the backend queries through a raw JSON-RPC client built with httpx.

## Tech Stack & Dependencies

- **Runtime:** Helm chart (no application runtime -- wraps arbitrary MCP server container images)
- **Container image:** Per-server, e.g. `quay.io/rh-ai-quickstart/alm-loki-mcp-server`
- **Key dependencies:** Toolhive operator CRDs (`toolhive.stacklok.dev/v1alpha1/MCPServer`) -- optional, chart falls back to Deployments
- **Helm subchart:** `mcp-servers` v0.5.7 from `https://rh-ai-quickstart.github.io/ai-architecture-charts`
- **Client library:** `httpx` (async HTTP client used by the Python MCP client in the backend)

## Key Patterns

### Dual Deployment Mode (Auto/MCPServer/Deployment)

Each MCP server entry supports a `deploymentMode` field. The chart detects Toolhive availability at render time by checking for both the CRD and the `toolhive-system` namespace:

```yaml
# From _helpers.tpl
{{- define "mcp-servers.canDeployMCPServer" -}}
  {{- $hasCRD := .Capabilities.APIVersions.Has "toolhive.stacklok.dev/v1alpha1/MCPServer" }}
  {{- $hasToolhiveNamespace := false }}
  {{- if $hasCRD }}
    {{- $namespaces := lookup "v1" "Namespace" "" "" }}
    {{- range $namespaces.items }}
      {{- if eq .metadata.name "toolhive-system" }}
        {{- $hasToolhiveNamespace = true }}
      {{- end }}
    {{- end }}
  {{- end }}
  {{- and $hasCRD $hasToolhiveNamespace }}
{{- end }}
```

When `deploymentMode: auto` (the default), the chart uses MCPServer CRDs if Toolhive is detected, otherwise falls back to standard Deployments. Setting `deploymentMode: mcpserver` or `deploymentMode: deployment` forces a specific mode.

### Data-Driven Server Definitions

MCP servers are defined declaratively in values.yaml. The chart iterates over all entries, rendering the appropriate resource type for each enabled server:

```yaml
# deploy/helm/ansible-log-monitor/values.yaml
mcp-servers:
  mcp-servers:
    weather:
      enabled: false                  # Disable default weather server
    loki-server:
      enabled: true
      deploymentMode: deployment      # Force standard K8s Deployment
      transport: sse
      targetPort: 8080
      image:
        repository: quay.io/rh-ai-quickstart/alm-loki-mcp-server
        tag: query-direction-support
      env:
        LOKI_URL: "http://loki:3100"
        PORT: "8080"
```

### Global Values Merge

The chart merges global and local MCP server definitions, allowing parent charts to override or extend server configs:

```yaml
# From _helpers.tpl
{{- define "mcp-servers.mergeMcpServers" -}}
  {{- $globalServers := .Values.global | default dict }}
  {{- $globalServers := index $globalServers "mcp-servers" | default dict }}
  {{- $localServers := index .Values "mcp-servers" | default dict }}
  {{- $merged := merge $globalServers $localServers }}
  {{- toJson $merged }}
{{- end }}
```

### MCPServer CRD Resource

When Toolhive mode is active, the chart renders `MCPServer` custom resources with full pod template spec support for security contexts, volumes, and env vars:

```yaml
# From templates/mcpserver.yaml (rendered output shape)
apiVersion: toolhive.stacklok.dev/v1alpha1
kind: MCPServer
metadata:
  name: {{ $key }}
spec:
  image: "{{ $server.image.repository }}:{{ $server.image.tag }}"
  proxyMode: {{ $server.proxyMode | default "sse" }}
  transport: {{ $server.transport | default "stdio" }}
  permissionProfile:
    name: network
    type: builtin
```

### Standard Deployment Fallback

When in `deployment` mode, the chart creates a regular Kubernetes Deployment and ClusterIP Service. The naming convention prefixes `mcp-` to the server key:

```yaml
# From templates/deployment.yaml (rendered output shape)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: mcp-{{ $key }}
spec:
  containers:
  - name: {{ $key }}
    image: "{{ $server.image.repository }}:{{ $server.image.tag }}"
```

### Raw JSON-RPC MCP Client

The backend uses a custom MCP client (`src/alm/mcp/mcp_client.py`) that communicates with MCP servers over HTTP using JSON-RPC 2.0. It manages session lifecycle via the `Mcp-Session-Id` header:

```python
# src/alm/mcp/mcp_client.py
class MCPClient:
    async def initialize(self):
        payload = {
            "jsonrpc": "2.0", "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "test-chat", "version": "1.0.0"},
            },
        }
        response = await self.client.post(self.server_url, json=payload)
        self.session_id = response.headers.get("Mcp-Session-Id")
```

### Per-Query Client Lifecycle

The MCP client is created and torn down for each Loki query. LangChain tools call `execute_loki_query` which creates a fresh `MCPClient`, initializes the session, calls the tool, and cleans up:

```python
# src/alm/tools/loki_tools.py
async def execute_loki_query(query, start, end, limit, ...):
    client = await create_mcp_client()
    try:
        result = await client.call_tool("loki_query", arguments)
        ...
    finally:
        if client:
            await client.__aexit__(None, None, None)
```

## Configuration

- **Environment variables:**
  - `LOKI_MCP_SERVER_URL` -- Backend env var pointing to the Loki MCP server endpoint. Set to `http://mcp-loki-server:8080/stream` in the Helm values. The `/stream` path indicates streamable-HTTP transport.
  - `LOKI_URL` -- Passed to the Loki MCP server container, pointing to the Loki instance (default: `http://loki:3100`).
  - `PORT` -- Container listen port for the MCP server (default: `8080`).
- **Helm values:** Server definitions live under the double-nested `mcp-servers.mcp-servers` key in the parent chart values. Each server entry supports `enabled`, `deploymentMode`, `transport`, `targetPort`, `image`, `env`, `resources`, `securityContext`, `podSecurityContext`, `volumes`, `volumeMounts`, `envSecrets`, and `oracleUserSecrets`.
- **Compose config:** In local dev, the Loki MCP server runs as a standalone service on port `8081` (host) mapped to `8080` (container), connected to the same Docker network as Loki.

## Known Gotchas

- **Double-nested values key:** The parent chart's values use `mcp-servers.mcp-servers` (the first level is the subchart name, the second is the key the chart iterates over). Misconfiguring this nesting silently produces no MCP server resources.
- **Service naming convention differs between modes:** In Deployment mode, services are named `mcp-<key>` (e.g., `mcp-loki-server`). In Toolhive MCPServer mode, the proxy service is named `mcp-<key>-proxy`. The `LOKI_MCP_SERVER_URL` in the backend values references `mcp-loki-server` which assumes Deployment mode.
- **Packaged chart dependency:** The `mcp-servers` chart is included as a `.tgz` archive (`mcp-servers-0.5.7.tgz`) rather than an unpacked directory. The Chart.yaml references it from the `ai-architecture-charts` Helm repo. The chart has its own `Chart.lock` with Toolhive operator CRD and operator chart dependencies that are conditionally used.
- **Per-query client creation:** The MCP client is created fresh for every Loki query (`create_mcp_client()` in `loki_tools.py`). This adds overhead for session initialization on each call but avoids stale session issues.
- **Default weather server override:** The chart ships with a default `weather` MCP server enabled. The parent chart explicitly disables it (`weather.enabled: false`) and adds the `loki-server` entry. Forgetting to disable the default would deploy an unwanted weather MCP server.
- **Image tag set to branch name:** The Loki MCP server image uses `tag: query-direction-support` (a branch name, not a semver tag), suggesting the image is built from a custom fork of the Loki MCP project.

## Testing Notes

- In Deployment mode, verify the MCP server pod is running: `oc get deployments -l app.kubernetes.io/component=mcp-server`
- In Toolhive mode, verify the MCPServer CRD resource: `oc get mcpservers`
- Test MCP connectivity by hitting the server's endpoint (e.g., `http://mcp-loki-server:8080/stream`) with a JSON-RPC `initialize` request
- The backend's `LOKI_MCP_SERVER_URL` must match the rendered service name and transport path

## Related Patterns

- Individual MCP server implementations follow the FastMCP pattern documented in `travel-research-mcp.md`, `hotel-mcp.md`, and `flight-mcp.md`
- The Loki MCP server in this quickstart is a custom fork (not FastMCP-based) that exposes a `loki_query` tool over SSE/streamable-HTTP transport
- The `mcp-servers` chart is sourced from `ai-architecture-charts` and is shared across quickstarts

---

## Approach B: LlamaStack Toolgroup Integration (from RAG)

### When to Use

Use this approach when the quickstart uses LlamaStack as its orchestration layer. MCP servers are registered as LlamaStack toolgroups and the LLM agent discovers and invokes them through the LlamaStack Responses API, rather than the backend calling MCP servers directly.

### Differences from Approach A

- **No custom MCP client code** -- LlamaStack handles MCP server communication natively via its toolgroup registration mechanism.
- **Auto-discovery** -- The Streamlit frontend fetches registered toolgroups from LlamaStack, filters MCP tools by `mcp::` prefix, and presents them as selectable UI pills. No hardcoded tool references.
- **Agent-mediated invocation** -- The LLM agent decides when to call MCP tools during Responses API streaming. The frontend passes `{"type": "mcp", "server_label": ..., "server_url": ...}` tool definitions to the Responses API.
- **Global values merge** -- MCP server definitions can be provided via `global.mcp-servers` in the parent chart, allowing the LlamaStack subchart to merge them with its own config.

### Helm Subchart Configuration

The RAG quickstart includes `mcp-servers` v0.5.18 as a dependency with `global.mcp-servers` for configuration:

```yaml
# deploy/helm/rag/Chart.yaml
dependencies:
  - name: mcp-servers
    version: 0.5.18
    repository: https://rh-ai-quickstart.github.io/ai-architecture-charts
    condition: mcp-servers.enabled
```

```yaml
# deploy/helm/rag/values.yaml
global:
  mcp-servers: {}

mcp-servers:
  enabled: true
```

Individual MCP servers are configured under `global.mcp-servers` and registered with LlamaStack automatically. For example, to add an MCP weather server:

```yaml
# Example from client-examples-python/README.md
llama-stack:
  mcp-servers: {}
    #  mcp-weather:
    #   uri: http://rag-mcp-weather:8000/sse
```

### Frontend Auto-Discovery of MCP Toolgroups

The Streamlit chat UI fetches all registered toolgroups from LlamaStack and separates MCP tools from built-in tools by prefix:

```python
# frontend/llama_stack_ui/distribution/ui/page/playground/chat.py
tool_groups = client.toolgroups.list()
tool_groups_list = [tool_group.identifier for tool_group in tool_groups]

mcp_tools_list = [tool for tool in tool_groups_list if tool.startswith("mcp::")]
builtin_tools_list = [tool for tool in tool_groups_list if not tool.startswith("mcp::")]
```

MCP tools are rendered as separate selectable pills in the sidebar:

```python
# frontend/llama_stack_ui/distribution/ui/page/playground/chat.py
if mcp_tools_list:
    mcp_selection = st.pills(
        label="MCP Servers",
        options=mcp_tools_list,
        selection_mode="multi",
        format_func=lambda tool: "".join(tool.split("::")[1:]),
        help="List of MCP servers registered to your llama stack server.",
    )
    toolgroup_selection = list(toolgroup_selection) + list(mcp_selection)
```

### Agent MCP Tool Invocation via Responses API

When the user selects an MCP toolgroup, the agent module resolves the server URL from LlamaStack's toolgroup metadata and passes it to the Responses API:

```python
# frontend/llama_stack_ui/distribution/ui/page/playground/agent.py
elif toolgroup_name.startswith("mcp::"):
    toolgroups = client.toolgroups.list()
    for toolgroup in toolgroups:
        if str(toolgroup.identifier) == toolgroup_name:
            agent_tools.append({
                "type": "mcp",
                "server_label": toolgroup.args.get(
                    "name", str(toolgroup.identifier)
                ),
                "server_url": toolgroup.mcp_endpoint.uri,
            })
            break
```

MCP call results stream back as `mcp_call` output items:

```python
# frontend/llama_stack_ui/distribution/ui/page/playground/agent.py
elif item_type == "mcp_call":
    if hasattr(item, 'output') and item.output:
        tool_name = getattr(item, 'name', 'mcp')
        state.tool_results.append({
            'title': f'MCP Tool Output: {tool_name}',
            'type': 'code',
            'content': str(item.output)
        })
```

### MCP Weather Server (Removed -- Historical Pattern)

The RAG quickstart originally contained a standalone FastMCP weather server under `mcp-servers/weather/` (removed in commit `c5dad8a`). This shows the canonical pattern for building a custom MCP server for the subchart:

```python
# mcp-servers/weather/weather.py (removed)
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("weather")

@mcp.tool()
async def get_forecast(latitude: str, longitude: str) -> str:
    points_url = f"{NWS_API_BASE}/points/{latitude},{longitude}"
    points_data = await make_nws_request(points_url)
    forecast_url = points_data["properties"]["forecast"]
    # ...

if __name__ == "__main__":
    mcp.run(transport='sse')
```

```dockerfile
# mcp-servers/weather/Containerfile (removed)
FROM registry.access.redhat.com/ubi9/python-311:latest
RUN pip install mcp["cli"]
WORKDIR /mcp_server
COPY . /mcp_server
EXPOSE 8000
ENTRYPOINT [ "python", "weather.py" ]
```

Registration was done via a REST call to LlamaStack:

```bash
# From mcp-servers/weather/README.md (removed)
curl -X POST -H "Content-Type: application/json" \
  --data '{ "provider_id": "model-context-protocol",
            "toolgroup_id": "mcp::weather",
            "mcp_endpoint": { "uri": "http://host.docker.internal:8000/sse" }}' \
  $LLAMA_STACK_ENDPOINT/v1/toolgroups
```

### Configuration

- **Environment variables:**
  - `LLAMA_STACK_ENDPOINT` -- Frontend env var for LlamaStack API. Default: `http://llamastack:8321`.
- **Helm values:**
  - `mcp-servers.enabled` -- Toggle the entire subchart (default: `true` in production, `false` in e2e tests).
  - `global.mcp-servers` -- Parent-level dict merged into the subchart's server definitions by LlamaStack.
- **MCP server registration:** Servers deployed by the subchart are automatically registered as LlamaStack toolgroups. The `mcp::` prefix identifies them in toolgroup listings.

### Known Gotchas

- **E2E tests disable MCP servers** -- Both `tests/e2e/values-e2e.yaml` and `tests/integration/llamastack/values-e2e.yaml` set `mcp-servers.enabled: false` because MCP servers add deployment complexity not needed for core RAG testing.
- **Empty `global.mcp-servers: {}`** -- The default production values.yaml sets `global.mcp-servers: {}`, meaning no MCP servers are deployed out-of-the-box. Users must add server entries to enable MCP functionality.
- **Weather server removed but subchart kept** -- Commit `c5dad8a` removed the `mcp-servers/weather/` source code, but the Helm subchart dependency remains in Chart.yaml. The subchart itself may still deploy a default weather server unless explicitly disabled.
- **Pod naming convention** -- Deployed MCP server pods follow the pattern `rag-mcp-<name>` (e.g., `rag-mcp-weather-9cc97d574-nf5q8` seen in `docs/openshift_setup_guide.md`), prefixed with the release name.

### Testing Notes

- MCP server auto-discovery depends on LlamaStack being up and the servers registered as toolgroups.
- Select "Agent-based" processing mode in the Streamlit UI to see MCP tools in the sidebar.
- Verify MCP toolgroup registration: `curl -sS $LLAMA_STACK_ENDPOINT/v1/toolgroups | jq`

### Related Patterns

- The LlamaStack orchestration layer is documented in `llamastack.md`
- The Streamlit frontend that renders MCP tools is in `streamlit-frontend.md`
- FastMCP server implementation patterns are in `flight-mcp.md`, `hotel-mcp.md`, and `travel-research-mcp.md`

---

## Choosing Between Approaches

| Criteria | Approach A (Raw JSON-RPC) | Approach B (LlamaStack Toolgroup) |
|----------|--------------------------|-----------------------------------|
| Orchestration layer | Backend calls MCP directly via httpx | LlamaStack manages MCP connections |
| Tool discovery | Hardcoded in backend code | Auto-discovered via toolgroup API |
| Agent control | Backend decides when to call MCP | LLM agent decides via Responses API |
| Session management | Manual Mcp-Session-Id header tracking | Handled by LlamaStack internally |
| Frontend integration | None (backend-only) | MCP tools appear as selectable UI pills |
| Custom client code needed | Yes (MCPClient class) | No (LlamaStack SDK handles it) |
| Best for | Backend services consuming MCP tools programmatically | Interactive agent applications where users select tools |
