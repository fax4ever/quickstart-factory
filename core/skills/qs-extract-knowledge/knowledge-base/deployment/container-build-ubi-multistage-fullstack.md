---
name: container-build-ubi-multistage-fullstack
description: Multi-stage UBI Containerfile combining React frontend build and FastAPI backend into a single image
summary: "Builds a single production container image combining a compiled React frontend and FastAPI backend using a two-stage UBI9 Containerfile (ubi9/nodejs-22 frontend-builder stage produces dist/ assets, ubi9/python-312 final stage serves them as static files via the backend). Use for fullstack Python+React quickstarts deployed to OpenShift that need one image with database migrations at startup -- MCP server sidecars use simpler single-stage python:3.11-slim Containerfiles instead, and local dev uses separate backend/frontend Containerfiles with volume mounts and Vite dev server on port 5173. Critical config: entrypoint installs nmap-ncat via `dnf install -y --disablerepo='rhel-*'` for PostgreSQL readiness checks, runs `alembic upgrade head`, then starts `uvicorn backend.main:app --host 0.0.0.0 --port 8000` as non-root user 1001, with `NODE_OPTIONS=--max-old-space-size=512` limiting memory during the frontend build stage. Gotcha: `frontend/src/assets/` must be COPY'd separately into `backend/public/assets` in addition to the built dist/ because the backend references assets independently of the frontend build output, and `--disablerepo='rhel-*'` is required on `dnf install` because UBI images may have inaccessible RHEL repos in non-subscribed environments."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [fastapi, react, python, nodejs]
  ai_pattern: []
  platform: [openshift]
source_examples:
  - quickstart: "ai-virtual-agent"
    repo: "https://github.com/rh-ai-quickstart/ai-virtual-agent"
    notes: "UBI9 Node.js 22 builds frontend; UBI9 Python 3.12 runs backend serving frontend dist as static files"
    approach: "A"
---

# Multi-Stage UBI Containerfile for Fullstack App

## Overview

This pattern builds a single production container image that includes both the compiled React frontend and the FastAPI backend. The frontend is built in a UBI9 Node.js stage and the resulting `dist/` output is copied into the backend stage, where the FastAPI application serves it as static files.

## Pattern Description

The production Containerfile uses two stages: a `frontend-builder` stage based on `ubi9/nodejs-22` that runs `npm install` and `npm run build`, and a final stage based on `ubi9/python-312` that installs Python dependencies, copies backend code, and receives the compiled frontend assets from the builder stage. The final image runs as non-root user 1001 and uses a custom entrypoint script that handles database migration before starting uvicorn.

## Implementation

### Production Containerfile

```dockerfile
# deploy/cluster/Containerfile
FROM registry.access.redhat.com/ubi9/nodejs-22 AS frontend-builder
USER root
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm install --debug
COPY frontend/ ./
ENV NODE_OPTIONS=--max-old-space-size=512
RUN npm run build

FROM registry.access.redhat.com/ubi9/python-312:latest
USER root
WORKDIR /app
RUN dnf install -y --disablerepo='rhel-*' nmap-ncat && dnf clean all
COPY backend/requirements.txt ./backend/
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend/ ./backend/
COPY frontend/src/assets/ ./backend/public/assets
COPY deploy/cluster/scripts/entrypoint.sh ./entrypoint.sh
COPY --from=frontend-builder /app/frontend/dist ./backend/public/
USER 1001
EXPOSE 8000
CMD ["./entrypoint.sh"]
```

### Entrypoint Script

The entrypoint waits for PostgreSQL to be reachable (using `nmap-ncat`), runs Alembic database migrations, then starts uvicorn:

```bash
# deploy/cluster/scripts/entrypoint.sh
#!/bin/bash -x
until nc -z "${DB_HOST}" "${DB_PORT}"; do
  echo "Waiting for PostgreSQL to be reachable..."
  sleep 5
done
echo "PostgreSQL is reachable!"
cd backend && alembic upgrade head && cd ..
uvicorn --log-level=debug backend.main:app --host 0.0.0.0 --port 8000
```

### MCP Server Containerfiles

The MCP servers use a simpler, single-stage build based on `python:3.11-slim` (not UBI):

```dockerfile
# mcp_servers/flight_mcp/Containerfile (identical for hotel_mcp, travel_research_mcp)
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY server.py .
ENV PYTHONUNBUFFERED=1
CMD ["python", "server.py"]
```

### Dev Containerfiles

Separate Containerfiles exist for local development. The backend dev Containerfile installs coverage tools and mounts code via volume (no COPY of backend source):

```dockerfile
# deploy/local/Containerfile.backend.dev (excerpt)
FROM registry.access.redhat.com/ubi9/python-312:latest
RUN pip install --prefer-binary --no-cache-dir -r requirements.txt
RUN pip install --prefer-binary --no-cache-dir 'coverage[toml]>=7.0.0'
COPY .coveragerc /app/.coveragerc
COPY deploy/local/scripts/start-backend-dev.sh /app/start-backend-dev.sh
CMD ["/app/start-backend-dev.sh"]
```

The frontend dev Containerfile runs the Vite dev server as non-root user 1001:

```dockerfile
# deploy/local/Containerfile.frontend.dev (excerpt)
FROM registry.access.redhat.com/ubi9/nodejs-22:latest
USER 1001
COPY --chown=1001:0 frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY --chown=1001:0 frontend/ ./
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]
```

## Configuration

- **Key settings:** `NODE_OPTIONS=--max-old-space-size=512` limits Node.js memory during frontend build; `nmap-ncat` is installed via `dnf` for the database readiness check
- **Defaults:** Production image runs as user 1001; dev images run the Vite dev server on port 5173
- **Dependencies:** Production build requires the `entrypoint.sh` script at `deploy/cluster/scripts/`; frontend assets from `frontend/src/assets/` are copied separately for static file serving alongside the built `dist/`

## Gotchas

- The production Containerfile copies `frontend/src/assets/` directly into `backend/public/assets` in addition to the built frontend `dist/`. This is because some assets (like images) are referenced by the backend independently of the frontend build output (see `deploy/cluster/Containerfile` line 40)
- The `--disablerepo='rhel-*'` flag on `dnf install` is needed because the UBI image may have RHEL repos configured that are not accessible in non-subscribed environments (see `deploy/cluster/Containerfile` line 31)
- MCP server Containerfiles use `python:3.11-slim` instead of UBI, which is a different base image family from the main application (see `mcp_servers/*/Containerfile`)

## Related Patterns

- `compose-local-dev-ollama-llamastack-mcp.md` -- uses the dev Containerfiles
- `github-actions-multi-image-release-pipeline.md` -- builds these Containerfiles in CI
