---
name: llama-stack-playground
description: "LlamaStack distribution deployed as RHOAI Playground proxy with inline Milvus vector I/O and RAG seed job"
summary: "Provides a playground UI for LlamaStack-served models via two approaches: Approach A deploys a LlamaStackDistribution CRD (`rh-dev`, `registry.redhat.io/rhoai/odh-llama-stack-core-rhel9` pinned by digest, labeled `opendatahub.io/dashboard: \"true\"`) as an RHOAI Early Access Playground proxy with built-in RAG via `inline::milvus`/`inline::sentence-transformers` (ibm-granite/granite-embedding-125m-english, 768d) and a `llama_stack_client` SDK seed job; Approach B deploys a pre-built Streamlit container (`quay.io/rh-aiservices-bu/llama-stack-playground:0.2.11`, port 8501) as a standard Deployment with OpenShift Route (TLS edge) and NetworkPolicy, delegating inference/RAG to a separate Llama Stack backend. Use Approach A when tight RHOAI dashboard integration with managed RAG (inline Milvus with default vector store mapped to sentence-transformers embedding model, auto-provisioned vector stores) is needed -- requires the LlamaStack operator, KServe Standard mode, and 12Gi memory for inline providers; use Approach B for an independent lightweight testing UI (1Gi, standalone Helm subchart) without operator dependencies, deployed in Phase 3 of multi-chart Helm installation. Approach A stores distribution config inline in a `llama-stack-config` ConfigMap with `remote::vllm` on KServe predictor port 8080/v1, `VLLM_API_TOKEN_1` literal `fake` (auth disabled via `security.opendatahub.io/enable-auth: 'false'` on InferenceService), and `network.allowedFrom.namespaces` restricting access to the release namespace with `exposeRoute: false`; Approach B connects via `LLAMA_STACK_ENDPOINT` env var with NetworkPolicy restricting ingress to openshift-ingress namespace and egress to llama-stack backend pods only. Approach A gotchas: vLLM uses port 8080 not 8443 in KServe Standard mode, all state is pod-local SQLite with no PVC (lost on reschedule), RAG seed job admin discovery fails without User-type admin RoleBinding, and vector store names use `hashlib.sha256(username.encode()).hexdigest()[:32]` which must match the Playground BFF auto-provisioning scheme; Approach B: `readOnlyRootFilesystem: false` required for Streamlit cache, explicit UID/GID omitted for OpenShift restricted SCC, and feature toggles (`enableChat`/`enableAgents`/`enableTools`) declared in values.yaml but not injected as env vars."
metadata:
  type: component
tags:
  tech_stack: [llamastack, vllm, milvus, sentence-transformers, helm, python, llama-stack-client, streamlit]
  ai_pattern: [rag, model-serving, vector-search, embeddings, agents]
  platform: [rhoai, openshift, kserve]
  data_layer: [milvus, sqlite]
source_examples:
  - quickstart: "llm-cpu-serving"
    repo: "https://github.com/rh-ai-quickstart/llm-cpu-serving"
    notes: "LlamaStack as RHOAI Playground proxy with LlamaStackDistribution CRD, inline Milvus for vector I/O, sentence-transformers for embeddings, and RAG seed job for auto-provisioning vector stores"
    approach: "A"
  - quickstart: "lls-observability"
    repo: "https://github.com/rh-ai-quickstart/lls-observability"
    notes: "Streamlit-based standalone playground UI deployed as standard Kubernetes Deployment with OpenShift Route, connecting to Llama Stack backend via LLAMA_STACK_ENDPOINT"
    approach: "B"
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

---

## Approach B: Streamlit Standalone Playground (from lls-observability)

### When to Use

Use this approach when you need a standalone, interactive web UI for testing Llama Stack features (chat, agents, tools) without tight RHOAI dashboard integration. This is well-suited for observability-focused quickstarts where the playground is one component in a larger multi-chart Helm deployment and the UI is deployed as its own independent service with an OpenShift Route.

### Differences from Approach A

- **Deployment method:** Standard Kubernetes Deployment (not a LlamaStackDistribution CRD) -- no operator dependency
- **Application runtime:** Pre-built Streamlit application served on port 8501 (container image `quay.io/rh-aiservices-bu/llama-stack-playground`)
- **External access:** OpenShift Route with TLS edge termination (Approach A has no route, relies on RHOAI dashboard)
- **RAG/vector stores:** Not included -- the playground connects directly to a separate Llama Stack instance that handles RAG/vector I/O
- **Helm structure:** Standalone subchart under `helm/03-ai-services/llama-stack-playground/` with its own `Chart.yaml`, `values.yaml`, and templates (Approach A uses inline templates in a single Helm chart)
- **Features:** Chat, agents, and tools via the Llama Stack backend (configured via `playground.enableChat`, `playground.enableAgents`, `playground.enableTools`)

### Tech Stack & Dependencies

- **Runtime:** Streamlit (Python), port 8501
- **Container image:** `quay.io/rh-aiservices-bu/llama-stack-playground:0.2.11`
- **Key dependencies:** Llama Stack backend instance (connected via `LLAMA_STACK_ENDPOINT` env var)
- **Helm subchart:** Standalone chart `llama-stack-playground` (version 1.0.0)

### Key Patterns

#### Standalone Helm Chart with Streamlit

The playground is deployed as a standard Kubernetes Deployment with a pre-built Streamlit container image. It connects to a separate Llama Stack instance service via the `LLAMA_STACK_ENDPOINT` environment variable.

```yaml
# helm/03-ai-services/llama-stack-playground/templates/deployment.yaml
env:
  {{- range $key, $value := .Values.env }}
  - name: {{ $key }}
    value: {{ $value | quote }}
  {{- end }}
  - name: LLAMA_STACK_ENDPOINT
    value: {{ .Values.playground.llamaStackUrl | quote }}
  - name: DEFAULT_MODEL
    value: {{ .Values.playground.defaultModel | quote }}
```

#### OpenShift Route with TLS Edge Termination

The playground exposes an OpenShift Route for external browser access. TLS is terminated at the edge with automatic HTTP-to-HTTPS redirect.

```yaml
# helm/03-ai-services/llama-stack-playground/values.yaml
route:
  enabled: true
  tls:
    enabled: true
    termination: edge
    insecureEdgeTerminationPolicy: Redirect
```

#### OpenShift-Compatible Security Context

The pod and container security contexts are configured for OpenShift's restricted SCC by omitting explicit UID/GID values and letting OpenShift assign them from the namespace range.

```yaml
# helm/03-ai-services/llama-stack-playground/values.yaml
podSecurityContext:
  runAsNonRoot: true
  # Remove specific UID/GID to let OpenShift assign them
  # fsGroup: 1001

securityContext:
  allowPrivilegeEscalation: false
  capabilities:
    drop:
    - ALL
  readOnlyRootFilesystem: false
  runAsNonRoot: true
```

#### Network Policy for Component Isolation

Network policies restrict ingress to the OpenShift ingress controller only and egress to the Llama Stack backend pods only.

```yaml
# helm/03-ai-services/llama-stack-playground/values.yaml
networkPolicy:
  enabled: true
  ingress:
    - from:
      - namespaceSelector:
          matchLabels:
            name: openshift-ingress
      ports:
      - protocol: TCP
        port: 8501
  egress:
    - to:
      - podSelector:
          matchLabels:
            app.kubernetes.io/name: llama-stack
      ports:
      - protocol: TCP
        port: 80
```

### Configuration

- **Environment variables:**
  - `LLAMA_STACK_ENDPOINT` -- Llama Stack backend URL (default: `http://llama-stack-instance-service:8321`)
  - `DEFAULT_MODEL` -- Default model ID for the playground (default: `meta-llama/Llama-3.2-3B-Instruct`)
  - `STREAMLIT_SERVER_PORT` -- Streamlit listening port (default: `8501`)
  - `STREAMLIT_SERVER_ADDRESS` -- Streamlit bind address (default: `0.0.0.0`)
  - `STREAMLIT_BROWSER_GATHER_USAGE_STATS` -- Disable Streamlit telemetry (default: `false`)
- **Helm values:**
  - `image.repository` / `image.tag` -- Container image (default: `quay.io/rh-aiservices-bu/llama-stack-playground:0.2.11`)
  - `playground.llamaStackUrl` -- Backend URL passed as `LLAMA_STACK_ENDPOINT`
  - `playground.defaultModel` -- Model ID passed as `DEFAULT_MODEL`
  - `playground.enableChat` / `playground.enableAgents` / `playground.enableTools` -- Feature toggles (all `true` by default)
  - `route.enabled` -- Whether to create an OpenShift Route (default: `true`)
  - `networkPolicy.enabled` -- Whether to create NetworkPolicy (default: `true`)

### Known Gotchas

- The Streamlit server runs on port 8501 inside the container, but the Service exposes port 80 externally (`service.port: 80`, `service.targetPort: 8501`). The Route targets the `http` named port on the Service, so the Service-to-container port mapping must remain consistent.
- The `readOnlyRootFilesystem` is set to `false` in the security context. Streamlit requires write access to the filesystem for its runtime cache (`.streamlit/` directory).
- The `values.yaml` comments out `fsGroup`, `runAsUser`, and `runAsGroup` with the note "Remove specific UID/GID to let OpenShift assign them." This is required for the restricted SCC on OpenShift; setting explicit UIDs would cause pod scheduling failures.
- The liveness probe has an `initialDelaySeconds: 30` while the readiness probe has `initialDelaySeconds: 5`. The Streamlit app may take up to 30 seconds to start serving on the root path (`/`).
- The `playground.enableChat`, `playground.enableAgents`, and `playground.enableTools` values appear in `values.yaml` but are not injected as environment variables in the deployment template. These may be intended for future use or are handled by the Streamlit app's own configuration discovery.
- Resource requests are 500m CPU / 512Mi memory with a limit of 1Gi memory (no CPU limit). This is significantly lighter than Approach A's 12Gi memory requirement since the Streamlit app is only a UI client -- all inference, embeddings, and vector I/O happen in the separate Llama Stack backend.

### Testing Notes

- Verify the Route is created: `oc get route llama-stack-playground -n <namespace>` should return a hostname.
- Access the playground in a browser via the Route URL; the Streamlit UI should load on the root path (`/`).
- The readiness probe checks `GET /` on port 8501. If the pod is not ready, check Streamlit startup logs: `oc logs deployment/llama-stack-playground -n <namespace>`.
- Confirm the playground can reach the Llama Stack backend: test inference through the chat interface. Connection failures will appear in the Streamlit UI.
- The playground is deployed in Phase 3 of the installation, after MCP servers and other AI services. The Llama Stack instance must be running before the playground can function.

### Related Patterns

- Components: llamastack (Llama Stack instance configuration), streamlit-frontend (Streamlit deployment patterns)
- Deployment: Multi-phase Helm installation with dependency ordering (operators -> observability -> AI services)

---

## Choosing Between Approaches

| Criteria | Approach A (RHOAI CRD Proxy) | Approach B (Streamlit Standalone) |
|----------|-------------------------------|-----------------------------------|
| Operator dependency | Requires OpenShift AI LlamaStack operator | No operator needed |
| RHOAI dashboard integration | Integrated with Early Access Playground UI | Standalone web app via OpenShift Route |
| RAG capabilities | Built-in (inline Milvus, seed job) | Delegated to separate Llama Stack backend |
| Memory footprint | 12Gi (inline providers run in-process) | 1Gi (UI client only) |
| External access | No route (dashboard-only) | OpenShift Route with TLS edge |
| Helm structure | Inline templates in parent chart | Standalone subchart with full Chart.yaml |
| Use case | Tight RHOAI platform integration with managed RAG | Independent testing UI in multi-component observability stack |
| State persistence | Pod-local SQLite (lost on reschedule) | Stateless (all state in Llama Stack backend) |
