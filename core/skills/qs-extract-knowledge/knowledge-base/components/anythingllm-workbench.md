---
name: anythingllm-workbench
description: "AnythingLLM chat UI deployed as a Kubeflow Notebook workbench on RHOAI with sidecar automation and seed jobs"
summary: "Deploys AnythingLLM as a Kubeflow Notebook CR on RHOAI, providing a RAG-capable chat UI that appears natively in the Data Science Projects dashboard with OAuth-protected access, using LanceDB for embedded vector storage, native embedding engine, and vLLM CPU (KServe InferenceService) as the LLM backend via the localai provider. Use when you need a self-hosted conversational UI with automated workspace provisioning on RHOAI — a keinos/sqlite3 sidecar injects API key sk-automation-workspace-setup into AnythingLLM's SQLite DB, enabling a seed Job to create workspaces, set system prompts, and upload RAG documents via the REST API on internal ClusterIP port 3001 (separate from notebook port 8888). Critical config: LOCAL_AI_BASE_PATH must point to the in-cluster KServe predictor URL (http://<service>-predictor.<namespace>.svc.cluster.local:8080/v1), NOTEBOOK_ARGS sets ServerApp.base_url=/notebook/<namespace>/<name> for RHOAI routing, NetworkPolicy restricts ingress to redhat-ods-applications namespace on ports 3001/8888/8443, and PVC uses helm.sh/resource-policy: keep to survive helm uninstall. Gotchas: the sidecar polls up to 120s for the SQLite DB file then fails, the hardcoded API key must match in both sidecar script and Kubernetes Secret, the sidecar runs sleep infinity permanently consuming 50m CPU/64Mi, and the ODH v2 Capabilities check switches inject-oauth to inject-auth annotation reducing the pod from 3 containers to 2."
metadata:
  type: component
tags:
  tech_stack: [anythingllm, sqlite, nodejs]
  ai_pattern: [rag, model-serving]
  platform: [rhoai, openshift, kserve, vllm]
  data_layer: [lancedb, sqlite]
source_examples:
  - quickstart: "llm-cpu-serving"
    repo: "https://github.com/rh-ai-quickstart/llm-cpu-serving"
    notes: "AnythingLLM deployed as RHOAI workbench with sidecar API key automation, init job for workspace seeding, and vLLM CPU backend"
    approach: "A"
---

# AnythingLLM Workbench

## Overview

AnythingLLM is a self-hosted chat interface deployed as a Kubeflow `Notebook` custom resource (workbench) inside RHOAI. It provides a RAG-capable conversational UI connected to an in-cluster vLLM model server. The workbench pattern makes it appear as a native RHOAI workbench in the Data Science Projects dashboard, with OAuth-protected access and persistent storage.

## Tech Stack & Dependencies

- **Runtime:** AnythingLLM (Node.js-based application served via a Jupyter-compatible `ServerApp` wrapper)
- **Container image:** `quay.io/rh-aiservices-bu/anythingllm-workbench:1.9.1`
- **Key dependencies:**
  - vLLM CPU model server (KServe `InferenceService`) for LLM inference
  - SQLite database (internal to AnythingLLM for API keys and workspace config)
  - LanceDB (embedded vector database for RAG document storage)
  - `keinos/sqlite3:latest` sidecar image for API key automation
  - `quay.io/curl/curl` image for the init/seed job
- **Helm subchart:** None (standalone Helm templates within the `vllm-cpu` chart)

## Key Patterns

### Kubeflow Notebook as Workbench Container

AnythingLLM is deployed as a `kubeflow.org/v1 Notebook` resource, which makes it appear as a workbench in the RHOAI dashboard. The annotations configure how RHOAI displays and manages the workbench, including image selection and auth injection.

```yaml
apiVersion: kubeflow.org/v1
kind: Notebook
metadata:
  annotations:
    notebooks.opendatahub.io/inject-oauth: 'true'
    opendatahub.io/image-display-name: AnythingLLM
    opendatahub.io/notebook-image-name: "anythingllm-workbench"
    opendatahub.io/workbench-image-namespace: {{ .Release.Namespace }}
    notebooks.opendatahub.io/last-image-selection: 'anythingllm-workbench:{{ .Values.images.anythingllm | splitList ":" | last }}'
  labels:
    app: anythingllm
    opendatahub.io/dashboard: 'true'
    opendatahub.io/odh-managed: 'true'
```

The `NOTEBOOK_ARGS` environment variable configures the Jupyter-compatible server layer that wraps AnythingLLM, setting the base URL path to match the RHOAI notebook routing convention (`/notebook/<namespace>/<name>`).

```yaml
- name: NOTEBOOK_ARGS
  value: |-
    --ServerApp.port=8888
                      --ServerApp.token=''
                      --ServerApp.password=''
                      --ServerApp.base_url=/notebook/{{ .Release.Namespace }}/anythingllm
                      --ServerApp.quit_button=False
```

### ODH v2 Auth Annotation Switch

The template uses a Helm capabilities check to switch between the legacy `inject-oauth` and the newer `inject-auth` annotation depending on the cluster's OpenDataHub version:

```yaml
{{- if .Capabilities.APIVersions.Has "datasciencecluster.opendatahub.io/v2" }}
notebooks.opendatahub.io/inject-auth: 'true'
{{- else }}
notebooks.opendatahub.io/inject-oauth: 'true'
{{- end }}
```

When the cluster does not have the v2 API, a full OAuth proxy sidecar container is injected using the `ose-oauth-proxy` image with OpenShift SAR-based authorization:

```yaml
- '--openshift-sar={"verb":"get","resource":"notebooks","resourceAPIGroup":"kubeflow.org","resourceName":"anythingllm","namespace":"{{ .Release.Namespace }}"}'
```

### Sidecar API Key Automation via SQLite

A `keinos/sqlite3:latest` sidecar container runs alongside AnythingLLM to inject an API key directly into the SQLite database. This enables the seed job to authenticate against the AnythingLLM API without manual UI setup.

```yaml
- name: anythingllm-automation
  image: keinos/sqlite3:latest
  command: ["/bin/sh", "-c"]
  args:
    - |
      DB_PATH="/opt/app-root/src/anythingllm/storage/anythingllm.db"
      # Wait for AnythingLLM to create the database
      for i in $(seq 1 120); do
        if [ -f "$DB_PATH" ]; then
          echo "Database found after ${i} seconds!"
          break
        fi
        sleep 1
      done
      sqlite3 "$DB_PATH" << 'EOF'
      INSERT OR REPLACE INTO api_keys (secret, createdBy, createdAt, lastUpdatedAt)
      VALUES ('sk-automation-workspace-setup', 1, datetime('now'), datetime('now'));
      EOF
      sleep infinity
```

The sidecar shares the PVC mount at `/opt/app-root/src` with the main AnythingLLM container, polls for the database file for up to 120 seconds, then inserts the key and sleeps indefinitely to keep the pod running.

### LLM Provider Configuration via Secret

AnythingLLM connects to the vLLM model server using the `localai` LLM provider (OpenAI-compatible API). Configuration is injected via a Kubernetes Secret mounted as environment variables through `envFrom`:

```yaml
kind: Secret
metadata:
  name: tinyllama-vllm-cpu
data:
  DISABLE_TELEMETRY: dHJ1ZQ==        # true
  EMBEDDING_ENGINE: bmF0aXZl          # native
  LLM_PROVIDER: bG9jYWxhaQ==          # localai
  LOCAL_AI_MODEL_PREF: dGlueWxsYW1h   # tinyllama
  LOCAL_AI_MODEL_TOKEN_LIMIT: NTEy    # 512
  VECTOR_DB: bGFuY2VkYg==            # lancedb
stringData:
  LOCAL_AI_BASE_PATH: "http://{{ .Values.model.name }}-predictor.{{ .Release.Namespace }}.svc.cluster.local:8080/v1"
```

The `LOCAL_AI_BASE_PATH` uses in-cluster KServe service discovery to reach the vLLM predictor pod on port 8080.

### Init Job for Workspace Seeding

A Kubernetes Job (`anythingllm-seed`) runs after deployment to create a workspace, set the system prompt, and upload RAG documents -- all via the AnythingLLM REST API using the sidecar-injected API key.

```yaml
SVC="anythingllm-api-internal.${NAMESPACE}.svc.cluster.local:3001"
BASE="http://${SVC}/api/v1"
AUTH="Authorization: Bearer ${ANYTHINGLLM_API_KEY}"

# Create workspace (idempotent)
curl -s -X POST "${BASE}/workspace/new" -H "${AUTH}" \
  -H "Content-Type: application/json" \
  -d "{\"name\":\"${WS_NAME}\"}"

# Set system prompt
curl -s -X POST "${BASE}/workspace/${WS_SLUG}/update" -H "${AUTH}" \
  -H "Content-Type: application/json" \
  -d '{"openAiPrompt": "<system-prompt>"}'

# Upload RAG documents via URL
curl -s -X POST "${BASE}/document/upload-link" -H "${AUTH}" \
  -H "Content-Type: application/json" \
  -d "{\"link\":\"${URL}\", \"addToWorkspaces\":\"${WS_SLUG}\"}"
```

The job connects to AnythingLLM via an internal ClusterIP service on port 3001 (the native AnythingLLM API port, separate from the Jupyter-wrapped port 8888).

### Network Policy for Cross-Namespace Access

A `NetworkPolicy` restricts ingress to the AnythingLLM pod, allowing access only from the RHOAI dashboard namespace (`redhat-ods-applications`) and the deployment namespace itself. Three ports are exposed: 3001 (API), 8888 (notebook), and 8443 (OAuth proxy).

```yaml
ingress:
  - from:
      - namespaceSelector:
          matchLabels:
            kubernetes.io/metadata.name: redhat-ods-applications
    ports:
      - port: 3001
      - port: 8888
      - port: 8443
  - from:
      - namespaceSelector:
          matchLabels:
            kubernetes.io/metadata.name: {{ .Release.Namespace }}
```

### Persistent Volume with Helm Keep Policy

The workbench PVC uses `helm.sh/resource-policy: keep` to prevent data loss on `helm uninstall`. This preserves the AnythingLLM database and any uploaded documents across chart reinstalls.

```yaml
kind: PersistentVolumeClaim
metadata:
  annotations:
    helm.sh/resource-policy: keep
  name: anythingllm
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 5Gi
  storageClassName: {{ .Values.storageClassName }}
```

## Configuration

- **Environment variables:**
  - `NOTEBOOK_ARGS` -- ServerApp configuration (port, base URL, auth tokens)
  - `JUPYTER_IMAGE` -- image reference for RHOAI dashboard display
  - `SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`, `PIP_CERT`, `GIT_SSL_CAINFO`, `PIPELINES_SSL_SA_CERTS` -- all set to `/etc/pki/tls/custom-certs/ca-bundle.crt` for custom CA trust
  - `LLM_PROVIDER` -- set to `localai` for OpenAI-compatible vLLM backend
  - `LOCAL_AI_BASE_PATH` -- in-cluster vLLM predictor URL
  - `LOCAL_AI_MODEL_PREF` -- model name preference (e.g., `tinyllama`)
  - `LOCAL_AI_MODEL_TOKEN_LIMIT` -- max token limit (e.g., `512`)
  - `EMBEDDING_ENGINE` -- set to `native` (AnythingLLM built-in embeddings)
  - `VECTOR_DB` -- set to `lancedb` (embedded vector database)
  - `DISABLE_TELEMETRY` -- set to `true`
- **Config files:** AnythingLLM uses its internal SQLite database at `/opt/app-root/src/anythingllm/storage/anythingllm.db` for all configuration
- **Helm values:**
  - `images.anythingllm` -- container image reference
  - `storageClassName` -- PVC storage class (default `gp3-csi`)
  - `aiLifecoach.workspace.name` -- pre-created workspace name
  - `aiLifecoach.workspace.systemPrompt` -- system prompt set on the workspace
  - `rag.seedDocuments` -- list of `{filename, url}` pairs for document seeding

## Known Gotchas

- **Sidecar waits up to 120 seconds for the database:** The `anythingllm-automation` sidecar polls for the SQLite database file at a fixed path. If AnythingLLM takes longer than 120 seconds to initialize (e.g., on very slow storage), the sidecar will exit with an error and the seed job will fail to authenticate.
- **Hardcoded API key in both sidecar and Secret:** The API key `sk-automation-workspace-setup` is hardcoded in the sidecar shell script and also stored base64-encoded in the `anythingllm-api` Secret. Both must match for the seed job to work.
- **Sidecar runs `sleep infinity` permanently:** The `anythingllm-automation` sidecar container remains running indefinitely after injecting the API key. It consumes 50m CPU / 64Mi memory for the life of the pod.
- **NOTEBOOK_ARGS has inconsistent indentation:** The `NOTEBOOK_ARGS` value string uses excessive indentation (18 spaces for continuation lines) baked into the Helm template. This is passed verbatim to the `ServerApp` and works, but can cause confusion when debugging.
- **Port 3001 exposed only via internal Service:** AnythingLLM's native API port (3001) is exposed through a separate `anythingllm-api-internal` ClusterIP Service, not through the notebook port (8888). The seed job and any API consumers must use port 3001, while the RHOAI dashboard routes to port 8888.
- **OAuth proxy only on pre-v2 clusters:** The OAuth proxy sidecar is conditionally included based on `Capabilities.APIVersions`. On ODH v2+ clusters, the `inject-auth` annotation replaces the entire OAuth proxy sidecar, changing the pod from 3 containers to 2.

## Testing Notes

- Verify the workbench appears in the RHOAI dashboard under Data Science Projects with the display name "AnythingLLM"
- Check pod reaches 3/3 (or 2/2 on ODH v2+) Ready state: `oc get pods -l app=anythingllm`
- Confirm the seed job completed: `oc logs -l job-name=anythingllm-seed --tail=5`
- Verify the API key was injected by checking the sidecar logs: `oc logs <pod> -c anythingllm-automation`
- Open the workbench through the RHOAI dashboard and confirm the pre-created workspace is available

## Related Patterns

- See `model-serving.md` for KServe InferenceService and ServingRuntime patterns used by the vLLM CPU backend
- See `notebooks.md` for other RHOAI workbench patterns and Kubeflow Notebook configurations
