---
name: mcp-weather
description: "MCP weather server deployed as a standalone Helm chart providing weather tool access to Llama Stack agents"
summary: "Deploys a pre-built MCP weather server (quay.io/rh-aiservices-bu/mcp-weather:0.1.0-amd64) as a standalone Helm chart with no application source code, providing weather data tools to Llama Stack agents via SSE transport on OpenShift. Use when adding weather tool capabilities to Llama Stack agents -- register via mcpServers array in llama-stack-instance values with in-cluster service URL on port 80, or consume from LangGraph notebooks via bind_tools with type \"mcp\" and the /sse endpoint. Supports demo mode (weather.demoMode: true) running without real API credentials by falling back WEATHER_API_KEY to \"demo-key\"; OpenShift restricted SCC compatible via runAsNonRoot: true, dropping all capabilities, and omitting UID/GID to let OpenShift assign them. Service port 80 maps to container targetPort 3001 (consumers use port 80), image tag 0.1.0-amd64 is architecture-specific with no multi-arch default, health probes use tcpSocket rather than HTTP endpoints, and networkPolicy/route values exist in values.yaml but corresponding templates are missing so policies never render."
metadata:
  type: component
tags:
  tech_stack: [mcp, helm]
  ai_pattern: [agents, mcp-server]
  platform: [openshift, kubernetes]
  data_layer: []
source_examples:
  - quickstart: "lls-observability"
    repo: "https://github.com/rh-ai-quickstart/lls-observability"
    notes: "Standalone Helm chart deploying a pre-built MCP weather server image consumed by Llama Stack agents via SSE transport"
    approach: "A"
---

# MCP Weather Server

## Overview

A pre-built MCP (Model Context Protocol) weather server deployed as a standalone Helm chart on OpenShift. Unlike source-based MCP servers (e.g., hotel-mcp, flight-mcp), this component ships as a container image (`quay.io/rh-aiservices-bu/mcp-weather`) with no application source code in the repo -- the Helm chart is the entire component. It provides weather data tools to Llama Stack agents via SSE transport and is consumed by the `llama-stack-instance` chart through MCP server registration.

## Tech Stack & Dependencies

- **Runtime:** Pre-built container image (Node.js-based, port 3001)
- **Container image:** `quay.io/rh-aiservices-bu/mcp-weather:0.1.0-amd64`
- **Key dependencies:** Llama Stack instance (consumer), external weather API (optional, has demo mode)
- **Helm subchart:** Standalone chart `mcp-weather` v1.0.0, not a subchart of a parent chart

## Key Patterns

### Pre-Built Image Deployment (No Application Source)

Unlike most MCP servers in the quickstart ecosystem that include Python/Node source code, this component is deployed purely from a pre-built image. The entire component definition is the Helm chart -- there is no `server.py`, `Dockerfile`, or `requirements.txt`.

```yaml
# From helm/04-mcp-servers/mcp-weather/values.yaml
image:
  repository: quay.io/rh-aiservices-bu/mcp-weather
  tag: "0.1.0-amd64"
  pullPolicy: IfNotPresent
```

Source: `helm/04-mcp-servers/mcp-weather/values.yaml`, lines 4-6.

### Demo Mode with Optional API Key

The chart supports running without a real weather API key by defaulting to demo mode. When no secret is configured, the deployment template falls back to a `demo-key` value:

```yaml
# From helm/04-mcp-servers/mcp-weather/values.yaml
weather:
  apiKeySecretName: ""
  apiKeySecretKey: "api-key"
  provider: "openweathermap"
  demoMode: true
```

Source: `helm/04-mcp-servers/mcp-weather/values.yaml`, lines 98-106.

The deployment template conditionally sources the API key from a Kubernetes secret or falls back to the demo key:

```yaml
# From helm/04-mcp-servers/mcp-weather/templates/deployment.yaml
{{- if .Values.weather.apiKeySecretName }}
- name: WEATHER_API_KEY
  valueFrom:
    secretKeyRef:
      name: {{ .Values.weather.apiKeySecretName }}
      key: {{ .Values.weather.apiKeySecretKey }}
{{- else }}
- name: WEATHER_API_KEY
  value: "demo-key"
{{- end }}
```

Source: `helm/04-mcp-servers/mcp-weather/templates/deployment.yaml`, lines 44-53.

### Llama Stack MCP Server Registration

The weather server is registered with Llama Stack by passing its in-cluster service URL as an `mcpServers` entry during `llama-stack-instance` Helm install:

```bash
# From README.md install instructions
helm install llama-stack-instance ./helm/03-ai-services/llama-stack-instance \
  -n ${AI_SERVICES_NAMESPACE} \
  --set 'mcpServers[0].name=weather' \
  --set 'mcpServers[0].uri=http://mcp-weather.${AI_SERVICES_NAMESPACE}.svc.cluster.local:80'
```

Source: `README.md`, lines 249-252.

The corresponding default in the llama-stack-instance values uses the same pattern:

```yaml
# From helm/03-ai-services/llama-stack-instance/values.yaml
mcpServers:
  - name: "weather"
    uri: "http://mcp-weather.llama-serve.svc.cluster.local:80"
```

Source: `helm/03-ai-services/llama-stack-instance/values.yaml`, lines 123-126.

### SSE Transport for LangGraph Integration

When consumed from LangGraph notebooks, the MCP weather server is accessed via its `/sse` endpoint, using the OpenAI-compatible `bind_tools` pattern with an MCP tool type:

```python
# From docs/notebooks/4-langgraph-tools.ipynb
llm_with_tools = llm.bind_tools([
    {
        "type": "mcp",
        "server_label": "weather",
        "server_url": "http://mcp-weather.llama-serve.svc.cluster.local:80/sse",
        "require_approval": "never",
    },
])
```

Source: `docs/notebooks/4-langgraph-tools.ipynb`, cell 7.

### OpenShift-Compatible Security Context

The chart is configured for OpenShift's restricted SCC by not specifying UID/GID (letting OpenShift assign them) while enforcing non-root and dropping all capabilities:

```yaml
# From helm/04-mcp-servers/mcp-weather/values.yaml
podSecurityContext:
  runAsNonRoot: true
  # Remove specific UID/GID to let OpenShift assign them

securityContext:
  allowPrivilegeEscalation: false
  capabilities:
    drop:
    - ALL
  readOnlyRootFilesystem: false
  runAsNonRoot: true
```

Source: `helm/04-mcp-servers/mcp-weather/values.yaml`, lines 20-35.

### Network Policy Restricting Access to Llama Stack

The values define a network policy that restricts ingress to only the OpenShift ingress controller and pods labeled `app.kubernetes.io/name: llama-stack`, and limits egress to HTTP/HTTPS for calling external weather APIs:

```yaml
# From helm/04-mcp-servers/mcp-weather/values.yaml
networkPolicy:
  enabled: true
  ingress:
    - from:
      - podSelector:
          matchLabels:
            app.kubernetes.io/name: llama-stack
      ports:
      - protocol: TCP
        port: 3001
```

Source: `helm/04-mcp-servers/mcp-weather/values.yaml`, lines 114-139.

## Configuration

- **Environment variables:**
  - `MCP_SERVER_PORT` — Server listen port, defaults to `3001`
  - `MCP_SERVER_HOST` — Server bind address, defaults to `0.0.0.0`
  - `WEATHER_CACHE_TTL` — Cache duration in seconds, defaults to `300` (5 minutes)
  - `WEATHER_API_KEY` — API key for weather provider, sourced from Kubernetes secret or defaults to `demo-key`
  - `WEATHER_PROVIDER` — Weather service backend, defaults to `openweathermap`
  - `WEATHER_DEMO_MODE` — When `true`, runs without requiring a real API key
- **Config files:** None; all configuration via environment variables and Helm values.
- **Helm values:**
  - `weather.apiKeySecretName` — Name of Kubernetes secret containing the API key (empty string disables secret lookup)
  - `weather.demoMode` — Boolean to enable demo mode without real API credentials
  - `weather.provider` — Weather service provider selection
  - `route.enabled` — Enables OpenShift Route (defaults to `true` with TLS edge termination)
  - `networkPolicy.enabled` — Enables network policy restricting ingress to Llama Stack pods

## Known Gotchas

- The service port (80) and container port (3001) differ -- the Kubernetes Service maps port 80 to targetPort 3001. Consumers use port 80 in their URIs (`http://mcp-weather...:80`) while the container listens on 3001. This is defined in `helm/04-mcp-servers/mcp-weather/values.yaml` lines 38-39.
- Health probes use `tcpSocket` on the `http` port rather than HTTP health endpoints, matching the pattern seen in other MCP servers where the MCP transport may not expose a standard HTTP health route. Source: `helm/04-mcp-servers/mcp-weather/values.yaml`, lines 70-84.
- The image tag `0.1.0-amd64` is architecture-specific. No multi-arch tag is provided in the defaults, which means ARM-based clusters would need an override. Source: `helm/04-mcp-servers/mcp-weather/values.yaml`, line 5.
- The network policy configuration exists in `values.yaml` but there is no corresponding `networkpolicy.yaml` template in `templates/` -- the network policy is defined but not rendered. The same applies to the `route` configuration (no route template). These would need to be added for the policies to take effect.
- The `readOnlyRootFilesystem` is set to `false` (line 30 of values.yaml), with comments removing specific UID/GID to let OpenShift assign them -- this is intentional for OpenShift restricted SCC compatibility.

## Testing Notes

- Deploy with demo mode enabled (default) to verify the server starts without external API credentials.
- Verify the service is reachable from within the cluster: `curl http://mcp-weather.<namespace>.svc.cluster.local:80/sse`.
- Confirm Llama Stack registration by checking the llama-stack-instance ConfigMap for the weather MCP server entry.
- Use the LangGraph notebook (`docs/notebooks/4-langgraph-tools.ipynb`) to test end-to-end agent-to-MCP tool invocation.

## Related Patterns

- Sibling MCP servers in the same quickstart: `hr-api` (REST API MCP), `openshift-mcp` (OpenShift operations MCP) under `helm/04-mcp-servers/`.
- The `llama-stack-instance` chart (`helm/03-ai-services/llama-stack-instance/`) is the consumer that registers MCP servers via its `mcpServers` values array.
- See `mcp-common.md` for the shared MCP utility library pattern used in other quickstarts' source-based MCP servers.
