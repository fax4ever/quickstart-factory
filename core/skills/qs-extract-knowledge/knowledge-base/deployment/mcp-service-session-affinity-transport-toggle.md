---
name: mcp-service-session-affinity-transport-toggle
description: MCP server Kubernetes Service with ClientIP session affinity and provider-mode-based transport toggle
summary: "Deploys EDB's PostgreSQL MCP server (pg-airman-mcp, 2 replicas) on Kubernetes with ClientIP session affinity (3-hour/10800s timeout) ensuring backend pods consistently reach the same MCP server pod, plus transport protocol toggling between streamable-http and SSE based on the upstream provider mode. Use streamable-http (default) for mcp_direct mode with direct MCP tool calling, or SSE for llama_stack compatibility -- the Makefile sets mcp.transport via PROVIDER_MODE; the Helm Service is conditionally created only for sse/streamable-http (not stdio transport). Container args dynamically select --sse-port or --streamable-http-port on port 8000 (mcp.port), access mode is restricted/unrestricted (mcp.accessMode) with allowCommentInRestricted option, and the mcp_readonly user's DATABASE_URI uses urlquery-encoded credentials in a separate Secret from the superuser password (postgres.readonlyPassword vs postgres.password). Pod restarts with new IPs break ClientIP session affinity losing MCP session state; probes use tcpSocket (not HTTP) since MCP lacks a standard health endpoint; the pgvector StatefulSet must be running first as the data-loader Job creates the mcp_readonly user."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, postgresql]
  ai_pattern: [agents]
  platform: [openshift]
  data_layer: [pgvector]
source_examples:
  - quickstart: "data-governance-co-pilot"
    repo: "https://github.com/rh-ai-quickstart/data-governance-co-pilot"
    notes: "pg-airman-mcp Service with 3-hour ClientIP session affinity; transport toggles between SSE and streamable-http"
    approach: "A"
---

# MCP Server Service with Session Affinity and Transport Toggle

## Overview

This pattern deploys a Model Context Protocol (MCP) server with a Kubernetes Service configured for ClientIP session affinity and a transport mode toggle controlled by the upstream provider mode. Session affinity ensures that each backend pod consistently connects to the same MCP server pod, preserving session state across requests. The transport protocol switches between SSE (for Llama Stack compatibility) and streamable-http (for direct MCP tool calling).

## Pattern Description

The pg-airman-mcp chart deploys EDB's PostgreSQL MCP server with two replicas, fronted by a Service with `sessionAffinity: ClientIP` and a 3-hour timeout. The MCP server's transport mode is configurable and is set by the Makefile based on `PROVIDER_MODE`: `streamable-http` for `mcp_direct` mode (default) and `sse` for `llama_stack` mode. The deployment also uses a read-only PostgreSQL user (`mcp_readonly`) with configurable access mode (restricted/unrestricted).

## Implementation

### Service with Session Affinity

```yaml
# helm/pg-airman-mcp/templates/service.yaml
{{- if or (eq .Values.mcp.transport "sse") (eq .Values.mcp.transport "streamable-http") }}
apiVersion: v1
kind: Service
metadata:
  name: pg-airman-mcp-service
spec:
  type: {{ .Values.service.type }}
  sessionAffinity: ClientIP
  sessionAffinityConfig:
    clientIP:
      timeoutSeconds: 10800  # 3 hours
  ports:
    - port: {{ .Values.service.port }}
      targetPort: mcp
      protocol: TCP
      name: mcp
  selector:
    app.kubernetes.io/name: pg-airman-mcp
{{- end }}
```

### Deployment with Transport Args

The container args dynamically select the transport protocol and its corresponding port flag:

```yaml
# helm/pg-airman-mcp/templates/deployment.yaml (container args)
args:
  - "pg-airman-mcp"
  - "--transport={{ .Values.mcp.transport }}"
  - "--access-mode={{ .Values.mcp.accessMode }}"
  {{- if eq .Values.mcp.transport "sse" }}
  - "--sse-port={{ .Values.mcp.port }}"
  {{- else if eq .Values.mcp.transport "streamable-http" }}
  - "--streamable-http-port={{ .Values.mcp.port }}"
  {{- end }}
```

### Read-Only Database User in Secret

The MCP server connects using a dedicated read-only user, not the PostgreSQL superuser:

```yaml
# helm/pg-airman-mcp/templates/secret.yaml
stringData:
  DATABASE_URI: "postgresql://{{ .Values.postgres.user | urlquery }}:{{ .Values.postgres.password | urlquery }}@{{ .Values.postgres.host }}:{{ .Values.postgres.port }}/{{ .Values.postgres.database }}"
```

```yaml
# helm/pg-airman-mcp/values.yaml
postgres:
  user: mcp_readonly  # Read-only user created by load_data.py
```

### Makefile Transport Toggle

```makefile
# helm/Makefile (pg-airman-mcp-install, PROVIDER_MODE branches)
ifeq ($(PROVIDER_MODE),llama_stack)
	@echo "PROVIDER_MODE=llama_stack: Using SSE transport for Llama Stack compatibility"
	@helm ... --set mcp.transport=sse ...
else
	@echo "Using streamable-http transport (default)"
	@helm ... ...  # uses default streamable-http from values.yaml
endif
```

## Configuration

- **Key settings:** `mcp.transport` (default `streamable-http`), `mcp.accessMode` (default `restricted`), `mcp.port` (default 8000), `replicas` (default 2), `mcp.allowCommentInRestricted` (default false)
- **Defaults:** Service uses ClusterIP type; session affinity timeout is 3 hours (10800s); database user is `mcp_readonly`
- **Dependencies:** Requires the pgvector StatefulSet to be running (the data-loader Job creates the `mcp_readonly` user); the Service is only created when transport is `sse` or `streamable-http` (not `stdio`)

## Gotchas

- The Service is conditionally created only for `sse` or `streamable-http` transports -- `stdio` transport (which uses stdin/stdout) does not need a Service at all (see `helm/pg-airman-mcp/templates/service.yaml` conditional)
- Liveness and readiness probes use `tcpSocket` on the MCP port rather than HTTP health checks, since the MCP protocol does not define a standard health endpoint (see `helm/pg-airman-mcp/templates/deployment.yaml`)
- The `mcp_readonly` user password is passed as a separate parameter (`postgres.readonlyPassword`) distinct from the superuser password (`postgres.password`) -- both must be provided at install time (see `helm/Makefile` lines 398-399)
- Session affinity with 3-hour timeout means if a backend pod restarts and gets a new IP, it will connect to a potentially different MCP pod, losing any session state (see `helm/pg-airman-mcp/templates/service.yaml`)

## Related Patterns

- `helm-llamastack-crd-mcp-remote-providers.md` -- the Llama Stack deployment that connects to this MCP service using SSE transport
- `container-build-clone-patch-third-party-mcp.md` -- how the pg-airman-mcp image is built
