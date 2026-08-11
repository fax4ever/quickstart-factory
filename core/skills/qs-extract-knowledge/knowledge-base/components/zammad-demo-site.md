---
name: zammad-demo-site
description: Static nginx-served demo login portal for Zammad with persona quick-pick sign-in and chat widget snippet
summary: "Provides a static nginx-unprivileged:alpine demo login portal for Zammad on OpenShift, rendering data-driven persona quick-pick tiles and a chat widget snippet page (configurable chatId) entirely from Helm values (demoSite.categories) with no code changes needed to manage demo accounts. Use when a Zammad instance needs a branded demo portal with one-click persona sign-in; requires same-origin hosting via path-based OpenShift Route sharing (configurable pathPrefix, default /demo-portal) with hostname resolved from explicit zammadRouteHost, publicUrl override, or lookup of the ssa-zammad Route at deploy time. All HTML pages and nginx default.conf are rendered into a ConfigMap with checksum/config annotation for rolling restarts; sign-in calls /api/v1/signshow for CSRF token then /api/v1/signin; BroadcastChannel coordinates portal and Zammad shell tabs (login_changed, ping/pong); hardened security enforces runAsNonRoot, readOnlyRootFilesystem, drop ALL capabilities, RuntimeDefault seccomp with emptyDir for /tmp and /var/cache/nginx. One-click sign-in only works on same origin (falls back to credentials modal); helm template without live cluster fails the ssa-zammad Route lookup causing a hard fail in external-route.yaml — set zammadRouteHost explicitly; nginx disables port_in_redirect/absolute_redirect/server_name_in_redirect for edge TLS termination; component is disabled by default (enabled: false) and NetworkPolicy restricts ingress to namespaces labeled network.openshift.io/policy-group: ingress."
metadata:
  type: component
tags:
  tech_stack: [nginx, helm, html, javascript]
  platform: [openshift]
source_examples:
  - quickstart: "it-self-service-agent"
    repo: "https://github.com/rh-ai-quickstart/it-self-service-agent"
    notes: "Nginx-served static demo portal with data-driven persona tiles, same-origin Zammad sign-in, and chat widget snippet"
    approach: "A"
---

# Zammad Demo Site

## Overview

A static HTML demo portal served by nginx-unprivileged that provides a branded login page for a Zammad ticketing instance. The component renders persona quick-pick tiles and a credentials table from Helm values, enabling one-click sign-in to Zammad via its REST API when served on the same hostname. It also hosts a chat widget snippet page for embedding the Zammad chat widget into external sites.

## Tech Stack & Dependencies

- **Runtime:** `nginxinc/nginx-unprivileged:alpine` container serving static HTML on port 8080
- **Container image:** `nginxinc/nginx-unprivileged:alpine` (set via `image` in values.yaml)
- **Key dependencies:** A running Zammad instance reachable via OpenShift Route; same-origin hosting required for one-click sign-in
- **Helm subchart:** Standalone chart (`apiVersion: v2`, `version: 0.1.0`) within the quickstart's `helm/` directory

## Key Patterns

### Data-Driven Persona Tiles from Helm Values

All demo accounts and persona UI tiles are defined entirely in `values.yaml` under `demoSite.categories`. The Helm template iterates over this structure to render both the persona grid on the main page and the full credentials table in the modal. No application code changes are needed to add, remove, or reconfigure demo users.

```yaml
# values.yaml (truncated)
demoSite:
  productName: "IT Self-Service"
  heroTitle: "Sign in to Zammad"
  categories:
    - id: cat-admin
      navLabel: Admin
      sectionTitle: Admin
      rows:
        - role: Administrator
          email: admin@zammad.local
          password: "ZammadR0cks!"
          persona:
            icon: "shield-icon"
            bg: "#dbeafe"
            shortName: Admin
            roleShort: Full admin
```

### Same-Origin Zammad Sign-In via REST API

When the demo site is served on the same hostname as Zammad (via path-based routing on the OpenShift Route), the JavaScript performs a two-step sign-in flow: first calling `/api/v1/signshow` to obtain a CSRF token, then posting credentials to `/api/v1/signin`. This avoids CORS issues entirely.

```javascript
// _demo-site.tpl — signInToZammad function (simplified)
return fetch(signshow.toString(), {
  method: 'POST',
  credentials: 'include',
  headers: json,
  body: JSON.stringify({ fingerprint: fp })
}).then(function(res) {
  var csrf = res.headers.get('csrf-token');
  return fetch(signin.toString(), {
    method: 'POST',
    credentials: 'include',
    headers: Object.assign({ 'X-CSRF-Token': csrf }, json),
    body: JSON.stringify({ username: username, password: password, fingerprint: fp })
  });
});
```

### Path-Based Route Sharing with Zammad

The demo site shares the same OpenShift Route hostname as Zammad by mounting at a configurable path prefix (default `/demo-portal`). The `_helpers.tpl` template resolves the Zammad hostname either from an explicit `zammadRouteHost` value or by looking up an existing Route named `ssa-zammad` at deploy time.

```yaml
# templates/_helpers.tpl
{{- define "zammad-demo-site.zammadHost" -}}
{{- $h := .Values.zammadRouteHost | default "" | trim -}}
{{- if $h -}}
{{- $h -}}
{{- else -}}
{{- $zr := lookup "route.openshift.io/v1" "Route" .Release.Namespace "ssa-zammad" -}}
{{- if $zr }}{{ $zr.spec.host }}{{ end -}}
{{- end -}}
{{- end -}}
```

### BroadcastChannel Window Coordination

The demo site uses the browser `BroadcastChannel` API to coordinate between the portal tab and the Zammad shell tab. When a user signs in, a `login_changed` message tells the shell iframe to reload, and `ping`/`pong` messages detect whether a Zammad window is already open to avoid session conflicts.

```javascript
// _demo-site.tpl — hub coordination
var hub = typeof BroadcastChannel !== 'undefined'
  ? new BroadcastChannel('zammad-demo-hub') : null;
// In zammad-shell.html:
hub.onmessage = function(ev) {
  if (data.action === 'login_changed') reloadZammad();
  if (data.action === 'focus') window.focus();
  if (data.action === 'ping') hub.postMessage({ action: 'pong' });
};
```

### Hardened Security Context

The deployment enforces a locked-down security posture: `runAsNonRoot`, `readOnlyRootFilesystem`, `drop ALL` capabilities, and `RuntimeDefault` seccomp profile. Writable paths (`/tmp`, `/var/cache/nginx`) use `emptyDir` volumes.

```yaml
# templates/deployment.yaml (security sections)
securityContext:
  runAsNonRoot: true
  seccompProfile:
    type: RuntimeDefault
containers:
- name: nginx
  securityContext:
    allowPrivilegeEscalation: false
    capabilities:
      drop:
      - ALL
    readOnlyRootFilesystem: true
```

### ConfigMap-Rendered HTML with Checksum Annotation

All HTML pages (index.html, chat-snippet.html, zammad-shell.html) and the nginx `default.conf` are rendered via Helm named templates and stored in a ConfigMap. The Deployment uses a `checksum/config` annotation to trigger a rolling restart whenever any HTML content or nginx config changes.

```yaml
# templates/deployment.yaml
annotations:
  checksum/config: {{ include (print $.Template.BasePath "/configmap.yaml") . | sha256sum }}
```

## Configuration

- **Environment variables:** None; all configuration is provided through Helm values and the ConfigMap
- **Config files:**
  - `default.conf` (nginx server block) -- rendered into ConfigMap, controls path-prefix routing
  - `index.html` -- demo portal main page, rendered from `_demo-site.tpl`
  - `chat-snippet.html` -- chat widget embed instructions, rendered from `_chat-snippet.tpl`
  - `zammad-shell.html` -- full-page iframe wrapper for Zammad, rendered from `_demo-site.tpl`
- **Helm values:**
  - `enabled` (bool, default `false`) -- master toggle for all resources
  - `externalRoute` (bool, default `true`) -- whether to create an OpenShift Route
  - `publicUrl` (string) -- override the Zammad base URL; if empty, derived from Route lookup
  - `pathPrefix` (string, default `/demo-portal`) -- URL path where the demo site is mounted
  - `zammadRouteHost` (string) -- explicit Zammad hostname; if empty, looked up from existing `ssa-zammad` Route
  - `chatId` (int, default `1`) -- Zammad chat channel ID for the widget snippet
  - `demoSite.productName`, `demoSite.heroTitle`, `demoSite.heroSubtitle` -- branding strings
  - `demoSite.categories[]` -- data-driven list of account categories, rows, and persona tile metadata
  - `image` (string, default `nginxinc/nginx-unprivileged:alpine`) -- container image

## Known Gotchas

- One-click persona sign-in only works when the demo site is served on the same origin as Zammad. The code checks `sameOriginAsZammad()` and falls back to showing the credentials modal with manual copy buttons if origins differ. This is enforced in `_demo-site.tpl` around line 888.
- The `_helpers.tpl` template uses `lookup` to find the existing `ssa-zammad` Route at deploy time. This only works during `helm install/upgrade` with live cluster access; `helm template` will return an empty result, causing a hard `fail` in `external-route.yaml` if `zammadRouteHost` is not also set.
- The nginx `default.conf` disables `port_in_redirect`, `absolute_redirect`, and `server_name_in_redirect` to avoid incorrect redirects behind OpenShift's edge TLS termination (the pod sees HTTP on 8080 but clients use HTTPS).
- The component is disabled by default (`enabled: false` in values.yaml); all templates are wrapped in `{{- if .Values.enabled }}` guards.
- The NetworkPolicy only allows ingress from namespaces labeled `network.openshift.io/policy-group: ingress`, which is the standard OpenShift router namespace label.

## Testing Notes

- After deploying with `enabled: true`, verify the Route is created: `oc get route ssa-zammad-demo-site`
- Browse to `https://<zammad-host>/demo-portal/` and confirm the persona tiles render with correct categories
- Test one-click sign-in by clicking a persona tile; verify the Zammad shell iframe opens and reloads with the signed-in session
- Open `https://<zammad-host>/demo-portal/chat-snippet.html` and verify the chat widget live preview loads (requires a Zammad agent to be online for chat)
- Confirm the ConfigMap contains all four keys: `index.html`, `chat-snippet.html`, `zammad-shell.html`, `default.conf`

## Related Patterns

- Deployment security patterns: hardened pod security context with read-only root filesystem
- OpenShift Route path-based routing: sharing a hostname between multiple services
- Helm `lookup` function for dynamic route discovery at deploy time
