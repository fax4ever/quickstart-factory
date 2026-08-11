---
name: openshift-mcp
description: "Go-based Kubernetes MCP server deployed via Helm for OpenShift cluster operations in agentic AI quickstarts"
summary: "Exposes Kubernetes/OpenShift cluster operations (pods, namespaces, events, projects) as MCP tools for AI agents via a Go-based server compiled from upstream kubernetes-mcp-server in a multi-stage UBI9 Containerfile (Go 1.24.1 builder, ubi-minimal runtime), deployed as a standalone Helm chart with SSE transport. Use for agentic quickstarts needing cluster introspection tools (e.g., Llama Stack agents); service name override (`serviceName: \"ocp-mcp-server\"`) enables integration via `http://ocp-mcp-server.<ns>.svc.cluster.local:8000/sse`; differs from Python FastMCP patterns in mcp-common.md. Deployment template overrides Containerfile entrypoint via `command`+`args` from `mcpServer.args`; RBAC binds ServiceAccount to `edit` ClusterRole (not the granular read-only `rbac.rules` declared in values.yaml); network policy restricts ingress to namespaces labeled `name: llama-serve`; resource defaults are 512Mi memory limit, 100m CPU / 256Mi requests. Containerfile hardcodes `--sse-port 8080` but Helm sets port 8000 causing mismatch during local `podman run`, `rbac.rules` in values.yaml are ignored by the rolebinding template which grants broader `edit` access, health probes are commented out so Kubernetes cannot restart unhealthy pods, and unpinned `git clone` (no branch/tag) makes builds non-reproducible."
metadata:
  type: component
tags:
  tech_stack: [golang, mcp, helm, podman]
  ai_pattern: [agents]
  platform: [openshift, kubernetes]
  data_layer: []
source_examples:
  - quickstart: "lls-observability"
    repo: "https://github.com/rh-ai-kickstart/llama-stack-observability"
    notes: "Go-based kubernetes-mcp-server deployed as a Helm subchart providing OpenShift/Kubernetes operations tools to Llama Stack agents via SSE transport"
    approach: "A"
---

# OpenShift MCP Server

## Overview

The OpenShift MCP server is a Go-based Model Context Protocol server that exposes Kubernetes and OpenShift cluster operations (pod management, namespace listing, event viewing, project listing) as MCP tools for AI agents. It uses the upstream [kubernetes-mcp-server](https://github.com/manusa/kubernetes-mcp-server) project, compiled from source in a multi-stage container build, and is deployed as a standalone Helm chart within the MCP servers deployment phase of the quickstart.

## Tech Stack & Dependencies

- **Runtime:** Go 1.24.1 (compiled from source in multi-stage build)
- **Upstream project:** `github.com/manusa/kubernetes-mcp-server`
- **Container base images:**
  - Builder: `registry.access.redhat.com/ubi9/ubi:latest`
  - Runtime: `registry.access.redhat.com/ubi9/ubi-minimal:latest`
- **Helm chart:** Standalone chart (not a subchart dependency), `apiVersion: v2`, version `0.1.0`
- **Transport:** SSE (Server-Sent Events) on port 8000
- **Key dependencies:** In-cluster Kubernetes credentials via ServiceAccount

## Key Patterns

### Multi-Stage Container Build from Upstream Source

The MCP server binary is built from the upstream `kubernetes-mcp-server` Go project in a multi-stage Containerfile. The builder stage installs Go, clones the repo, and runs `make build`. The runtime stage copies only the compiled binary into a minimal UBI image.

```dockerfile
FROM registry.access.redhat.com/ubi9/ubi:latest as builder
WORKDIR /app
USER root
RUN dnf install -y wget tar git make && \
    wget https://go.dev/dl/go1.24.1.linux-amd64.tar.gz && \
    tar -C /usr/local -xzf go1.24.1.linux-amd64.tar.gz && \
    rm -f go1.24.1.linux-amd64.tar.gz
ENV PATH="/usr/local/go/bin:${PATH}"
RUN git clone https://github.com/manusa/kubernetes-mcp-server.git && \
    cd kubernetes-mcp-server && \
    make build

FROM registry.access.redhat.com/ubi9/ubi-minimal:latest
WORKDIR /app
COPY --from=builder /app/kubernetes-mcp-server/kubernetes-mcp-server /app/kubernetes-mcp-server
ENTRYPOINT ["./kubernetes-mcp-server", "--sse-port", "8080", "--log-level", "9"]
```

### SSE Transport with Configurable Port

The server uses Server-Sent Events transport. The port is configurable via Helm values at `mcpServer.port` and `mcpServer.args`. The deployment template passes these args to the binary command.

```yaml
# values.yaml
mcpServer:
  port: 8000
  args:
    - "--sse-port"
    - "8000"
```

```yaml
# deployment.yaml (relevant section)
command: ["./kubernetes-mcp-server"]
args:
  {{- toYaml .Values.mcpServer.args | nindent 12 }}
```

### RBAC via ClusterRole Binding to Edit Role

The chart binds the MCP server's ServiceAccount to the built-in `edit` ClusterRole via a namespace-scoped RoleBinding, granting read/write access to workload resources. The `values.yaml` also defines granular read-only rules under `rbac.rules`, but the actual template uses the `edit` ClusterRole directly.

```yaml
# rolebinding.yaml
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: edit
```

```yaml
# values.yaml rbac.rules (declared but not used in rolebinding template)
rbac:
  rules:
    - apiGroups: [""]
      resources: ["pods", "services", "endpoints", "configmaps", "secrets"]
      verbs: ["get", "list", "watch"]
    - apiGroups: ["route.openshift.io"]
      resources: ["routes"]
      verbs: ["get", "list", "watch"]
```

### Service Name Override for Llama Stack Integration

The service name is overridden via `serviceName` in values to match the endpoint expected by the Llama Stack instance configuration. The service template uses this override instead of the standard fullname helper.

```yaml
# values.yaml
serviceName: "ocp-mcp-server"

# Consumed by llama-stack-instance as:
# uri: "http://ocp-mcp-server.llama-serve.svc.cluster.local:8000"
```

```yaml
# service.yaml
metadata:
  name: {{ .Values.serviceName | default (include "openshift-mcp.fullname" .) }}
```

### Network Policy Restricting Ingress

A network policy restricts inbound traffic to the MCP server port, allowing only connections from pods in namespaces labeled `name: llama-serve`.

```yaml
# values.yaml
networkPolicy:
  enabled: true
  ingress:
    - from:
      - namespaceSelector:
          matchLabels:
            name: llama-serve
      ports:
      - protocol: TCP
        port: 8000
```

## Configuration

- **Environment variables:** Configurable via `env` map in values.yaml (empty by default)
- **Container args:** `--sse-port` and port number passed via `mcpServer.args`
- **Helm values:**
  - `image.repository` / `image.tag` -- container image coordinates (default: `quay.io/hveeradh/ocp-mcp-server:latest`)
  - `serviceAccount.name` -- SA name (default: `ocp-mcp`)
  - `serviceName` -- overrides service name for integration with Llama Stack
  - `mcpServer.port` / `mcpServer.args` -- SSE transport configuration
  - `rbac.create` -- toggles RoleBinding creation
  - `networkPolicy.enabled` -- toggles network policy
  - `resources.limits.memory` -- 512Mi default; `resources.requests` -- 100m CPU, 256Mi memory

## Known Gotchas

- **Port mismatch between Containerfile and values.yaml:** The Containerfile `ENTRYPOINT` hardcodes `--sse-port 8080` and `EXPOSE 8080`, but `values.yaml` sets `mcpServer.port: 8000` and the deployment template overrides the entrypoint via `command` + `args`. The deployment template wins at runtime, but the mismatch can cause confusion during local testing with `podman run` (which would use port 8080).
- **RBAC rules in values.yaml are not used by the template:** The `rbac.rules` list in `values.yaml` defines granular read-only permissions, but the `rolebinding.yaml` template binds directly to the `edit` ClusterRole, which grants broader read-write access. The declared rules appear to be aspirational or documentation-only.
- **Health probes are commented out:** Both `livenessProbe` and `readinessProbe` are set to empty objects `{}` with example configurations commented out. The deployment runs without health checks, meaning Kubernetes cannot automatically restart unhealthy pods or remove them from service endpoints.
- **No pinned upstream version:** The Containerfile clones the `kubernetes-mcp-server` repo without specifying a branch or tag (`git clone` defaults to `main`), so builds are not reproducible and may break if upstream changes.

## Testing Notes

- After deployment, verify the MCP server pod is running and the service is reachable at the configured `serviceName` on port 8000
- Test MCP connectivity from a Llama Stack agent using the SSE endpoint: `http://ocp-mcp-server.<namespace>.svc.cluster.local:8000/sse`
- The README suggests testing with `app/src/0_simple_agent.py` using a prompt like "Please list all the pods running in my xyz namespace?" with `REMOTE_MCP_URL` set to the SSE endpoint

## Related Patterns

- `llamastack.md` -- Llama Stack instance that consumes this MCP server as a tool provider
- `mcp-common.md` -- shared Python MCP utilities (different pattern: Python FastMCP vs Go kubernetes-mcp-server)
- `mcp-servers.md` -- broader MCP server patterns across quickstarts
