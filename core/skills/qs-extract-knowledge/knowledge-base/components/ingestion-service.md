---
name: ingestion-service
description: Standalone Python document ingestion service using Docling and LlamaStack for multi-source RAG vector DB population
summary: "Covers two ingestion patterns: Approach A is a one-shot Python 3.12 container (restart:\"no\" compose or K8s Job) fetching PDFs from GitHub (shallow --depth 1 clone with token auth), S3/MinIO (SSL verify disabled), and URLs, processing via Docling DocumentConverter (tesseract-ocr, poppler-utils) with HybridChunker filtering TEXT/PARAGRAPH DocItemLabel chunks, inserting embeddings into pgvector via LlamaStack vector_io using all-MiniLM-L6-v2 (384d, 512-token chunks); Approach B is a persistent FastAPI service (port 8001, hatchling build in Turborepo monorepo) receiving structured transactions via POST /transactions/, transforming string amounts/fraud flags, forwarding to downstream API via httpx AsyncClient with graceful degradation and dual health endpoints (/healthz liveness, /health readiness reporting \"degraded\"). Use Approach A for YAML-driven batch document ingestion at stack startup configured via INGESTION_CONFIG env var pointing to mounted per-pipeline enable/disable config (no Helm subchart -- parent chart ingestion-pipeline values), and Approach B for real-time structured event ingestion/forwarding without AI/ML dependencies. Critical patterns: A waits for LlamaStack via client.models.list() retry loop (30 retries, 5s delay), registers vector DBs with dynamically discovered provider_id from first vector_io provider, prints exit summary with success/failed/skipped counts; B returns processed transaction even when downstream unreachable, reports \"degraded\" status via /health readiness check. Common gotchas: A re-runs insert duplicate chunks because vector_dbs.register() silently tolerates \"already exists\" without clearing data, GitHub tokens embedded in plain-text clone URLs, CPU-only PyTorch, PDF-only; B has missing common.models module, no Containerfile, datetime module-vs-class import bug in /health, new httpx client created per request, and spending-monitor-db cross-package path dependency."
metadata:
  type: component
tags:
  tech_stack: [python, docling, llama-stack-client, boto3, pyyaml, fastapi, httpx, pydantic, uvicorn]
  ai_pattern: [rag, embeddings, data-pipeline, vector-search]
  platform: [openshift, kubernetes, rhoai]
  data_layer: [pgvector]
source_examples:
  - quickstart: "RAG"
    repo: "https://github.com/rh-ai-quickstart/RAG"
    notes: "Standalone one-shot ingestion container using Docling for PDF parsing, LlamaStack client for vector DB registration, with GitHub/S3/URL multi-source pipeline support"
    approach: "A"
  - quickstart: "spending-transaction-monitor"
    repo: "https://github.com/rh-ai-quickstart/spending-transaction-monitor"
    notes: "Persistent FastAPI service for financial transaction data transformation and forwarding to downstream API via httpx"
    approach: "B"
---

# Ingestion Service

## Overview

The ingestion service is a standalone Python container that runs once at stack startup to fetch documents from multiple sources (GitHub repos, S3/MinIO buckets, direct URLs), process them with Docling for PDF parsing and chunking, and insert the resulting embeddings into vector databases via the LlamaStack API. It is deployed as a one-shot `podman-compose` service (or Kubernetes Job via Helm values) and exits after all configured pipelines complete.

## Tech Stack & Dependencies

- **Runtime:** Python 3.12 (python:3.12-slim base image)
- **Container image:** Built from `ingestion-service/Containerfile`
- **Key dependencies:** llama-stack-client 0.2.22, docling >=2.0.0, docling-core >=2.0.0, boto3, PyYAML, torch (CPU-only via `--extra-index-url https://download.pytorch.org/whl/cpu`), opencv-python-headless
- **System packages:** git, tesseract-ocr, poppler-utils, libgl1, libglib2.0-0 (required for Docling PDF processing)
- **Helm subchart:** None -- configured as a section in the parent chart's `values.yaml` under `ingestion-pipeline:`

## Key Patterns

### YAML-Driven Multi-Pipeline Architecture

The service processes multiple ingestion pipelines from a single YAML configuration file. Each pipeline defines its source type, vector store name, and source-specific configuration. Pipelines can be independently enabled/disabled.

```yaml
# deploy/local/ingestion-config.yaml
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

### Multi-Source Document Fetching

The service dispatches document fetching based on the `source` field in each pipeline configuration. Three source types are supported with dedicated methods.

```python
# ingestion-service/ingest.py (lines 312-319)
if source == 'GITHUB':
    pdf_files = self.fetch_from_github(source_config, temp_dir)
elif source == 'S3':
    pdf_files = self.fetch_from_s3(source_config, temp_dir)
elif source == 'URL':
    pdf_files = self.fetch_from_urls(source_config, temp_dir)
```

GitHub fetching uses a shallow clone (`--depth 1`) with optional token authentication for private repos by inserting the token into the HTTPS URL.

### Docling Document Processing with HybridChunker

Documents are processed with Docling's `DocumentConverter` (configured for PDF with picture image generation) and then chunked using `HybridChunker`. Only text and paragraph chunks are retained -- other content types (images, tables) are filtered out.

```python
# ingestion-service/ingest.py (lines 52-59, 221-225)
pipeline_options = PdfPipelineOptions()
pipeline_options.generate_picture_images = True
self.converter = DocumentConverter(
    format_options={
        InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
    }
)
self.chunker = HybridChunker()

# Chunk filtering -- only TEXT and PARAGRAPH labels are kept
if any(
    c.label in [DocItemLabel.TEXT, DocItemLabel.PARAGRAPH]
    for c in chunk.meta.doc_items
):
```

### LlamaStack Vector DB Registration and Insertion

Vector databases are registered via the LlamaStack client API, then documents are inserted using the RAG tool runtime. The provider ID is discovered dynamically by querying the `vector_io` API provider.

```python
# ingestion-service/ingest.py (lines 246-251, 262-268)
def get_provider_id(self) -> str:
    providers = self.client.providers.list()
    for provider in providers:
        if provider.api == "vector_io":
            return provider.provider_id
    return None

self.client.vector_dbs.register(
    vector_db_id=vector_store_name,
    embedding_model=self.vector_db_config['embedding_model'],
    embedding_dimension=self.vector_db_config['embedding_dimension'],
    provider_id=self.get_provider_id(),
)
```

### Startup Wait Loop for LlamaStack

The service waits for LlamaStack to become available before processing, using a retry loop that calls `client.models.list()` as a health check.

```python
# ingestion-service/ingest.py (lines 61-80)
def wait_for_llamastack(self, max_retries: int = 30, retry_delay: int = 5):
    for attempt in range(max_retries):
        try:
            self.client = LlamaStackClient(base_url=self.llama_stack_url)
            self.client.models.list()
            logger.info("Llama Stack is ready!")
            return True
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
```

### One-Shot Container in Compose

The ingestion service runs as a `restart: "no"` container in podman-compose, executing once at stack startup and exiting. The config file is mounted read-only from the host.

```yaml
# deploy/local/podman-compose.yml
rag-ingestion:
  platform: linux/amd64
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

## Configuration

- **Environment variables:**
  - `INGESTION_CONFIG`: Path to the YAML configuration file inside the container (default: `/config/ingestion-config.yaml`, set in Containerfile)
  - `PYTHONUNBUFFERED=1`: Set in Containerfile for real-time log output
- **Config files:**
  - `deploy/local/ingestion-config.yaml`: Main pipeline configuration defining LlamaStack URL, vector DB settings, and per-pipeline source configs
- **Helm values:**
  - `ingestion-pipeline.enabled`: Enable/disable the ingestion pipeline
  - `ingestion-pipeline.serviceAccount.name`: Service account for pipeline execution (default: `rag-pipeline-notebook`)
  - `ingestion-pipeline.pipelines.<name>.source`: Source type (GITHUB, S3, URL)
  - `ingestion-pipeline.pipelines.<name>.embedding_model`: Embedding model name (default: `all-MiniLM-L6-v2`)
  - `ingestion-pipeline.pipelines.<name>.vector_store_name`: Vector store identifier passed to LlamaStack
- **Vector DB defaults:**
  - `embedding_model: "all-MiniLM-L6-v2"`
  - `embedding_dimension: 384`
  - `chunk_size_in_tokens: 512`

## Known Gotchas

- **Vector DB "already exists" is silently tolerated:** When `vector_dbs.register()` raises an exception containing "already exists", the service logs a message and continues with document insertion. This means re-running the ingestion service will insert duplicate chunks into an existing vector database rather than skipping or clearing it. The code at `ingest.py` lines 273-275 explicitly catches this: `if 'already exists' in error_msg.lower(): logger.info(f"Vector DB '{vector_store_name}' already exists, continuing...")`.
- **Provider ID is dynamically discovered, not configurable:** The `get_provider_id()` method iterates all providers and returns the first one with `api == "vector_io"`. A commented-out line at `ingest.py` line 267 shows `provider_id` was originally intended to be configurable via `self.vector_db_config['provider_id']` but was replaced with the dynamic lookup: `# provider_id=self.vector_db_config['provider_id'] or self.get_provider_id()`.
- **CPU-only PyTorch by default:** The `requirements.txt` explicitly uses `--extra-index-url https://download.pytorch.org/whl/cpu` with a comment: `# Explicitly avoid CUDA dependencies for CPU-only deployment`. This keeps the image smaller but means the service will not use GPU acceleration for any torch-based operations in Docling.
- **S3 SSL verification disabled:** The S3 client in `fetch_from_s3()` sets `verify=False` (line 141) when connecting to the endpoint, which disables SSL certificate verification for MinIO/S3 connections.
- **Only PDF files are supported:** All three source fetchers filter for `.pdf` files only. The README FAQ confirms: "Currently PDF only. Docling supports others but requires code changes."
- **GitHub token inserted into URL in plain text:** Private repo authentication inserts the token directly into the HTTPS URL at `ingest.py` line 97: `auth_url = url.replace('https://', f'https://{token}@')`. The token appears in the process command line.

## Testing Notes

- Verify the service completed successfully by checking container exit code: `podman ps -a | grep rag-ingestion`
- Watch real-time progress: `podman logs -f rag-ingestion`
- The service prints an ingestion summary at exit with counts for successful, failed, and skipped pipelines
- To re-run ingestion: `podman-compose up --build rag-ingestion`
- To start fresh, remove the pgvector volume: `podman volume rm pgvector_data`
- For development without containers, set `INGESTION_CONFIG` to the local config path and run `python ingest.py`

## Related Patterns

- `components/llamastack.md` -- LlamaStack API server that the ingestion service registers vector DBs with
- `components/pgvector.md` -- Vector database backend where embeddings are stored
- `components/minio.md` -- S3-compatible object storage used as a document source
- `components/ingestion-pipeline.md` -- Alternative Kubernetes/Kubeflow-based ingestion approach (from ai-virtual-agent)

---

## Approach B: Transaction Data Ingestion Service (from spending-transaction-monitor)

### When to Use

Use this approach when the ingestion service is a persistent FastAPI web service that receives structured transaction data via HTTP POST, transforms it into an internal format, and forwards it to a downstream API service. This pattern suits real-time event-driven ingestion of structured records (financial transactions, IoT events, log entries) rather than batch document processing.

### Differences from Approach A

- **Persistent service vs one-shot container:** Runs continuously as a FastAPI web server (port 8001) rather than executing once at startup and exiting
- **No AI/ML dependencies:** No Docling, LlamaStack, torch, or vector DB interaction -- purely data transformation and HTTP forwarding
- **Receives data via API:** Accepts incoming transaction data on `POST /transactions/` instead of fetching documents from external sources
- **Forwards to downstream API:** Uses httpx async client to POST transformed data to a separate API service instead of inserting into a vector database
- **No Containerfile:** Unlike Approach A, this component has no Containerfile in the repo; other packages (api, db, ui) do have them
- **Monorepo package:** Lives in a Turborepo monorepo under `packages/ingestion-service/` with its own `pyproject.toml` and `uv.lock`, using hatchling build system

### Tech Stack & Dependencies

- **Runtime:** Python 3.12 (hatchling build system)
- **Container image:** None -- no Containerfile present in the component directory
- **Key dependencies:** fastapi >=0.104.0, uvicorn[standard] >=0.24.0, pydantic >=2.5.0, pydantic-settings >=2.1.0, httpx >=0.25.0, certifi >=2023.0.0
- **Cross-package dependency:** References `spending-monitor-db` as a local editable path dependency via `[tool.uv.sources]`
- **Helm subchart:** None -- no Helm chart or values found for this component

### Key Patterns

#### Transaction Data Transformation Pipeline

The service implements a two-stage transformation: raw incoming data (with string amounts like `"$150.00"` and `"Yes"/"No"` fraud flags) is first converted to an internal `Transaction` model, then reshaped into an API-compatible format with UUID generation.

```python
# packages/ingestion-service/src/main.py (lines 58-83)
def transform_transaction(incoming_transaction: IncomingTransaction) -> Transaction:
    """Transform incoming transaction to internal format"""
    amount = float(incoming_transaction.Amount.replace('$', ''))
    is_fraud = incoming_transaction.is_fraud == 'Yes'

    # split time string into hours and minutes
    time_parts = incoming_transaction.Time.split(':')
    hour, minute = int(time_parts[0]), int(time_parts[1])

    return Transaction(
        user=incoming_transaction.User,
        card=incoming_transaction.Card,
        # ... field mappings
        is_fraud=is_fraud,
    )
```

#### Async HTTP Forwarding with httpx

The `APIClient` class forwards transformed transactions to a downstream API service using httpx. The API host and port are configured via environment variables.

```python
# packages/ingestion-service/src/main.py (lines 16-37)
class APIClient:
    def __init__(self):
        self.api_host = os.environ.get('API_HOST', 'localhost')
        self.api_port = os.environ.get('API_PORT', '8000')
        self.api_base_url = f'http://{self.api_host}:{self.api_port}'
        self.timeout = 30.0

    async def post_transaction(self, transaction_data: dict) -> bool:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f'{self.api_base_url}/transactions', json=transaction_data
                )
                response.raise_for_status()
                return True
        except Exception as e:
            print(f'Failed to post transaction to API: {e}')
            return False
```

#### Graceful Degradation on Downstream Failure

The transaction endpoint returns the processed transaction even when the downstream API is unreachable, treating the forwarding as best-effort rather than a hard dependency.

```python
# packages/ingestion-service/src/main.py (lines 125-139)
@app.post('/transactions/')
async def create_transaction(incoming_transaction: IncomingTransaction):
    transaction = transform_transaction(incoming_transaction)
    api_transaction_data = transform_to_api_format(transaction)
    api_success = await api_client.post_transaction(api_transaction_data)

    if not api_success:
        print('Warning: Transaction processed but not sent to API service')
        # Still return the transaction even if API posting fails

    return transaction
```

#### Dual Health Check Endpoints

The service exposes two health endpoints: `/healthz` for simple liveness checks, and `/health` for readiness checks that include downstream API connectivity status, reporting `"degraded"` when the API is unreachable.

```python
# packages/ingestion-service/src/main.py (lines 142-164)
@app.get('/healthz')
async def healthz():
    return {'status': 'ok'}

@app.get('/health')
async def health():
    api_health = await api_client.health_check()
    overall_status = 'healthy' if api_health['api_status'] == 'healthy' else 'degraded'
    return {
        'status': overall_status,
        'service': 'ingestion-service',
        # ...
    }
```

### Configuration

- **Environment variables:**
  - `API_HOST`: Hostname of downstream API service (default: `localhost`)
  - `API_PORT`: Port of downstream API service (default: `8000`)
- **Config files:**
  - `packages/ingestion-service/pyproject.toml`: Package metadata, dependencies, and tooling config (ruff, mypy, pytest)
- **Helm values:** None -- no ingestion-service section in `deploy/helm/spending-monitor/values.yaml`

### Known Gotchas

- **Missing `common.models` module:** The main entry point imports `from .common.models import IncomingTransaction, Transaction` (line 13 of `src/main.py`) but no `common/` directory exists under `packages/ingestion-service/src/`. The source tree contains only `src/main.py`. This suggests the models are expected to be created or linked before the service can run.
- **No Containerfile for this service:** Unlike the `api`, `db`, and `ui` packages which each have a `Containerfile`, the `ingestion-service` package has none, indicating it may not yet be containerized or is run directly in development.
- **Bug in `/health` endpoint:** Line 157 calls `datetime.now(UTC)` but the file imports `import datetime` (the module, not the class). The correct call would be `datetime.datetime.now(datetime.timezone.utc)`. Additionally, `UTC` is never imported or defined. Other uses in the same file correctly use `datetime.time(...)` and `datetime.datetime.combine(...)` with the module prefix.
- **New httpx client created per request:** The `post_transaction` method (line 28) creates a new `httpx.AsyncClient` context manager for every transaction POST rather than reusing a persistent client instance, as seen in the `async with httpx.AsyncClient(...)` pattern inside the method body.
- **Cross-package path dependency:** `pyproject.toml` references `spending-monitor-db` as a local editable dependency via `[tool.uv.sources]` with `path = "../db"`, coupling this package to the monorepo layout.

### Testing Notes

- The service runs on port 8001 according to `docs/DEVELOPER_GUIDE.md`
- Test configuration in `pyproject.toml` excludes integration and e2e tests by default: `addopts = "-v --tb=short --ignore=tests/integration --ignore=tests/e2e"`
- Dev dependencies include pytest, pytest-asyncio, httpx (for test client), ruff, and mypy

### Related Patterns

- `components/fastapi-backend.md` -- The downstream API service that receives forwarded transactions

---

## Choosing Between Approaches

| Criteria | Approach A (RAG Document Ingestion) | Approach B (Transaction Data Ingestion) |
|----------|--------------------------------------|------------------------------------------|
| **Lifecycle** | One-shot container (runs once, exits) | Persistent web service (runs continuously) |
| **Data type** | Unstructured documents (PDFs) | Structured records (financial transactions) |
| **Data flow** | Pulls from sources (GitHub, S3, URLs) | Receives via HTTP POST, forwards downstream |
| **AI/ML** | Docling parsing, vector embeddings, LlamaStack | None -- pure data transformation |
| **Output target** | pgvector via LlamaStack vector_io API | Downstream FastAPI service via httpx |
| **Deployment** | Compose service with `restart: "no"` or K8s Job | Standard web service deployment |
| **Use case** | Batch document ingestion for RAG pipelines | Real-time event ingestion and forwarding |
