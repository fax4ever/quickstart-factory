---
name: notebooks
description: "Jupyter notebooks for data ingestion, model download-to-S3, and Llama Stack testing in RHOAI workbenches"
summary: "Jupyter notebooks in RHOAI workbenches handle AI quickstart data preparation, validation, and interactive demos via three approaches: Approach A (data-governance-co-pilot) runs manually for CSV-to-PostgreSQL star-schema ingestion with SQL governance artifacts (COMMENT ON for certified/deprecated views), HuggingFace model download via snapshot_download with boto3 S3 upload using AWS_* workbench env vars, and Llama Stack 0.3.5 MCP/agent testing via client.alpha.agents; Approach B (RAG) automates repeatable PDF ingestion through KFP pipelines using docling DocumentConverter + HybridChunker (TEXT/PARAGRAPH filtering), storing into pgvector via Llama Stack vector_dbs.register with all-MiniLM-L6-v2 (384 dims) and rag_tool.insert, backed by ingestion-pipeline Helm subchart v0.7.5 and DSPA; Approach C (lls-observability) provides interactive demos for RAG with Milvus, full LlamaStack evaluation (subset_of, llm_as_judge with ABCDE grading, HuggingFace dataset benchmarks, regex_parser multiple choice), and LangGraph StateGraph agents via ChatOpenAI on LlamaStack's OpenAI-compatible endpoint (/v1/openai/v1) with MCP tools bound via bind_tools. Use Approach A for one-time data prep, model staging to MinIO, and Llama Stack validation in workbenches (no Helm); Approach B when repeatable production RAG document ingestion is needed with DSPA + MinIO + pgvector infrastructure -- notebooks/ directory serves dual purpose holding .ipynb files and source PDF subdirectories; Approach C for guided capability exploration including evaluation framework and agentic integration with Milvus vector search, requiring openai_api_key=\"fake\" and use_responses_api=True on ChatOpenAI. Critical: Llama Stack requires SSE transport (/sse not /mcp) for MCP, Agents API for tool calling (chat.completions lacks tool_groups), model IDs with provider prefix vllm-inference/<model-name>, dynamically extracted provider_id (mcp-tools not model-context-protocol), Approach B compiles KFP pipelines to YAML submitted to ds-pipeline-dspa:8888 with env vars captured at compilation time not pod runtime, and Approach C uses conditional sampling (greedy at temp 0.0, else top_p) with timeout=600.0 for evaluation operations. Gotchas: MCP service names require -service suffix (pg-airman-mcp-service), data ingestion uses hardcoded localhost:5432 requiring port-forwarding, gated models need notebook_login(), workbench PVC must hold 14-16 GB per model, Approach B has vector_db_id mismatch between register (\"rag-db\") and insert (\"test\") with hardcoded pgvector credentials (postgres/rag_password) and SSL verification disabled, Approach C has model alias inconsistency across notebooks (llama32 vs llama3-2-3b) and self-judging limitation using same model as evaluator and judge, and vector table naming follows vector_store_<db_id>_v<version> convention."
metadata:
  type: component
tags:
  tech_stack: [jupyter, python, pandas, psycopg2, boto3, huggingface-hub, llama-stack-client, kfp, docling, docling-core, langgraph, langchain-openai, langchain-core]
  ai_pattern: [data-pipeline, model-serving, agents, rag, embeddings, evaluation, vector-search]
  platform: [rhoai, openshift, vllm, kserve]
  data_layer: [postgresql, minio, pgvector, milvus]
source_examples:
  - quickstart: "data-governance-co-pilot"
    repo: "https://github.com/rh-ai-quickstart/data-governance-co-pilot"
    notes: "Data ingestion, model prep, and Llama Stack integration test notebooks run from RHOAI workbenches"
    approach: "A"
  - quickstart: "RAG"
    repo: "https://github.com/rh-ai-quickstart/RAG"
    notes: "Kubeflow Pipeline notebook for PDF ingestion via docling into pgvector, plus pgvector verification notebook"
    approach: "B"
  - quickstart: "lls-observability"
    repo: "https://github.com/rh-ai-quickstart/lls-observability"
    notes: "Interactive demo notebooks for RAG with Milvus, LlamaStack evaluation framework, and LangGraph agent integration via OpenAI-compatible endpoint"
    approach: "C"
---

# Notebooks

## Overview

Jupyter notebooks running inside RHOAI workbenches that handle pre-deployment data preparation and post-deployment integration testing. In the data-governance-co-pilot quickstart, notebooks cover three distinct concerns: loading CSV datasets into PostgreSQL with a star-schema design, downloading HuggingFace models and uploading them to in-cluster S3 (MinIO), and verifying a Llama Stack deployment including MCP tool registration and agent orchestration.

## Tech Stack & Dependencies

- **Runtime:** Python (RHOAI workbench image, path `/opt/app-root/src/`)
- **Container image:** Standard RHOAI workbench image (no custom Dockerfile)
- **Key dependencies:**
  - `pandas`, `psycopg2` -- data ingestion into PostgreSQL
  - `boto3`, `botocore` -- S3 upload of model artifacts
  - `huggingface_hub` (`snapshot_download`, `notebook_login`) -- model download
  - `torch`, `sentence_transformers`, `transformers` -- imported in model prep notebooks
  - `llama-stack-client==0.3.5` -- Llama Stack integration testing
- **Helm subchart:** None (notebooks are run manually, not deployed as a service)

## Key Patterns

### Data Ingestion via psycopg2 execute_batch

The `check_in_data.ipynb` notebook loads CSV files from a local `dataset/` directory into PostgreSQL using pandas DataFrames converted to tuples, then bulk-inserted with `psycopg2.extras.execute_batch`. Each table has its own populate function following the same pattern.

```python
def _populate_dim_customer(conn, df):
    df_copy = df.copy()
    cols_list = ["customer_id", "customer_unique_id",
                 "customer_city", "customer_state"]
    df_copy = df_copy[cols_list].dropna()
    tuples = [tuple(x) for x in df_copy.to_numpy()]
    cols = ",".join(cols_list)
    placeholders = ",".join(["%s"] * len(cols_list))
    query = f"INSERT INTO {table} ({cols}) VALUES ({placeholders})"
    cursor = conn.cursor()
    execute_batch(cursor, query, tuples)
    conn.commit()
```

Tables follow a star-schema layout: `dim_customer`, `fact_orders`, `fact_order_payments` with foreign keys and CHECK constraints.

### Database Governance Artifacts (Views, Comments, Deprecation)

The data ingestion notebook embeds SQL DDL as string literals that create views with governance metadata. This is central to the quickstart's purpose -- providing a realistic database environment with certified vs. deprecated objects for the AI copilot to reason about.

```sql
COMMENT ON TABLE dim_customer IS
  'Core customer table. CONTAINS PII (PCI, address).
   DO NOT USE FOR general BI. Only for auth_service.';

COMMENT ON VIEW v_cust_ltv_agg_DEPRECATED IS
  'DEPRECATED as of Q3 2024. Inaccurate.
   Use v_rpt_customer_ltv_certified.';

COMMENT ON VIEW v_rpt_customer_ltv_certified IS
  '[CERTIFIED] Gold-standard, PII-scrubbed view
   for all customer LTV reporting.
   Maintained by: Finance BI Team';
```

### HuggingFace Model Download + S3 Upload

Three notebooks (`download_gritlm.ipynb`, `download_llama_3_1.ipynb`, `download_nemotron.ipynb`) follow an identical pattern: download a model from HuggingFace Hub using `snapshot_download`, then upload the entire model directory to an S3-compatible bucket (MinIO) using boto3. S3 credentials come from RHOAI workbench environment variables.

```python
from huggingface_hub import snapshot_download

models_dir = Path.cwd() / "models"
models_dir.mkdir(parents=True, exist_ok=True)
model_prefix = "meta-llama"
model_name = "Llama-3.1-8B-Instruct"
full_model_name = f"{model_prefix}/{model_name}"
save_path = models_dir / model_prefix

snapshot_download(repo_id=full_model_name, local_dir=save_path)
```

S3 upload reads credentials from environment variables set in the RHOAI workbench data connection:

```python
aws_access_key_id = os.environ.get('AWS_ACCESS_KEY_ID')
aws_secret_access_key = os.environ.get('AWS_SECRET_ACCESS_KEY')
endpoint_url = os.environ.get('AWS_S3_ENDPOINT')
region_name = os.environ.get('AWS_DEFAULT_REGION')
bucket_name = os.environ.get('AWS_S3_BUCKET')

session = boto3.session.Session(
    aws_access_key_id=aws_access_key_id,
    aws_secret_access_key=aws_secret_access_key
)
s3_resource = session.resource(
    's3',
    config=botocore.client.Config(signature_version='s3v4'),
    endpoint_url=endpoint_url,
    region_name=region_name
)
```

### Llama Stack Integration Testing

The `test_llama_stack.ipynb` notebook validates the full Llama Stack deployment: client connection, model listing, provider inspection, basic inference, MCP toolgroup registration, agent-based tool calling, and streaming responses. It uses `llama-stack-client==0.3.5`.

```python
from llama_stack_client import LlamaStackClient

client = LlamaStackClient(base_url=LLAMA_STACK_URL)

# Register MCP tools as a toolgroup (required before use)
client.toolgroups.register(
    toolgroup_id="mcp::pg_airman",
    provider_id=provider_id,
    mcp_endpoint={"uri": mcp_uri}
)

# Create agent with toolgroup access
agent_response = agents_api.create(
    agent_config={
        "model": model_to_use,
        "instructions": "You are a helpful database assistant.",
        "toolgroups": ["mcp::pg_airman"],
        "tool_choice": "auto",
    }
)
```

## Configuration

- **Environment variables:**
  - `AWS_ACCESS_KEY_ID` -- S3/MinIO access key (set via RHOAI workbench data connection)
  - `AWS_SECRET_ACCESS_KEY` -- S3/MinIO secret key
  - `AWS_S3_ENDPOINT` -- S3/MinIO endpoint URL
  - `AWS_DEFAULT_REGION` -- S3 region
  - `AWS_S3_BUCKET` -- target bucket for model uploads
- **Config files:** None (all config is inline in notebook cells)
- **Helm values:** Not applicable (notebooks run in RHOAI workbench, not deployed via Helm)

## Known Gotchas

- **Llama Stack model IDs require provider prefix:** The test notebook documents that the correct model identifier is `vllm-inference/redhataillama-31-8b-instruct` (with provider prefix), not just `redhataillama-31-8b-instruct`. The notebook discovers this by calling `client.models.list()` and using `models[0].identifier`.
- **MCP toolgroups must be registered before use:** Llama Stack 0.3.5 requires calling `client.toolgroups.register()` with the correct `provider_id` from config (e.g., `mcp-tools`), not a generic type like `model-context-protocol`. The notebook dynamically extracts `provider_id` from the provider list.
- **Agents API required for MCP tool calling:** `chat.completions.create()` does not support a `tool_groups` parameter. MCP tools must be used through the Agents API (`client.agents.create` / `agents.turn.create`), which the notebook accesses via `client.alpha.agents` in v0.3.5.
- **Llama Stack 0.3.5 requires SSE transport for MCP:** The notebook documents that Streamable HTTP (`/mcp` endpoint) is not yet supported; the MCP server must be configured with SSE transport (`/sse` endpoint) when `PROVIDER_MODE=llama_stack`.
- **MCP service name includes `-service` suffix:** The correct Kubernetes service name is `pg-airman-mcp-service`, not `pg-airman-mcp`. The notebook accesses it at `http://pg-airman-mcp-service.{namespace}.svc.cluster.local:8000/sse`.
- **Database connection uses hardcoded localhost credentials:** The `check_in_data.ipynb` notebook connects to PostgreSQL at `localhost:5432` with `admin/password`, relying on port-forwarding or a local dev setup rather than in-cluster service discovery.
- **Gated models require HuggingFace login:** The Llama 3.1 and Nemotron download notebooks call `notebook_login()` for HuggingFace authentication. The GritLM notebook has this commented out since that model is not gated.

## Testing Notes

- Run the data ingestion notebook (`check_in_data.ipynb`) first to populate the database before testing the copilot application
- Model download notebooks must be run inside an RHOAI workbench with a data connection configured (provides the `AWS_*` environment variables)
- The Llama Stack test notebook (`test_llama_stack.ipynb`) requires the full stack to be deployed first (`make install PROVIDER_MODE=llama_stack`) and the `NAMESPACE` variable must be updated to match the deployment namespace
- Model download notebooks each download 14-16 GB of model weights; ensure the workbench PVC has sufficient storage

## Related Patterns

- See `llamastack.md` for the Llama Stack server-side deployment patterns
- See `pgvector.md` or `postgresql` patterns for database component details
- See `mcp-servers.md` for the MCP server (pg-airman-mcp) that the test notebook connects to
- See `minio.md` for S3-compatible storage used as the model upload target

---

## Approach B: Kubeflow Pipeline PDF Ingestion + pgvector Verification (from RAG)

### When to Use

Use this approach when the quickstart requires automated, repeatable document ingestion from S3/MinIO into a vector database via Kubeflow Pipelines (KFP), rather than manual one-time data loading. This is the pattern for RAG-style applications where PDFs are chunked, embedded, and stored in pgvector through a pipeline orchestrated by OpenShift AI Data Science Pipelines.

### Differences from Approach A

- **Execution model:** Compiled KFP pipeline (automated, repeatable) vs manual notebook execution in an RHOAI workbench
- **Data source:** PDF documents fetched from MinIO/S3 buckets vs local CSV files
- **Processing:** docling-based PDF parsing and hybrid chunking vs pandas DataFrame loading
- **Storage target:** pgvector via Llama Stack client (`vector_dbs.register` + `tool_runtime.rag_tool.insert`) vs direct PostgreSQL inserts with psycopg2
- **Deployment:** Backed by a Helm subchart (`ingestion-pipeline` v0.7.5) and a `DataSciencePipelinesApplication` (DSPA) vs no Helm integration
- **Directory dual purpose:** The `notebooks/` directory contains both the `.ipynb` files and subdirectories of source PDF documents (hr, legal, sales, procurement, techsupport) used by the ingestion pipelines

### Tech Stack & Dependencies

- **Runtime:** Python 3.12 (KFP component base image)
- **Container image:** `python:3.12` (specified in `@component` decorator)
- **Key dependencies:**
  - `kfp` -- Kubeflow Pipelines SDK for pipeline definition, compilation, and submission
  - `docling`, `docling-core` -- PDF document conversion and hybrid chunking
  - `llama-stack-client==0.2.22` -- vector DB registration and document insertion
  - `boto3` -- MinIO/S3 file retrieval
  - `psycopg2`, `pandas`, `tabulate` -- pgvector verification notebook
- **Helm subchart:** `ingestion-pipeline` v0.7.5 from `ai-architecture-charts`

### Key Patterns

#### KFP Pipeline-as-Notebook for PDF Ingestion

The `data-ingestion-pipeline.ipynb` notebook defines a single KFP component that performs the entire ingestion in one step: fetch PDFs from MinIO, chunk with docling, store in pgvector via Llama Stack. The pipeline is compiled to YAML and submitted to the KFP server.

```python
@component(
    base_image="python:3.12",
    packages_to_install=[
        "boto3",
        "llama-stack-client==0.2.22",
        "docling",
        "docling-core"
    ])
def fetch_from_minio_docling_process_store(
    bucket_name: str,
    minio_endpoint: str,
    minio_access_key: str,
    minio_secret_key: str,
    llamastack_base_url: str):
```

The component bundles all dependencies inside the `@component` decorator so KFP installs them in the pipeline pod at runtime.

#### Docling PDF Parsing and Hybrid Chunking

Documents are converted using docling's `DocumentConverter` with PDF pipeline options, then chunked using `HybridChunker`. Only text/paragraph chunks are retained for embedding.

```python
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling_core.transforms.chunker.hybrid_chunker import HybridChunker
from docling_core.types.doc.labels import DocItemLabel

pipeline_options = PdfPipelineOptions()
pipeline_options.generate_picture_images = True
converter = DocumentConverter(
    format_options={
        InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
    }
)
chunker = HybridChunker()
```

Chunks are filtered to only include `DocItemLabel.TEXT` and `DocItemLabel.PARAGRAPH` items before being wrapped as `LlamaStackDocument` objects.

#### Vector DB Registration and Insertion via Llama Stack

The notebook uses Llama Stack client to register a pgvector-backed vector database and insert chunked documents. The embedding model (`all-MiniLM-L6-v2`, 384 dimensions) is specified at registration time.

```python
client = LlamaStackClient(base_url=llamastack_base_url)
client.vector_dbs.register(
    vector_db_id="rag-db",
    embedding_model="all-MiniLM-L6-v2",
    embedding_dimension=384,
    provider_id="pgvector",
)
client.tool_runtime.rag_tool.insert(
    documents=llama_documents,
    vector_db_id="test",
    chunk_size_in_tokens=512,
)
```

#### KFP Pipeline Compilation and Submission

The pipeline is compiled to a YAML file and submitted to the Data Science Pipelines Application (DSPA) running in-cluster. The KFP client connects to the DSPA endpoint with SSL verification disabled.

```python
compiler.Compiler().compile(
    pipeline_func=full_pipeline,
    package_path=pipeline_yaml
)
client = Client(
    host="https://ds-pipeline-dspa:8888",
    verify_ssl=False
)
uploaded_pipeline = client.upload_pipeline(
    pipeline_package_path=pipeline_yaml,
    pipeline_name="fetch-docling-process-store-pipeline"
)
```

#### pgvector Verification Notebook

The `query_pgvector.ipynb` notebook provides a debugging/verification tool for inspecting the vector database after ingestion. It connects directly to PostgreSQL, lists tables, describes schemas, and queries stored documents with optional vector column exclusion.

```python
DB_HOST = 'pgvector.llama-stack-rag.svc.cluster.local'
DB_PORT = '5432'
DB_NAME = 'rag_blueprint'
DB_USER = 'postgres'
DB_PASSWORD = 'rag_password'
TABLE_NAME = 'vector_store_demo_rag_vector_db_v1_0'
```

### Configuration

- **Environment variables (pipeline notebook):**
  - `MINIO_ENDPOINT` -- MinIO API endpoint URL
  - `MINIO_ACCESS_KEY` -- MinIO access key
  - `MINIO_SECRET_KEY` -- MinIO secret key
  - `LLAMASTACK_BASE_URL` -- Llama Stack server URL for vector DB operations
- **Environment variables (verification notebook):** None (all values hardcoded in notebook cells)
- **Helm values:** `ingestion-pipeline.enabled`, `ingestion-pipeline.serviceAccount.name`, per-pipeline `source`, `embedding_model`, `vector_store_name`, and `GITHUB.url`/`path`/`branch` for each document collection
- **Ingestion config (local):** `deploy/local/ingestion-config.yaml` defines pipeline configs with source type (GITHUB/S3/URL), vector DB names, and embedding settings

### Known Gotchas

- **vector_db_id mismatch in insert call:** The notebook registers the vector DB as `"rag-db"` but inserts documents into `"test"` -- this is a discrepancy in the source code that would cause the insert to target a different (or non-existent) vector database at runtime.
- **Pipeline environment variables accessed at definition time:** The `full_pipeline()` function reads `os.environ` at pipeline definition time inside the `@pipeline` decorator, but these values need to be available when the notebook cell executes (compilation time), not when the pipeline pod runs. KFP pipeline parameters would be the correct mechanism for runtime values.
- **Hardcoded pgvector credentials in verification notebook:** The `query_pgvector.ipynb` notebook has `DB_PASSWORD = 'rag_password'` and `DB_USER = 'postgres'` hardcoded in a cell. These must be updated to match the actual deployment credentials.
- **KFP client uses hardcoded DSPA endpoint:** The pipeline client connects to `https://ds-pipeline-dspa:8888` which assumes the DSPA service name and namespace. The DSPA must be configured with MinIO credentials before the pipeline can run.
- **`notebooks/` directory serves dual purpose:** The directory contains both `.ipynb` notebook files and subdirectories of source PDF documents (hr/, legal/, sales/, procurement/, techsupport/, zippity-zoo/) that are referenced by the ingestion pipeline configurations via GitHub URLs.
- **SSL verification disabled:** Both the MinIO S3 client (`verify=False`) and the KFP client (`verify_ssl=False`) disable SSL verification, which works for in-cluster self-signed certificates but would need adjustment for production.

### Testing Notes

- Configure a DataSciencePipelinesApplication (DSPA) in the namespace before running the pipeline notebook
- Get MinIO credentials from the `minio` secret: `oc get secret minio -o jsonpath='{.data.username}' | base64 --decode`
- After running the pipeline, verify embeddings using the `query_pgvector.ipynb` notebook or direct SQL: `oc exec -it pgvector-0 -- psql -d rag_blueprint -U postgres -c "SELECT COUNT(*) FROM vector_store_demo_rag_vector_db_v1_0;"`
- The table name `vector_store_demo_rag_vector_db_v1_0` follows the Llama Stack naming convention: `vector_store_<db_id>_v<version>`

---

## Approach C: Interactive LlamaStack Demo Notebooks -- RAG, Evaluation, and LangGraph Agents (from lls-observability)

### When to Use

Use this approach when the quickstart provides interactive, educational demo notebooks that walk users through LlamaStack capabilities: RAG with Milvus vector search, model evaluation (subset_of, llm_as_judge, benchmark datasets), and third-party agentic framework integration (LangGraph) via LlamaStack's OpenAI-compatible endpoint. These notebooks are designed for guided exploration on a running LlamaStack deployment with observability, not for data preparation or automated pipelines.

### Differences from Approach A and B

- **Purpose:** Interactive demos and tutorials vs data preparation (A) or automated ingestion pipelines (B)
- **Vector DB backend:** Milvus via LlamaStack `provider_id="milvus"` vs PostgreSQL/psycopg2 (A) or pgvector via LlamaStack (B)
- **LlamaStack APIs used:** Inference, RAG Tool, Evaluation/Scoring/Benchmarks, and OpenAI-compatible endpoint (`/v1/openai/v1`) vs basic client testing (A) or `vector_dbs.register` + `rag_tool.insert` only (B)
- **Agentic framework:** LangGraph StateGraph with `ChatOpenAI` pointing to LlamaStack vs direct Agents API (A) or none (B)
- **MCP tool binding:** Via `ChatOpenAI.bind_tools` with MCP server URL vs `toolgroups.register` (A) or none (B)
- **Evaluation coverage:** Full LlamaStack eval framework (scoring functions, datasets, benchmarks) -- not present in A or B

### Tech Stack & Dependencies

- **Runtime:** Python (RHOAI workbench or Jupyter environment on cluster)
- **Container image:** Standard RHOAI workbench image (no custom Dockerfile)
- **Key dependencies:**
  - `llama_stack_client` + `fire` + `dotenv` -- LlamaStack client for RAG and evaluation notebooks
  - `llama-stack-client==0.2.12` -- pinned version for evaluation notebook
  - `langgraph==0.6.7` -- LangGraph agent framework for agent notebooks
  - `langchain-openai==0.3.32` -- ChatOpenAI client bridging LangGraph to LlamaStack
  - `langchain-core==0.3.75` -- LangChain core for tool definitions and message types
  - `termcolor` -- colorized console output in RAG notebook
- **Helm subchart:** None (notebooks run interactively against a deployed LlamaStack instance)

### Key Patterns

#### RAG with Milvus via LlamaStack RAG Tool

The `1-simpleRAG.ipynb` notebook registers a Milvus-backed vector database, ingests PDF documents from URLs using LlamaStack's built-in RAG tool (which handles download, parsing, chunking, and embedding), then queries with semantic search and context injection for LLM generation.

```python
client.vector_dbs.register(
    vector_db_id=vector_db_id,
    embedding_model="all-MiniLM-L6-v2",
    embedding_dimension=384,
    provider_id="milvus",
)

client.tool_runtime.rag_tool.insert(
    documents=documents,
    vector_db_id=vector_db_id,
    chunk_size_in_tokens=512,
)
```

Documents are wrapped as `RAGDocument` objects with `content` pointing to a URL and `mime_type` set to `"application/pdf"`. LlamaStack handles the entire ingestion pipeline internally.

#### RAG Context Injection Pattern

The notebook demonstrates manual context injection: query the vector DB with `rag_tool.query`, then prepend the retrieved content as context in the LLM prompt rather than using an agent with automatic tool calling.

```python
rag_response = client.tool_runtime.rag_tool.query(
    content=prompt,
    vector_db_ids=[vector_db_id],
    query_config={
        "chunk_template": "Result {index}\nContent: {chunk.content}\nMetadata: {metadata}\n",
    },
)

prompt_context = rag_response.content
extended_prompt = f"Please answer the given query using the context below.\n\nCONTEXT:\n{prompt_context}\n\nQUERY:\n{prompt}"
```

#### LlamaStack Evaluation Framework -- subset_of Scoring

The `2-evals.ipynb` notebook uses LlamaStack's built-in `basic::subset_of` scoring function for exact substring matching between generated and expected answers. Rows are structured with `input_query`, `generated_answer`, and `expected_answer` fields.

```python
scoring_response = client.scoring.score(
    input_rows=handmade_eval_rows,
    scoring_functions={"basic::subset_of": None}
)

results = scoring_response.results['basic::subset_of']
accuracy = results.aggregated_results['accuracy']['accuracy']
```

#### LlamaStack Evaluation Framework -- LLM-as-Judge Scoring

The same notebook demonstrates semantic evaluation using an LLM as judge. A custom prompt template classifies the relationship between generated and expected answers into categories (A through E), and a regex extracts the letter grade.

```python
scoring_response = client.scoring.score(
    input_rows=handmade_eval_rows,
    scoring_functions={
        "llm-as-judge::base": {
            "judge_model": model_id,
            "prompt_template": JUDGE_PROMPT,
            "type": "llm_as_judge",
            "judge_score_regexes": ["Answer: (A|B|C|D|E)"],
        }
    }
)
```

The judge prompt uses five categories: (A) subset, (B) superset, (C) same details, (D) factual disagreement, (E) immaterial differences. Categories A, B, C, E are treated as correct.

#### LlamaStack Evaluation Framework -- Dataset Benchmarks

The evaluation notebook registers external datasets from HuggingFace, creates benchmarks, and runs end-to-end evaluation with model inference and scoring in a single API call.

```python
client.datasets.register(
    purpose="eval/messages-answer",
    source={
        "type": "uri",
        "uri": "huggingface://datasets/llamastack/simpleqa?split=train",
    },
    dataset_id="huggingface::simpleqa",
)

client.benchmarks.register(
    benchmark_id="meta-reference::simpleqa",
    dataset_id="huggingface::simpleqa",
    scoring_functions=["llm-as-judge::base"],
)

response = client.eval.evaluate_rows(
    benchmark_id="meta-reference::simpleqa",
    input_rows=eval_rows.data,
    scoring_functions=["llm-as-judge::base"],
    benchmark_config={
        "eval_candidate": {
            "type": "model",
            "model": model_id,
            "sampling_params": {"strategy": {"type": "greedy"}, "max_tokens": 512},
        },
    },
)
```

The `evaluate_rows` API generates model responses and scores them in one call, returning both `generations` and `scores` arrays.

#### Multiple Choice Evaluation with Regex Parser

The evaluation notebook also demonstrates MMLU-style multiple choice evaluation using `basic::regex_parser_multiple_choice_answer`. Questions include options (A/B/C/D) in the prompt, and the scoring function extracts the letter answer from the model's response.

```python
response = client.eval.evaluate_rows(
    benchmark_id="meta-reference::financial-sample",
    input_rows=mmlu_sample_rows,
    scoring_functions=["basic::regex_parser_multiple_choice_answer"],
    benchmark_config={
        "eval_candidate": {
            "type": "model",
            "model": model_id,
            "sampling_params": {
                "strategy": {"type": "top_p", "temperature": 0.1, "top_p": 0.95},
                "max_tokens": 512,
            },
            "system_message": system_message,
        },
    },
)
```

#### LangGraph Agent via LlamaStack OpenAI-Compatible Endpoint

The `3-langgraph-agent.ipynb` and `4-langgraph-tools.ipynb` notebooks demonstrate using LangGraph with LlamaStack by pointing `ChatOpenAI` at LlamaStack's OpenAI-compatible endpoint. This enables using any OpenAI-compatible agentic framework without LlamaStack-specific client code.

```python
from langchain_openai import ChatOpenAI

llm = ChatOpenAI(
    model="llama3-2-3b",
    openai_api_key="fake",
    openai_api_base="http://llama-stack-instance-service.llama-serve.svc.cluster.local:8321/v1/openai/v1",
    use_responses_api=True,
)
```

The LangGraph StateGraph pattern defines a `State` TypedDict with an `add_messages` annotated list, a chatbot node that invokes the LLM, and edges from START to chatbot to END.

```python
class State(TypedDict):
    messages: Annotated[list, add_messages]

def chatbot(state: State):
    message = llm.invoke(state["messages"])
    return {"messages": [message]}

graph_builder = StateGraph(State)
graph_builder.add_node("chatbot", chatbot)
graph_builder.add_edge(START, "chatbot")
graph_builder.add_edge("chatbot", END)
graph = graph_builder.compile()
```

#### MCP Tool Binding via ChatOpenAI bind_tools

The `4-langgraph-tools.ipynb` notebook binds MCP tools to the LLM using `ChatOpenAI.bind_tools()` with a dictionary specifying the MCP server URL. This is different from Approach A's `toolgroups.register` method -- tools are bound at the LangChain/LangGraph level rather than through LlamaStack's native Agents API.

```python
llm_with_tools = llm.bind_tools([
    {
        "type": "mcp",
        "server_label": "weather",
        "server_url": "http://mcp-weather.llama-serve.svc.cluster.local:80/sse",
        "require_approval": "never",
    },
])
```

### Configuration

- **Environment variables:** None explicitly used (all connection URLs are hardcoded in notebook cells)
- **LlamaStack endpoint:** `http://llama-stack-instance-service.llama-serve.svc.cluster.local:8321` for native client, with `/v1/openai/v1` suffix for OpenAI-compatible access
- **Model ID:** `llama32` (RAG notebook) or `llama3-2-3b` (evaluation and agent notebooks) -- the same underlying model referenced by different aliases
- **Embedding model:** `all-MiniLM-L6-v2` with 384 dimensions (same as Approach B but stored in Milvus rather than pgvector)
- **Config files:** None (all config inline in notebook cells)
- **Helm values:** Not applicable (notebooks run interactively against pre-deployed services)

### Known Gotchas

- **Model ID alias inconsistency across notebooks:** The RAG notebook uses `model_id = "llama32"` while the evaluation and agent notebooks use `model_id = "llama3-2-3b"`. Both refer to the same deployed model but use different aliases. The evaluation notebook discovers the correct alias dynamically via `client.models.list()`.
- **OpenAI API key set to `"fake"`:** The LangGraph notebooks set `openai_api_key="fake"` because LlamaStack's OpenAI-compatible endpoint does not require authentication in the default in-cluster deployment. This must be updated if authentication is enabled.
- **`use_responses_api=True` required for ChatOpenAI:** The LangGraph notebooks explicitly set `use_responses_api=True` on the `ChatOpenAI` client when connecting to LlamaStack's OpenAI-compatible endpoint.
- **MCP tool binding uses SSE endpoint:** The MCP weather tool URL uses the `/sse` path (`http://mcp-weather.llama-serve.svc.cluster.local:80/sse`), consistent with Approach A's finding that LlamaStack requires SSE transport for MCP.
- **Extended timeout for evaluation:** The evaluation notebook sets `timeout=600.0` on the LlamaStack client because evaluation operations (especially `evaluate_rows` with LLM-as-judge) can be slow when running multiple inference calls.
- **Self-judging limitation:** The evaluation notebook uses the same model (`llama3-2-3b`) as both the evaluated model and the judge in LLM-as-judge scoring. The notebook itself notes this is not ideal for production -- a more capable model should be used as judge.
- **Sampling strategy conditional logic:** The RAG notebook implements a conditional sampling strategy: `{"type": "greedy"}` when `temperature == 0.0`, otherwise `{"type": "top_p", "temperature": temperature, "top_p": 0.95}`. This pattern is required by LlamaStack's inference API.

### Testing Notes

- All four notebooks require a running LlamaStack instance with vLLM-served Llama 3.2 3B model deployed in the cluster
- The RAG notebook additionally requires Milvus to be configured as a vector store provider in LlamaStack
- The agent notebooks require the MCP weather service to be deployed at `mcp-weather.llama-serve.svc.cluster.local:80`
- The evaluation notebook requires network access to HuggingFace for dataset registration (`huggingface://datasets/llamastack/simpleqa`)
- Run notebooks in order: 1 (RAG basics) -> 2 (evaluation) -> 3 (basic agent) -> 4 (agent with tools)

---

## Choosing Between Approaches

| Criteria | Approach A (Manual Workbench) | Approach B (KFP Pipeline) | Approach C (Interactive Demos) |
|----------|-------------------------------|---------------------------|-------------------------------|
| Execution model | Manual notebook run in RHOAI workbench | Automated KFP pipeline compiled from notebook | Interactive tutorial notebooks run on cluster |
| Data source | Local CSV files | PDFs from MinIO/S3 buckets | PDFs from URLs (fetched by LlamaStack) |
| Document processing | pandas DataFrame loading | docling PDF conversion + hybrid chunking | LlamaStack RAG Tool handles parsing and chunking |
| Vector DB backend | PostgreSQL (psycopg2) | pgvector via LlamaStack | Milvus via LlamaStack |
| Storage method | Direct psycopg2 `execute_batch` inserts | LlamaStack `vector_dbs.register` + `rag_tool.insert` | LlamaStack `vector_dbs.register` + `rag_tool.insert` |
| Agentic framework | LlamaStack native Agents API | None | LangGraph via OpenAI-compatible endpoint |
| Evaluation coverage | None | None | subset_of, llm_as_judge, dataset benchmarks, multiple choice |
| MCP tools | `toolgroups.register` (native API) | None | `ChatOpenAI.bind_tools` (OpenAI-compatible) |
| Repeatability | One-time manual execution | Repeatable pipeline runs via KFP | Repeatable interactive demos |
| Helm integration | None | `ingestion-pipeline` subchart v0.7.5 | None |
| Infrastructure required | RHOAI workbench only | DSPA + MinIO + Llama Stack + pgvector | LlamaStack + vLLM + Milvus + MCP servers |
| Best for | Data preparation and integration testing | Production RAG document ingestion | Guided learning and capability demonstration |
