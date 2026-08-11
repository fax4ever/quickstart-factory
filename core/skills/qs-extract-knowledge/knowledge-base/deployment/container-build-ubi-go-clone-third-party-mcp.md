---
name: container-build-ubi-go-clone-third-party-mcp
description: UBI multi-stage Go build that clones third-party kubernetes-mcp-server repo and compiles binary
summary: "Containerizes the third-party manusa/kubernetes-mcp-server Go-based MCP server for OpenShift using a UBI9 multi-stage build that clones the upstream repo, compiles via make build with Go 1.24.1 installed from go.dev tarball (dnf adds wget/tar/git/make), and produces a ubi-minimal runtime image containing only the statically compiled binary. Use when deploying a Go third-party MCP server (SSE transport) that compiles cleanly from upstream source without sed patching — unlike the Python clone-and-patch pattern (container-build-clone-patch-third-party-mcp); a pre-built image at quay.io/hveeradh/ocp-mcp-server:latest is available as the default in Helm values. Critical config: the Containerfile and Helm chart live at helm/04-mcp-servers/openshift-mcp/, with runtime args --sse-port and --log-level (default 9, verbose) configurable via mcpServer.args in values.yaml. The Containerfile ENTRYPOINT sets --sse-port 8080 but Helm values override to 8000 via deployment template args causing a port mismatch if not aligned, the upstream repo is cloned at HEAD without version pinning making builds non-reproducible, and the builder stage requires internet access for both the Go tarball download and git clone."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [golang]
  ai_pattern: [agents]
  platform: [openshift]
source_examples:
  - quickstart: "lls-observability"
    repo: "https://github.com/rh-ai-kickstart/llama-stack-observability"
    notes: "UBI9 multi-stage build cloning manusa/kubernetes-mcp-server, compiling with make build, running on ubi-minimal"
    approach: "A"
---

# UBI Multi-Stage Go Build for Third-Party MCP Server

## Overview

This pattern builds a container image for a third-party MCP (Model Context Protocol) server by cloning the upstream Go repository at build time, compiling the binary using `make build`, and producing a minimal UBI runtime image containing only the compiled binary. The Containerfile is stored alongside the Helm chart for the MCP server deployment.

## Pattern Description

The openshift-mcp chart includes a `mcp-containerfile/Containerfile` that builds the `kubernetes-mcp-server` binary from the upstream `manusa/kubernetes-mcp-server` GitHub repository. The builder stage uses a full UBI9 image with Go 1.24.1 installed from the official Go download, clones the repo, and runs `make build`. The runtime stage copies just the compiled binary to a `ubi9/ubi-minimal` image. Unlike Python-based MCP server builds that require sed patching, the Go binary compiles cleanly from upstream source.

## Implementation

### Multi-Stage Containerfile

```dockerfile
# helm/04-mcp-servers/openshift-mcp/mcp-containerfile/Containerfile
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

EXPOSE 8080
```

### Pre-Built Image in Values

The chart defaults to a pre-built image rather than building from the Containerfile:

```yaml
# helm/04-mcp-servers/openshift-mcp/values.yaml
image:
  repository: quay.io/hveeradh/ocp-mcp-server
  tag: "latest"
  pullPolicy: IfNotPresent
```

### Runtime Configuration via Args

The MCP server is configured entirely through command-line arguments:

```yaml
# helm/04-mcp-servers/openshift-mcp/values.yaml
mcpServer:
  port: 8000
  args:
    - "--sse-port"
    - "8000"
```

## Configuration

- **Key settings:** The Containerfile hardcodes Go 1.24.1 and clones `main` branch HEAD; the runtime args `--sse-port` and `--log-level` control the MCP server behavior
- **Defaults:** Pre-built image at `quay.io/hveeradh/ocp-mcp-server:latest`; SSE port 8080 in Containerfile but 8000 in Helm values; log level 9 (verbose)
- **Dependencies:** Network access during build for Go download and git clone; the pre-built image must be accessible from the cluster

## Gotchas

- The Containerfile exposes port 8080 and uses `--sse-port 8080` in its ENTRYPOINT, but the Helm chart values configure `mcpServer.port: 8000` with args `--sse-port 8000` -- the deployment template overrides the Containerfile entrypoint with the chart's args (see Containerfile ENTRYPOINT vs `values.yaml` mcpServer.args)
- Go is installed by downloading the tarball from `go.dev` rather than using the UBI-provided Go package, because UBI9 may not have the required Go version (1.24.1) -- this means the builder stage requires internet access (see Containerfile RUN wget)
- The upstream repo is cloned at HEAD without version pinning, making builds non-reproducible -- the same issue as the Python clone-and-patch pattern (see Containerfile RUN git clone)
- The runtime image uses `ubi-minimal` which lacks common debugging tools; the binary is statically compiled Go so no additional libraries are needed (see Containerfile FROM ubi-minimal)

## Related Patterns

- `container-build-clone-patch-third-party-mcp.md` -- similar clone-at-build-time pattern but for Python MCP servers with sed patches
- `helm-llamastack-crd-mcp-remote-providers.md` -- the Llama Stack configuration that connects to this MCP server
