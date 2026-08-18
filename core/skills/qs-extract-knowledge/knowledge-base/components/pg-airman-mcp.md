---
name: pg-airman-mcp
description: "PostgreSQL MCP server providing database analysis tools for AI agents via streamable-http transport"
summary: "pg-airman-mcp is an EnterpriseDB PostgreSQL MCP server exposing 10 database tools (schema discovery, SQL execution, explain plans, index recommendations, health checks) via FastMCP/streamable-http for AI agents in data governance workflows, deployed as quay.io/rh-ai-quickstart/pg-airman-mcp with 2 replicas and OpenShift restricted SCC (arbitrary UID via chmod g=u). Use when AI agents need structured database access via MCP — consumers wire via mcp.serviceUrl for copilot-backend MCP Direct mode or mcp.serviceName for Llama Stack agent delegation; only streamable-http transport is supported despite sse/stdio chart templating. Defense-in-depth uses mcp_readonly PostgreSQL user with DATABASE_URI in a Kubernetes Secret and restricted accessMode, ClientIP session affinity (10800s) for MCP state preservation, and default postgres.host targeting StatefulSet pod pgvector-0 by ordinal. The upstream image is broken — a custom BuildConfig must fix four issues: missing libpq5 for psycopg (ImportError at startup), MCP SDK >=1.8.0 DNS rebinding 421 on Kubernetes service names (patched via TransportSecuritySettings(enable_dns_rebinding_protection=False)), list_schemas noop parameter for agent frameworks, and virtualenv shebang path mismatch; additionally add_comment_to_object (1/10 tools) fails with mcp_readonly user due to COMMENT ON requiring table ownership."
metadata:
  type: component
tags:
  tech_stack: [python, mcp, fastmcp, psycopg, uv]
  ai_pattern: [agents, mcp-tools]
  platform: [openshift, kubernetes]
  data_layer: [postgresql, pgvector]
source_examples:
  - quickstart: "data-governance-co-pilot"
    repo: "https://github.com/rh-ai-quickstart/data-governance-co-pilot"
    notes: "PostgreSQL MCP server exposing 10 database tools (schema discovery, query execution, index analysis, health checks) for a data governance copilot with read-only user defense-in-depth"
    approach: "A"
---

# pg-airman-mcp

## Overview

A PostgreSQL Model Context Protocol (MCP) server from EnterpriseDB that exposes database analysis tools -- schema discovery, SQL execution, explain plans, index recommendations, and health checks -- as JSON-RPC tools consumable by AI agents over streamable-http transport. In the data-governance-co-pilot quickstart, the copilot-backend (in MCP Direct mode) or Llama Stack (in agent delegation mode) connects to this server to give the LLM structured access to a PostgreSQL database for data governance workflows.

## Tech Stack & Dependencies

- **Runtime:** Python 3.12 (`python:3.12-slim-bookworm` base image)
- **Container image:** `quay.io/rh-ai-quickstart/pg-airman-mcp:latest` (custom-built via OpenShift BuildConfig; the upstream `enterprisedb/pg-airman-mcp` image is broken)
- **Key dependencies:** `mcp` (FastMCP framework), `psycopg` (PostgreSQL adapter requiring `libpq5` runtime library)
- **Helm subchart:** Standalone Helm chart at `helm/pg-airman-mcp/` (not a shared subchart)
- **Upstream project:** [EnterpriseDB/pg-airman-mcp](https://github.com/EnterpriseDB/pg-airman-mcp)

## Key Patterns

### Custom Image Build via OpenShift BuildConfig

The upstream Docker image is missing the `libpq5` runtime library, causing `ImportError: libpq.so.5: cannot open shared object file` at startup. The quickstart builds a fixed image using an OpenShift BuildConfig with an inline multi-stage Dockerfile that adds `libpq5` and applies patches.

```yaml
# helm/pg-airman-mcp/buildconfig.yaml (lines 14-17, 51-58)
spec:
  source:
    type: Dockerfile
    dockerfile: |
      # ...
      # CRITICAL FIX: Install libpq5 (runtime library) not just libpq-dev (headers)
      RUN apt-get update && apt-get install -y --no-install-recommends \
          libpq5 \
          dnsutils \
          iputils-ping \
          net-tools \
          && rm -rf /var/lib/apt/lists/*
```

The built image is stored in the OpenShift internal registry via an ImageStream:

```yaml
# helm/pg-airman-mcp/imagestream.yaml (lines 1-6)
apiVersion: image.openshift.io/v1
kind: ImageStream
metadata:
  name: pg-airman-mcp
spec:
  lookupPolicy:
    local: true
```

### DNS Rebinding Protection Patch for Kubernetes

MCP Python SDK v1.8.0+ introduced Host header validation that rejects requests from Kubernetes service DNS names (e.g., `pg-airman-mcp-service:8000`) with `421 Misdirected Request`. The BuildConfig patches the upstream source to disable this protection, since Kubernetes provides its own network security boundaries.

```bash
# helm/pg-airman-mcp/buildconfig.yaml (lines 38-40)
RUN sed -i '/from mcp.server.fastmcp import FastMCP/a from mcp.server.transport_security import TransportSecuritySettings' src/pg_airman_mcp/server.py && \
    sed -i 's/mcp = FastMCP("pg-airman-mcp")/mcp = FastMCP(\n    "pg-airman-mcp",\n    transport_security=TransportSecuritySettings(\n        enable_dns_rebinding_protection=False,\n    )\n)/' src/pg_airman_mcp/server.py
```

### list_schemas Noop Parameter Workaround

The `list_schemas` tool is patched to add a required string parameter, matching the pattern used by `list_objects`. This works around an issue where parameterless MCP tools cause problems in some agent frameworks.

```bash
# helm/pg-airman-mcp/buildconfig.yaml (line 41)
sed -i "s/async def list_schemas() -> ResponseType:/async def list_schemas(noop: str = Field(description=\"Workaround parameter, always use 'doit'\")) -> ResponseType:/" src/pg_airman_mcp/server.py
```

### Read-Only Database User for Defense-in-Depth

The MCP server connects to PostgreSQL using a dedicated `mcp_readonly` user instead of the `postgres` superuser. This user can SELECT from tables/views and read system catalogs but cannot modify data or schema, limiting blast radius if the server is compromised.

```yaml
# helm/pg-airman-mcp/values.yaml (lines 4-11)
# SECURITY: Uses read-only user (mcp_readonly) for defense-in-depth
postgres:
  host: pgvector-0.pgvector-postgres-service
  port: 5432
  user: mcp_readonly
  password: <postgres readonly password>
  database: <postgres database>
```

The DATABASE_URI is constructed and stored as a Kubernetes Secret:

```yaml
# helm/pg-airman-mcp/templates/secret.yaml (lines 10-12)
stringData:
  DATABASE_URI: "postgresql://{{ .Values.postgres.user | urlquery }}:{{ .Values.postgres.password | urlquery }}@{{ .Values.postgres.host }}:{{ .Values.postgres.port }}/{{ .Values.postgres.database }}"
```

### Transport and Access Mode via Container Args

The deployment template passes transport and access mode as command-line arguments, with conditional port arguments depending on the selected transport.

```yaml
# helm/pg-airman-mcp/templates/deployment.yaml (lines 38-45)
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

### ClientIP Session Affinity for MCP State Preservation

The Service uses `sessionAffinity: ClientIP` to ensure each copilot-backend pod connects to the same MCP pod, preserving database connection state across requests. The timeout is set to 3 hours.

```yaml
# helm/pg-airman-mcp/templates/service.yaml (lines 14-18)
sessionAffinity: ClientIP
sessionAffinityConfig:
  clientIP:
    timeoutSeconds: 10800  # 3 hours
```

### OpenShift-Compatible Security Context

The deployment uses a restricted security context with non-root execution, dropped capabilities, and seccomp profiling to comply with OpenShift's restricted SCC.

```yaml
# helm/pg-airman-mcp/templates/deployment.yaml (lines 22-35)
securityContext:
  runAsNonRoot: true
  seccompProfile:
    type: RuntimeDefault
# ...
securityContext:
  allowPrivilegeEscalation: false
  capabilities:
    drop:
      - ALL
  privileged: false
  runAsNonRoot: true
```

The Dockerfile also sets `chmod -R g=u /app && chgrp -R 0 /app` to support OpenShift's arbitrary UID assignment.

## Configuration

- **Environment variables:**
  - `DATABASE_URI` -- PostgreSQL connection string, injected from Kubernetes Secret (`pg-airman-mcp-secret`). Constructed from Helm values for user, password, host, port, and database.
  - `ALLOW_COMMENT_IN_RESTRICTED` -- Whether to allow `add_comment_to_object` in restricted mode (default: `false`).
- **Config files:** None; all configuration via Helm values and environment variables.
- **Helm values:**
  - `mcp.accessMode` -- `restricted` (read-only, default) or `unrestricted` (read-write, development only)
  - `mcp.transport` -- `streamable-http` (default and only supported option in this quickstart), `sse`, or `stdio`
  - `mcp.port` -- Port for HTTP transports (default: `8000`)
  - `postgres.host` -- PostgreSQL hostname (default: `pgvector-0.pgvector-postgres-service` -- points to pgvector StatefulSet pod)
  - `postgres.user` -- Database user (default: `mcp_readonly`)
  - `postgres.password` / `postgres.database` -- Required, provided at install time
  - `replicas` -- Number of replicas (default: `2`)
  - `image.repository` -- Container image (default: `quay.io/rh-ai-quickstart/pg-airman-mcp`)
- **Consumer wiring:**
  - `copilot-backend` references MCP via `mcp.serviceUrl: "http://pg-airman-mcp-service:8000"` in its values.yaml
  - `copilot-llama-stack` references MCP via `mcp.serviceName: "pg-airman-mcp-service"` and `mcp.port: 8000`

## Known Gotchas

- **Upstream image missing libpq5:** The official `enterprisedb/pg-airman-mcp` Docker image installs `libpq-dev` (headers) but not `libpq5` (runtime library) in the final stage, causing `ImportError: libpq.so.5: cannot open shared object file`. The quickstart works around this with a custom BuildConfig (see `LIBPQ_FIX.md` and `buildconfig.yaml`). Cannot be fixed at runtime on OpenShift because containers run as non-root with random UIDs.
- **MCP SDK DNS rebinding protection breaks Kubernetes service names:** MCP Python SDK >= 1.8.0 rejects requests with Host headers like `pg-airman-mcp-service:8000` as DNS rebinding attacks, returning `421 Misdirected Request`. The BuildConfig patches the server to disable this check (see `PATCH_NOTES.md`).
- **Shebang path mismatch after COPY:** The builder stage installs the virtualenv at `/tmp/pg-airman-mcp/.venv`, but the runtime stage copies it to `/app/.venv`. The BuildConfig includes a `find /app/.venv/bin -type f -exec sed -i` to fix shebangs (buildconfig.yaml line 66).
- **add_comment_to_object tool fails with readonly user:** The `mcp_readonly` user lacks table ownership required for `COMMENT ON`, so this tool (1 of 10) returns a permission error. The remaining 9 tools work normally. Documented in `READONLY_USER_IMPLEMENTATION.md`.
- **Only streamable-http transport is supported:** The README explicitly states "Use mcp.transport 'streamable-http' only. The other options are not supported by this quickstart," despite the chart templating also supporting `sse` and `stdio` transports.
- **Postgres host targets StatefulSet pod directly:** The default `postgres.host` value (`pgvector-0.pgvector-postgres-service`) connects to a specific StatefulSet pod by ordinal rather than through a load-balanced service, which is appropriate for single-replica PostgreSQL but would need adjustment for replicated setups.

## Testing Notes

- Check pod starts without `ImportError` by viewing logs: `oc logs -l app.kubernetes.io/name=pg-airman-mcp`
- Verify libpq5 is installed inside the container: `dpkg -l | grep libpq` should show `libpq5`
- Test MCP connectivity by port-forwarding: `oc port-forward svc/pg-airman-mcp-service 8000:8000` then `curl http://localhost:8000/health`
- Verify restricted mode blocks writes by attempting an `execute_sql` with INSERT/UPDATE via the MCP client
- Confirm session affinity works by checking that repeated requests from the same backend pod reach the same MCP pod (inspect logs for source IPs)

## Related Patterns

- The copilot-backend connects to this server via `mcp.serviceUrl` in MCP Direct mode, managing the agentic loop itself
- Llama Stack connects via `mcp.serviceName` when used in agent delegation mode, with Llama Stack managing the agentic loop
- The pgvector chart creates the `mcp_readonly` user that this server authenticates with
- The disabled `networkpolicy.yaml` shows a pattern for restricting MCP server network access to only the copilot-backend and pgvector pods
