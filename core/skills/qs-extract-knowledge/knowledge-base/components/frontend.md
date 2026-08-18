---
name: frontend
description: Pre-built vendor frontend container deployed via Helm subchart with OpenShift Route and env-var-based backend wiring
summary: "Deploys a pre-built vendor frontend container (quay.io/noeloc/redhat-bp-ui:latest, forked from nvcr.io/nvidia/blueprint/rag-frontend:2.4.0) as a standalone Helm subchart (apiVersion v2) on OpenShift, configured at deploy time via VITE_* env vars for in-cluster service discovery of rag-server:8081, ingestor-server:8082, and Milvus:19530. Use when the frontend is a vendor-provided or forked container image needing only deploy-time env var wiring and OpenShift Route exposure rather than source builds -- all templates are guarded by an enabled flag for conditional deployment, with route.host auto-generated when left empty. Critical pattern: the deployment template must use Helm's tpl function to resolve Go template expressions ({{ .Release.Namespace }}) embedded in the values.yaml envVars map for namespace-scoped service DNS, and fullnameOverride: \"rag-frontend\" creates a fixed service name relied upon by cross-chart references and kubectl route lookups. Common gotchas: imagePullSecret ngc-api is a cross-chart dependency created by the ingest chart (must exist before frontend install), pullPolicy: Always is required for :latest tags, omitting tpl causes {{ .Release.Namespace }} to inject as literal strings, and the NVIDIA image was replaced with a custom Red Hat fork after multiple reverts (commits 23e0760, 6114f5d, 8ddae57)."
metadata:
  type: component
tags:
  tech_stack: [vite, react, helm]
  ai_pattern: [rag]
  platform: [openshift, kubernetes]
source_examples:
  - quickstart: "aml-rag-nvidia"
    repo: "https://github.com/rh-ai-quickstart/aml-rag-nvidia"
    notes: "Pre-built NVIDIA RAG Blueprint frontend deployed via standalone Helm subchart with OpenShift Route and VITE_* env vars for backend service discovery"
    approach: "A"
---

# Frontend

## Overview

A pre-built vendor frontend container image deployed as a standalone Helm subchart on OpenShift. Rather than building the frontend from source, this pattern uses a container image provided by a vendor (NVIDIA RAG Blueprint) or a custom fork, configured at deploy time via environment variables that point to in-cluster backend services. An OpenShift Route provides TLS-terminated external access.

## Tech Stack & Dependencies

- **Runtime:** Pre-built container image (Vite/React app based on VITE_* env var convention), port 3000
- **Container image:** `quay.io/noeloc/redhat-bp-ui:latest` (forked from `nvcr.io/nvidia/blueprint/rag-frontend:2.4.0`)
- **Key dependencies:** Requires in-cluster `rag-server` (port 8081) and `ingestor-server` (port 8082) services, plus Milvus vector database (port 19530)
- **Helm subchart:** Standalone chart at `charts/frontend/` (Chart.yaml `apiVersion: v2`, `type: application`, `version: 0.1.0`)

## Key Patterns

### Helm-Templated Environment Variables with tpl Function

The deployment template iterates over `.Values.envVars` and uses Helm's `tpl` function to resolve Go template expressions embedded in values.yaml strings. This allows env var values to reference the release namespace for in-cluster service DNS names:

```yaml
# values.yaml
envVars:
  VITE_API_CHAT_URL: "http://rag-server.{{ .Release.Namespace }}.svc:8081/v1"
  VITE_API_VDB_URL: "http://ingestor-server.{{ .Release.Namespace }}.svc:8082/v1"
  VITE_MILVUS_URL: "http://milvus.{{ .Release.Namespace }}.svc:19530"
```

```yaml
# templates/deployment.yaml
env:
{{- range $key, $value := .Values.envVars }}
- name: {{ $key }}
  value: {{ tpl $value $ | quote }}
{{- end }}
```

The `tpl` call is critical -- without it, `{{ .Release.Namespace }}` would render as a literal string rather than expanding to the actual namespace.

### OpenShift Route with Edge TLS Termination

The chart creates an OpenShift Route with edge TLS termination and HTTP-to-HTTPS redirect, with optional host override (auto-generated if empty):

```yaml
# values.yaml
route:
  enabled: true
  host: ""  # If empty, OpenShift will auto-generate
  tls:
    enabled: true
    termination: edge
    insecureEdgeTerminationPolicy: Redirect
```

```yaml
# templates/route.yaml
apiVersion: route.openshift.io/v1
kind: Route
spec:
  {{- if .Values.route.host }}
  host: {{ .Values.route.host }}
  {{- end }}
  to:
    kind: Service
    name: {{ include "frontend.fullname" . }}
    weight: 100
  port:
    targetPort: http
  tls:
    termination: {{ .Values.route.tls.termination }}
    insecureEdgeTerminationPolicy: {{ .Values.route.tls.insecureEdgeTerminationPolicy }}
```

### Conditional Deployment with enabled Flag

All templates (Deployment, Service, Route) are guarded by `{{- if .Values.enabled }}`, allowing the frontend to be disabled without removing the chart from the install:

```yaml
# values.yaml
enabled: true
```

### Image Pull Secret for Vendor Registries

The deployment references an image pull secret for private registries. In this quickstart, it references the NGC API secret created by the ingest chart:

```yaml
# values.yaml
imagePullSecret:
  name: ngc-api  # References the NGC secret from ingest chart
```

```yaml
# templates/deployment.yaml
{{- if .Values.imagePullSecret.name }}
imagePullSecrets:
  - name: {{ .Values.imagePullSecret.name }}
{{- end }}
```

### Health Probes on Root Path

Liveness and readiness probes target the root path on port 3000 with staggered timing to avoid premature restarts:

```yaml
livenessProbe:
  httpGet:
    path: /
    port: 3000
  initialDelaySeconds: 10
  periodSeconds: 30
readinessProbe:
  httpGet:
    path: /
    port: 3000
  initialDelaySeconds: 5
  periodSeconds: 10
```

## Configuration

- **Environment variables:**
  - `VITE_API_CHAT_URL` - RAG server chat API endpoint (namespace-scoped in-cluster URL)
  - `VITE_API_VDB_URL` - Ingestor server vector DB API endpoint (namespace-scoped in-cluster URL)
  - `VITE_MILVUS_URL` - Milvus vector database endpoint (namespace-scoped in-cluster URL)
- **Config files:** None (all configuration via Helm values and env vars)
- **Helm values:**
  - `fullnameOverride: "rag-frontend"` - Hardcoded service name for cross-chart references
  - `image.repository` / `image.tag` - Container image coordinates
  - `image.pullPolicy: Always` - Forces pull on every deploy (appropriate for `latest` tags)
  - `service.port: 3000` - ClusterIP service port matching container port
  - `route.enabled` / `route.tls` - OpenShift Route configuration
  - `envVars` - Map of environment variables, supports Helm template expressions

## Known Gotchas

- **Image tag changed from NVIDIA to custom fork:** The original NVIDIA image (`nvcr.io/nvidia/blueprint/rag-frontend:2.4.0`) was replaced with a custom Red Hat fork (`quay.io/noeloc/redhat-bp-ui`). The commit history shows this was reverted once and then changed again, suggesting the NVIDIA image had issues or needed customization (commits `23e0760`, `6114f5d`, `8ddae57`).
- **VITE_* env vars require tpl in deployment template:** The `envVars` map in values.yaml contains Go template expressions (`{{ .Release.Namespace }}`). The deployment template must use `tpl $value $` when rendering these, or they will be injected as literal template strings into the container environment.
- **Image pull secret is cross-chart dependency:** The `imagePullSecret.name: ngc-api` references a secret created by the ingest chart, not by the frontend chart itself. The frontend chart must be installed after the ingest chart (or the secret must exist beforehand).
- **fullnameOverride creates fixed service name:** `fullnameOverride: "rag-frontend"` means the service name is always `rag-frontend` regardless of the Helm release name, which is relied upon by the README command `kubectl get route -n rag rag-frontend`.

## Testing Notes

- Get the frontend URL after deployment: `echo "https://$(kubectl get route -n rag rag-frontend -o jsonpath='{.spec.host}')"`
- Verify the UI loads in a browser and the chat interface is functional
- Upload documents via the "New Collection" button to test the ingestor-server integration
- Verify backend connectivity by submitting a chat query (tests VITE_API_CHAT_URL wiring to rag-server)

## Related Patterns

- Component: ingestion-pipeline (ingestor-server that the frontend connects to for document upload)
- Deployment: Helm subchart wiring for multi-component quickstarts
- Architecture: RAG pipeline with NVIDIA NIM model serving
