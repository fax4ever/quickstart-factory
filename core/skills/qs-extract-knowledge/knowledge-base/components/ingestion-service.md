---
name: ingestion-service
description: Standalone Python document ingestion service using Docling and LlamaStack for multi-source RAG vector DB population
summary: "Standalone Python 3.12 one-shot container that fetches PDFs from GitHub (shallow --depth 1 clone with optional token auth), S3/MinIO (SSL verify disabled), and URLs, processes them with Docling DocumentConverter (requires tesseract-ocr, poppler-utils) and HybridChunker filtering only TEXT/PARAGRAPH DocItemLabel chunks, then inserts embeddings into pgvector via LlamaStack vector_io API using all-MiniLM-L6-v2 (384d, 512-token chunks). Use when you need YAML-driven multi-pipeline batch ingestion at stack startup with per-pipeline enable/disable for each source type (GITHUB, S3, URL) and target vector store -- deployed as restart:\"no\" compose service or Kubernetes Job configured via parent Helm chart ingestion-pipeline values (no subchart). Critical pattern: service waits for LlamaStack via client.models.list() retry loop (30 retries, 5s delay), registers vector DBs with dynamically discovered provider_id from the first vector_io provider, reads pipeline definitions from INGESTION_CONFIG env var pointing to a mounted YAML config, and prints exit summary with success/failed/skipped pipeline counts. Common gotchas: re-runs insert duplicate chunks because vector_dbs.register() silently tolerates \"already exists\" errors without clearing existing data, GitHub tokens are embedded in plain-text HTTPS clone URLs exposing them in process args, PyTorch is CPU-only via --extra-index-url, and only PDF files are supported across all three source types."
metadata:
  type: component
tags:
  tech_stack: [python, docling, llama-stack-client, boto3, pyyaml]
  ai_pattern: [rag, embeddings, data-pipeline, vector-search]
  platform: [openshift, kubernetes, rhoai]
  data_layer: [pgvector]
source_examples:
  - quickstart: "RAG"
    repo: "https://github.com/rh-ai-quickstart/RAG"
    notes: "Standalone one-shot ingestion container using Docling for PDF parsing, LlamaStack client for vector DB registration, with GitHub/S3/URL multi-source pipeline support"
    approach: "A"
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
