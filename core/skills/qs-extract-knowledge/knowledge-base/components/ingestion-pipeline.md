---
name: ingestion-pipeline
description: Kubernetes-based document ingestion pipeline using Kubeflow, Docling, and LlamaStack for RAG knowledge bases
summary: "Automates document processing and vector database population for RAG knowledge bases on Kubernetes, deploying as an ingestion-pipeline Helm subchart (v0.6.5) from ai-architecture-charts with a companion configure-pipeline subchart (v0.5.6) for MinIO setup and sample file uploads, triggered by the FastAPI backend via httpx AsyncClient to INGESTION_PIPELINE_URL endpoints (/add, /delete, /status). Use when you need multi-format document parsing (PDF/HTML/DOCX/Markdown via Docling with HybridChunker) orchestrated as a Kubeflow Pipeline with automated vector store registration in LlamaStack+pgvector -- agent templates can also auto-trigger ingestion via knowledge_base_config with skip_kb_validation for async processing. A two-container monitor pod polls PostgreSQL for unregistered KBs and spawns Kubeflow jobs (ingestion-pipeline-{kb_name}) executing three steps: MinIO S3 fetch, Docling+HybridChunker processing, and LlamaStack vector store registration (vector_store_id=\"{name}-v{version}\", embedding_model=\"all-MiniLM-L6-v2\", chunk_size_in_tokens=512); pipeline URL discovered via http://{Release.Name}-ingestion-pipeline; KnowledgeBaseCreate.pipeline_model_dict() handles URL sources (urls list) vs S3/dict sources (key flattening); a seeded admin user (ingestion-pipeline@change.me) authenticates pipeline-to-backend calls. Fallback URL silently routes to LlamaStack's built-in endpoint (http://llamastack:8321/ingestion_pipeline/) instead of the dedicated pipeline when INGESTION_PIPELINE_URL is unset in non-Helm deployments; deletion is fire-and-forget leaving orphaned cluster jobs; status is dynamically computed via /status but never persisted to the database; agent template auto-ingestion creates agents before their KB is ready."
metadata:
  type: component
tags:
  tech_stack: [kubeflow, docling, python, fastapi, httpx]
  ai_pattern: [rag, embeddings, data-pipeline, vector-search]
  platform: [rhoai, openshift, kubernetes, kserve]
  data_layer: [pgvector, minio]
source_examples:
  - quickstart: "ai-virtual-agent"
    repo: "https://github.com/rh-ai-quickstart/ai-virtual-agent"
    notes: "Helm subchart-based ingestion pipeline with monitor pod, Kubeflow orchestration, and Docling document processing for multi-source KB creation"
    approach: "A"
---

# Ingestion Pipeline

## Overview

The ingestion pipeline is a dedicated Kubernetes-based system that handles document processing and vector database population for RAG knowledge bases. It runs as a separate service (deployed via a Helm subchart from ai-architecture-charts) and is invoked by the backend application through an HTTP API. The pipeline uses Kubeflow for multi-step orchestration, Docling for document parsing, and LlamaStack for vector store registration and embedding insertion.

## Tech Stack & Dependencies

- **Runtime:** Python / Kubeflow Pipelines
- **Container image:** Deployed via `ingestion-pipeline` Helm subchart from ai-architecture-charts
- **Key dependencies:** Kubeflow Pipelines, Docling (PDF/HTML/DOCX/Markdown parsing), HybridChunker, MinIO (S3-compatible storage), LlamaStack client, pgvector
- **Helm subchart:** `ingestion-pipeline` v0.6.5 from `https://rh-ai-quickstart.github.io/ai-architecture-charts`
- **Companion subchart:** `configure-pipeline` v0.5.6 (handles MinIO setup and sample file uploads)

## Key Patterns

### Backend-to-Pipeline HTTP API Integration

The FastAPI backend communicates with the ingestion pipeline through a simple HTTP API. The URL is resolved from the `INGESTION_PIPELINE_URL` environment variable, falling back to LlamaStack's built-in ingestion endpoint.

```python
# backend/app/api/v1/knowledge_bases.py
def get_ingestion_pipeline_url():
    try:
        return os.environ["INGESTION_PIPELINE_URL"]
    except KeyError:
        return "http://llamastack:8321/ingestion_pipeline/"
```

Three operations are supported: `/add` (create), `/delete` (remove), and `/status` (poll state).

### Pipeline Creation via Backend

When a knowledge base is created, the backend immediately triggers the ingestion pipeline with the KB's configuration. The pipeline runs asynchronously -- the backend does not wait for ingestion to complete.

```python
# backend/app/api/v1/knowledge_bases.py
async def create_ingestion_pipeline(kb: KnowledgeBaseCreate):
    """Create ingestion pipeline via external API."""
    add_pipeline = get_ingestion_pipeline_url() + "/add"
    data = kb.pipeline_model_dict()
    async with httpx.AsyncClient() as client:
        response = await client.post(add_pipeline, json=data)
        response.raise_for_status()
```

### Pipeline Model Dictionary (Source Type Handling)

The `KnowledgeBaseCreate` schema generates the payload sent to the ingestion pipeline API. It handles two source types differently: URL sources pass a list of URLs, while S3/dict-based sources flatten configuration keys.

```python
# backend/app/schemas/knowledge_bases.py
def pipeline_model_dict(self) -> Dict[str, Any]:
    base = {
        "name": self.name,
        "version": self.version,
        "source": self.source,
        "embedding_model": self.embedding_model,
        "vector_store_name": self.vector_store_name,
    }
    if self.source == "URL":
        return base | {"urls": self.source_configuration}
    if isinstance(self.source_configuration, dict):
        return base | {k.lower(): v for k, v in self.source_configuration.items()}
    else:
        return base | {"config": self.source_configuration}
```

### Helm Subchart Wiring

The ingestion pipeline is deployed as a Helm subchart dependency. The backend discovers it through a release-name-prefixed service URL injected as an environment variable in the deployment template.

```yaml
# deploy/cluster/helm/Chart.yaml (dependency)
- name: ingestion-pipeline
  version: 0.6.5
  repository: https://rh-ai-quickstart.github.io/ai-architecture-charts
```

```yaml
# deploy/cluster/helm/templates/deployment.yaml
- name: INGESTION_PIPELINE_URL
  value: http://{{ .Release.Name }}-ingestion-pipeline
```

### Monitor Pod Architecture

The ingestion pipeline deploys a monitor pod with two containers that poll PostgreSQL for new knowledge bases and create Kubeflow Pipeline jobs for each one. The monitor runs continuously in the cluster.

```bash
# From docs/knowledge-base-architecture.md
# Monitor polls every 10 seconds for new KBs
kubectl get deployment ingestion-pipeline-monitor
kubectl get pods -l app=ingestion-pipeline-monitor
```

The monitor detects KBs that exist in the database but not yet in LlamaStack's vector store registry, then launches a Kubeflow Pipeline job named `ingestion-pipeline-{kb_name}`.

### Kubeflow Pipeline Components

The pipeline executes three sequential steps:

1. **S3 Fetch** (`fetch_from_s3`): Downloads documents from MinIO storage bucket
2. **Document Processing** (`process_and_store_pgvector`): Uses Docling for parsing and HybridChunker for intelligent chunking
3. **Vector Registration**: Registers the vector database in LlamaStack and inserts document embeddings

```python
# From docs/knowledge-base-architecture.md
# Vector database creation in LlamaStack
client.vector_stores.register(
    vector_store_id=f"{name}-v{version}",
    embedding_model="all-MiniLM-L6-v2",
    provider_id="pgvector"
)
client.tool_runtime.rag_tool.insert(
    documents=llama_documents,
    vector_store_id=vector_store_name,
    chunk_size_in_tokens=512
)
```

### Async Status Polling

Pipeline status is not stored in the database. It is computed dynamically by querying the ingestion pipeline's `/status` endpoint and cross-referencing DB records with LlamaStack vector stores.

```python
# backend/app/api/v1/knowledge_bases.py
async def get_pipeline_status(pipeline_name: str) -> str:
    status_endpoint = get_ingestion_pipeline_url() + "/status"
    data = {"pipeline_name": pipeline_name}
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(status_endpoint, params=data)
            response.raise_for_status()
            return response.json().get("state", "unknown")
        except Exception as e:
            logger.error(f"could not fetch pipeline status for {pipeline_name}: {str(e)}")
            return "unknown"
```

### Agent Template Auto-Ingestion

Agent templates can include a `knowledge_base_config` that triggers automatic KB creation and ingestion when the template is deployed. The `skip_kb_validation` flag is used because ingestion is asynchronous.

```yaml
# backend/agent_templates/business_banking.yaml
knowledge_base_config:
  name: "Commercial Banking Reference"
  version: "1.0"
  embedding_model: "all-MiniLM-L6-v2"
  provider_id: "pgvector"
  vector_store_name: "commercial_banking_kb"
  is_external: false
  source: "URL"
  source_configuration:
    - "https://www.irs.gov/pub/irs-mssp/combank.pdf"
```

```python
# backend/app/api/v1/agent_templates.py (line 369)
# Skip KB validation if we just created a KB (ingestion is async)
skip_validation = knowledge_base_created and knowledge_base_name is not None
```

## Configuration

- **Environment variables:**
  - `INGESTION_PIPELINE_URL`: URL of the ingestion pipeline service (default: `http://llamastack:8321/ingestion_pipeline/`; set by Helm to `http://<release-name>-ingestion-pipeline`)
- **Helm values:**
  - `configure-pipeline.minio.secret.user/password/host/port`: MinIO credentials for the configure-pipeline companion subchart
  - `configure-pipeline.minio.sampleFileUpload.enabled`: Whether to upload sample documents to MinIO on install
  - `configure-pipeline.minio.sampleFileUpload.bucket`: Target bucket name (e.g., `documents`)
  - `configure-pipeline.minio.sampleFileUpload.urls`: List of URLs to fetch and upload as sample documents
- **Seeded user:** The Alembic migration seeds an `ingestion-pipeline` admin user (`ingestion-pipeline@change.me`) so the pipeline can authenticate against the backend's LlamaStack proxy

## Known Gotchas

- **Fallback URL mismatch:** The `get_ingestion_pipeline_url()` function falls back to `http://llamastack:8321/ingestion_pipeline/` when `INGESTION_PIPELINE_URL` is not set. This works in dev (LlamaStack has a built-in ingestion endpoint) but in cluster deployments the Helm template sets the env var to the dedicated subchart service. Forgetting to set the env var in a non-Helm deployment will silently route requests to LlamaStack instead of the dedicated pipeline.
- **Pipeline deletion is fire-and-forget:** The `delete_knowledge_base` endpoint catches and logs pipeline deletion failures as warnings (`logger.warning(f"failed to delete ingestion pipeline: {str(e)}")`) rather than failing the overall KB deletion. This means a KB can be removed from the database while the pipeline job still exists in the cluster.
- **Status field is not persisted:** The `KnowledgeBase` model has a `status` column but the architecture doc says status is "computed dynamically." In practice, the backend sets `kb.status` from `get_pipeline_status()` before returning responses, but this value is not saved back to the database.
- **Agent template KB validation skip:** When deploying an agent template with `include_knowledge_base=True`, the code sets `skip_kb_validation=True` for the agent creation step because ingestion is async. This means the agent is created and returned to the user before its KB is actually ready.

## Testing Notes

- Unit tests mock `create_ingestion_pipeline`, `delete_ingestion_pipeline`, and `get_pipeline_status` to avoid external dependencies (see `tests/unit/test_knowledge_bases_api.py`)
- To verify the ingestion pipeline is running on-cluster: `kubectl get deployment ingestion-pipeline-monitor` and `kubectl get pods -l app=ingestion-pipeline-monitor`
- To monitor a specific ingestion job: `kubectl logs -f job/ingestion-pipeline-{kb-name}`
- To check status transition from PENDING to READY: poll the `/api/v1/knowledge_bases/{vector_store_name}` endpoint and watch the `status` field

## Related Patterns

- `components/pgvector.md` -- Vector database storage backend for embeddings
- `components/llamastack.md` -- Vector store registration and RAG tool integration
- `deployment/helm-subchart-wiring.md` -- How subcharts are wired together
