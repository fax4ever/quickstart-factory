---
name: helm-secret-mounted-runtime-config-react-spa
description: Helm Secret containing window.__RUNTIME_CONFIG__ JS mounted as a file into a React SPA nginx container for runtime config injection
summary: "Injects deploy-time runtime configuration (API endpoints, LLM credentials, model names) into a statically-built React/Vite SPA served by nginx on OpenShift without image rebuilds, sourced from portfolio-manager-agent. Use when the SPA needs Helm-controlled secrets like API tokens at deploy time — prefer over nginx envsubst (see container-build-node-nginx-envsubst-ws-proxy-runtime-config.md) when credentials must stay in a Secret rather than a ConfigMap, and over Vite build-time VITE_* env vars when the same image must serve different environments. Helm Secret template (secret-ui-runtime-config.yaml) generates runtime-config.js assigning values.yaml entries (ui.orchestratorUrl, ui.llm.endpoint/apiToken/model) to window.__RUNTIME_CONFIG__ via toJson, subPath-mounted at /usr/share/nginx/html/runtime-config.js in deployment-ui.yaml; React app loads via script tag and must check window.__RUNTIME_CONFIG__ before falling back to import.meta.env defaults. Critical: subPath mount is mandatory — without it the entire nginx html directory is replaced by Secret contents destroying all static files; use Secret over ConfigMap because config contains VITE_OPENAI_API_TOKEN credentials; toJson required for safe JavaScript value quoting."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, react, nginx]
  ai_pattern: []
  platform: [openshift]
source_examples:
  - quickstart: "portfolio-manager-agent"
    repo: "https://github.com/rh-ai-quickstart/portfolio-manager-agent"
    notes: "Secret with runtime-config.js containing window.__RUNTIME_CONFIG__ mounted into nginx html directory via subPath volume mount"
    approach: "A"
---

# Secret-Mounted Runtime Config for React SPA

## Overview

This pattern injects runtime configuration into a statically-built React SPA by mounting a Helm-managed Secret as a JavaScript file (`runtime-config.js`) into the nginx serving directory. It enables environment-specific values (API endpoints, model names, API tokens) to be configured at deploy time without rebuilding the container image.

## Pattern Description

A Helm Secret template generates a `runtime-config.js` file that assigns values from `values.yaml` into `window.__RUNTIME_CONFIG__`. This file is volume-mounted into the UI Deployment's nginx container at `/usr/share/nginx/html/runtime-config.js` using a `subPath` mount. The React application loads this script via a `<script>` tag and reads the configuration at runtime, overriding any build-time defaults.

## Implementation

### Secret Template

The Secret contains a JavaScript snippet that assigns Helm values to the global `window.__RUNTIME_CONFIG__` object:

```yaml
# deploy/helm/templates/secret-ui-runtime-config.yaml
apiVersion: v1
kind: Secret
metadata:
  name: ui-runtime-config
  namespace: {{ .Values.namespace }}
type: Opaque
stringData:
  runtime-config.js: |
    window.__RUNTIME_CONFIG__ = {
      VITE_ORCHESTRATOR_URL: {{ .Values.ui.orchestratorUrl | toJson }},
      VITE_OPENAI_API_ENDPOINT: {{ .Values.ui.llm.endpoint | toJson }},
      VITE_OPENAI_API_TOKEN: {{ .Values.ui.llm.apiToken | toJson }},
      VITE_OPENAI_MODEL: {{ .Values.ui.llm.model | toJson }}
    };
```

### Deployment Volume Mount

The Secret is mounted into the UI Deployment using a `subPath` to place the file directly in the nginx html directory without shadowing other files:

```yaml
# deploy/helm/templates/deployment-ui.yaml
spec:
  template:
    spec:
      volumes:
        - name: runtime-config
          secret:
            secretName: ui-runtime-config
      containers:
        - name: container
          image: {{ .Values.image.repository }}:{{ .Values.image.tags.ui }}
          ports:
            - containerPort: 8080
              protocol: TCP
          volumeMounts:
            - name: runtime-config
              mountPath: /usr/share/nginx/html/runtime-config.js
              subPath: runtime-config.js
              readOnly: true
```

### Values Configuration

```yaml
# deploy/helm/values.yaml
ui:
  orchestratorUrl: ""
  llm:
    endpoint: ""
    apiToken: ""
    model: ""
```

## Configuration

- **Key settings:** `ui.orchestratorUrl` sets the API endpoint for the orchestrator; `ui.llm.endpoint`, `ui.llm.apiToken`, `ui.llm.model` configure the LLM connection; all values are serialized via `toJson` for proper JavaScript quoting
- **Defaults:** All values default to empty strings; the Makefile's `deploy-cluster` target conditionally passes these as `--set-string` only when the corresponding env vars are set
- **Dependencies:** The React application must include a `<script src="/runtime-config.js">` tag to load the config; nginx must serve the file from the mount path

## Gotchas

- A Secret is used instead of a ConfigMap because the runtime config includes the `VITE_OPENAI_API_TOKEN` which is a sensitive credential -- using a ConfigMap would expose the token in plain text via `kubectl get configmap -o yaml` (see `deploy/helm/templates/secret-ui-runtime-config.yaml`)
- The `subPath: runtime-config.js` mount is critical -- without `subPath`, the entire `/usr/share/nginx/html/` directory would be replaced by the Secret contents, removing all other static files (see `deploy/helm/templates/deployment-ui.yaml`)
- The `toJson` Helm function is used for value serialization, which properly handles empty strings, special characters, and null values as JSON/JavaScript-safe values (see `deploy/helm/templates/secret-ui-runtime-config.yaml`)
- Build-time Vite env vars (`VITE_*`) in the Dockerfile provide defaults, while the runtime-config.js overrides them at runtime -- the React app must check `window.__RUNTIME_CONFIG__` before falling back to `import.meta.env` values (see `frontend/Dockerfile` ARGs and `deploy/helm/templates/secret-ui-runtime-config.yaml`)

## Related Patterns

- `container-build-node-nginx-envsubst-ws-proxy-runtime-config.md` -- alternative pattern using nginx envsubst for runtime config injection
- `container-build-ubi9-node-nginx-multistage-vite-api-proxy.md` -- the frontend container image this config is mounted into
