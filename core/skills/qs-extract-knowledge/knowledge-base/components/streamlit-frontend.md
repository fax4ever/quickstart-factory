---
name: streamlit-frontend
description: Streamlit chat UI with dual-panel guardrail comparison, LlamaStack/OpenAI SDK integration, and RAG document management
summary: "Provides a Streamlit dual-panel chat UI for the f5-ai-guardrails quickstart that sends the same prompt via OpenAI Python SDK to both an F5 Guardrails Moderator proxy and a direct LlamaStack endpoint, comparing guardrail-filtered vs. unfiltered responses with cai_error.scanner_results parsing and Moderator API scanner name resolution. Use when building a side-by-side guardrail evaluation interface with integrated RAG document management -- the app queries pgvector directly via asyncpg (table convention vs_{id.replace('-','_')}) since LlamaStack lacks document enumeration, injects retrieved context by prepending it to user prompts, and uses st.navigation for multi-page routing. Critical patterns: LlamaStack URL normalization strips legacy /v1/openai/v1 suffixes for 0.6+ compatibility; custom httpx transport disables TLS verify for OpenShift cluster URLs; F5 endpoint settings persist to a JSON state file (F5_GUARDRAILS_STATE_FILE); repetition_penalty extra_body is sent only to direct LlamaStack, not through the Moderator proxy; RAG_QUESTION_SUGGESTIONS injected via ConfigMap. Gotchas: OpenShift edge routes return HTML on http:// (start.sh auto-detects TLS), llama-stack-client maps HTTP 5xx to InternalServerError with misleading names when edge returns HTML (format_api_connection_error generates OpenShift debugging hints), Streamlit password inputs return empty on early frames corrupting stored tokens, and emptyDir-backed guardrail state is lost on pod replacement -- use a PVC on /data for persistence."
metadata:
  type: component
tags:
  tech_stack: [streamlit, python, openai, llama-stack, pandas, asyncpg, httpx, uv]
  ai_pattern: [rag, guardrails, vector-search]
  platform: [openshift, kubernetes, rhoai]
  data_layer: [pgvector]
source_examples:
  - quickstart: "f5-ai-guardrails"
    repo: "https://github.com/rh-ai-quickstart/f5-ai-guardrails"
    notes: "Streamlit dual-panel chat comparing F5 AI Guardrails proxy vs direct LlamaStack inference, with RAG vector DB management"
    approach: "A"
---

# Streamlit Frontend

## Overview

A Streamlit-based frontend that provides a dual-panel chat comparison interface for AI guardrail evaluation. The left panel routes prompts through an F5 AI Guardrails proxy, while the right panel sends the same prompt directly to LlamaStack, letting users visually compare guardrail-filtered vs. unfiltered responses. The UI also provides RAG document management (vector DB creation, document upload, querying) and settings pages for configuring both endpoints.

## Tech Stack & Dependencies

- **Runtime:** Python 3.12, Streamlit framework
- **Container image:** `quay.io/rh-ai-quickstart/f5-ai-guardrails` (built from `python:3.12-slim`)
- **Key dependencies:** `llama-stack-client==0.6.0`, `llama-stack==0.6.0`, `openai` (Python SDK), `pandas`, `asyncpg` (direct pgvector queries), `httpx` (custom HTTP transport), `streamlit-option-menu`, `fire`
- **Helm subchart:** Deployed via `deploy/helm/rag/` chart with `pgvector`, `llm-service`, and `llama-stack` subcharts from `ai-architecture-charts`

## Key Patterns

### Dual-Panel Chat Comparison via OpenAI SDK

The same user prompt is sent to two separate OpenAI-compatible endpoints in parallel columns. Both use the OpenAI Python SDK `chat.completions.create`, but with different `base_url` values -- one pointing at the F5 Guardrails proxy, the other at the LlamaStack server directly:

```python
# chat.py — F5 side uses the guardrail proxy URL
f5_oai = llama_stack_api.create_openai_client(
    f5_ep.strip(), f5_tk.strip(),
)
resp = f5_oai.chat.completions.create(
    model=f5_model,
    messages=messages_for_api,
    max_tokens=max_tokens,
    temperature=temperature,
    top_p=top_p,
)
```

```python
# chat.py — LlamaStack side targets the server directly
ls_oai = llama_stack_api.create_openai_client_for_llamastack(
    st.session_state.ls_endpoint_url,
    st.session_state.ls_api_token,
)
resp = ls_oai.chat.completions.create(
    model=ls_model,
    messages=messages_for_api,
    extra_body={"repetition_penalty": repetition_penalty},
)
```

### LlamaStack URL Normalization for Multiple API Versions

The API module normalizes endpoint URLs to handle differences between LlamaStack versions. The OpenAI SDK requires `base_url` ending in `/v1`, but users may paste URLs with legacy suffixes or trailing path segments:

```python
# api.py — strips legacy /v1/openai/v1 suffixes from older docs
_LLAMA_OPENAI_SDK_SUFFIX = "/v1"

def llamastack_openai_chat_base_url(endpoint: str) -> str:
    u = (endpoint or "").strip().rstrip("/")
    # ... strips /chat/completions, legacy /v1/openai/v1, /v1/models
    legacy = "/v1/openai/v1"
    while u.endswith(legacy):
        u = u[: -len(legacy)].rstrip("/")
    if not u.endswith(suf):
        u = u + suf
    return u
```

### OpenShift-Aware HTTP Transport

A custom httpx client factory detects OpenShift route URLs and disables TLS verification for cluster-hosted endpoints while preserving strict defaults for localhost development:

```python
# api.py
def _httpx_client_for_url(url: str) -> httpx.Client | None:
    u = (url or "").lower().rstrip("/")
    if "localhost" in u or "127.0.0.1" in u:
        return httpx.Client(follow_redirects=True, timeout=_HTTPX_TIMEOUT)
    if u.startswith("http://") or u.startswith("https://"):
        return httpx.Client(verify=False, follow_redirects=True,
                            timeout=_HTTPX_TIMEOUT)
    return None
```

### Guardrail Block Parsing from F5 Moderator API

When the F5 proxy blocks a request, the error body contains a `cai_error` with scanner results. The frontend parses this to show which specific scanners triggered and fetches human-readable scanner names from the Moderator API:

```python
# chat.py
cai_error = body.get("cai_error", {})
scanner_results = cai_error.get("scanner_results", [])
failed = [s for s in scanner_results if s.get("outcome") == "failed"]
name_map = _get_scanner_names()
for s in failed:
    sid = s.get("scanner_id", "unknown")
    scanner_name = name_map.get(sid)
```

### Persistent Guardrail Settings via JSON State File

F5 endpoint URL and API token are persisted to a JSON file so they survive Streamlit reruns. On startup, the app hydrates session state from the file, with environment variables as fallback:

```python
# guardrails_storage.py
def state_path() -> Path:
    override = os.environ.get("F5_GUARDRAILS_STATE_FILE", "").strip()
    if override:
        return Path(override)
    return Path.home() / ".config" / "f5-guardrails" / "guardrails_state.json"
```

### Multi-Page Navigation with st.navigation

The app uses Streamlit's `st.navigation` API (not the older `st.sidebar.radio` pattern) for multi-page routing:

```python
# app.py
pages = {
    "Chat": ("page/playground/chat.py", "\U0001f4ac"),
    "Settings": ("page/distribution/inspect.py", "⚙️"),
}
nav_items = [
    st.Page(path, title=name, icon=icon, default=(name == "Chat"))
    for name, (path, icon) in pages.items()
]
pg = st.navigation({"Playground": nav_items}, expanded=False)
pg.run()
```

### Direct pgvector Queries for Document Management

The vector DB management page bypasses the LlamaStack API to query pgvector directly via asyncpg for listing and deleting documents, since the LlamaStack API does not expose document enumeration:

```python
# vector_dbs.py — table naming convention
table_name = f"vs_{vector_db_id.replace('-', '_')}"
query = f"""
    SELECT DISTINCT
        COALESCE(
            NULLIF(document->'chunk_metadata'->>'source', 'null'),
            document->'metadata'->>'document_id'
        ) as document_id
    FROM {table_name}
    WHERE document->'metadata'->>'document_id' IS NOT NULL
"""
```

### RAG Context Injection into Chat Prompts

When vector DBs are selected, the chat page retrieves context via the LlamaStack RAG tool API and prepends it to the user prompt before sending to both endpoints:

```python
# chat.py
rag_resp = rag_tool_query(
    client, content=prompt, vector_db_ids=list(vdb_ids),
)
extended_prompt = (
    f"Please answer the following query using the context below.\n\n"
    f"CONTEXT:\n{rag_resp.content}\n\nQUERY:\n{prompt}"
)
```

## Configuration

- **Environment variables:**
  - `LLAMA_STACK_ENDPOINT` - LlamaStack server URL (default: `http://localhost:8321`, auto-detected from OpenShift route `llamastack-http` via `start.sh`)
  - `LLAMA_STACK_API_TOKEN` - Optional bearer token for LlamaStack
  - `F5_GUARDRAIL_URL` - F5 Moderator OpenAI proxy endpoint (seedable via env, also settable in UI)
  - `F5_GUARDRAIL_API_TOKEN` - Bearer token for F5 Guardrails (seedable via env, also settable in UI)
  - `F5_GUARDRAILS_STATE_FILE` - Override path for guardrail config persistence (default: `~/.config/f5-guardrails/guardrails_state.json`, set to `/data/guardrails_state.json` in Helm values)
  - `PGVECTOR_HOST`, `PGVECTOR_PORT`, `PGVECTOR_USER`, `PGVECTOR_PASSWORD`, `PGVECTOR_DB` - Direct pgvector connection for document management
  - `RAG_QUESTION_SUGGESTIONS` - JSON map of vector DB name/ID to suggested question lists, injected via ConfigMap
- **Config files:** `guardrails_state.json` (auto-generated, persists F5 endpoint URL and API token)
- **Helm values:**
  - `image.repository` / `image.tag` - Container image (`quay.io/rh-ai-quickstart/f5-ai-guardrails`)
  - `service.port: 8501` - Streamlit default port
  - `env` - Array of env var objects injected into the Deployment
  - `volumes` / `volumeMounts` - emptyDir for `/.streamlit` (Streamlit config) and `/data` (guardrail state)
  - `suggestedQuestions` - Optional map rendered into a ConfigMap as `RAG_QUESTION_SUGGESTIONS` env var

## Known Gotchas

- **OpenShift edge routes return HTML, not JSON, on http://.** The `_httpx_client_for_url` function in `api.py` comments: "OpenShift edge routes are HTTPS; http:// to *.apps... often returns HTML/redirects." The `start.sh` script auto-detects TLS termination on the route and switches to `https://` accordingly.
- **LlamaStack 0.6 changed the OpenAI-compatible path.** A code comment in `api.py` states: "LlamaStack 0.6+ serves chat there; /v1/openai/v1/... exists in some older builds but returns 404 on 0.6 starter." The URL normalization function strips the legacy suffix.
- **llama-stack-client reports misleading exception names for HTTP 5xx.** The `format_api_connection_error` function in `utils.py` documents: "llama-stack-client maps HTTP 502/503/504 to InternalServerError (status_code >= 500), so the exception *name* is often misleading when the edge returns HTML." The function detects HTML in error bodies and generates actionable OpenShift debugging hints.
- **Streamlit password inputs can return empty on early frames.** A comment in `models.py` warns: "Do not use separate widget keys + copy from return values: password inputs can return '' on early frames and would overwrite a file-loaded token and corrupt JSON."
- **Guardrail state file on emptyDir is lost on pod replacement.** The Helm `values.yaml` comments: "Guardrail URL + API token persisted by the UI to this path (emptyDir /data). Lost if the pod is replaced; use a PVC on /data for values that must survive rescheduling."
- **Do not send vLLM-only extra_body through the Moderator proxy.** A comment in `chat.py` states: "Do not send vLLM-only extra_body through the Moderator; some stacks return 200 with empty messages." The `repetition_penalty` parameter is only sent to the direct LlamaStack side.
- **pgvector table naming convention uses underscores.** The `vector_dbs.py` code converts vector DB IDs to table names: `f"vs_{vector_db_id.replace('-', '_')}"`.

## Testing Notes

- After Helm install, get the UI URL: `oc get route -n <namespace> -l app.kubernetes.io/name=f5-ai-guardrails -o jsonpath='{.items[0].spec.host}'`
- For local development, run `cd frontend && NAMESPACE=<ns> ./dev-on-cluster.sh` which auto-discovers the LlamaStack route and optionally port-forwards
- Verify dual-panel works: configure both F5 Guardrails and LlamaStack endpoints in Settings, then send a chat message and confirm both panels respond
- Test guardrail blocking: send a prompt that triggers a scanner policy and verify the left panel shows scanner names from `cai_error`
- Verify RAG: create a vector DB in Settings > Vector Databases, upload a document, select it in the chat sidebar, and ask a question about its content

## Related Patterns

- Component: pgvector (vector database used for RAG document storage and queried directly via asyncpg)
- Component: llamastack (backend inference server this frontend connects to)
- Component: llm-service (vLLM model serving subchart providing models to LlamaStack)
