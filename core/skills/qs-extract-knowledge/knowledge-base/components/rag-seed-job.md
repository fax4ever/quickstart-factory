---
name: rag-seed-job
description: "Helm hook Job that seeds RAG documents into a LlamaStack vector store with K8s-based user auto-discovery"
summary: "Pre-populates a LlamaStack vector store with web-fetched seed documents before application startup, deployed as a Helm pre-install/pre-upgrade hook Job with weighted resources (RBAC at -2, ConfigMap at -1, Job at 0) and /v1/version readiness polling. Use when a RAG application needs pre-seeded documents at first launch with automatic user discovery — the job lists K8s RoleBindings (minimal list-only RBAC) to find the namespace admin and creates a user-scoped vector store named SHA-256(username)[:32], matching the BFF naming convention so both share the same store. Inline Python script runs on the LlamaStack distribution image (registry.redhat.io/rhoai/odh-llama-stack-core-rhel9, no separate build), reads SEED_DOCS JSON env var from rag.seedDocuments values, regex-strips HTML, truncates to 60k chars, uploads via client.files.create(purpose=\"assistants\"), and skips existing filenames for idempotent re-runs. Critical gotchas: backoffLimit: 0 with restartPolicy: Never means a single failure is permanent; admin discovery raises RuntimeError without an OpenShift-style User-subject admin RoleBinding; before-hook-creation delete policy re-runs the seed job on every helm upgrade but idempotent file checks prevent duplicate uploads."
metadata:
  type: component
tags:
  tech_stack: [python, llama-stack-client, helm]
  ai_pattern: [rag, vector-search, embeddings]
  platform: [openshift, kubernetes, rhoai, kserve]
  data_layer: [milvus]
source_examples:
  - quickstart: "llm-cpu-serving"
    repo: "https://github.com/rh-ai-quickstart/llm-cpu-serving"
    notes: "Helm pre-install/pre-upgrade hook Job that auto-discovers namespace admin, creates a user-scoped vector store in LlamaStack, and indexes seed documents from web URLs"
    approach: "A"
---

# RAG Seed Job

## Overview

The RAG seed job is a Kubernetes Job deployed as a Helm hook that pre-populates a LlamaStack vector store with seed documents before the main application starts. It runs at `pre-install` and `pre-upgrade`, auto-discovers the namespace admin user via the K8s RBAC API, creates a user-scoped vector store (named by SHA-256 hash of the username), and fetches/indexes web documents using the LlamaStack files and vector_stores APIs.

## Tech Stack & Dependencies

- **Runtime:** Python 3 (inline script via ConfigMap, no separate image build)
- **Container image:** Reuses the LlamaStack distribution image (`registry.redhat.io/rhoai/odh-llama-stack-core-rhel9`)
- **Key dependencies:** `llama_stack_client` (bundled in the LlamaStack image), K8s service account with RBAC list permissions
- **Helm subchart:** None (standalone template in `helm/templates/rag-seed-job.yaml`)

## Key Patterns

### Helm Hook Orchestration with Weighted Resources

The job uses Helm hooks to ensure all RBAC resources are created before the seed script runs. The ServiceAccount, Role, and RoleBinding use hook-weight `-2`, while the ConfigMap containing the script uses hook-weight `-1`, and the Job itself has no explicit weight (defaults to `0`), ensuring correct ordering.

```yaml
# ServiceAccount, Role, RoleBinding all use weight -2
apiVersion: v1
kind: ServiceAccount
metadata:
  name: rag-seed
  annotations:
    "helm.sh/hook": pre-install,pre-upgrade
    "helm.sh/hook-delete-policy": before-hook-creation
    "helm.sh/hook-weight": "-2"
```

```yaml
# ConfigMap uses weight -1 (created after RBAC, before Job)
apiVersion: v1
kind: ConfigMap
metadata:
  name: rag-seed-script
  annotations:
    "helm.sh/hook": pre-install,pre-upgrade
    "helm.sh/hook-delete-policy": before-hook-creation
    "helm.sh/hook-weight": "-1"
```

### Kubernetes RBAC Auto-Discovery of Namespace Admin

The seed script discovers the deploying user's identity by listing RoleBindings in its own namespace via the K8s API, looking for the `admin` role binding, and extracting the first `User` subject. This avoids requiring the username as a Helm value.

```python
req = urllib.request.Request(
    f'https://kubernetes.default.svc/apis/rbac.authorization.k8s.io/v1/namespaces/{namespace}/rolebindings',
    headers={'Authorization': f'Bearer {k8s_token}', 'Accept': 'application/json'}
)
with urllib.request.urlopen(req, context=k8s_ctx, timeout=10) as r:
    rbs = json.loads(r.read())

username = None
for rb in rbs.get('items', []):
    if rb.get('roleRef', {}).get('name') == 'admin':
        for subj in rb.get('subjects', []):
            if subj.get('kind') == 'User':
                username = subj['name']
                break
```

The Role grants only `list` on `rolebindings` -- minimal RBAC surface:

```yaml
rules:
  - apiGroups: ["rbac.authorization.k8s.io"]
    resources: ["rolebindings"]
    verbs: ["list"]
```

### User-Scoped Vector Store with SHA-256 Naming

The vector store is named using a SHA-256 hash of the admin username (truncated to 32 chars). This matches the naming convention used by the BFF (backend-for-frontend), so the seed job and the UI share the same vector store. If the vector store already exists (user opened UI first), the job seeds into it; otherwise it creates it with auto-provisioning metadata.

```python
hashed = hashlib.sha256(username.encode()).hexdigest()[:32]

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

### LlamaStack Readiness Polling

The job polls the LlamaStack `/v1/version` endpoint in a loop before attempting any API calls, with a 10-second sleep between attempts. This handles the case where the Helm hook Job starts before the LlamaStack distribution pod is ready.

```python
while True:
    try:
        urllib.request.urlopen(base_url + "/v1/version", timeout=5)
        print("LlamaStack is ready!")
        break
    except Exception as e:
        print(f"  not ready: {e}")
        time.sleep(10)
```

### Idempotent Document Ingestion

The job checks existing files in the vector store and skips any that are already uploaded, making re-runs safe. Documents are fetched from web URLs, HTML-stripped with regex, and truncated to 60,000 characters before upload via the LlamaStack files API.

```python
existing = {f.filename for f in client.files.list().data}

for doc in seed_docs:
    filename, url = doc["filename"], doc["url"]
    if filename in existing:
        print(f"Skipping {filename} (already uploaded)")
        continue
    text = fetch_text(url)
    f = client.files.create(
        file=(filename, io.BytesIO(text.encode("utf-8")), "text/plain"),
        purpose="assistants",
    )
    client.vector_stores.files.create(vector_store_id=vs_id, file_id=f.id)
```

## Configuration

- **Environment variables:**
  - `LLAMASTACK_URL`: Internal service URL for the LlamaStack distribution (e.g., `http://lsd-genai-playground-service.<namespace>.svc.cluster.local:8321`)
  - `SEED_DOCS`: JSON array of `{filename, url}` objects from `values.yaml`
- **Config files:** The Python seed script is stored in a ConfigMap (`rag-seed-script`) and mounted at `/scripts/seed.py`
- **Helm values:**
  - `images.llamaStack`: Container image for the job (reuses the LlamaStack distribution image)
  - `rag.seedDocuments`: Array of documents to seed, each with `filename` and `url` keys

Example values.yaml configuration:

```yaml
rag:
  seedDocuments:
    - filename: hr-compliance-strategies.txt
      url: https://www.goco.io/blog/key-hr-compliance-strategies-for-financial-services
    - filename: strong-compliance-culture.txt
      url: https://crosscheckcompliance.com/resources/articles/strong-compliance-culture/
```

## Known Gotchas

- The job has `backoffLimit: 0` and `restartPolicy: Never`, meaning a single failure causes the job to fail permanently. If LlamaStack never becomes ready or a seed URL is unreachable, the job will fail without retry.
- The admin user discovery depends on an OpenShift-style RoleBinding where the deploying user is bound as a `User` subject with the `admin` role. If no such binding exists (e.g., the namespace was created differently), the job raises `RuntimeError("Could not find admin User in namespace RoleBindings")`.
- The HTML-to-text extraction uses regex-based tag stripping (`re.sub(r"<[^>]+>", " ", html)`) with a 60,000 character truncation, which may lose content from large web pages.
- The `before-hook-creation` delete policy means each `helm upgrade` deletes and recreates all hook resources (ServiceAccount, Role, RoleBinding, ConfigMap, Job), so the seed job runs again on every upgrade. However, the idempotent file check prevents duplicate document uploads.
- The job reuses the LlamaStack distribution image rather than a minimal Python image, which means a larger container pull but avoids needing a separate image with `llama_stack_client` installed.

## Testing Notes

- After deployment, verify the seed job completed: `oc get jobs | grep rag-seed` should show `1/1` completions
- Check job logs for successful document indexing: `oc logs job/rag-seed`
- Verify the vector store was created in LlamaStack by querying the API or checking the UI
- If the job fails, check that the namespace has an admin RoleBinding with a `User` subject

## Related Patterns

- `llamastack.md` -- LlamaStack distribution server that this job seeds into
- `tenant-bootstrap.md` -- Similar pattern of K8s Job-based initialization for namespace setup
