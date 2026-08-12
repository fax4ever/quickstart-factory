---
name: peoplemesh-app
description: Quarkus backend with embedded React SPA for semantic talent discovery using LangChain4j and pgvector
summary: "Provides AI-powered semantic talent discovery as a Quarkus monolith with embedded React SPA, using LangChain4j for LLM orchestration, pgvector for vector similarity search, Docling for CV/resume parsing, and Keycloak OIDC authentication with issuer URL auto-detected from the OpenShift console route. Use when building a Java-based talent/HR search application with multi-LLM support -- three backends (Ollama, vLLM, external OpenAI-compatible) are switched via a single `llm.mode` Helm value with conditional ConfigMap/Secret wiring; Helm `lookup` retrieves the vLLM KServe SA token at render time and preserves secrets (`sessionSecret`, `oauthStateSecret`, `maintenanceApiKey`) on upgrade. Critical pattern: a post-install secrets-sync-job Helm hook patches Keycloak OIDC secrets into peoplemesh-secrets and restarts the deployment to solve the chicken-and-egg ordering problem; Flyway seed data classpath (`db/granite` vs `db/openai`) must match the LLM mode to produce compatible embeddings. Common gotchas: vLLM token falls back to \"vllm-token-pending\" on first install requiring restart after InferenceService is ready, OpenShift Route needs `haproxy.router.openshift.io/timeout: 300s` for CPU-based Docling CV imports (3-4 min), Ollama LangChain4j timeout needs 240s for first model load, HTTP idle/read timeouts are 5m for long CV operations, all three security secrets are `required` on fresh install only, and stale browser cookies cause login errors after reinstall."
metadata:
  type: component
tags:
  tech_stack: [quarkus, langchain4j, react, postgresql, java]
  ai_pattern: [semantic-search, embeddings, rag, vector-search]
  platform: [openshift, kubernetes]
  data_layer: [pgvector]
source_examples:
  - quickstart: "peoplemesh"
    repo: "https://github.com/rh-ai-quickstart/peoplemesh"
    notes: "Quarkus monolith with embedded React SPA, multi-LLM backend (Ollama/vLLM/external), OIDC auth via Keycloak, Docling CV import"
    approach: "A"
---

# Peoplemesh Application

## Overview

Peoplemesh is a Quarkus-based monolith (backend + embedded React SPA) that provides AI-powered talent discovery through semantic search. It uses LangChain4j for LLM integration, pgvector for vector similarity search, and supports multiple LLM backends (Ollama, vLLM, external OpenAI-compatible). The component connects to Keycloak for OIDC authentication and Docling for intelligent document parsing of resumes/CVs.

## Tech Stack & Dependencies

- **Runtime:** Quarkus (Java) with embedded React SPA frontend
- **Container image:** `quay.io/rh-ai-quickstart/peoplemesh:latest`
- **Key dependencies:** LangChain4j (LLM framework), pgvector (vector search), Flyway (DB migrations), Docling (document parsing), Keycloak (OIDC auth)
- **Helm subchart:** `charts/peoplemesh` (standalone subchart within umbrella)

## Key Patterns

### Multi-LLM Backend Switching

The application supports three LLM modes configured via a single Helm value (`llm.mode`). The ConfigMap and Secret templates use conditional blocks to wire the correct environment variables per mode.

```yaml
# From charts/peoplemesh/templates/config-map.yaml
{{- if eq .Values.llm.mode "ollama" }}
OPENAI_BASE_URL: "http://{{ .Values.llm.ollama.serviceName }}.{{ .Release.Namespace }}.svc.cluster.local:{{ .Values.llm.ollama.port }}/v1"
LLM_MODEL: {{ .Values.llm.ollama.chatModel | quote }}
EMBEDDING_MODEL: {{ .Values.llm.ollama.embeddingModel | quote }}
EMBEDDING_DIMENSION: {{ .Values.llm.ollama.embeddingDimension | quote }}
QUARKUS_LANGCHAIN4J_OPENAI_TIMEOUT: "240s"
{{- else if eq .Values.llm.mode "vllm" }}
OPENAI_BASE_URL: "http://{{ .Values.llm.vllm.serviceName }}.{{ .Release.Namespace }}.svc.cluster.local/v1"
{{- else if eq .Values.llm.mode "external" }}
# External LLM mode - configuration in secrets
{{- end }}
```

### vLLM Token Retrieval via Helm Lookup

When using vLLM mode, the secrets template uses Helm's `lookup` function to retrieve the KServe service account token at render time. A fallback value is provided for first-install scenarios where the vLLM secret does not yet exist.

```yaml
# From charts/peoplemesh/templates/secrets.yaml
{{- $vllmTokenSecret := lookup "v1" "Secret" .Release.Namespace (printf "default-name-%s-sa" .Values.llm.vllm.modelName) }}
{{- if $vllmTokenSecret }}
OPENAI_API_KEY: {{ index $vllmTokenSecret.data "token" | b64dec | quote }}
{{- else }}
OPENAI_API_KEY: "vllm-token-pending"
{{- end }}
```

### Post-Install Secrets Sync Job

A Helm hook Job runs after install/upgrade to synchronize Keycloak OIDC secrets into the peoplemesh-secrets Secret. This solves a chicken-and-egg problem where the Keycloak chart creates `keycloak-client-secret` after the peoplemesh chart renders its own secrets.

```yaml
# From charts/peoplemesh/templates/secrets-sync-job.yaml
annotations:
  "helm.sh/hook": post-install,post-upgrade
  "helm.sh/hook-weight": "5"
  "helm.sh/hook-delete-policy": before-hook-creation,hook-succeeded
```

The Job uses `oc` CLI to wait up to 120 seconds for `keycloak-client-secret`, then patches the peoplemesh secrets and restarts the deployment.

### Keycloak Issuer URL Auto-Detection

The `_helpers.tpl` auto-detects the Keycloak issuer URL from the OpenShift console route when not explicitly provided, extracting the cluster domain and constructing the URL.

```go
# From charts/peoplemesh/templates/_helpers.tpl
{{- $console := lookup "route.openshift.io/v1" "Route" "openshift-console" "console" }}
{{- if $console }}
  {{- $host := $console.spec.host }}
  {{- $clusterDomain := regexReplaceAll "^console-openshift-console\\." $host "" }}
  {{- printf "https://keycloak-%s.%s/realms/peoplemesh" .Release.Namespace $clusterDomain }}
{{- end }}
```

### Secret Preservation on Upgrade

The helpers use Helm `lookup` to check for existing secrets before requiring user-provided values. On first install, secrets are required; on upgrade, existing values are preserved from the cluster.

```go
# From charts/peoplemesh/templates/_helpers.tpl
{{- define "peoplemesh.sessionSecret" -}}
{{- $secret := lookup "v1" "Secret" .Release.Namespace "peoplemesh-secrets" -}}
{{- if $secret -}}
  {{- index $secret.data "SESSION_SECRET" | b64dec -}}
{{- else -}}
  {{- required "peoplemesh.security.sessionSecret is required." .Values.security.sessionSecret -}}
{{- end -}}
{{- end }}
```

### GPU Tolerations

The deployment spec includes tolerations for common GPU node taints, allowing the pod to schedule on GPU nodes when needed (e.g., for direct embedding computation).

```yaml
# From charts/peoplemesh/templates/deployment.yaml
tolerations:
  - key: "nvidia.com/gpu"
    operator: "Exists"
    effect: "NoSchedule"
  - key: "g5-gpu"
    operator: "Exists"
    effect: "NoSchedule"
```

### Flyway Migration with Seed Data Modes

The ConfigMap controls Flyway migration locations to optionally include seed data, supporting different deployment profiles (demo vs production).

```yaml
# From charts/peoplemesh/templates/config-map.yaml
# Options: "classpath:db/migration,classpath:db/granite" or "classpath:db/migration,classpath:db/openai"
# For production: omit this or set to "classpath:db/migration" only
QUARKUS_FLYWAY_LOCATIONS: "classpath:db/migration,classpath:db/granite"
```

## Configuration

- **Environment variables:**
  - `DB_URL`, `DB_USER`, `DB_PASSWORD` -- JDBC connection to pgvector database
  - `OPENAI_BASE_URL`, `OPENAI_API_KEY`, `LLM_MODEL`, `EMBEDDING_MODEL`, `EMBEDDING_DIMENSION` -- LLM configuration (varies by mode)
  - `OIDC_KEYCLOAK_CLIENT_ID`, `OIDC_KEYCLOAK_CLIENT_SECRET`, `OIDC_KEYCLOAK_ISSUER_URL` -- Keycloak OIDC
  - `SESSION_SECRET`, `OAUTH_STATE_SECRET`, `MAINTENANCE_API_KEY` -- Security secrets
  - `QUARKUS_DOCLING_BASE_URL` -- Docling service endpoint
  - `CV_IMPORT_PROVIDER` -- CV parser backend (docling or openai)
  - `CLUSTERING_ENABLED`, `PEOPLEMESH_FRONTEND_ENABLED` -- Feature flags
  - `QUARKUS_LANGCHAIN4J_OPENAI_TIMEOUT` -- LLM timeout (240s for Ollama CPU mode)
  - `QUARKUS_HTTP_IDLE_TIMEOUT`, `QUARKUS_HTTP_READ_TIMEOUT` -- HTTP timeouts (5m for long CV imports)
  - `DB_POOL_MIN_SIZE` (4), `DB_POOL_MAX_SIZE` (24), `DB_POOL_ACQUIRE_TIMEOUT` (30s) -- Connection pool tuning
  - `HIBERNATE_BATCH_SIZE` (32), `HIBERNATE_FETCH_SIZE` (100) -- Hibernate performance tuning

- **Config files:** All configuration injected via ConfigMap (`peoplemesh-config`) and Secret (`peoplemesh-secrets`) using `envFrom`

- **Helm values:** See `charts/peoplemesh/values.yaml` -- key overrides include `llm.mode`, `database.*`, `security.oidc.*`, `features.*`, `organization.*`

## Known Gotchas

- **Keycloak secret chicken-and-egg:** The peoplemesh secrets template needs Keycloak client secret and issuer URL, but those are created by the Keycloak chart after the peoplemesh chart renders. The `secrets-sync-job` (Helm post-install hook) patches the secret and restarts the deployment to resolve this. On first install, the fallback value `"none"` is used for `OIDC_KEYCLOAK_CLIENT_SECRET`.

- **vLLM token pending on first install:** When `llm.mode=vllm`, the vLLM service account token secret may not exist during first Helm render. The template falls back to `"vllm-token-pending"`, requiring the secrets-sync or a manual restart after the vLLM InferenceService is ready.

- **OpenShift Route timeout for CV import:** CPU-based resume processing via Docling + Ollama can take 3-4 minutes. The Route annotation `haproxy.router.openshift.io/timeout: 300s` is set explicitly (from `charts/peoplemesh/templates/route.yaml`) to prevent HAProxy from terminating long requests.

- **Ollama CPU timeout:** The LangChain4j OpenAI timeout is extended to 240 seconds for Ollama mode because first model load can take 30-60s and concurrent requests under CPU can be slow (comment in `config-map.yaml`).

- **HTTP timeouts for long operations:** `QUARKUS_HTTP_IDLE_TIMEOUT` and `QUARKUS_HTTP_READ_TIMEOUT` are both set to 5 minutes to handle long-running CV import operations.

- **Stale browser cookies after reinstall:** After uninstalling and reinstalling, users may encounter login errors due to stale browser cookies from the previous Keycloak session. Users must clear cookies for the Peoplemesh domain (documented in README).

- **Flyway seed data classpath:** The `QUARKUS_FLYWAY_LOCATIONS` value must match the LLM mode -- `classpath:db/granite` for Ollama/Granite models, `classpath:db/openai` for external OpenAI. Using the wrong seed data produces incompatible embeddings.

- **Secrets required on first install only:** The `_helpers.tpl` uses Helm `lookup` to preserve secrets on upgrade, but on fresh install all three secrets (`sessionSecret`, `oauthStateSecret`, `maintenanceApiKey`) are `required` and installation will fail without them.

## Testing Notes

- **Health probes:** Liveness at `/q/health/live` (initialDelay 60s, failureThreshold 6), readiness at `/q/health/ready` (initialDelay 30s, failureThreshold 3) -- standard Quarkus SmallRye Health endpoints
- **Verify deployment:** `curl -k "https://$(oc get route peoplemesh -o jsonpath='{.spec.host}')/q/health/ready"` should return `{"status":"UP"}`
- **Test login:** Navigate to the route URL, sign in via Keycloak with `testuser@example.com` and the configured test password
- **CV upload test:** Upload a PDF resume and verify Docling processing completes (10-20s GPU, 2-3 min CPU)
- **Semantic search test:** Search for "mobile developer in Italy" -- should return results matching related concepts like "iOS engineer"

## Related Patterns

- `pgvector.md` -- Vector database component used for semantic search storage
- `ollama.md` -- Local LLM runtime used as default inference backend
- `keycloak.md` -- OIDC authentication provider
