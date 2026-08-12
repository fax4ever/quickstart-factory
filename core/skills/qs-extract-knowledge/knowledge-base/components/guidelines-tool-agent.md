---
name: guidelines-tool-agent
description: Flask tool agent that parses investment guideline PDFs to extract prohibited ticker symbols using TF-IDF + MLP classification
summary: "The guidelines tool agent is a Flask microservice (port 7003, UBI10-minimal) within a multi-agent portfolio management system that parses investment guideline PDFs to extract prohibited ticker symbols using a scikit-learn TF-IDF bigram + MLP(64) classifier trained on hardcoded synthetic data, with context-aware regex ticker extraction applying parenthesization, exchange-colon, and prohibition-cue heuristics above a configurable threshold (default 0.65). Dual inference mode controlled by INFERENCE_URL -- when empty, bootstraps and thread-lock-serializes a local model from synthetic data on first startup (self-healing); when set, delegates classification to KServe MLServer (seldonio/mlserver:1.7.1-sklearn) via V2 protocol at /v2/models/guidelines-mlp/infer for production throughput. The agent advertises via OpenAI-compatible /tools GET endpoint (doubles as readiness probe) for orchestrator discovery, accepts PDF URLs or client IDs mapped to docs/client-{id}/investment-guidelines.pdf mounted from a Kubernetes Secret named guidelines-docs, and is deployed as a standalone Helm Deployment template. Critical gotcha: the agent wraps models in metadata dicts but MLServer expects bare pipelines -- unwrap_model.py must run at container build time when the model is updated; local-mode throughput is serialized by a global threading Lock, and the local PDF lookup uses a hardcoded path pattern requiring the guidelines-docs Secret mount."
metadata:
  type: component
tags:
  tech_stack: [flask, scikit-learn, pdfminer, python, joblib]
  ai_pattern: [agents, model-serving]
  platform: [kserve, rhoai, openshift]
  data_layer: []
source_examples:
  - quickstart: "portfolio-manager-agent"
    repo: "https://github.com/rh-ai-quickstart/portfolio-manager-agent"
    notes: "Flask tool agent with embedded MLP classifier and optional remote MLServer inference for parsing investment guidelines"
    approach: "A"
---

# Guidelines Tool Agent

## Overview

The guidelines tool agent is a Flask microservice that functions as a callable tool within a multi-agent portfolio management system. It parses investment guideline PDF documents to identify prohibited ticker symbols using a combination of NLP (TF-IDF sentence vectorization), an MLP neural-network classifier, and context-aware regex-based ticker extraction. The service supports both local model inference and remote inference via a KServe-hosted MLServer sklearn runtime.

## Tech Stack & Dependencies

- **Runtime:** Python 3.12 on UBI10 minimal (`registry.access.redhat.com/ubi10/python-312-minimal`)
- **Container image:** Built from `tools/guidelines/src/Dockerfile`
- **Key dependencies:**
  - `Flask==3.1.2` - HTTP API framework
  - `scikit-learn==1.8.0` - TF-IDF vectorizer + MLP classifier pipeline
  - `pdfminer.six==20250506` - PDF text extraction
  - `joblib==1.5.3` - Model serialization/deserialization
  - `requests==2.32.5` - Remote PDF fetching and MLServer inference calls
- **Helm subchart:** None; deployed as a standalone Deployment template (`deploy/helm/templates/deployment-guidelines.yaml`)

## Key Patterns

### Tool Registry Pattern

The agent advertises its capabilities via a `/tools` GET endpoint using OpenAI-compatible JSON Schema function definitions. This allows the orchestrator to discover available tools dynamically.

```python
TOOLS = [
    {
        "type": "function",
        "name": "prohibited_symbols",
        "description": "Given a client number or URL, parse an investment guidelines document to determine prohibited ticker symbols",
        "parameters": {
            "type": "object",
            "properties": {
                "url_investment_guidelines": {
                    "type": "string",
                    "description": "URL where the document can be found in the DMS",
                },
                "client": {
                    "type": "string",
                    "description": "Client number as defined in the document management system",
                },
            },
        },
    }
]
```

### Dual Inference Mode (Local vs Remote)

The agent supports two inference paths controlled by the `INFERENCE_URL` environment variable. When unset, it trains and loads a local sklearn Pipeline; when set, it delegates classification to a remote MLServer V2 endpoint.

```python
INFERENCE_URL = os.environ.get("INFERENCE_URL", "")

if INFERENCE_URL:
    print(f"Using remote inference at {INFERENCE_URL} — skipping local model load")
else:
    bootstrap_model()
```

Remote inference calls the MLServer V2 protocol at `/v2/models/guidelines-mlp/infer`:

```python
def predict_proba_remote(sentences: List[str]) -> List[float]:
    url = f"{INFERENCE_URL}/v2/models/guidelines-mlp/infer"
    payload = {
        "inputs": [
            {
                "name": "predict_input",
                "datatype": "BYTES",
                "shape": [len(sentences)],
                "data": sentences,
                "parameters": {"content_type": "str"},
            }
        ],
        "outputs": [{"name": "predict_proba"}],
    }
```

### Synthetic Training Data for MLP Classifier

The model is trained on hardcoded synthetic positive (prohibition) and negative (permitted/neutral) examples. The pipeline uses TF-IDF bigrams with an MLP hidden layer of 64 neurons.

```python
model = Pipeline(
    [
        (
            "tfidf",
            TfidfVectorizer(ngram_range=(1, 2), lowercase=True, max_features=8000),
        ),
        (
            "mlp",
            MLPClassifier(
                hidden_layer_sizes=(64,),
                activation="relu",
                solver="adam",
                random_state=42,
                max_iter=400,
            ),
        ),
    ]
)
```

### Context-Aware Ticker Extraction

The ticker extractor uses multiple heuristics to avoid false positives: company-name context detection, credit-rating filtering, upper-case stopword exclusion, and special handling for short (1-2 letter) ambiguous tokens that require parenthesization, exchange-colon patterns, or prohibition cue context.

```python
# Short tokens only accepted with strong contextual evidence
if len(c) <= 2:
    if not (
        _is_parenthesized_ticker(line, s, e)
        or _is_exchange_colon_pattern(line, s)
        or has_cues
    ):
        continue
```

### Model Serialization Wrapper

The agent wraps the sklearn Pipeline in a metadata dict for saving, but MLServer expects a bare pipeline. A separate `unwrap_model.py` utility strips the wrapper before deploying to MLServer.

```python
payload = {
    "model": model,
    "saved_at": datetime.utcnow().isoformat() + "Z",
    "sklearn_version": getattr(model, "__module__", "sklearn"),
    "type": "prohibition_mlp_pipeline_v1",
}
joblib.dump(payload, path)
```

## Configuration

- **Environment variables:**
  - `PORT` (default `7003`) - Flask server port
  - `MODEL_PATH` (default `models/investment-guidelines-mlp.joblib`) - Path to the serialized sklearn model
  - `INFERENCE_URL` (default `""`) - When set, delegates classification to a remote MLServer; when empty, uses local model
  - `PYTHONUNBUFFERED` - Set to `1` for immediate log output
- **Config files:** None; all configuration is via environment variables
- **Helm values:**
  - `guidelines.inferenceUrl` - Sets the `INFERENCE_URL` env var, defaults to `http://guidelines-mlp:80` (the KServe InferenceService)
  - `image.tags.guidelines` - Container image tag
- **Request parameters:**
  - `url_investment_guidelines` - Remote URL to fetch the PDF from
  - `client` - Client ID to look up a local PDF at `docs/client-{id}/investment-guidelines.pdf`
  - `threshold` (default `0.65`) - Probability threshold for classifying a sentence as prohibition-related

## Known Gotchas

- **Model wrapper incompatibility:** The agent saves models wrapped in a metadata dict (`{"model": Pipeline(...), ...}`), but MLServer's sklearn runtime expects `joblib.load()` to return the model directly. The `tools/guidelines-model/unwrap_model.py` script handles this conversion at container build time. If the model is updated, the MLServer image must be rebuilt.
- **Local PDF lookup path convention:** When using the `client` parameter, the agent looks for PDFs at a hardcoded path pattern `docs/client-{id}/investment-guidelines.pdf`. On Kubernetes, this directory is mounted from a Secret named `guidelines-docs` (see the Helm Deployment template), not a PVC.
- **Thread safety with model lock:** Local inference uses a global `model_lock` (threading Lock) to serialize access to the in-memory sklearn Pipeline. This limits local-mode throughput to one classification at a time. The remote MLServer path avoids this bottleneck.
- **Bootstrap behavior:** On startup without `INFERENCE_URL`, if no model file exists at `MODEL_PATH`, the agent trains a new model from synthetic data and saves it. This means first startup takes longer but is self-healing.

## Testing Notes

- The readiness probe is configured as `GET /tools` on port 7003 (visible in the Helm Deployment template)
- The `/tools/prohibited_symbols` endpoint returns a structured JSON response with `prohibited_tickers`, `matches` (with sentences, tickers, and scores), and `meta` (sentence count, match count, threshold)
- In local compose, the guidelines service depends on `mlserver` and uses `INFERENCE_URL: "http://mlserver:8080"` for remote inference
- The MLServer container uses `seldonio/mlserver:1.7.1-sklearn` as its base image with the model baked in at build time

## Related Patterns

- The companion MLServer container (`tools/guidelines-model/`) hosts the same sklearn model as a KServe InferenceService for production deployment
- On OpenShift, the model is served via a KServe `InferenceService` resource (`inferenceservice-guidelines-mlp.yaml`) using `RawDeployment` mode with the sklearn model stored in MinIO (`s3://models/guidelines-mlp`)
- The orchestrator discovers this tool via the `/tools` endpoint and invokes it as part of the agentic portfolio management workflow
