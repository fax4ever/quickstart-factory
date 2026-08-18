---
name: container-build-ubi9-node-nginx-multistage-vite-api-proxy
description: UBI9 Node 20 + UBI9 Nginx 120 multistage for React/Vite with build-time ARGs and nginx /api/ reverse proxy
summary: "Containerizes a React/Vite SPA for enterprise OpenShift using UBI9-only multistage builds (ubi9/nodejs-20 builder, ubi9/nginx-120 runtime) to avoid Docker Hub dependency in restricted environments. Use when the frontend needs UBI9-based images with nginx serving and /api/ reverse proxy to a backend orchestrator; prefer container-build-node-nginx-envsubst-ws-proxy-runtime-config.md when runtime environment injection via envsubst is needed without image rebuilds. Dockerfile passes Vite variables as build ARGs (VITE_ORCHESTRATOR_URL defaults to /api/chat, plus optional VITE_OPENAI_API_ENDPOINT/TOKEN/MODEL) converted to ENV for build-time import.meta.env injection; nginx.conf is a full replacement (not conf.d partial) serving on port 8080 with try_files SPA routing, /api/ rewrite-and-proxy to http://orchestrator:5000 at 300s timeout, and chgrp -R 0 + chmod g+rwX for OpenShift arbitrary UID. Vite ARGs are baked at build time (rebuild required unless overridden by runtime-config.js Secret mount), proxy_pass hardcodes DNS name \"orchestrator\" which must resolve via compose service or Kubernetes Service created by the Helm chart, and nginx.conf replaces the entire config so it must include worker_processes/events/pid blocks."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [react, nodejs, nginx]
  ai_pattern: []
  platform: [openshift]
source_examples:
  - quickstart: "portfolio-manager-agent"
    repo: "https://github.com/rh-ai-quickstart/portfolio-manager-agent"
    notes: "UBI9 Node 20 builder with Vite ARGs, UBI9 Nginx 120 runtime with custom nginx.conf proxying /api/ to orchestrator backend"
    approach: "A"
---

# UBI9 Node + Nginx Multistage for React/Vite with API Reverse Proxy

## Overview

This pattern builds a React/Vite SPA using a multistage UBI9-based Dockerfile and serves it via UBI9 Nginx with a custom configuration that reverse-proxies API requests to the backend orchestrator. It keeps the frontend image based entirely on Red Hat Universal Base Images for enterprise environments where Docker Hub pulls may be restricted.

## Pattern Description

The build stage uses `ubi9/nodejs-20` to install npm dependencies and run the Vite build, with Vite environment variables passed as Docker build ARGs that become available during the build. The runtime stage uses `ubi9/nginx-120` to serve the built static files, with a custom `nginx.conf` that handles SPA client-side routing (`try_files`) and reverse-proxies `/api/` requests to the backend service. The group permissions are adjusted for OpenShift's arbitrary UID support.

## Implementation

### Multistage Dockerfile

```dockerfile
# frontend/Dockerfile
# Stage 1: build (Red Hat UBI -- avoids Docker Hub auth in restricted environments)
FROM registry.access.redhat.com/ubi9/nodejs-20 AS build

USER 0
WORKDIR /app

ARG VITE_ORCHESTRATOR_URL=/api/chat
ARG VITE_OPENAI_API_ENDPOINT=
ARG VITE_OPENAI_API_TOKEN=
ARG VITE_OPENAI_MODEL=

ENV VITE_ORCHESTRATOR_URL=$VITE_ORCHESTRATOR_URL \
    VITE_OPENAI_API_ENDPOINT=$VITE_OPENAI_API_ENDPOINT \
    VITE_OPENAI_API_TOKEN=$VITE_OPENAI_API_TOKEN \
    VITE_OPENAI_MODEL=$VITE_OPENAI_MODEL

COPY package.json package-lock.json* ./
RUN npm install

COPY . .
RUN npm run build

# Stage 2: serve
FROM registry.access.redhat.com/ubi9/nginx-120

USER 0
COPY nginx.conf /etc/nginx/nginx.conf
COPY --from=build /app/dist /usr/share/nginx/html
RUN chgrp -R 0 /usr/share/nginx/html && chmod -R g+rwX /usr/share/nginx/html

EXPOSE 8080

CMD ["nginx", "-g", "daemon off;"]
```

### Nginx Configuration with API Proxy

```nginx
# frontend/nginx.conf
worker_processes auto;
error_log /var/log/nginx/error.log notice;
pid /run/nginx.pid;

events {
    worker_connections 1024;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    sendfile on;
    keepalive_timeout 65;

    server {
        listen 8080;
        server_name _;
        root /usr/share/nginx/html;
        index index.html;

        location /api/ {
            rewrite ^/api/(.*)$ /$1 break;
            proxy_pass http://orchestrator:5000;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_read_timeout 300s;
        }

        location / {
            try_files $uri $uri/ /index.html;
        }

        gzip on;
        gzip_types text/plain text/css application/json application/javascript text/xml application/xml;
    }
}
```

## Configuration

- **Key settings:** `VITE_ORCHESTRATOR_URL` defaults to `/api/chat` (relative path, proxied by nginx); `VITE_OPENAI_API_ENDPOINT`, `VITE_OPENAI_API_TOKEN`, `VITE_OPENAI_MODEL` default to empty strings for optional LLM configuration
- **Defaults:** Nginx listens on port 8080; API proxy targets `http://orchestrator:5000`; `proxy_read_timeout` is 300s for long-running LLM requests; gzip enabled for common web content types
- **Dependencies:** Backend orchestrator service must be reachable at `http://orchestrator:5000` from within the container network; nginx.conf is a complete replacement (not a partial override)

## Gotchas

- The `/api/` location uses `rewrite ^/api/(.*)$ /$1 break` to strip the `/api/` prefix before forwarding to the backend -- the orchestrator does not have `/api/` in its routes (see `frontend/nginx.conf`)
- The Vite ARG/ENV pattern (`ARG VITE_X` followed by `ENV VITE_X=$VITE_X`) is required because Vite reads from `import.meta.env` at build time, not runtime -- changing these values requires rebuilding the image unless overridden by the runtime-config.js Secret mount (see `frontend/Dockerfile`)
- The nginx.conf copies `nginx.conf` to `/etc/nginx/nginx.conf` (the main config), not to `/etc/nginx/conf.d/` (a partial config) -- this replaces the entire nginx configuration, which is why it includes `worker_processes`, `error_log`, `pid`, and `events` blocks (see `frontend/Dockerfile`)
- The `chgrp -R 0 /usr/share/nginx/html && chmod -R g+rwX` ensures the static files are readable by OpenShift's arbitrary UID, since the UBI nginx image runs with a random UID in the root group (see `frontend/Dockerfile`)
- The `proxy_pass http://orchestrator:5000` hardcodes the backend DNS name, which only works in compose or Kubernetes where DNS resolves `orchestrator` to the backend service; on the cluster, the Helm chart creates a Service named `orchestrator` matching this expectation (see `frontend/nginx.conf` and `deploy/helm/templates/service-orchestrator.yaml`)

## Related Patterns

- `helm-secret-mounted-runtime-config-react-spa.md` -- runtime config injection for this frontend at deploy time
- `container-build-node-nginx-envsubst-ws-proxy-runtime-config.md` -- alternative pattern using envsubst and alpine images
- `container-build-node-multistage-ubi9-nginx-react-console-plugin.md` -- UBI9 nginx for console plugins
