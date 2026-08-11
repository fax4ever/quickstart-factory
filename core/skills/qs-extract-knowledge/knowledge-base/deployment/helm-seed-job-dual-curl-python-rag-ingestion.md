---
name: helm-seed-job-dual-curl-python-rag-ingestion
description: Two seed Jobs -- curl-based AnythingLLM workspace setup and Python llama-stack-client vector store seeding with K8s API discovery
summary: "Seeds RAG content into two frontends from one Helm install using dual Kubernetes Jobs: curl-based anythingllm-seed creates a workspace with double-JSON-encoded system prompt (toJson|toJson) and uploads documents via upload-link to anythingllm-api-internal:3001 bypassing OAuth proxy, while Python rag-seed mounts a ConfigMap script using llama-stack-client (300s timeout) to discover the namespace admin via K8s RoleBindings API with dedicated ServiceAccount RBAC, create a vector store named SHA256(username)[:32] matching BFF convention, and ingest HTML stripped of tags/scripts/styles/nav truncated to 60k chars. Use when a quickstart needs to populate both an AnythingLLM workspace and a Llama Stack vector store from shared rag.seedDocuments values -- the rag-seed Job runs as Helm hooks (pre-install,pre-upgrade with before-hook-creation delete policy) for ordering while anythingllm-seed runs as a regular workload, both with backoffLimit: 0 and readiness wait loops. Critical config: the rag-seed Job requires a dedicated ServiceAccount with list rolebindings RBAC and its script is mounted from a ConfigMap; the anythingllm-seed connects to an internal Service on port 3001 bypassing the Notebook OAuth proxy and Jupyter routing. Common gotchas: the SHA256(username)[:32] vector store naming must match the frontend/BFF auto-provisioning convention or users get empty stores; anythingllm-seed depends on the SQLite sidecar injecting the API key secret first; rag-seed depends on the LlamaStackDistribution CR being ready; and the Python HTML text extraction works for blog-style content but may miss structured data."
metadata:
  type: deployment-pattern
tags:
  tech_stack: [helm, python, llama-stack]
  ai_pattern: [rag]
  platform: [openshift, rhoai]
source_examples:
  - quickstart: "llm-cpu-serving"
    repo: "https://github.com/rh-ai-quickstart/llm-cpu-serving"
    notes: "Dual seed jobs: curl-based AnythingLLM workspace/doc upload + Python llama-stack-client vector store seeding with namespace admin discovery"
    approach: "A"
---

# Dual Seed Jobs -- curl-based and Python RAG Ingestion

## Overview

This pattern uses two separate Kubernetes Jobs to seed RAG content into two different frontends from a single Helm install. One Job uses curl to create an AnythingLLM workspace, set a system prompt, and upload documents via the AnythingLLM REST API. The other Job uses a Python script with the `llama-stack-client` SDK to discover the namespace admin via Kubernetes RBAC, create a user-specific vector store in Llama Stack, and ingest documents by fetching and parsing web pages.

## Pattern Description

The two seed Jobs run independently and target different services. The AnythingLLM seed Job (`anythingllm-seed`) uses a minimal `quay.io/curl/curl` image to interact with the AnythingLLM API, creating a workspace and uploading document URLs via `upload-link`. The Llama Stack seed Job (`rag-seed`) uses the Llama Stack distribution image itself and runs a Python script mounted from a ConfigMap. This Python script discovers the namespace admin by querying the Kubernetes RoleBindings API, creates a vector store named by a SHA256 hash of the admin username, and ingests documents by fetching HTML from URLs and uploading them as text files. The rag-seed Job uses Helm hooks (`pre-install,pre-upgrade`) for ordering, while the anythingllm-seed runs as a regular workload.

## Implementation

### AnythingLLM Seed Job (curl-based)

```yaml
# helm/templates/init_job.yaml (excerpt)
apiVersion: batch/v1
kind: Job
metadata:
  name: anythingllm-seed
spec:
  backoffLimit: 0
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: seeder
        image: quay.io/curl/curl
        command: ["/bin/sh","-lc"]
        env:
        - name: ANYTHINGLLM_API_KEY
          valueFrom:
            secretKeyRef:
              name: anythingllm-api
              key: key
        - name: WORKSPACE_NAME
          value: {{ .Values.aiLifecoach.workspace.name | quote }}
        - name: SEED_URL
          value: "{{ range .Values.rag.seedDocuments }}{{ .url }} {{ end }}"
        args:
        - |
          set -eu
          SVC="anythingllm-api-internal.${NAMESPACE}.svc.cluster.local:3001"
          BASE="http://${SVC}/api/v1"
          AUTH="Authorization: Bearer ${ANYTHINGLLM_API_KEY}"
          # Health check wait loop
          while true; do
            HEALTH_CODE=$(curl -s -o /dev/null -w '%{http_code}' -H "${AUTH}" "${BASE}/system")
            [ "$HEALTH_CODE" = "200" ] && break
            sleep 10
          done
          # Create workspace (idempotent)
          CREATE_RESP="$(curl -s -X POST "${BASE}/workspace/new" -H "${AUTH}" \
            -H "Content-Type: application/json" -d "{\"name\":\"${WS_NAME}\"}")"
          # Set system prompt
          curl -s -X POST "${BASE}/workspace/${WS_SLUG}/update" -H "${AUTH}" \
            -H "Content-Type: application/json" \
            -d '{"openAiPrompt": ...}' >/dev/null
          # Upload documents via URL
          for URL in ${SEED_URL}; do
            curl -s -X POST "${BASE}/document/upload-link" \
              -H "${AUTH}" -H "Content-Type: application/json" \
              -d "{\"link\":\"${URL}\", \"addToWorkspaces\":\"${WS_SLUG}\"}"
          done
```

### Llama Stack Seed Job (Python with K8s API Discovery)

The seed Job uses Helm hooks for ordering and mounts its script from a ConfigMap:

```yaml
# helm/templates/rag-seed-job.yaml (excerpt)
apiVersion: v1
kind: ConfigMap
metadata:
  name: rag-seed-script
  annotations:
    "helm.sh/hook": pre-install,pre-upgrade
    "helm.sh/hook-delete-policy": before-hook-creation
    "helm.sh/hook-weight": "-1"
data:
  seed.py: |
    import urllib.request, re, io, time, json, os, ssl, hashlib
    from llama_stack_client import LlamaStackClient

    # Auto-discover namespace admin via Kubernetes API
    with open('/var/run/secrets/kubernetes.io/serviceaccount/token') as f:
        k8s_token = f.read().strip()
    with open('/var/run/secrets/kubernetes.io/serviceaccount/namespace') as f:
        namespace = f.read().strip()

    req = urllib.request.Request(
        f'https://kubernetes.default.svc/apis/rbac.authorization.k8s.io/v1/namespaces/{namespace}/rolebindings',
        headers={'Authorization': f'Bearer {k8s_token}'}
    )
    # Find user with admin RoleBinding
    username = None
    for rb in rbs.get('items', []):
        if rb.get('roleRef', {}).get('name') == 'admin':
            for subj in rb.get('subjects', []):
                if subj.get('kind') == 'User':
                    username = subj['name']
                    break

    hashed = hashlib.sha256(username.encode()).hexdigest()[:32]
    # Create or find vector store named by hashed username
    vs = client.vector_stores.create(name=hashed, ...)
    # Fetch HTML, strip tags, upload as text files
    for doc in seed_docs:
        text = fetch_text(url)
        f = client.files.create(file=(filename, io.BytesIO(text.encode("utf-8")), "text/plain"), purpose="assistants")
        client.vector_stores.files.create(vector_store_id=vs_id, file_id=f.id)
```

### RBAC for K8s API Discovery

The seed Job gets its own ServiceAccount with permission to list RoleBindings:

```yaml
# helm/templates/rag-seed-job.yaml (excerpt)
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: rag-seed-role
  annotations:
    "helm.sh/hook": pre-install,pre-upgrade
    "helm.sh/hook-delete-policy": before-hook-creation
rules:
  - apiGroups: ["rbac.authorization.k8s.io"]
    resources: ["rolebindings"]
    verbs: ["list"]
```

### Seed Documents from values.yaml

Both Jobs consume the same seed document list from values:

```yaml
# helm/values.yaml (excerpt)
rag:
  seedDocuments:
    - filename: hr-compliance-strategies.txt
      url: https://www.goco.io/blog/key-hr-compliance-strategies-for-financial-services
    - filename: strong-compliance-culture.txt
      url: https://crosscheckcompliance.com/resources/articles/strong-compliance-culture/
```

## Configuration

- **Key settings:** `rag.seedDocuments` defines the document URLs and filenames to ingest; `aiLifecoach.workspace.name` and `aiLifecoach.workspace.systemPrompt` configure the AnythingLLM workspace; the internal service DNS `anythingllm-api-internal` at port 3001 is used by the curl Job
- **Defaults:** AnythingLLM seed Job has `backoffLimit: 0` (no retries); Llama Stack seed Job also uses `backoffLimit: 0`; Llama Stack client timeout is 300 seconds; HTML text is truncated to 60,000 characters
- **Dependencies:** The AnythingLLM seed Job depends on the SQLite sidecar having injected the API key first; the Llama Stack seed Job depends on the LlamaStackDistribution CR being ready; both require network access to external URLs for document fetching

## Gotchas

- The Llama Stack seed Job uses Helm hooks (`pre-install,pre-upgrade`) with `hook-delete-policy: before-hook-creation` while the AnythingLLM seed Job does not use hooks -- this means the Llama Stack Job's RBAC and ConfigMap are created before the main chart resources, but the Job itself may run before the LlamaStackDistribution is ready, which is why it includes its own readiness wait loop (see `helm/templates/rag-seed-job.yaml`)
- The namespace admin discovery hashes the username with SHA256 and takes the first 32 characters as the vector store name -- this must match the convention used by any frontend (BFF) that auto-provisions vector stores for users (see `rag-seed-job.yaml` seed.py script)
- The AnythingLLM seed Job connects via a separate internal Service (`anythingllm-api-internal:3001`) rather than the Notebook's port 8888 -- this bypasses the OAuth proxy and Jupyter routing (see `helm/templates/anythingllm-api-service.yaml` and `helm/templates/init_job.yaml`)
- The Python script's `fetch_text` function strips HTML tags, scripts, styles, nav, header, footer, and aside elements -- this is a basic text extraction that works for blog-style content but may miss structured data (see `rag-seed-job.yaml` seed.py)
- The `system prompt` is set on the AnythingLLM workspace via a POST to `/workspace/{slug}/update` using double-JSON encoding (`toJson | toJson`) in Helm to properly escape the multiline prompt string (see `helm/templates/init_job.yaml`)

## Related Patterns

- `helm-workbench-sqlite-sidecar-api-key-injection.md` -- the sidecar that provides the API key consumed by the AnythingLLM seed Job
- `helm-llamastack-crd-inline-milvus-rag-configmap.md` -- the LlamaStackDistribution that the Python seed Job waits for
- `helm-init-job-llamastack-registration-db-migration.md` -- alternative init Job pattern using application image for LlamaStack registration
