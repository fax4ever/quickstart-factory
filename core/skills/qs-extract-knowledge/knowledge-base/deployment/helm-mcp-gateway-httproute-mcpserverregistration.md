---
name: helm-mcp-gateway-httproute-mcpserverregistration
description: Kubernetes Gateway API HTTPRoutes and Kagenti MCPServerRegistration CRDs for MCP server discovery with tool prefixes
summary: "Centralizes MCP server discovery and routing through a shared cluster-wide MCP Gateway by pairing Kubernetes Gateway API HTTPRoute resources with Kagenti MCPServerRegistration CRDs (mcp.kagenti.com/v1alpha1), enabling tool name prefixing (e.g., risk_, weather_) to avoid collisions between multiple MCP servers. Use when deploying multiple MCP servers that need centralized gateway-based routing and tool discovery — requires Gateway API CRDs and the Kagenti MCP Gateway controller in gateway-system namespace; can operate independently of full Kagenti A2A integration since mcpGateway.enabled is separate from kagenti.enabled. Each server needs an HTTPRoute with parentRefs (name, namespace, sectionName) pointing to the shared gateway and an MCPServerRegistration with toolPrefix, targetRef linking to the HTTPRoute, and the kagenti/mcp: \"true\" label for controller reconciliation; a ConfigMap in redhat-ods-applications provides RHOAI-native discovery gated on individual server enabled flags independently of mcpGateway.enabled. Hostnames use .mcp.local which is cluster-internal only (not externally resolvable), the weather server requires explicit path: /sse for SSE transport while risk defaults to root (port 8081 vs 80), and the redhat-ods-applications ConfigMap is created regardless of mcpGateway.enabled — gated only on mcpRiskServer.enabled or mcpWeatherServer.enabled."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm]
  ai_pattern: [agents]
  platform: [openshift]
source_examples:
  - quickstart: "multi-agent-loan-origination"
    repo: "https://github.com/rh-ai-quickstart/multi-agent-loan-origination"
    notes: "Gateway API HTTPRoutes + MCPServerRegistration CRDs for risk and weather MCP servers with tool prefixes"
    approach: "A"
---

# MCP Gateway with HTTPRoute and MCPServerRegistration CRDs

## Overview

This pattern registers MCP (Model Context Protocol) servers with a cluster-wide MCP Gateway using Kubernetes Gateway API `HTTPRoute` resources paired with Kagenti `MCPServerRegistration` CRDs. It enables centralized MCP server discovery and routing through a shared gateway, with tool name prefixing to avoid collisions between servers.

## Pattern Description

Each MCP server gets two resources: an `HTTPRoute` that routes traffic from the MCP Gateway to the backend service, and an `MCPServerRegistration` CR that registers the server's tools with the gateway. The `MCPServerRegistration` references the `HTTPRoute` via `targetRef` and adds a `toolPrefix` to namespace all tools from that server. The entire stack is gated behind `mcpGateway.enabled` since the CRDs may not exist on all clusters.

## Implementation

### HTTPRoute for MCP Service Routing

Each MCP server gets an HTTPRoute pointing to its backend service via the shared gateway:

```yaml
# deploy/helm/mortgage-ai/templates/mcp-server-registrations.yaml
{{- if .Values.mcpGateway.enabled }}
apiVersion: gateway.networking.k8s.io/v1
kind: HTTPRoute
metadata:
  name: mcp-risk-server-route
spec:
  parentRefs:
    - name: {{ .Values.mcpGateway.gateway.name }}
      namespace: {{ .Values.mcpGateway.gateway.namespace }}
      sectionName: {{ .Values.mcpGateway.gateway.sectionName }}
  hostnames:
    - "{{ .Values.mcpRiskServer.name }}.mcp.local"
  rules:
    - matches:
        - path:
            type: PathPrefix
            value: /
      backendRefs:
        - name: {{ .Values.mcpRiskServer.name }}
          port: {{ .Values.mcpRiskServer.service.port }}
{{- end }}
```

### MCPServerRegistration with Tool Prefix

The `MCPServerRegistration` CR registers the MCP server with the gateway, prefixing tool names to avoid collisions:

```yaml
# deploy/helm/mortgage-ai/templates/mcp-server-registrations.yaml
apiVersion: mcp.kagenti.com/v1alpha1
kind: MCPServerRegistration
metadata:
  name: mcp-risk-server
  labels:
    "kagenti/mcp": "true"
spec:
  toolPrefix: risk_
  targetRef:
    group: gateway.networking.k8s.io
    kind: HTTPRoute
    name: mcp-risk-server-route
```

### Weather Server with SSE Path

The weather MCP server uses a custom path (`/sse`) for Server-Sent Events transport:

```yaml
# deploy/helm/mortgage-ai/templates/mcp-server-registrations.yaml
apiVersion: mcp.kagenti.com/v1alpha1
kind: MCPServerRegistration
metadata:
  name: mcp-weather
  labels:
    "kagenti/mcp": "true"
spec:
  toolPrefix: weather_
  path: /sse
  targetRef:
    group: gateway.networking.k8s.io
    kind: HTTPRoute
    name: mcp-weather-route
```

### MCP Server ConfigMap for redhat-ods-applications

A separate ConfigMap in the `redhat-ods-applications` namespace provides MCP server metadata for RHOAI discovery:

```yaml
# deploy/helm/mortgage-ai/templates/mcp-configmap.yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: gen-ai-aa-mcp-servers
  namespace: redhat-ods-applications
data:
  Risk-MCP-Server: |
    {
      "url": "http://{{ .Values.mcpRiskServer.name }}.{{ .Release.Namespace }}.svc.cluster.local:{{ .Values.mcpRiskServer.service.port }}/mcp",
      "transport": "sse",
      "description": "An MCP server for mortgage risk assessment and analysis."
    }
```

## Configuration

- **Key settings:** `mcpGateway.enabled` toggles the entire Gateway API + MCPServerRegistration stack; `mcpGateway.gateway.name` (default: `mcp-gateway`), `.namespace` (default: `gateway-system`), and `.sectionName` (default: `mcps`) identify the shared gateway; each server's `toolPrefix` namespaces its tools
- **Defaults:** MCP risk server at port 8081 with transport path `/mcp`; weather server at port 80 with SSE path `/sse`; gateway namespace is `gateway-system`
- **Dependencies:** Kubernetes Gateway API CRDs must be installed; Kagenti MCP Gateway CRD (`mcp.kagenti.com/v1alpha1`) must be available; the MCP Gateway controller must be running in `gateway-system`; the ConfigMap in `redhat-ods-applications` requires access to create resources in that namespace

## Gotchas

- The `mcpGateway.enabled` flag is separate from `kagenti.enabled` -- MCP Gateway can be deployed without full Kagenti A2A integration and vice versa (see `deploy/helm/mortgage-ai/values.yaml` lines 291-297)
- The ConfigMap in `redhat-ods-applications` namespace is created regardless of `mcpGateway.enabled` -- it is gated only on `mcpRiskServer.enabled` or `mcpWeatherServer.enabled`, providing RHOAI-native discovery even without the Gateway API (see `deploy/helm/mortgage-ai/templates/mcp-configmap.yaml` line 1)
- Hostnames use `.mcp.local` domain which is a cluster-internal convention for the MCP Gateway -- these are not externally resolvable (see `deploy/helm/mortgage-ai/templates/mcp-server-registrations.yaml`)
- The weather server's `path: /sse` in the MCPServerRegistration tells the gateway which endpoint to use for SSE transport, while the risk server omits `path` and defaults to the root (see `deploy/helm/mortgage-ai/templates/mcp-server-registrations.yaml`)
- The `kagenti/mcp: "true"` label on MCPServerRegistration resources enables the Kagenti controller to discover and reconcile them (see `deploy/helm/mortgage-ai/templates/mcp-server-registrations.yaml`)

## Related Patterns

- `helm-kagenti-agentruntime-a2a-spire-mlflow-toggle.md` -- Kagenti AgentRuntime for A2A protocol alongside MCP Gateway
- `mcp-service-session-affinity-transport-toggle.md` -- MCP server transport and session patterns
