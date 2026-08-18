---
name: ingestion-pipeline
description: Kubernetes-based document ingestion pipeline using Kubeflow, Docling, and LlamaStack for RAG knowledge bases
summary: "Automates document processing and vector database population for RAG knowledge bases on Kubernetes via two approaches: (A) Kubeflow-orchestrated monitor pod polling PostgreSQL for unregistered KBs, triggered by FastAPI backend httpx AsyncClient to INGESTION_PIPELINE_URL /add /delete /status endpoints with KnowledgeBaseCreate.pipeline_model_dict() handling URL vs S3 payloads, deployed as Helm subcharts ingestion-pipeline v0.6.5 + configure-pipeline v0.5.6; (B) config-driven one-shot Python script reading YAML pipeline definitions with GitHub (shallow clone + token auth)/S3/URL multi-source fetch, dynamic vector_io provider discovery, idempotent vector DB registration, and Docling label filtering (TEXT/PARAGRAPH only), deployed via podman-compose or Helm subchart v0.7.5. Choose Approach A for multi-tenant apps needing runtime KB creation via API and agent template auto-ingestion (skip_kb_validation for async processing) -- choose Approach B for fixed-set KBs populated at deploy time with lower complexity (no Kubeflow, no monitor pod, single script with run-once exit semantics); both use Docling+HybridChunker parsing, all-MiniLM-L6-v2 embeddings at chunk_size_in_tokens=512, and LlamaStack pgvector registration with vector_store_id=\"{name}-v{version}\". Approach A discovers pipeline via http://{Release.Name}-ingestion-pipeline with a seeded admin user (ingestion-pipeline@change.me) for auth; Approach B polls LlamaStack readiness (30x5s retries via client.models.list()); Approach B currently processes PDFs only (other formats silently ignored). Fallback URL silently routes to LlamaStack's built-in endpoint when INGESTION_PIPELINE_URL is unset; Approach A deletion is fire-and-forget leaving orphaned jobs, status is dynamically computed but never persisted, and agent template auto-ingestion creates agents before KBs are ready; Approach B has config structure divergence between local YAML (config key) and Helm values (source type key), disables S3 SSL verification, exposes GitHub tokens in clone URLs, and exits with code 1 if any pipeline fails even when others succeeded."
metadata:
  type: component
tags:
  tech_stack: [kubeflow, docling, python, fastapi, httpx, llama-stack-client, boto3, pyyaml]
  ai_pattern: [rag, embeddings, data-pipeline, vector-search]
  platform: [rhoai, openshift, kubernetes, kserve]
  data_layer: [pgvector, minio]
source_examples:
  - quickstart: "ai-virtual-agent"
    repo: "https://github.com/rh-ai-quickstart/ai-virtual-agent"
    notes: "Helm subchart-based ingestion pipeline with monitor pod, Kubeflow orchestration, and Docling document processing for multi-source KB creation"
    approach: "A"
  - quickstart: "RAG"
    repo: "https://github.com/rh-ai-quickstart/RAG"
    notes: "Standalone config-driven Python ingestion service with Docling, multi-source fetch (GitHub/S3/URL), run as one-shot container at stack startup via podman-compose and Helm subchart"
    approach: "B"
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

---

## Approach B: Config-Driven One-Shot Ingestion Service (from RAG)

### When to Use

Use this approach when you need a self-contained, config-driven ingestion service that runs once at stack startup (or on demand) without requiring Kubeflow, a monitor pod, or a FastAPI backend to orchestrate it. Suited for local development with podman-compose and for simpler Helm deployments where the ingestion pipeline is a Kubernetes Job rather than a long-running service.

### Differences from Approach A

- **No Kubeflow:** Runs as a single Python script (`ingest.py`) with no pipeline orchestration framework
- **No monitor pod:** Does not poll for unregistered KBs; instead runs once at startup and exits
- **No HTTP API:** Not triggered by a backend; reads pipeline definitions from a YAML config file
- **Multi-source fetch in-process:** GitHub clone, S3/MinIO download, and URL fetch all happen inside the same script
- **Dual deployment:** Local via podman-compose (build from Containerfile) and cluster via Helm subchart (`ingestion-pipeline` v0.7.5 from ai-architecture-charts)
- **Run-once semantics:** Container uses `restart: "no"` in podman-compose; exits with code 0 on success or 1 on failure

### Tech Stack & Dependencies

- **Runtime:** Python 3.12 (python:3.12-slim base image)
- **Container image:** Built from `ingestion-service/Containerfile`
- **Key dependencies:** `llama-stack-client==0.2.22`, `docling>=2.0.0`, `docling-core>=2.0.0`, `boto3>=1.34.0`, `pyyaml>=6.0`
- **System dependencies:** `tesseract-ocr`, `poppler-utils`, `libgl1`, `libglib2.0-0` (for Docling PDF processing)
- **Helm subchart:** `ingestion-pipeline` v0.7.5 from `https://rh-ai-quickstart.github.io/ai-architecture-charts`
- **CPU-only PyTorch:** Uses `--extra-index-url https://download.pytorch.org/whl/cpu` and `opencv-python-headless` to avoid GPU/GUI dependencies

### Key Patterns

#### YAML-Driven Pipeline Configuration

All pipelines are defined in a single YAML config file (`ingestion-config.yaml`). Each pipeline specifies a source type, vector store name, and source-specific config. Pipelines can be individually enabled/disabled.

```yaml
# deploy/local/ingestion-config.yaml
llamastack:
  base_url: "http://llamastack:8321"

vector_db:
  embedding_model: "all-MiniLM-L6-v2"
  embedding_dimension: 384
  chunk_size_in_tokens: 512

pipelines:
  hr-pipeline:
    enabled: true
    name: "hr-vector-db"
    version: "1.0"
    vector_store_name: "hr-vector-db-v1-0"
    source: GITHUB
    config:
      url: "https://github.com/rh-ai-quickstart/RAG.git"
      path: "notebooks/hr"
      branch: "main"
```

#### Multi-Source Document Fetching

The ingestion service supports three source types handled by dedicated methods. GitHub sources use shallow clones (`--depth 1`), S3 sources use boto3 with pagination, and URL sources use direct HTTP downloads.

```python
# ingestion-service/ingest.py
if source == 'GITHUB':
    pdf_files = self.fetch_from_github(source_config, temp_dir)
elif source == 'S3':
    pdf_files = self.fetch_from_s3(source_config, temp_dir)
elif source == 'URL':
    pdf_files = self.fetch_from_urls(source_config, temp_dir)
```

#### GitHub Private Repo Authentication

For private repos, a GitHub token is inserted into the clone URL at runtime. The token is passed via the YAML config, not an environment variable.

```python
# ingestion-service/ingest.py
if token:
    auth_url = url.replace('https://', f'https://{token}@')
    cmd = ['git', 'clone', '--depth', '1', '--branch', branch, auth_url, clone_dir]
```

#### Docling Document Processing with Label Filtering

Documents are processed through Docling's `DocumentConverter` with PDF pipeline options, then chunked with `HybridChunker`. Only chunks with `TEXT` or `PARAGRAPH` labels are retained -- other labels (tables, figures, etc.) are filtered out.

```python
# ingestion-service/ingest.py
docling_doc = self.converter.convert(source=file_path).document
chunks = self.chunker.chunk(docling_doc)
for chunk in chunks:
    if any(
        c.label in [DocItemLabel.TEXT, DocItemLabel.PARAGRAPH]
        for c in chunk.meta.doc_items
    ):
        llama_documents.append(
            LlamaStackDocument(
                document_id=f"doc-{doc_id}",
                content=chunk.text,
                mime_type="text/plain",
                metadata={"source": os.path.basename(file_path)},
            )
        )
```

#### Dynamic Vector IO Provider Discovery

Instead of hardcoding the provider ID, the service queries LlamaStack's provider registry to find the `vector_io` provider at runtime. A commented-out line shows this was previously configurable via config.

```python
# ingestion-service/ingest.py
def get_provider_id(self) -> str:
    providers = self.client.providers.list()
    for provider in providers:
        if provider.api == "vector_io":
            return provider.provider_id
    return None

# Usage: provider_id is discovered, not configured
self.client.vector_dbs.register(
    vector_db_id=vector_store_name,
    embedding_model=self.vector_db_config['embedding_model'],
    embedding_dimension=self.vector_db_config['embedding_dimension'],
    provider_id=self.get_provider_id(),
)
```

#### LlamaStack Readiness Wait Loop

The service polls LlamaStack at startup, retrying up to 30 times with 5-second delays (2.5 minutes total). It uses `client.models.list()` as a health check since LlamaStack does not expose a dedicated readiness endpoint for the ingestion flow.

```python
# ingestion-service/ingest.py
def wait_for_llamastack(self, max_retries: int = 30, retry_delay: int = 5):
    for attempt in range(max_retries):
        try:
            self.client = LlamaStackClient(base_url=self.llama_stack_url)
            self.client.models.list()
            return True
        except Exception as e:
            time.sleep(retry_delay)
```

#### Idempotent Vector DB Registration

The service catches "already exists" errors during `vector_dbs.register()` and continues with document insertion. This makes re-running ingestion safe without needing to clean up first.

```python
# ingestion-service/ingest.py
try:
    self.client.vector_dbs.register(...)
except Exception as e:
    if 'already exists' in str(e).lower():
        logger.info(f"Vector DB '{vector_store_name}' already exists, continuing...")
    else:
        return False
```

#### Helm Subchart Values for Cluster Deployment

On OpenShift/Kubernetes, the ingestion pipeline is deployed via the `ingestion-pipeline` Helm subchart. Pipeline definitions are passed through `values.yaml` with a slightly different structure than the local config (source type as a nested key rather than a `config` dict).

```yaml
# deploy/helm/rag/values.yaml
ingestion-pipeline:
  enabled: true
  serviceAccount:
    create: true
    name: rag-pipeline-notebook
  pipelines:
    hr-pipeline:
      enabled: true
      source: GITHUB
      embedding_model: "all-MiniLM-L6-v2"
      name: "hr-vector-db"
      version: "1.0"
      vector_store_name: "hr-vector-db-v1-0"
      GITHUB:
        url: https://github.com/rh-ai-quickstart/RAG.git
        path: notebooks/hr
        token: auth_token
        branch: main
```

#### Podman-Compose One-Shot Container

For local development, the service is built from source and runs as a one-shot container that exits after processing all pipelines. It depends on LlamaStack being started first.

```yaml
# deploy/local/podman-compose.yml
rag-ingestion:
  build:
    context: ../../ingestion-service
    dockerfile: Containerfile
  depends_on:
    llamastack:
      condition: service_started
  environment:
    INGESTION_CONFIG: "/config/ingestion-config.yaml"
  volumes:
    - ./ingestion-config.yaml:/config/ingestion-config.yaml:ro
  restart: "no"
```

### Configuration

- **Environment variables:**
  - `INGESTION_CONFIG`: Path to the YAML config file inside the container (default: `/config/ingestion-config.yaml`)
  - `PYTHONUNBUFFERED=1`: Ensures real-time log output
- **Config file keys:**
  - `llamastack.base_url`: URL of the LlamaStack service (e.g., `http://llamastack:8321`)
  - `vector_db.embedding_model`: Embedding model name (e.g., `all-MiniLM-L6-v2`)
  - `vector_db.embedding_dimension`: Embedding vector dimension (e.g., `384`)
  - `vector_db.chunk_size_in_tokens`: Chunk size for document splitting (e.g., `512`)
  - `pipelines.<name>.enabled`: Enable/disable individual pipelines
  - `pipelines.<name>.source`: Source type (`GITHUB`, `S3`, `URL`)
  - `pipelines.<name>.vector_store_name`: ID for the vector store in LlamaStack
- **Helm values:**
  - `ingestion-pipeline.enabled`: Enable the subchart
  - `ingestion-pipeline.serviceAccount.name`: ServiceAccount for the pipeline Job (e.g., `rag-pipeline-notebook`)
  - `ingestion-pipeline.pipelines.<name>.*`: Pipeline definitions mirroring the local YAML config

### Known Gotchas

- **PDF-only processing:** The `fetch_from_*` methods only collect files ending in `.pdf`. The README states "Currently PDF only. Docling supports others but requires code changes." Other formats are silently ignored.
- **Config structure divergence between local and Helm:** The local `ingestion-config.yaml` nests source config under a `config` key, while the Helm `values.yaml` nests it under the source type name (e.g., `GITHUB:`). The subchart handles the translation, but copying local config to Helm values verbatim will fail.
- **S3 SSL verification disabled:** The `fetch_from_s3` method sets `verify=False` when creating the boto3 client, which disables SSL certificate verification for MinIO/S3 connections.
- **No parallel pipeline execution:** Pipelines are processed sequentially in a for-loop. Large deployments with many pipelines will have cumulative startup latency.
- **Token in clone URL:** GitHub tokens are embedded directly in the git clone URL (`https://{token}@github.com/...`), which may appear in container logs or process listings.
- **Exit code behavior:** The service calls `sys.exit(1)` if any pipeline fails, even if others succeeded. This can cause the container to show as failed in podman/kubectl even if most pipelines completed successfully.

### Testing Notes

- Re-run ingestion locally with `podman-compose up --build rag-ingestion` or `make ingest` from `deploy/local/`
- Check ingestion logs: `podman logs rag-ingestion`
- Verify vector DBs were created: use `client-examples-python/rag-list-vector-db.py` with `LLAMA_STACK_SERVER=http://localhost:8321`
- To start fresh, remove pgvector data: `podman volume rm pgvector_data` then re-run

---

## Choosing Between Approaches

| Criteria | Approach A (ai-virtual-agent) | Approach B (RAG) |
|----------|-------------------------------|-------------------|
| **Orchestration** | Kubeflow Pipelines with multi-step DAG | Single Python script, no orchestration framework |
| **Lifecycle** | Long-running monitor pod that polls for new KBs | One-shot container that runs at startup and exits |
| **Trigger mechanism** | HTTP API called by FastAPI backend | Config file read at container startup |
| **Runtime KB creation** | Yes -- users create KBs via API at any time | No -- pipelines defined at deploy time only |
| **Local dev** | Not designed for local dev | Podman-compose with build-from-source |
| **Cluster deployment** | Helm subchart with monitor Deployment | Helm subchart as Job |
| **Dependencies** | Kubeflow, FastAPI backend, monitor pod | Only LlamaStack and source endpoints |
| **Complexity** | Higher -- monitor pod, HTTP API, async status | Lower -- single script, YAML config, exit codes |
| **Best for** | Multi-tenant apps where KBs are created dynamically | Fixed-set KBs populated at deploy time |
