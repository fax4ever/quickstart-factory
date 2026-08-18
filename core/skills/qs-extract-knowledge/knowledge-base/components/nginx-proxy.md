---
name: nginx-proxy
description: "Nginx reverse proxy unifying UI and API behind a single endpoint with WebSocket support and CORS handling"
summary: "Nginx reverse proxy (nginx:1.25-alpine) unifies React UI (port 8080) and FastAPI API (port 8000) behind a single endpoint with path-based routing, WebSocket upgrades (/api/ws/ with HTTP/1.1 upgrade headers and 3600s timeout), and CORS handling -- used for local podman-compose development (bind-mounted nginx.conf at localhost:3000) but disabled by default on OpenShift in favour of native Routes. Toggle via Helm nginx.enabled (default false): when disabled, set routes.sharedHost to create three separate OpenShift Routes (UI, API, health) sharing one hostname; when enabled, a single Route points to the nginx Service (resources: 64Mi/128Mi memory, 50m/200m CPU). The Helm ConfigMap (nginx-configmap.yaml) enables OpenShift restricted-SCC compatibility by redirecting pid and all temp paths (proxy_temp_path, client_body_temp_path, fastcgi_temp_path, uwsgi_temp_path, scgi_temp_path) to /tmp, adds hardened security headers (X-Frame-Options, CSP, X-Content-Type-Options), explicit CORS with OPTIONS preflight returning 204, and forwards the Authorization header for Keycloak integration. Never use rewrite ^/api/(.*)$ /$1 break; to strip the /api/ prefix -- FastAPI expects it and stripping causes 404s (removed in commit 74af2b1); the /api/ws/ WebSocket location must precede the generic /api/ block or upgrade headers are lost; and all nginx temp paths must redirect to /tmp for OpenShift restricted SCC or the container fails on read-only filesystems."
metadata:
  type: component
tags:
  tech_stack: [nginx, openshift-routes]
  platform: [openshift, kubernetes]
source_examples:
  - quickstart: "spending-transaction-monitor"
    repo: "https://github.com/rh-ai-quickstart/spending-transaction-monitor"
    notes: "Nginx reverse proxy for local dev; disabled on OpenShift in favour of native Routes"
    approach: "A"
---

# Nginx Proxy

## Overview

Nginx acts as a reverse proxy that unifies a React UI and a FastAPI API behind a single entry point, handling path-based routing, WebSocket upgrades, and CORS. In the spending-transaction-monitor quickstart the proxy is used for local (podman-compose) development but is disabled by default on OpenShift, where native Routes provide the same path-based routing without an extra container.

## Tech Stack & Dependencies

- **Runtime:** `nginx:1.25-alpine` (Helm), `nginx:alpine` (podman-compose)
- **Container image:** `docker.io/library/nginx:alpine` (local), `nginx:1.25-alpine` (Helm values)
- **Key dependencies:** Upstream `spending-monitor-ui` (port 8080) and `spending-monitor-api` (port 8000)
- **Helm subchart:** None -- deployed as part of the `spending-monitor` chart via dedicated templates (`nginx-deployment.yaml`, `nginx-service.yaml`, `nginx-configmap.yaml`)

## Key Patterns

### Path-Based Reverse Proxy (Local Development)

The root-level `nginx.conf` is bind-mounted read-only into the podman-compose container and routes traffic by URL path.

```nginx
upstream ui {
    server spending-monitor-ui:8080;
}
upstream api {
    server spending-monitor-api:8000;
}
server {
    listen 80;
    location /api/ws/ { ... }   # WebSocket -- most specific first
    location /api/   { ... }    # REST API
    location /health/ { ... }   # Health probe
    location /       { ... }    # UI fallback
}
```

Source: `nginx.conf` (root of repo)

### WebSocket Proxy Support

WebSocket connections under `/api/ws/` require HTTP/1.1 upgrade headers and extended timeouts. The location block must appear before the generic `/api/` block to match first.

```nginx
location /api/ws/ {
    proxy_pass http://api/api/ws/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
}
```

Source: `nginx.conf`, lines 18-30

### OpenShift-Restricted Security Context (Helm)

The Helm ConfigMap redirects all temp paths to `/tmp` so nginx can run as a non-root, read-only-capable user under OpenShift's restricted SCC.

```nginx
pid /tmp/nginx.pid;
http {
    proxy_temp_path /tmp/proxy_temp;
    client_body_temp_path /tmp/client_temp;
    fastcgi_temp_path /tmp/fastcgi_temp;
    uwsgi_temp_path /tmp/uwsgi_temp;
    scgi_temp_path /tmp/scgi_temp;
    ...
}
```

Source: `deploy/helm/spending-monitor/templates/nginx-configmap.yaml`, lines 10-21

### CORS Handling in Helm ConfigMap

The Helm variant adds explicit CORS headers and an OPTIONS preflight handler on the `/api/` location, which the local `nginx.conf` omits (the API handles CORS itself locally).

```nginx
location /api/ {
    ...
    add_header 'Access-Control-Allow-Origin' '*' always;
    add_header 'Access-Control-Allow-Methods' 'GET, POST, PUT, DELETE, OPTIONS' always;
    if ($request_method = 'OPTIONS') {
        return 204;
    }
}
```

Source: `deploy/helm/spending-monitor/templates/nginx-configmap.yaml`, lines 42-64

### Security Headers (Helm)

The Helm ConfigMap adds hardened response headers inside the `server` block.

```nginx
add_header X-Frame-Options "SAMEORIGIN" always;
add_header X-XSS-Protection "1; mode=block" always;
add_header X-Content-Type-Options "nosniff" always;
add_header Referrer-Policy "no-referrer-when-downgrade" always;
add_header Content-Security-Policy "default-src 'self' http: https: data: blob: 'unsafe-inline'" always;
```

Source: `deploy/helm/spending-monitor/templates/nginx-configmap.yaml`, lines 84-88

### Toggle Between Nginx and Native OpenShift Routes

The Helm chart supports two routing modes controlled by `nginx.enabled`. When nginx is disabled, the `routes.yaml` template creates separate UI, API, and health Routes sharing a single hostname (`routes.sharedHost`).

```yaml
# values.yaml
nginx:
  enabled: false   # default -- use native Routes on OpenShift
routes:
  enabled: true
  sharedHost: ""   # REQUIRED when nginx.enabled=false
```

Source: `deploy/helm/spending-monitor/values.yaml`, lines 170-226

The `routes.yaml` template branches on `nginx.enabled`:

```yaml
{{- if .Values.nginx.enabled -}}
# Single Route pointing to the nginx Service
{{- else -}}
# Three separate Routes: UI (/), API (/api), Health (/health)
{{- end -}}
```

Source: `deploy/helm/spending-monitor/templates/routes.yaml`, lines 1-140

## Configuration

- **Environment variables:** None for nginx itself; upstream services are resolved by Kubernetes DNS names configured in `values.yaml` (`api.name`, `ui.name`)
- **Config files:**
  - `nginx.conf` (repo root) -- local podman-compose development config, bind-mounted read-only
  - `nginx-configmap.yaml` (Helm template) -- OpenShift-adapted config generated from Helm values
- **Helm values:**
  - `nginx.enabled` -- toggle the entire nginx Deployment, Service, and Route (default `false`)
  - `nginx.image.repository` / `nginx.image.tag` -- container image (`nginx`, `1.25-alpine`)
  - `nginx.service.port` -- ClusterIP service port (`8080`)
  - `nginx.replicas` -- replica count (`1`)
  - `nginx.resources` -- resource requests/limits (`64Mi`/`128Mi` memory, `50m`/`200m` CPU)
  - `nginx.healthCheck.enabled` / `.path` / `.initialDelaySeconds` / `.periodSeconds` -- liveness and readiness probes (`/health`)
  - `routes.sharedHost` -- required shared hostname when using native Routes instead of nginx

## Known Gotchas

- **Do not use `rewrite` to strip the `/api/` prefix.** An earlier version included `rewrite ^/api/(.*)$ /$1 break;` in the Helm ConfigMap, which was removed in commit `74af2b1` because the FastAPI backend expects the `/api/` prefix in the path. Stripping it caused 404s.
- **WebSocket location must precede generic `/api/`.** Nginx matches locations by specificity; the `/api/ws/` block must appear before `/api/` or WebSocket upgrade requests will be handled by the regular proxy block (missing `Upgrade`/`Connection` headers). This ordering was fixed in commit `48ecb29`.
- **Temp paths are mandatory for OpenShift restricted SCC.** The default nginx image writes to `/var/cache/nginx/` which is not writable under the restricted security context. Redirecting `pid`, `proxy_temp_path`, `client_body_temp_path`, `fastcgi_temp_path`, `uwsgi_temp_path`, and `scgi_temp_path` to `/tmp` is required.
- **Nginx is disabled by default on OpenShift.** The `values.yaml` comment (line 171-173) explicitly recommends using native OpenShift Routes instead of the nginx proxy for production OpenShift deployments, as committed in `4ca38fb`.

## Testing Notes

- For local development, run `podman-compose up` and verify the unified endpoint at `http://localhost:3000` serves both the UI (root path) and API (`/api/`).
- On OpenShift with nginx enabled, check the `/health` endpoint returns `200 "healthy\n"` via the nginx Route.
- On OpenShift with nginx disabled (default), verify that three separate Routes exist (UI, API, health) and share the same hostname for path-based routing.

## Related Patterns

- `fastapi-backend` -- the upstream API service proxied by nginx
- `react-frontend` / `react-ui-app` -- the upstream UI service proxied by nginx
- `keycloak` -- authentication service; the nginx proxy forwards the `Authorization` header explicitly via `proxy_set_header Authorization $http_authorization`
