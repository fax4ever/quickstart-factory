---
name: mcp-servers
description: "Reusable Helm subchart for deploying MCP servers with dual-mode support (Toolhive CRD or standard Deployment)"
summary: "The mcp-servers Helm subchart (v0.5.7, ai-architecture-charts) provides a data-driven way to deploy one or more MCP servers on OpenShift/Kubernetes with dual-mode support -- Toolhive MCPServer CRDs with permissionProfile/proxyMode (auto-detected via CRD + toolhive-system namespace lookup) or standard Deployments with ClusterIP Services prefixed mcp-<key>. Use when quickstarts need MCP tool servers alongside the main app; set deploymentMode to auto (default) for Toolhive detection, or force deployment mode as fallback -- the backend consumes servers via a raw JSON-RPC 2.0 httpx client over streamable-HTTP rather than an MCP SDK, with per-query client lifecycle managing Mcp-Session-Id headers. Server entries live under the double-nested mcp-servers.mcp-servers values key with fields for deploymentMode (auto|mcpserver|deployment), transport, image, env, resources, securityContext, volumes, and envSecrets; the backend connects via LOKI_MCP_SERVER_URL (e.g., http://mcp-loki-server:8080/stream) and local dev uses compose on port 8081:8080. The double-nested values key silently produces no resources if misconfigured, service names differ between Deployment (mcp-<key>) and Toolhive (mcp-<key>-proxy) modes breaking URL references when switching, the chart ships a default weather server that must be explicitly disabled, and image tags may use branch names instead of semver."
metadata:
  type: component
tags:
  tech_stack: [python, httpx, helm]
  ai_pattern: [mcp, agents]
  platform: [openshift, kubernetes, toolhive]
source_examples:
  - quickstart: "ansible-log-analysis"
    repo: "https://github.com/rh-ai-quickstart/ansible-log-analysis"
    notes: "Deploys a Loki MCP server via the mcp-servers subchart; backend consumes it through a raw JSON-RPC MCP client over streamable-HTTP"
    approach: "A"
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
