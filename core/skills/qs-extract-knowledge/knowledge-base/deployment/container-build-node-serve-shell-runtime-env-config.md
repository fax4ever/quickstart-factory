---
name: container-build-node-serve-shell-runtime-env-config
description: Node pnpm workspace multi-stage build with serve static server and shell script generating window.ENV runtime config at startup
summary: "Solves runtime-configurable React SPA container deployment using Node 20-alpine multi-stage build where the builder copies pnpm workspace root plus UI and shared configs packages (eslint/prettier dependencies), runs `pnpm install --no-frozen-lockfile` and `build:vite`, and the runtime installs `serve` globally with a non-root nodejs:1001 user. Use over nginx-based alternatives (container-build-node-nginx-envsubst-ws-proxy-runtime-config) when reverse proxy, WebSocket, and API forwarding are unnecessary; prefer Helm Secret-based config (helm-secret-mounted-runtime-config-react-spa) when config changes should trigger Helm release updates rather than pod restarts with env var injection. The startup shell script writes `window.ENV` from VITE_-prefixed env vars — BYPASS_AUTH as unquoted JS boolean, string values single-quoted — with `${VAR:-default}` fallbacks for Keycloak URL/realm/client-id, API base URL, and environment, served via `CMD [\"sh\", \"-c\", \"generate-env-config.sh && serve -s dist -l 8080\"]`. Critical gotcha: the env-config directory requires `chmod -R 777` (not just chown) for OpenShift arbitrary UID compatibility, `--no-frozen-lockfile` in the builder signals the lockfile may be out of sync with workspace structure, and the shared configs package must be copied into the builder stage even though only UI is built."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [react, nodejs]
  ai_pattern: []
  platform: [openshift]
source_examples:
  - quickstart: "spending-transaction-monitor"
    repo: "https://github.com/rh-ai-quickstart/spending-transaction-monitor"
    notes: "Node 20-alpine multi-stage with pnpm workspace, serve static server, generate-env-config.sh writing window.ENV at startup for Keycloak and API config"
    approach: "A"
---

# Node Multi-Stage with serve and Shell Script Runtime Config

## Overview

This pattern builds a React SPA using a multi-stage container with a pnpm workspace builder and a lightweight Node.js runtime that uses the `serve` npm package (not nginx) for static file serving. A shell script generates a `window.ENV` JavaScript object at container startup, enabling runtime configuration of API URLs, Keycloak endpoints, and feature flags without rebuilding the image.

## Pattern Description

The builder stage uses Node 20-alpine with pnpm workspaces to build only the UI package while copying workspace dependencies (configs package). The runtime stage uses a second Node 20-alpine image with the `serve` package installed globally, copies built assets from the builder, and runs a shell script at startup to generate an `env-config.js` file from environment variables. The SPA loads this file to get runtime-configurable settings like Keycloak URLs and auth bypass flags.

## Implementation

### Builder Stage with pnpm Workspace

```dockerfile
FROM node:20-alpine AS builder
WORKDIR /app
RUN npm install -g pnpm

# Copy root package files for workspace setup (context is root)
COPY package.json pnpm-lock.yaml* pnpm-workspace.yaml ./
COPY packages/ui/ ./packages/ui/
COPY packages/configs/ ./packages/configs/

WORKDIR /app/packages/ui
RUN pnpm install --no-frozen-lockfile
RUN pnpm run build:vite
```

Source: `packages/ui/Containerfile`

### Runtime Stage with serve

```dockerfile
FROM node:20-alpine
WORKDIR /app
RUN npm install -g serve

COPY --from=builder /app/packages/ui/dist ./dist
COPY packages/ui/generate-env-config.sh /usr/local/bin/generate-env-config.sh
RUN chmod +x /usr/local/bin/generate-env-config.sh

RUN addgroup -g 1001 -S nodejs && adduser -S nodejs -u 1001 -G nodejs
RUN mkdir -p /app/dist/env-config \
    && chmod -R 777 /app/dist/env-config \
    && chown -R nodejs:nodejs /app

USER nodejs
EXPOSE 8080
CMD ["sh", "-c", "generate-env-config.sh && serve -s dist -l 8080"]
```

Source: `packages/ui/Containerfile`

### Runtime Config Generation Script

The `generate-env-config.sh` script writes a JavaScript file that assigns configuration to `window.ENV`, using shell parameter expansion with defaults:

```sh
#!/bin/sh
cat > /app/dist/env-config/env-config.js << EOF
window.ENV = {
  BYPASS_AUTH: ${VITE_BYPASS_AUTH:-false},
  API_BASE_URL: '${VITE_API_BASE_URL:-/api}',
  ENVIRONMENT: '${VITE_ENVIRONMENT:-production}',
  KEYCLOAK_URL: '${VITE_KEYCLOAK_URL:-http://localhost:8080}',
  KEYCLOAK_REALM: '${VITE_KEYCLOAK_REALM:-spending-monitor}',
  KEYCLOAK_CLIENT_ID: '${VITE_KEYCLOAK_CLIENT_ID:-spending-monitor}',
  DEV: true
};
console.log('Runtime config loaded:', window.ENV);
EOF
```

Source: `packages/ui/generate-env-config.sh`

## Configuration

- **Runtime variables:** `VITE_BYPASS_AUTH`, `VITE_API_BASE_URL`, `VITE_ENVIRONMENT`, `VITE_KEYCLOAK_URL`, `VITE_KEYCLOAK_REALM`, `VITE_KEYCLOAK_CLIENT_ID`
- **Defaults:** All variables have sensible defaults via `${VAR:-default}` shell syntax
- **Port:** `serve -l 8080` serves on port 8080
- **Config path:** `/app/dist/env-config/env-config.js` directory is pre-created with `chmod 777` for OpenShift arbitrary UID compatibility

## Gotchas

- The `env-config` directory requires `chmod -R 777` because the non-root user needs to write the generated JS file at startup; `chown` alone is insufficient under OpenShift's arbitrary UID model
- `pnpm install --no-frozen-lockfile` is used instead of `--frozen-lockfile` in the builder, indicating the lockfile may not be committed or may be out of sync with workspace structure
- The `packages/configs/` directory must be copied into the builder even though only `packages/ui/` is being built, because it contains shared workspace dependencies (eslint, prettier configs)
- The `BYPASS_AUTH` variable is output without quotes in the JS (`${VITE_BYPASS_AUTH:-false}`) making it a boolean literal, while string values like `API_BASE_URL` use single quotes
- This uses `serve` (Node-based static server) instead of nginx, which is simpler but does not provide reverse proxy, WebSocket support, or API forwarding -- those are handled by separate OpenShift Routes or an nginx sidecar container

## Related Patterns

- `container-build-node-nginx-envsubst-ws-proxy-runtime-config.md` - nginx-based alternative with envsubst
- `helm-secret-mounted-runtime-config-react-spa.md` - Helm Secret-based config injection
