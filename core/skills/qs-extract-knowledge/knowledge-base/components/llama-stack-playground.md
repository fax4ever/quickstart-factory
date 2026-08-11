---
name: llama-stack-playground
description: "LlamaStack distribution deployed as RHOAI Playground proxy with inline Milvus vector I/O and RAG seed job"
summary: "Deploys a LlamaStackDistribution CRD (`rh-dev` distribution, config version 2, image `registry.redhat.io/rhoai/odh-llama-stack-core-rhel9` pinned by digest) as a proxy between the RHOAI Early Access Playground UI and a vLLM CPU inference backend, with `remote::vllm` inference on KServe predictor port 8080/v1, `inline::sentence-transformers` for ibm-granite/granite-embedding-125m-english embeddings (768d), `inline::milvus` backed by local SQLite for vector I/O, and distribution config stored inline in a `llama-stack-config` ConfigMap with default vector store provider mapping Milvus to the sentence-transformers embedding model. Use when integrating LlamaStack with the RHOAI dashboard Playground feature (`opendatahub.io/dashboard: \"true\"`) to provide RAG-enabled chat with auto-provisioned vector stores; requires the OpenShift AI LlamaStack operator and KServe Standard deployment mode (not RawDeployment). The RAG seed job uses `llama_stack_client` SDK to auto-discover the namespace admin from RoleBindings, creates a SHA-256-hashed vector store name (`hashlib.sha256(username.encode()).hexdigest()[:32]`) matching the Playground BFF auto-provisioning scheme, fetches HTML documents (stripped of script/style/nav tags and truncated to 60,000 chars), and uploads them idempotently by checking existing vector stores. Key gotchas: vLLM inference uses port 8080 (not 8443) in KServe Standard mode; inline providers (sentence-transformers, Milvus) require 12Gi memory limit; `VLLM_API_TOKEN_1` is literal `fake` since auth is disabled via `security.opendatahub.io/enable-auth: 'false'`; all state is pod-local with no PVC so vector stores and documents are lost on reschedule; admin discovery fails if the namespace lacks a User-type admin RoleBinding."
metadata:
  type: component
tags:
  tech_stack: [llamastack, vllm, milvus, sentence-transformers, helm, python, llama-stack-client]
  ai_pattern: [rag, model-serving, vector-search, embeddings]
  platform: [rhoai, openshift, kserve]
  data_layer: [milvus, sqlite]
source_examples:
  - quickstart: "llm-cpu-serving"
    repo: "https://github.com/rh-ai-quickstart/llm-cpu-serving"
    notes: "LlamaStack as RHOAI Playground proxy with LlamaStackDistribution CRD, inline Milvus for vector I/O, sentence-transformers for embeddings, and RAG seed job for auto-provisioning vector stores"
    approach: "A"
---

# Llama Stack Playground

## Overview

The Llama Stack Playground component deploys a LlamaStack distribution server as a proxy layer between the RHOAI Playground UI and a vLLM CPU inference backend. It uses the `LlamaStackDistribution` CRD managed by the OpenShift AI operator and provides a complete RAG-enabled playground experience with inline Milvus vector storage, sentence-transformers embeddings, and a seed job that auto-provisions vector stores with documents. The component is labeled for the RHOAI dashboard (`opendatahub.io/dashboard: "true"`) so it integrates with the Early Access Playground feature.

## Tech Stack & Dependencies

- **Runtime:** LlamaStack distribution server (config version 2, distribution `rh`)
- **Container image:** `registry.redhat.io/rhoai/odh-llama-stack-core-rhel9` (Red Hat certified, pinned by digest)
- **Key dependencies:** vLLM CPU model server via KServe InferenceService, `llama_stack_client` Python SDK (used by the RAG seed job)
- **Helm subchart:** None (standalone Helm template at `helm/templates/playground.yaml`)

## Key Patterns

### LlamaStackDistribution CRD with Inline Config

The component deploys a `LlamaStackDistribution` custom resource that references a ConfigMap containing the full distribution config. The CRD is reconciled by the OpenShift AI LlamaStack operator. Network access is restricted to the release namespace only, and no external route is exposed.

```yaml
# helm/templates/playground.yaml
apiVersion: llamastack.io/v1alpha1
kind: LlamaStackDistribution
metadata:
  annotations:
    openshift.io/display-name: lsd-genai-playground
  labels:
    opendatahub.io/dashboard: "true"
  name: lsd-genai-playground
spec:
  network:
    allowedFrom:
      namespaces:
        - {{ .Release.Namespace }}
    exposeRoute: false
  replicas: 1
  server:
    distribution:
      name: rh-dev
    userConfig:
      configMapName: llama-stack-config
```

### Multi-Provider Distribution Config

The ConfigMap contains a comprehensive distribution config with multiple provider types. Inference uses `remote::vllm` connecting to the KServe predictor, while embeddings use `inline::sentence-transformers` with the `ibm-granite/granite-embedding-125m-english` model (768 dimensions). Vector I/O uses `inline::milvus` backed by a local SQLite-based Milvus DB file.

```yaml
# helm/templates/playground.yaml (ConfigMap data)
providers:
  inference:
  - provider_id: sentence-transformers
    provider_type: inline::sentence-transformers
    config: {}
  - provider_id: vllm-{{ .Values.model.name }}
    provider_type: remote::vllm
    config:
      api_token: ${env.VLLM_API_TOKEN_1:=fake}
      base_url: http://{{ .Values.model.name }}-predictor.{{ .Release.Namespace }}.svc.cluster.local:8080/v1
  vector_io:
  - provider_id: milvus
    provider_type: inline::milvus
    config:
      db_path: /opt/app-root/src/.llama/distributions/rh/milvus.db
```

### Registered Models with Embedding Metadata

The distribution config pre-registers both the LLM and embedding models. The embedding model registration includes the `embedding_dimension: 768` metadata required by vector store operations and uses the `sentence-transformers` provider prefix.

```yaml
# helm/templates/playground.yaml (ConfigMap data)
registered_resources:
  models:
  - provider_id: sentence-transformers
    model_id: sentence-transformers/ibm-granite/granite-embedding-125m-english
    provider_model_id: ibm-granite/granite-embedding-125m-english
    model_type: embedding
    metadata:
      embedding_dimension: 768
  - provider_id: vllm-{{ .Values.model.name }}
    model_id: {{ .Values.model.name }}
    model_type: llm
```

### Default Vector Store Configuration

The config designates Milvus as the default vector store provider and maps it to the sentence-transformers embedding model. This means any vector store created through the Playground or seed job will automatically use Milvus for storage and `ibm-granite/granite-embedding-125m-english` for embedding generation.

```yaml
# helm/templates/playground.yaml (ConfigMap data)
vector_stores:
  default_provider_id: milvus
  default_embedding_model:
    provider_id: sentence-transformers
    model_id: ibm-granite/granite-embedding-125m-english
```

### RAG Seed Job with Auto-Provisioned Vector Stores

A Kubernetes Job runs after deployment to seed the playground with documents for RAG. The job auto-discovers the namespace admin username from RoleBindings, hashes it with SHA-256 to create a vector store name (matching the RHOAI Playground BFF auto-provisioning scheme), and uploads seed documents. The job uses the `llama_stack_client` SDK to interact with the LlamaStack server.

```python
# helm/templates/rag-seed-job.yaml (seed.py inline script)
client = LlamaStackClient(base_url=base_url, timeout=300)

# Auto-discover namespace admin from RoleBindings
for rb in rbs.get('items', []):
    if rb.get('roleRef', {}).get('name') == 'admin':
        for subj in rb.get('subjects', []):
            if subj.get('kind') == 'User':
                username = subj['name']

hashed = hashlib.sha256(username.encode()).hexdigest()[:32]
```

The job is idempotent: it checks existing vector stores by name and skips files that are already uploaded.

```python
# helm/templates/rag-seed-job.yaml (seed.py inline script)
vs_list = client.vector_stores.list()
for vs in vs_list.data:
    if vs.name == hashed or vs.id == hashed:
        vs_id = vs.id
        break
if not vs_id:
    vs = client.vector_stores.create(
        name=hashed,
        metadata={"created_by": "auto-provisioning", "username": username},
    )
```

### HTML-to-Text Document Extraction

The seed job fetches documents from URLs, strips HTML tags, and uploads the plain text to LlamaStack. The extraction removes script, style, nav, header, footer, and aside elements, then strips remaining HTML tags and collapses whitespace. Text is truncated to 60,000 characters.

```python
# helm/templates/rag-seed-job.yaml (seed.py inline script)
def fetch_text(url):
    html = r.read().decode("utf-8", errors="ignore")
    html = re.sub(r"<(script|style|nav|header|footer|aside)[^>]*>.*?</\1>", " ", html, flags=re.DOTALL|re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", html)
    return text.strip()[:60000]
```

## Configuration

- **Environment variables (LlamaStack container):**
  - `VLLM_TLS_VERIFY` -- Set to `"false"` for cluster-internal self-signed certificates
  - `VLLM_MAX_TOKENS` -- Maximum output tokens, set from `.Values.model.maxOutputTokens` (default: `512`)
  - `VLLM_API_TOKEN_1` -- API token for vLLM (set to `fake` for in-cluster KServe without auth)
  - `MILVUS_DB_PATH` -- Milvus database path (default: `~/.llama/milvus.db`)
  - `FMS_ORCHESTRATOR_URL` -- FMS orchestrator URL (set to `http://localhost`, unused placeholder)
  - `LLAMA_STACK_CONFIG_DIR` -- Distribution config directory (default: `/opt/app-root/src/.llama/distributions/rh/`)
- **Environment variables (RAG seed job):**
  - `LLAMASTACK_URL` -- LlamaStack service endpoint (`http://lsd-genai-playground-service.<namespace>.svc.cluster.local:8321`)
  - `SEED_DOCS` -- JSON array of seed documents from `.Values.rag.seedDocuments`
- **Config files:**
  - Distribution config is inline in the `llama-stack-config` ConfigMap (no external `run.yaml`)
- **Helm values:**
  - `images.llamaStack` -- LlamaStack container image (default: `registry.redhat.io/rhoai/odh-llama-stack-core-rhel9@sha256:...`)
  - `model.name` -- Model name used to construct the vLLM provider ID and KServe predictor URL (default: `tinyllama`)
  - `model.maxOutputTokens` -- Maximum output tokens passed to LlamaStack (default: `512`)
  - `rag.seedDocuments` -- Array of `{filename, url}` objects for RAG seeding

## Known Gotchas

- The vLLM inference endpoint uses port `8080` (`http://<model>-predictor.<ns>.svc.cluster.local:8080/v1`) instead of the `8443` HTTPS endpoint used by other quickstarts. This is because the `llm-cpu-serving` quickstart uses KServe Standard deployment mode (not RawDeployment), and the predictor service exposes HTTP on 8080 within the cluster.
- The LlamaStack container resource limits are set to 2 CPU and 12Gi memory, with requests of 250m CPU and 500Mi memory (`helm/templates/playground.yaml` lines 169-175). The high memory limit is needed because inline providers (sentence-transformers, Milvus) run in-process.
- The `VLLM_API_TOKEN_1` is set to the literal string `fake` in both the ConfigMap config (`${env.VLLM_API_TOKEN_1:=fake}`) and the container env. This works because the InferenceService has `security.opendatahub.io/enable-auth: 'false'` (see `inferenceservice.yaml` line 6).
- The RAG seed job uses the same LlamaStack container image (`images.llamaStack`) as both the seed runner and the LlamaStack server. This ensures `llama_stack_client` SDK version compatibility but means the seed job pulls the full LlamaStack image just to run a Python script.
- The seed job discovers the namespace admin by listing RoleBindings and finding one with `roleRef.name == 'admin'` and a `User` subject. If the namespace was created differently (e.g., via ServiceAccount-only binding), the job will fail with `"Could not find admin User in namespace RoleBindings"`.
- The vector store name is a truncated SHA-256 hash of the admin username (`hashlib.sha256(username.encode()).hexdigest()[:32]`). This must match the hash the RHOAI Playground BFF uses for auto-provisioning, or the user will see a different vector store in the Playground UI.
- Storage uses SQLite for metadata, kvstore, and SQL backends at `/opt/app-root/src/.llama/distributions/rh/`. All state is local to the pod; if the pod is rescheduled, vector stores and uploaded documents are lost since there is no PVC.
- The seed job's `fetch_text` function truncates documents to 60,000 characters (`text.strip()[:60000]`), which may silently drop content from longer web pages (see `rag-seed-job.yaml`).
- The `FMS_ORCHESTRATOR_URL` environment variable is set to `http://localhost` but is not used by the configuration. It appears to be a placeholder from the base distribution template.

## Testing Notes

- Verify LlamaStack readiness via the seed job: it polls `$LLAMASTACK_URL/v1/version` until a successful response before proceeding with document upload.
- After deployment, check the RAG seed job status: `oc get job rag-seed -n <namespace>` should show `1/1` completions.
- Check the LlamaStackDistribution status: `oc get llamastackdistribution lsd-genai-playground -n <namespace>`.
- The Playground UI is accessed through the RHOAI dashboard (requires Early Access "Playground" feature enabled): navigate to Gen AI studio, then Playground, then select the project.
- Verify seed documents were uploaded by checking the seed job logs for `indexed: <file_id>` messages.
- To test RAG, enable the Knowledge tab in the Playground UI and ask a question related to the seed documents.

## Related Patterns

- Components: llamastack (comprehensive LlamaStack deployment patterns), model-serving (KServe InferenceService with vLLM CPU)
- Deployment: Helm chart with LlamaStackDistribution CRD, RAG seed job pattern
