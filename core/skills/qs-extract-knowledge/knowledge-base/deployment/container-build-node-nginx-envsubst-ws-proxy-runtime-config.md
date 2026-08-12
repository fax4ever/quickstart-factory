---
name: container-build-node-nginx-envsubst-ws-proxy-runtime-config
description: Node 20-alpine pnpm workspace build with nginx runtime using envsubst for API upstream, WebSocket proxy, and inline JS runtime config
summary: "Solves deploying React SPAs that need runtime-configurable backend URLs (API_UPSTREAM), auth endpoints (KEYCLOAK_EXTERNAL), and branding without container rebuilds, using a Node 20-alpine pnpm workspace builder (corepack enable, --frozen-lockfile, build:vite producing dist/) and nginx alpine runtime with envsubst template substitution via the official docker-entrypoint.sh. Use when the SPA must reverse-proxy both REST and WebSocket traffic to a single backend, serve environment-specific config to the browser via a /runtime-config.js endpoint (JS assignment into window.__RUNTIME_CONFIG__ loaded by script tag, not JSON), and run under OpenShift's restricted SCC with arbitrary UIDs -- single approach covering build, proxy, and runtime config in one multi-stage Containerfile. Critical: the WebSocket upgrade map must be sed-injected into nginx.conf (not the conf.d template) because envsubst replaces $http_upgrade/$connection_upgrade with empty strings; nginx listens on port 8080 with proxy_read_timeout 300s for WebSocket, proxies /api/ plus /health/, /docs, /openapi.json, /admin/ for OpenShift Route path-multiplexing, and uses 1-year immutable static asset caching with SPA try_files fallback to /index.html. OpenShift arbitrary UID requires chmod/chgrp g+rwx on /var/cache/nginx, /var/log/nginx, /etc/nginx/conf.d, /etc/nginx/templates plus PID relocation from /run/nginx.pid to /var/run/nginx/nginx.pid; full packages/ directory must be copied in the builder because pnpm workspace dependencies (eslint-config, prettier-config) must resolve even when only packages/ui is built."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [react, nodejs, nginx]
  ai_pattern: []
  platform: [openshift]
source_examples:
  - quickstart: "multi-agent-loan-origination"
    repo: "https://github.com/rh-ai-quickstart/multi-agent-loan-origination"
    notes: "Node 20-alpine + nginx alpine multi-stage with pnpm workspace, envsubst API upstream, WebSocket upgrade map, runtime-config.js endpoint, and OpenShift arbitrary UID"
    approach: "A"
---

# Node-Nginx Multi-Stage with envsubst Runtime Config and WebSocket Proxy

## Overview

This pattern builds a React SPA using a multi-stage container: a Node 20-alpine builder with pnpm workspaces, and an nginx alpine runtime that serves static assets, reverse-proxies API and WebSocket traffic, and injects runtime configuration via nginx's envsubst mechanism. It solves the challenge of SPA applications needing runtime-configurable backend URLs and auth endpoints without rebuilding the container.

## Pattern Description

The builder stage copies the entire pnpm workspace, installs dependencies with `--frozen-lockfile`, and builds only the UI package. The runtime stage uses the official nginx alpine image with a custom config template. Nginx's built-in `docker-entrypoint.sh` substitutes environment variables (like `API_UPSTREAM` and `KEYCLOAK_EXTERNAL`) into the config template at container startup. A `runtime-config.js` endpoint dynamically returns a JavaScript object with configuration values, enabling the SPA to read environment-specific settings without a rebuild.

## Implementation

### Builder Stage with pnpm Workspace

```dockerfile
# packages/ui/Containerfile
FROM node:20-alpine AS builder
WORKDIR /app

# Copy root package files (for workspace setup)
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml* .npmrc* ./

# Copy all packages to support workspace dependencies
COPY packages/ ./packages/

# Enable corepack (uses packageManager field from package.json)
RUN corepack enable

# Install dependencies from root (workspace support)
RUN pnpm install --frozen-lockfile

# Build the UI application (vite only -- storybook is dev-only)
WORKDIR /app/packages/ui
RUN pnpm run build:vite
```

### Nginx Runtime with OpenShift Arbitrary UID Support

```dockerfile
# packages/ui/Containerfile (continued)
FROM docker.io/nginx:alpine AS runtime

COPY --from=builder /app/packages/ui/dist /usr/share/nginx/html

# Copy nginx config template (envsubst substitutes API_UPSTREAM at runtime)
COPY packages/ui/nginx/default.conf.template /etc/nginx/templates/default.conf.template

# Bake WebSocket upgrade map into nginx.conf (NOT in conf.d/ where
# envsubst would mangle the $http_upgrade / $connection_upgrade variables)
RUN sed -i '/http {/a \    map $http_upgrade $connection_upgrade {\n        default upgrade;\n        ""      close;\n    }' /etc/nginx/nginx.conf

# Make directories writable for OpenShift's arbitrary UID
RUN chmod -R g+rwx /var/cache/nginx /var/log/nginx /etc/nginx/conf.d /etc/nginx/templates && \
    chgrp -R 0 /var/cache/nginx /var/log/nginx /etc/nginx/conf.d /etc/nginx/templates && \
    mkdir -p /var/run/nginx && \
    chmod -R g+rwx /var/run/nginx && chgrp -R 0 /var/run/nginx

# Point nginx PID to a writable location
RUN sed -i 's|/run/nginx.pid|/var/run/nginx/nginx.pid|' /etc/nginx/nginx.conf
```

### Nginx Config Template with WebSocket and Runtime Config

```nginx
# packages/ui/nginx/default.conf.template
server {
    listen 8080;
    root /usr/share/nginx/html;

    # API reverse proxy (REST + WebSocket)
    location /api/ {
        proxy_pass http://${API_UPSTREAM}/api/;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_read_timeout 300s;
    }

    # Runtime config (injected at container start)
    location = /runtime-config.js {
        default_type application/javascript;
        return 200 'window.__RUNTIME_CONFIG__={KEYCLOAK_URL:"${KEYCLOAK_EXTERNAL}",KEYCLOAK_REALM:"${KEYCLOAK_REALM}",KEYCLOAK_CLIENT_ID:"${KEYCLOAK_CLIENT_ID}",COMPANY_NAME:"${COMPANY_NAME}",AGENT_NAME:"${AGENT_NAME}"};';
    }

    # SPA client-side routing
    location / {
        try_files $uri $uri/ /index.html;
    }

    # Static asset caching (1 year, immutable)
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {
        expires 1y;
        add_header Cache-Control "public, immutable";
    }
}
```

## Configuration

- **Key settings:** `API_UPSTREAM` (default: `mortgage-ai-api:8000`) sets the backend host:port; `KEYCLOAK_EXTERNAL` provides the browser-reachable Keycloak URL; `COMPANY_NAME` and `AGENT_NAME` are display-only branding values
- **Defaults:** Listens on port 8080; WebSocket timeout is 300s; static assets cached 1 year; SPA fallback to `/index.html`
- **Dependencies:** The pnpm workspace root must contain the lockfile; the UI build (`build:vite`) must produce output in `dist/`; nginx image must be the official image with `docker-entrypoint.sh` that processes `/etc/nginx/templates/`

## Gotchas

- The WebSocket upgrade `map` is injected directly into `nginx.conf` via `sed`, not into the template file -- this is because envsubst in `conf.d/` templates would mangle the `$http_upgrade` and `$connection_upgrade` variables, replacing them with empty strings (see `packages/ui/Containerfile` lines 39-41)
- The `runtime-config.js` endpoint returns a JavaScript assignment, not JSON -- the SPA loads this via a `<script>` tag and reads `window.__RUNTIME_CONFIG__`; envsubst substitutes the env vars at runtime (see `packages/ui/nginx/default.conf.template`)
- The PID file location must be changed from `/run/nginx.pid` to `/var/run/nginx/nginx.pid` because `/run/` is not writable under OpenShift's restricted SCC (see `packages/ui/Containerfile` line 54)
- The `packages/` directory is copied entirely in the builder stage even though only `packages/ui/` is built -- this is because pnpm workspace dependencies (eslint-config, prettier-config) must be present for install to succeed (see `packages/ui/Containerfile` line 15-16)
- The config template proxies `/health/`, `/docs`, `/redoc`, `/openapi.json`, and `/admin/` paths to the API backend -- these proxy locations support the OpenShift Route path-multiplexing pattern where all paths share one hostname (see `packages/ui/nginx/default.conf.template`)

## Related Patterns

- `container-build-ubi-multistage-fullstack.md` -- UBI-based fullstack build pattern
- `helm-openshift-routes-shared-host-path-multiplexing.md` -- the Route pattern that works with this nginx config
