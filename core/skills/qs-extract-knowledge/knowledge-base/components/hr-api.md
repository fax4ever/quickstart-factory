---
name: hr-api
description: "Node.js HR Enterprise API deployed as an MCP server for Llama Stack agent tool integration on OpenShift"
summary: "Deploys a Node.js Express HR domain MCP server as a standalone Helm chart (hr-enterprise-api v1.0.0, image quay.io/rh-aiservices-bu/sample-hr-app:0.0.1) providing HR tools to Llama Stack agents on OpenShift, demonstrated in the lls-observability quickstart alongside weather and OpenShift MCP servers. Use when adding an enterprise API as an MCP tool group to Llama Stack -- the chart registers as mcp::hr-api-tools via SSE transport where the Llama Stack configmap template conditionally appends /sse to the URI for named MCP servers; includes TLS edge-terminated Route and Swagger UI at /api-docs. Chart generates app-config.json via ConfigMap with checksum annotation for rolling restarts, OpenShift restricted SCC compatibility (UID/GID commented out, runAsNonRoot: true), rate limiting (100 req/15min), pod anti-affinity, PDB, and probes at /health (liveness, 30s delay) and /ready (readiness, 5s delay). Network policy allows only same-app pods and openshift-ingress but not Llama Stack pods requiring policy update for cross-namespace access, Service port 80 maps to container port 3000 by design matching the Llama Stack MCP URI, CPU limits are intentionally omitted (250m request only, 512Mi memory limit), and readOnlyRootFilesystem is false because the Node.js app needs filesystem write access."
metadata:
  type: component
tags:
  tech_stack: [nodejs, helm]
  ai_pattern: [agents, mcp]
  platform: [openshift, rhoai]
source_examples:
  - quickstart: "lls-observability"
    repo: "https://github.com/rh-ai-quickstart/lls-observability"
    notes: "Standalone Helm chart for HR API as MCP server registered with Llama Stack via SSE endpoint"
    approach: "A"
---

# HR API

## Overview

The HR Enterprise API is a Node.js-based MCP (Model Context Protocol) server that provides HR domain tools to a Llama Stack agent. It is deployed as a standalone Helm chart under `helm/04-mcp-servers/hr-api/` and registered with the Llama Stack instance as a tool group accessible via the `/sse` endpoint. In the lls-observability quickstart, it serves as one of several MCP servers (alongside weather and OpenShift MCP) that demonstrate agentic tool use with observability.

## Tech Stack & Dependencies

- **Runtime:** Node.js (Express-based, listening on port 3000)
- **Container image:** `quay.io/rh-aiservices-bu/sample-hr-app:0.0.1`
- **Key dependencies:** Llama Stack instance (consumer of this MCP server's tools)
- **Helm subchart:** Standalone chart `hr-enterprise-api` v1.0.0 (not a shared subchart)

## Key Patterns

### Standalone MCP Server Helm Chart

The HR API is packaged as its own Helm chart with a standard OpenShift-compatible Deployment, Service, Route, ConfigMap, and ServiceAccount. The chart is installed independently in the AI services namespace:

```bash
# From README.md deployment instructions
helm install hr-api ./helm/04-mcp-servers/hr-api -n ${AI_SERVICES_NAMESPACE}
```

### MCP Registration with Llama Stack

The HR API is registered as an MCP tool group in the Llama Stack instance's values.yaml. The Llama Stack configmap template conditionally appends `/sse` to the URI for MCP servers that use Server-Sent Events transport:

```yaml
# From llama-stack-instance/values.yaml
mcpServers:
  - name: "hr-api-tools"
    uri: "http://hr-enterprise-api.llama-serve.svc.cluster.local:80"
```

```yaml
# From llama-stack-instance/templates/configmap.yaml
- toolgroup_id: mcp::{{ .name }}
  provider_id: model-context-protocol
  mcp_endpoint:
    uri: {{ .uri }}{{ if or (eq .name "weather") (eq .name "hr-api-tools") (eq .name "openshift") }}/sse{{ end }}
```

### OpenShift-Compatible Security Context

The chart explicitly removes hardcoded UID/GID values to let OpenShift assign them via the restricted SCC, with comments documenting this decision:

```yaml
# From values.yaml
podSecurityContext:
  runAsNonRoot: true
  # Remove specific UID/GID to let OpenShift assign them
  # fsGroup: 1001

securityContext:
  allowPrivilegeEscalation: false
  capabilities:
    drop:
    - ALL
  readOnlyRootFilesystem: false
  runAsNonRoot: true
  # Remove specific UID/GID to let OpenShift assign them
  # runAsUser: 1001
  # runAsGroup: 1001
```

### ConfigMap-Driven Application Configuration

The chart generates an `app-config.json` via ConfigMap, embedding Helm values into a JSON configuration for the Node.js application:

```yaml
# From templates/configmap.yaml
app-config.json: |
  {
    "server": {
      "port": {{ .Values.env.PORT }},
      "cors": { "enabled": true, "origins": ["*"] },
      "rateLimit": {
        "enabled": {{ .Values.env.ENABLE_RATE_LIMITING }},
        "windowMs": 900000, "max": 100
      }
    },
    "swagger": {
      "enabled": {{ .Values.env.ENABLE_SWAGGER }},
      "path": "/api-docs"
    }
  }
```

### Config Checksum Annotation for Rolling Restarts

The Deployment template includes a checksum annotation on the ConfigMap so that config changes trigger a pod restart:

```yaml
# From templates/deployment.yaml
annotations:
  checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
```

### Network Policy Restricting Ingress

Network policies limit who can reach port 3000 to only the OpenShift ingress namespace and pods with the same app label:

```yaml
# From values.yaml
networkPolicy:
  enabled: true
  ingress:
    - from:
      - namespaceSelector:
          matchLabels:
            name: openshift-ingress
      ports:
      - protocol: TCP
        port: 3000
    - from:
      - podSelector:
          matchLabels:
            app.kubernetes.io/name: hr-enterprise-api
      ports:
      - protocol: TCP
        port: 3000
```

### Pod Anti-Affinity for HA

The chart configures preferred pod anti-affinity to spread replicas across nodes:

```yaml
# From values.yaml
affinity:
  podAntiAffinity:
    preferredDuringSchedulingIgnoredDuringExecution:
    - weight: 100
      podAffinityTerm:
        labelSelector:
          matchExpressions:
          - key: app.kubernetes.io/name
            operator: In
            values:
            - hr-enterprise-api
        topologyKey: kubernetes.io/hostname
```

## Configuration

- **Environment variables:**
  - `NODE_ENV`: Set to `production` in values.yaml
  - `PORT`: `3000` (Node.js listen port)
  - `ENABLE_SWAGGER`: `true` (Swagger UI at `/api-docs`)
  - `ENABLE_RATE_LIMITING`: `true` (100 requests per 15-minute window)
  - `CONFIG_MAP_NAME`: Injected automatically when configMap is enabled
- **Config files:** `app-config.json` generated from ConfigMap with server, CORS, rate limiting, swagger, and logging settings
- **Helm values:**
  - `route.enabled`: `true` (OpenShift Route with TLS edge termination)
  - `networkPolicy.enabled`: `true` (restricts ingress)
  - `podDisruptionBudget.enabled`: `true` with `minAvailable: 1`
  - `serviceMonitor.enabled`: `false` (optional Prometheus monitoring at `/metrics`)
  - `redis.enabled`: `false` (optional Redis integration)
  - `persistence.enabled`: `false` (optional PVC at `/opt/app-root/data`)

## Known Gotchas

- **SSE endpoint must be supported**: The comment `# HR-API should support MCP protocol with /sse endpoint` in `llama-stack-instance/values.yaml` (line 131) indicates the container image must expose an `/sse` endpoint for MCP transport. The Llama Stack configmap template hardcodes the `/sse` suffix for `hr-api-tools` specifically.
- **UID/GID commented out for OpenShift**: The `runAsUser`, `runAsGroup`, and `fsGroup` values are intentionally commented out with explicit notes to let OpenShift assign them. Re-enabling these will conflict with OpenShift's restricted SCC.
- **CPU limits intentionally omitted**: The `cpu` limit under `resources.limits` is commented out while memory limit is set to `512Mi`. Only CPU requests (`250m`) are specified.
- **Service port mismatch by design**: The Service listens on port 80 (`service.port: 80`) but targets container port 3000 (`service.targetPort: 3000`). The Llama Stack instance references port 80 in its MCP server URI.
- **Network policy does not explicitly allow Llama Stack pods**: Unlike the mcp-weather chart which allows ingress from `app.kubernetes.io/name: llama-stack`, the hr-api network policy only allows same-app pods and OpenShift ingress. The Llama Stack instance must be in the same namespace or the policy needs updating for cross-namespace access.
- **readOnlyRootFilesystem set to false**: Unlike many hardened charts, `readOnlyRootFilesystem` is `false`, suggesting the Node.js app needs write access to the filesystem at runtime.

## Testing Notes

- Verify the `/health` endpoint returns success (liveness probe, initial delay 30s)
- Verify the `/ready` endpoint returns success (readiness probe, initial delay 5s)
- Confirm the `/sse` endpoint is accessible for MCP transport
- Check Swagger UI at `/api-docs` when `ENABLE_SWAGGER` is enabled
- Verify the Llama Stack instance can discover and use `hr-api-tools` as a tool group
- If `serviceMonitor.enabled` is set to `true`, confirm Prometheus scrapes `/metrics` on port `http`

## Related Patterns

- `mcp-common.md` -- shared MCP server patterns across quickstarts
- `mcp-servers.md` -- MCP server deployment and registration patterns
- `llamastack.md` -- Llama Stack instance that consumes this MCP server's tools
