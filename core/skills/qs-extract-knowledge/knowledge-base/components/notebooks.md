---
name: notebooks
description: "Jupyter notebooks for data ingestion, model download-to-S3, and Llama Stack testing in RHOAI workbenches"
summary: "Jupyter notebooks in RHOAI workbenches cover three concerns for AI quickstarts: CSV-to-PostgreSQL ingestion via pandas+psycopg2 execute_batch with star-schema tables and SQL governance artifacts (COMMENT ON for certified/deprecated views enabling AI copilot reasoning), HuggingFace model download via snapshot_download with boto3 upload to MinIO using AWS_* env vars from workbench data connections, and Llama Stack 0.3.5 integration testing covering MCP toolgroup registration and agent-based tool calling via client.alpha.agents. Use when notebooks must prepare data, stage 14-16 GB models to S3, or validate Llama Stack deployments — these run manually in RHOAI workbenches (not deployed via Helm); data ingestion uses hardcoded localhost:5432 requiring port-forwarding. Critical: Llama Stack requires SSE transport (/sse not /mcp) for MCP, the Agents API for tool calling (chat.completions lacks tool_groups support), model IDs with provider prefix format vllm-inference/<model-name>, and S3 credentials sourced from RHOAI workbench data connection environment variables (AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_S3_ENDPOINT, AWS_S3_BUCKET). Gotchas: MCP service names need -service suffix (pg-airman-mcp-service not pg-airman-mcp), toolgroup registration requires correct provider_id extracted dynamically from provider list (e.g., mcp-tools not model-context-protocol), gated models require notebook_login() for HF auth, and workbench PVC must accommodate 14-16 GB per model download."
metadata:
  type: component
tags:
  tech_stack: [jupyter, python, pandas, psycopg2, boto3, huggingface-hub, llama-stack-client]
  ai_pattern: [data-pipeline, model-serving, agents]
  platform: [rhoai, openshift, vllm]
  data_layer: [postgresql, minio]
source_examples:
  - quickstart: "data-governance-co-pilot"
    repo: "https://github.com/rh-ai-quickstart/data-governance-co-pilot"
    notes: "Data ingestion, model prep, and Llama Stack integration test notebooks run from RHOAI workbenches"
    approach: "A"
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
