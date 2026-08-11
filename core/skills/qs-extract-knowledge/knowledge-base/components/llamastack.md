---
name: llamastack
description: "LlamaStack distribution server providing inference, agents, safety, tool runtime, and vector I/O APIs"
summary: "LlamaStack provides a unified AI orchestration server exposing inference, agents, safety, tool runtime, vector I/O, and files APIs between the application backend and model providers (Ollama or vLLM), with Approach A (ai-virtual-agent, v0.6.1) using compose with Responses API and StreamAggregator-based SSE streaming in a pluggable LlamaStack/LangGraph/CrewAI runner dispatch, Approach B (data-governance-co-pilot, v0.3.5) deploying a LlamaStackDistribution CRD via OpenShift AI operator with alpha.agents API managing the full agentic loop and session-to-conversation event mapping, Approach C (f5-ai-guardrails/f5-api-security/RAG, v0.6.1) using ai-architecture-charts llama-stack subchart v0.8.6 with dual-client pattern (LlamaStackClient + OpenAI SDK) or single LlamaStackClient (files API for document upload, XC URL dynamic endpoint switching, direct pgvector access) for RAG with optional F5 guardrails proxy dual-panel comparison, fileProcessors (pypdf) for PDF extraction, vector DB register/insert/query via tool_runtime.rag_tool with 600s client timeout for large uploads, MaaS e2e testing with initContainers override, and TAVILY secrets via llama-stack.secrets Helm values, Approach D (it-self-service-agent) using Helm subchart v0.8.5 with Responses API, PostgreSQL persistence (kv_postgres + sql_postgres) for multi-replica horizontal scaling, centralized client factory with K8s auto-discovery, MCP + file_search tools with per-request headers, knowledge base registration via vector_stores API with provider_id: pgvector, post-init scaler Job, retry with exponential backoff (1s-16s cap), and fault injection decorator for resilience testing, and Approach E (lls-observability) using standalone Helm chart with Red Hat ET image (quay.io/redhat-et/llama:vllm-0.2.6), OpenTelemetry collector sidecar for distributed tracing via OpenTelemetryCollector CRD in sidecar mode, inline::milvus for vector I/O, dual vLLM inference providers (primary + Llama Guard safety), network policies restricting access to openshift-ingress and playground pods, PVC-backed /.llama persistence, optional MaaS provider via LiteLLM, and ArgoCD sync-wave deployment ordering. Use Approach A for local dev or when the application manages the agentic loop with dynamic MCP toolgroup resolution, input shield validation via client.safety.run_shield(), and automatic tool retry with exclusion; use Approach B for production OpenShift AI deployments where the operator manages LlamaStack lifecycle (600s DeploymentReady wait, 100m/256Mi lightweight proxy resources), vLLM serves inference via KServe, and Makefile populates Helm model.name/url/apiKey values at install time; use Approach C for RAG apps needing shared Helm subcharts with global.models across llm-service/llama-stack, Streamlit frontend with URL normalization for 0.6+ and auto-detected route via start.sh, rawDeploymentMode toggle for non-OpenShift environments, and optional external guardrails proxy; use Approach D for production multi-agent apps needing horizontal scaling with PostgreSQL-backed shared state, lazy model discovery via models.list() filtering by custom_metadata.model_type, and post-init scaler Job coordinating initialization before scaling replicas; use Approach E for observability-focused deployments needing OpenTelemetry integration with traces and metrics exported to a central collector (observability-hub namespace), Milvus Lite for embedded vector search, network policy-restricted access, and optional MaaS model alongside local vLLM -- Nemotron models are incompatible with llama_stack mode (enforced by check-model-provider-compatibility, use mcp_direct). Configured via llamastack-run.yaml (RUN_CONFIG_PATH) declaring providers -- Approach A uses remote::ollama with AsyncLlamaStackClient (180s timeout, K8s SA token + X-Forwarded-User/Email auth headers for RBAC); Approach B uses remote::vllm with provider-prefixed model name (vllm-inference/<model>), vLLM URL derived from KServe predictor (https://<model>-predictor.<ns>.svc.cluster.local:8443/v1), VLLM_TLS_VERIFY='false' for self-signed certs, and static MCP endpoint in Helm-templated ConfigMap; Approach C uses dual clients with OpenAI SDK targeting LlamaStack /v1/chat/completions or single client with files API, HTTPX verify=False for cluster TLS, vector_dbs fallback to vector_stores on 404, auto-detects LlamaStack route via start.sh for TLS protocol selection, and Kind e2e requires stub OpenShift Route CRD; Approach D uses centralized client factory with LLAMASTACK_SERVICE_HOST (avoiding LLAMASTACK_PORT tcp:// format), OpenAI client at /v1/openai/v1, metadataStore with db_path: null to prevent SQLite fallback, pgvector max_connections=200 shared across all consumers, and max output tokens set server-side per-model (no per-request max_tokens in Responses API); Approach E uses dual vLLM providers (vllm-inference at VLLM_URL + vllm-safety at SAFETY_MODEL with separate max_tokens), TELEMETRY_SINKS='console, sqlite, otel_trace, otel_metric' with endpoints pointing to central collector, MILVUS_DB_PATH for inline Milvus at working directory, configmap checksum annotation for pod restart on config changes, and OpenShift-compatible securityContext (runAsNonRoot, drop ALL, readOnlyRootFilesystem: false). Container runs as root (user 0:0) with 90s healthcheck start_period, SDK attribute names changed between 0.3.x and 0.6.1 (identifier to id, api_model_type to model_type) requiring _get_model_type/_get_model_id helpers, SQLite storage is dev-only, platform linux/amd64 causes ARM emulation perf hit, regex-based tool retry parsing (Tool '(\\w+)' not found) is fragile, has_output_text=False emits error event to prevent silent empty responses, LLAMA_STACK_ENDPOINT vs LLAMA_STACK_SERVER env var name inconsistency across contexts, Approach B values.yaml has empty placeholders requiring Makefile --set population, static agent instructions require conversation restart on policy update via requires_conversation_restart_on_policy_update(), Approach C guardrails_state.json on emptyDir is lost on pod replacement, legacy URL suffix /v1/openai/v1 must be stripped for 0.6+ compatibility, llama-stack-client version pinning differs between frontend (0.6.0) and integration tests (>=0.2.9,<0.2.13), Approach D must avoid LLAMASTACK_PORT (K8s sets to tcp://host:port format) using LLAMASTACK_CLIENT_PORT or LLAMASTACK_SERVICE_PORT instead, with post-init scaler requiring bitnami/kubectl image mirroring in air-gapped environments, and Approach E's MILVUS_DB_PATH as relative path resolves outside the PVC mount at /.llama (lost on pod replacement), VLLM_API_TOKEN is hardcoded to 'fake' (not from Secret), CUSTOM_TIKTOKEN_CACHE_DIR at /app/cache differs from /.cache emptyDir mount, and pythainlp emptyDir at /pythainlp-data is required to prevent startup write failures."
metadata:
  type: component
tags:
  tech_stack: [llamastack, ollama, python, fastapi, llama-stack-client, vllm, helm, streamlit, openai-sdk, langgraph, opentelemetry]
  ai_pattern: [agents, model-serving, guardrails, rag, vector-search, mcp, embeddings, observability]
  platform: [openshift, kubernetes, rhoai, kserve]
  data_layer: [sqlite, faiss, pgvector, milvus]
source_examples:
  - quickstart: "ai-virtual-agent"
    repo: "https://github.com/rh-ai-quickstart/ai-virtual-agent"
    notes: "LlamaStack as unified AI orchestration layer with Ollama backend, Responses API streaming, MCP tool integration, and safety shields"
    approach: "A"
  - quickstart: "data-governance-co-pilot"
    repo: "https://github.com/rh-ai-quickstart/data-governance-co-pilot"
    notes: "LlamaStack deployed via OpenShift AI operator CRD with remote vLLM inference, Agents alpha API for agentic orchestration, and Helm chart"
    approach: "B"
  - quickstart: "f5-ai-guardrails"
    repo: "https://github.com/rh-ai-quickstart/f5-ai-guardrails"
    notes: "LlamaStack as ai-architecture-charts Helm subchart for RAG + guardrails, dual-client pattern (LlamaStackClient + OpenAI SDK), Streamlit frontend with URL normalization for 0.6+"
    approach: "C"
  - quickstart: "f5-api-security"
    repo: "https://github.com/rh-ai-quickstart/f5-api-security"
    notes: "LlamaStack as ai-architecture-charts Helm subchart for RAG with single LlamaStackClient (no OpenAI SDK), Streamlit frontend with XC URL dynamic endpoint switching, files API for vector store document upload, and direct pgvector access for document listing/deletion"
    approach: "C"
  - quickstart: "it-self-service-agent"
    repo: "https://github.com/rh-ai-quickstart/it-self-service-agent"
    notes: "LlamaStack as ai-architecture-charts Helm subchart with Responses API, PostgreSQL persistence for multi-replica scaling, centralized client factory with K8s auto-discovery, MCP + file_search tools, and post-init scaler Job"
    approach: "D"
  - quickstart: "RAG"
    repo: "https://github.com/rh-ai-quickstart/RAG"
    notes: "LlamaStack as ai-architecture-charts Helm subchart v0.8.7 for RAG with dual-client pattern, fileProcessors (pypdf), vector DB register/insert/query via tool_runtime.rag_tool, 600s client timeout for large uploads, MaaS e2e testing with initContainers override, and shield management"
    approach: "C"
  - quickstart: "lls-observability"
    repo: "https://github.com/rh-ai-quickstart/lls-observability"
    notes: "LlamaStack as standalone Helm chart with direct Kubernetes Deployment, Red Hat ET image (quay.io/redhat-et/llama:vllm-0.2.6), OpenTelemetry collector sidecar for distributed tracing, inline Milvus for vector I/O, network policies, and optional MaaS provider"
    approach: "E"
---

# LlamaStack

## Overview

LlamaStack serves as a unified AI orchestration layer in the ai-virtual-agent quickstart, providing a single server that exposes inference, agents, safety, tool runtime, vector I/O, and files APIs. It sits between the FastAPI backend and the underlying model provider (Ollama in local dev) and is consumed through the `llama_stack_client` Python SDK. The backend uses the LlamaStack Responses API with Conversations for streaming chat, MCP tool execution, input shield validation, and model/resource enumeration.

## Tech Stack & Dependencies

- **Runtime:** LlamaStack distribution server v0.6.1
- **Container image:** `docker.io/ogxai/distribution-starter:0.6.1`
- **Key dependencies:** `llama_stack_client==0.6.1` (Python SDK), Ollama as inference provider, SQLite for internal state
- **Helm subchart:** None (deployed as a compose service in local dev)

## Key Patterns

### Distribution Run Configuration

LlamaStack is configured via a YAML run config (`llamastack-run.yaml`) that declares which APIs to expose and wires each API to a specific provider. The config is mounted into the container at runtime.

```yaml
version: 2
image_name: ollama
apis:
- agents
- inference
- safety
- tool_runtime
- vector_io
- files
providers:
  inference:
  - provider_id: ollama
    provider_type: remote::ollama
    config:
      base_url: http://ollama:11434/v1
  safety:
  - provider_id: llama-guard
    provider_type: inline::llama-guard
    config:
      excluded_categories: []
```

The config mounts into the container via a volume bind:

```yaml
# compose.yaml
volumes:
  - ./llamastack-run.yaml:/app-config/config.yaml:Z
environment:
  - RUN_CONFIG_PATH=/app-config/config.yaml
```

### Async Client Factory with Auth Forwarding

The backend creates `AsyncLlamaStackClient` instances that forward Kubernetes service account tokens and user identity headers (`X-Forwarded-User`, `X-Forwarded-Email`) to LlamaStack for RBAC-aware requests.

```python
# backend/app/api/llamastack.py
LLAMASTACK_URL = os.getenv("LLAMASTACK_URL", "http://localhost:8321")
LLAMASTACK_TIMEOUT = float(os.getenv("LLAMASTACK_TIMEOUT", "180.0"))

def get_llamastack_client(
    api_key: Optional[str], headers: Optional[dict[str, str]] = None
) -> AsyncLlamaStackClient:
    client = AsyncLlamaStackClient(
        base_url=LLAMASTACK_URL,
        default_headers=headers or {},
        timeout=httpx.Timeout(LLAMASTACK_TIMEOUT),
    )
    if api_key:
        client.api_key = api_key
    return client
```

A request-scoped factory extracts the SA token from `/var/run/secrets/kubernetes.io/serviceaccount/token` and merges user headers from the incoming HTTP request, while a sync factory adds the `ADMIN_USERNAME` env var for background operations.

### Responses API Streaming with StreamAggregator

The `LlamaStackRunner` uses the LlamaStack Responses API (`client.responses.create`) with Conversations for message history. A `StreamAggregator` class accumulates raw streaming events into simplified SSE events the frontend consumes. It handles reasoning deltas, output text deltas, tool calls (MCP, function, web search, file search), refusal detection, and token usage reporting.

```python
# backend/app/services/runners/llamastack_runner.py
response_params = {
    "model": model_for_request,
    "input": openai_input,
    "stream": True,
}
if tools:
    response_params["tools"] = tools

response_params["conversation"] = conversation_id

async for chunk in await client.responses.create(**response_params):
    chunk_dict = jsonable_encoder(chunk)
    async for simplified_event in aggregator.process_chunk(chunk_dict):
        yield f"data: {json.dumps(simplified_event)}\n\n"
```

### Tool Retry with Automatic Exclusion

When a tool is not found on the LlamaStack server, the runner automatically retries the request with that tool excluded, up to the total number of tools configured.

```python
# backend/app/services/runners/llamastack_runner.py
excluded_tools: set = set()
max_retries = len(tools) if tools else 0

for attempt in range(max_retries + 1):
    current_tools = [
        t for t in (tools or []) if t.get("type") not in excluded_tools
    ]
    # ... stream response ...
    match = re.search(r"Tool '(\w+)' not found", error_obj.get("message", ""))
    if match and attempt < max_retries:
        failed_tool = match.group(1)
        excluded_tools.add(failed_tool)
        retry = True
        break
```

### Input Shield Validation

Before streaming a response, the runner can invoke LlamaStack safety shields to check user input for policy violations. Shields are called via `client.safety.run_shield()` and a violation short-circuits the stream with an error event.

```python
# backend/app/services/runners/llamastack_runner.py
for shield_id in shield_ids:
    shield_response = await client.safety.run_shield(
        shield_id=shield_id,
        messages=[{"role": "user", "content": text_content}],
        params={},
    )
    if hasattr(shield_response, "violation") and shield_response.violation:
        violation_msg = shield_response.violation.user_message
        return {"type": "error", "message": violation_msg}
```

### MCP Tool Integration via Responses API

Tools from virtual agent config are converted to OpenAI Responses API format. MCP tools resolve their `server_url` by querying LlamaStack's toolgroups endpoint at runtime.

```python
# backend/app/services/runners/llamastack_runner.py
elif tool_id.startswith("mcp::"):
    client = get_llamastack_client_from_request(request)
    toolgroups = await client.toolgroups.list()
    for toolgroup in toolgroups:
        if str(toolgroup.identifier) == tool_id:
            responses_tools.append({
                "type": "mcp",
                "server_label": toolgroup.args.get("name", str(toolgroup.identifier)),
                "server_url": toolgroup.mcp_endpoint.uri,
            })
```

### Runner Abstraction (Multi-Framework Support)

LlamaStack is the default runner in a pluggable runner system. The `ChatService` dispatches to `LlamaStackRunner`, `LangGraphRunner`, or `CrewAIRunner` based on the agent's `runner_type` field (defaults to `"llamastack"`).

```python
# backend/app/services/chat.py
if runner_type == "llamastack" or not runner_type:
    return LlamaStackRunner(self.request, self.db, self.user_id)
```

### Resource Enumeration Endpoints

The backend exposes API endpoints that proxy LlamaStack resource listing with version-compatibility helpers that handle attribute name changes between LlamaStack 0.3.x and 0.6.1 (`identifier` vs `id`, `api_model_type` vs `model_type`).

```python
# backend/app/api/v1/llama_stack.py
def _get_model_type(model):
    """Get model type from various API versions"""
    for attr in ("api_model_type", "model_type"):
        val = getattr(model, attr, None)
        if val is not None:
            return val
    meta = getattr(model, "custom_metadata", None) or {}
    return meta.get("model_type")
```

## Configuration

- **Environment variables:**
  - `LLAMASTACK_URL` -- LlamaStack server URL (default: `http://localhost:8321`)
  - `LLAMASTACK_TIMEOUT` -- Client timeout in seconds (default: `180.0`)
  - `LLAMASTACK_PORT` -- Exposed port for LlamaStack server (default: `8321`)
  - `DEFAULT_INFERENCE_MODEL` -- Override model for local dev (e.g., `ollama/llama3.2:1b`)
  - `ADMIN_USERNAME` -- Username for `X-Forwarded-User` header in sync client
  - `TAVILY_API_KEY` -- API key for Tavily web search tool runtime provider
  - `RUN_CONFIG_PATH` -- Path inside container to the distribution run config YAML
- **Config files:**
  - `deploy/local/llamastack-run.yaml` -- Distribution run config defining APIs, providers, storage, registered models, and tool groups
- **Helm values:** N/A (compose-based local deployment)

## Known Gotchas

- The LlamaStack container runs as `user: "0:0"` (root) in compose to avoid permission issues with the `.llama` volume mounts (see `compose.yaml` line 72).
- The `platform: linux/amd64` is explicitly set in compose, meaning ARM-based dev machines (e.g., Apple Silicon) will use emulation, which impacts performance.
- The healthcheck uses a 90-second `start_period` because LlamaStack needs time to initialize providers and download model metadata after Ollama becomes healthy (`compose.yaml` lines 88-90).
- The LlamaStack SDK changed attribute names between versions 0.3.x and 0.6.1 (e.g., `identifier` to `id`, `api_model_type` to `model_type`). The backend has version-compatibility helpers to handle both (`_get_model_type`, `_get_model_id`, `_get_provider_resource_id` in `backend/app/api/v1/llama_stack.py`).
- Storage backends use SQLite by default (`kv_sqlite` and `sql_sqlite` in the run config), which stores state inside the container volume at `/.llama/distributions/ollama/`. This is fine for dev but not for production persistence.
- When `has_output_text` is False after stream completion (e.g., the model only emitted tool calls with no text), the `StreamAggregator` emits an error event telling the user to retry -- this is by design to prevent silent empty responses (`llamastack_runner.py` lines 365-370).
- The tool retry mechanism parses error messages with regex (`Tool '(\w+)' not found`) which is fragile if LlamaStack changes its error message format.

## Testing Notes

- Unit tests mock the LlamaStack client using `_MockLlamaClient` stubs that expose `.models.list()`, `.vector_stores.list()`, and `.toolgroups.list()` as async coroutines returning Pydantic models (see `tests/unit/test_llamastack_endpoints.py`).
- The mock pattern uses a `_Proxy(list)` subclass that adds an async `list()` method returning itself, enabling `await client.models.list()` to work on a plain list.
- Healthcheck endpoint: `curl -f http://localhost:8321/v1/health`
- After deployment, verify model registration: the compose entrypoint runs `ollama run llama3.2:1b --keepalive 60m hi` to ensure the model is pulled and warm before LlamaStack starts.

## Related Patterns

- Architecture: agent orchestration, multi-runner framework dispatch
- Deployment: compose-based local dev with service dependency chains
- Components: ollama (inference backend), postgresql (session/agent storage)

---

## Approach B: OpenShift AI Operator + Helm Chart with vLLM (from data-governance-co-pilot)

### When to Use

Use this approach when deploying LlamaStack on OpenShift AI with the Llama Stack operator, using remote vLLM for inference and Helm for chart management. This is the production-oriented path that leverages the operator's CRD (`LlamaStackDistribution`) to manage the LlamaStack lifecycle on-cluster.

### Differences from Approach A

- **Deployment**: Helm chart creating a `LlamaStackDistribution` CRD (managed by OpenShift AI operator) instead of docker-compose service
- **Inference provider**: `remote::vllm` instead of `remote::ollama`
- **API version**: LlamaStack 0.3.5 with `alpha.agents` API (agent-managed agentic loop) instead of 0.6.1 Responses API
- **MCP integration**: Configured as a provider in the run.yaml ConfigMap at deploy time, not resolved dynamically from toolgroups
- **Storage paths**: Operator-provided volume mount at `/opt/app-root/src/.llama/distributions/rh/` instead of container-local `/.llama/distributions/ollama/`
- **Security**: Kubernetes Secrets for vLLM API keys, OpenShift Routes with TLS edge termination

### Tech Stack & Dependencies

- **Runtime:** LlamaStack distribution server v0.3.5
- **Container image:** Operator-managed (distribution `imageName: "rh-dev"`)
- **Key dependencies:** `llama_stack_client` (Python SDK), vLLM model server via KServe InferenceService, MCP server (`pg-airman-mcp-service`)
- **Helm subchart:** None (standalone chart at `helm/copilot-llama-stack/`)

### Key Patterns

#### LlamaStackDistribution CRD Deployment

The chart deploys a `LlamaStackDistribution` custom resource that the OpenShift AI Llama Stack operator reconciles into a running deployment. The CRD references a ConfigMap containing the `run.yaml` distribution config.

```yaml
# templates/llamastackdistribution.yaml
apiVersion: llamastack.io/v1alpha1
kind: LlamaStackDistribution
metadata:
  name: {{ .Values.distribution.name }}
spec:
  replicas: {{ .Values.distribution.replicas }}
  server:
    distribution:
      name: {{ .Values.distribution.imageName | quote }}
    userConfig:
      configMapName: {{ .Values.distribution.name }}-config
    containerSpec:
      name: {{ .Values.container.name }}
      port: {{ .Values.container.port }}
```

#### Run Config via Helm-Templated ConfigMap

The `run.yaml` is generated as a ConfigMap using Helm templating. Environment variable references (`${env.VLLM_URL}`, `${env.INFERENCE_MODEL}`) are resolved at runtime by LlamaStack, not by Helm.

```yaml
# templates/configmap.yaml (abbreviated)
providers:
  inference:
    - provider_id: vllm-inference
      provider_type: remote::vllm
      config:
        url: ${env.VLLM_URL}
        api_token: ${env.VLLM_API_TOKEN}
        model: ${env.INFERENCE_MODEL}
  tool_runtime:
    - provider_id: mcp-tools
      provider_type: remote::model-context-protocol
      config:
        mcp_endpoint:
          uri: {{ include "copilot-llama-stack.mcpEndpoint" . }}
```

#### Model Name Prefixing for vLLM Provider

LlamaStack 0.3.x requires the model name to be prefixed with the provider ID when passed as `INFERENCE_MODEL`. The Helm template handles this in the `LlamaStackDistribution` env vars.

```yaml
# templates/llamastackdistribution.yaml
env:
  - name: INFERENCE_MODEL
    value: {{ printf "vllm-inference/%s" .Values.model.name | quote }}
```

#### vLLM URL Resolution with Fallback

The `_helpers.tpl` constructs the vLLM URL from either an explicit override or by deriving it from the KServe InferenceService predictor name.

```yaml
# templates/_helpers.tpl
{{- define "copilot-llama-stack.vllmUrl" -}}
{{- if .Values.model.url }}
{{- .Values.model.url }}
{{- else }}
{{- printf "https://%s-predictor.%s.svc.cluster.local:8443/v1" .Values.model.name .Release.Namespace }}
{{- end }}
{{- end }}
```

#### Agents Alpha API with Session Management

The Python provider uses LlamaStack's `alpha.agents` API where LlamaStack manages the complete agentic loop. The provider creates a persistent agent with toolgroups and manages session-to-conversation mapping.

```python
# packages/copilot/src/copilot/providers/llama_stack.py
agent = self.client.alpha.agents.create(
    agent_config={
        "model": self.llama_stack_model,
        "instructions": self.get_system_prompt(enable_reasoning=True),
        "toolgroups": [self.toolgroup_id],
        "tool_choice": "auto",
        "sampling_params": {
            "max_tokens": 2048,
            "temperature": self.temperature,
            "min_p": self.min_p,
        },
    }
)
```

#### Makefile-Driven Model Configuration

Model values (`model.name`, `model.url`, `model.apiKey`) are not stored in `values.yaml` -- they are populated at install time by the Makefile, which either extracts them from a deployed KServe InferenceService or reads them from `copilot-backend/values.yaml`.

```makefile
# helm/Makefile (copilot-llama-stack-install target)
MODEL_URL="https://$$(oc get route $$MODEL_NAME -o jsonpath='{.spec.host}' -n $(NAMESPACE))/v1"; \
MODEL_API_KEY=$$(oc get secret default-name-$$MODEL_NAME-sa -n $(NAMESPACE) \
  -o jsonpath='{.data.token}' | base64 -d); \
helm upgrade --install $(LLAMA_STACK_DISTRIBUTION_NAME) $(COPILOT_LLAMA_STACK_CHART) \
  --set model.name=$$MODEL_NAME \
  --set model.url=$$MODEL_URL \
  --set model.apiKey=$$MODEL_API_KEY
```

#### Event Mapping from Agents API to Standardized Schema

The provider maps LlamaStack agent events (`step_start`, `step_progress`, `step_complete`, `turn_complete`) to a standardized event schema consumed by the frontend. Tool execution steps do not emit new `iteration_start` events -- they belong to the same iteration as the inference step that triggered them.

```python
# packages/copilot/src/copilot/providers/llama_stack.py
if event_type == "step_start":
    step_type = payload.step_type if hasattr(payload, 'step_type') else "unknown"
    if step_type != "tool_execution":
        return [{"type": "iteration_start", "step_type": step_type}]
    else:
        return []
```

### Configuration

- **Environment variables (container):**
  - `INFERENCE_MODEL` -- Model name prefixed with provider ID (e.g., `vllm-inference/qwen3-model`)
  - `VLLM_URL` -- vLLM service endpoint URL
  - `VLLM_API_TOKEN` -- API token from Kubernetes Secret or `"not-needed"`
  - `VLLM_TLS_VERIFY` -- Set to `'false'` for cluster-internal TLS
- **Environment variables (backend):**
  - `COPILOT_PROVIDER_MODE` -- Set to `llama_stack` to activate this provider
  - `LLAMA_STACK_BASE_URL` -- LlamaStack endpoint (default: `http://copilot-llama-stack:8000`)
  - `LLAMA_STACK_MODEL` -- Model identifier (default: `vllm-inference/redhataillama-31-8b-instruct`)
- **Config files:** `run.yaml` generated as ConfigMap from Helm values
- **Helm values:**
  - `distribution.name` -- CRD resource name (default: `copilot-llama-stack`)
  - `distribution.imageName` -- Distribution image name (default: `rh-dev`)
  - `container.port` -- Service port (default: `8321`)
  - `model.name`, `model.url`, `model.apiKey` -- Populated at install time via Makefile
  - `mcp.serviceName` -- MCP server K8s service name (default: `pg-airman-mcp-service`)
  - `config.apis` -- List of APIs to enable (inference, agents, safety, vector_io, tool_runtime)
  - `route.enabled` -- Create OpenShift Route (default: `true`)

### Known Gotchas

- Nemotron models are incompatible with `llama_stack` mode because they use a custom `<TOOLCALL>` format that LlamaStack does not support. The Makefile enforces this with `check-model-provider-compatibility` (see `helm/Makefile` line 221). Use `PROVIDER_MODE=mcp_direct` for Nemotron or `PROVIDER_MODE=llama_stack` with Qwen3.
- LlamaStack agent instructions are static and set at agent creation time. Updating the governance policy requires recreating the agent, which invalidates all existing sessions. The `requires_conversation_restart_on_policy_update()` method returns `True` for this reason (see `llama_stack.py` line 685).
- The `model.name`, `model.url`, and `model.apiKey` values in `values.yaml` are intentionally empty placeholders. They are populated at deploy time by the Makefile via `--set` flags. Installing the chart directly without the Makefile will result in a broken deployment.
- LlamaStack is described as a "lightweight proxy" in the values.yaml comments -- resource requests are only 100m CPU / 256Mi memory, with limits of 500m CPU / 512Mi (see `values.yaml` lines 14-18). This is because it delegates inference to the vLLM model server.
- The `oc wait` for LlamaStack readiness checks `.status.conditions[?(@.type=="DeploymentReady")].status=True` on the `LlamaStackDistribution` CRD with a 600-second timeout (`helm/Makefile` line 754).
- The vLLM URL helper (`copilot-llama-stack.vllmUrl`) defaults to constructing a KServe predictor URL at port 8443 (`https://<model>-predictor.<ns>.svc.cluster.local:8443/v1`) when no explicit URL is provided (see `_helpers.tpl` line 65).
- `VLLM_TLS_VERIFY` is set to `'false'` in the container env because cluster-internal TLS uses self-signed certificates from the KServe predictor service.

### Testing Notes

- Verify `LlamaStackDistribution` status: `oc get llamastackdistribution copilot-llama-stack -n <ns>`
- Check API health: `curl -k https://$ROUTE_URL/v1/version`
- Verify MCP connectivity: ensure `pg-airman-mcp-service` is running in the same namespace before deploying LlamaStack
- The uninstall target also cleans up PVCs owned by the `LlamaStackDistribution` resource (`helm/Makefile` copilot-llama-stack-uninstall target)

---

## Approach C: ai-architecture-charts Helm Subchart with Dual-Client Pattern (from f5-ai-guardrails)

### When to Use

Use this approach when deploying LlamaStack as a shared Helm subchart from `ai-architecture-charts` alongside other subcharts (`llm-service`, `pgvector`), with a Streamlit frontend that communicates via both the LlamaStack Python SDK and the OpenAI Python SDK. This is the pattern for RAG applications where LlamaStack provides OpenAI-compatible chat completions plus native vector DB and tool runtime APIs, optionally routed through an external guardrails proxy.

### Differences from Approach A

- **Deployment**: `ai-architecture-charts` Helm subchart (`llama-stack` v0.8.6) instead of docker-compose service
- **Client pattern**: Dual clients (`LlamaStackClient` for resource management + `OpenAI` SDK for chat completions) instead of single `AsyncLlamaStackClient` with Responses API
- **Frontend**: Streamlit app (`llama_stack_ui`) talks directly to LlamaStack instead of going through a FastAPI backend
- **Model configuration**: `global.models` Helm values shared across `llm-service` and `llama-stack` subcharts instead of per-provider run.yaml
- **RAG**: Uses LlamaStack's tool_runtime rag_tool insert/query endpoints for document management instead of vector_io only

### Differences from Approach B

- **Deployment**: `ai-architecture-charts` shared subchart instead of standalone chart creating a `LlamaStackDistribution` CRD
- **LlamaStack version**: 0.6+ (subchart default image `ogxai/distribution-starter:0.6.1`) instead of 0.3.5
- **Client API**: OpenAI-compatible `/v1/chat/completions` for inference instead of `alpha.agents` API
- **Lifecycle**: Helm manages the Deployment directly instead of an operator reconciling a CRD

### Tech Stack & Dependencies

- **Runtime:** LlamaStack distribution server (subchart default: `ogxai/distribution-starter:0.6.1`)
- **Container image:** Managed by `ai-architecture-charts` `llama-stack` subchart
- **Key dependencies:** `llama-stack-client==0.6.0`, `openai` Python SDK, `httpx`, `streamlit` (frontend)
- **Helm subchart:** `llama-stack` v0.8.6 from `https://rh-ai-quickstart.github.io/ai-architecture-charts`

### Key Patterns

#### Shared Helm Subchart Deployment

LlamaStack is declared as a dependency in `Chart.yaml` alongside `pgvector` and `llm-service`, all from the same chart repository. The `global.models` values map is shared between `llm-service` (which deploys vLLM model servers) and `llama-stack` (which registers them as providers).

```yaml
# deploy/helm/rag/Chart.yaml
dependencies:
  - name: pgvector
    version: 0.1.0
    repository: https://rh-ai-quickstart.github.io/ai-architecture-charts
  - name: llm-service
    version: 0.5.2
    repository: https://rh-ai-quickstart.github.io/ai-architecture-charts
  - name: llama-stack
    version: 0.8.6
    repository: https://rh-ai-quickstart.github.io/ai-architecture-charts
```

#### Dual-Client Pattern (LlamaStackClient + OpenAI SDK)

The frontend uses two client types: `LlamaStackClient` for native LlamaStack APIs (models, vector DBs, tool groups, RAG tool operations) and `OpenAI` for chat completions via the OpenAI-compatible `/v1/chat/completions` endpoint on LlamaStack 0.6+.

```python
# frontend/llama_stack_ui/distribution/ui/modules/api.py
class LlamaStackApi:
    def __init__(self):
        base = os.environ.get("LLAMA_STACK_ENDPOINT", "http://localhost:8321")
        token = os.environ.get("LLAMA_STACK_API_TOKEN", "")
        self.client = self.create_client_with_url(base, token)

    def create_openai_client_for_llamastack(self, base_url: str = "", api_token: str = "") -> OpenAI:
        """Create an OpenAI client targeting LlamaStack chat at {origin}/v1/chat/completions."""
        raw = base_url or os.environ.get("LLAMA_STACK_ENDPOINT", "http://localhost:8321")
        openai_base = llamastack_openai_chat_base_url(raw)
        hx = _httpx_client_for_url(origin) or httpx.Client(follow_redirects=True, timeout=_HTTPX_TIMEOUT)
        return OpenAI(base_url=openai_base, api_key=api_token or "no-key", http_client=hx)
```

#### URL Normalization for LlamaStack 0.6+

LlamaStack 0.6+ serves chat at `/v1/chat/completions`. Older builds used `/v1/openai/v1/...`. The frontend includes a normalization function that strips legacy suffixes and ensures the base_url ends with `/v1` for the OpenAI Python SDK.

```python
# frontend/llama_stack_ui/distribution/ui/modules/api.py
_LLAMA_OPENAI_SDK_SUFFIX = "/v1"

def llamastack_openai_chat_base_url(endpoint: str) -> str:
    u = (endpoint or "").strip().rstrip("/")
    legacy = "/v1/openai/v1"
    while u.endswith(legacy):
        u = u[: -len(legacy)].rstrip("/")
    if not u.endswith(suf):
        u = u + suf
    return u
```

#### HTTPX Client Factory for Cluster TLS

OpenShift edge routes use HTTPS with cluster-signed certificates. The frontend creates HTTPX clients with `verify=False` for HTTPS endpoints and relaxed redirects, while keeping defaults for local dev.

```python
# frontend/llama_stack_ui/distribution/ui/modules/api.py
def _httpx_client_for_url(url: str) -> httpx.Client | None:
    u = (url or "").lower().rstrip("/")
    if "localhost" in u or "127.0.0.1" in u:
        return httpx.Client(follow_redirects=True, timeout=_HTTPX_TIMEOUT)
    if u.startswith("http://llamastack") and ".apps." not in u:
        return httpx.Client(follow_redirects=True, timeout=_HTTPX_TIMEOUT)
    if u.startswith("http://") or u.startswith("https://"):
        return httpx.Client(verify=False, follow_redirects=True, timeout=_HTTPX_TIMEOUT)
    return None
```

#### Vector DB Operations with Fallback

The frontend lists vector databases using the `vector_dbs` resource when available, falling back to the OpenAI-compatible `vector_stores` endpoint for LlamaStack 0.6+ distributions that may not expose `/v1/vector-dbs`.

```python
# frontend/llama_stack_ui/distribution/ui/modules/api.py
def list_vector_catalog(client: LlamaStackClient) -> List[Any]:
    vd = getattr(client, "vector_dbs", None)
    if vd is not None:
        return list(vd.list()) if vd.list() is not None else []
    try:
        raw = client.get("/v1/vector-dbs", cast_to=object)
    except Exception as e:
        if getattr(e, "status_code", None) == 404:
            return _vector_catalog_from_vector_stores(client)
        raise
```

#### Guardrails Proxy Dual-Panel Comparison

The Chat page sends the same prompt to both the F5 AI Guardrails Moderator endpoint and the direct LlamaStack endpoint, displaying results side by side. Both paths use the OpenAI `chat.completions.create()` API but with different base URLs.

```python
# frontend/llama_stack_ui/distribution/ui/page/playground/chat.py
# F5 Guardrails path (OpenAI client → Moderator proxy → LlamaStack → vLLM)
f5_oai = llama_stack_api.create_openai_client(f5_ep.strip(), f5_tk.strip())
resp = f5_oai.chat.completions.create(model=f5_model, messages=messages_for_api, ...)

# Direct LlamaStack path (OpenAI client → LlamaStack /v1/chat/completions → vLLM)
ls_oai = llama_stack_api.create_openai_client_for_llamastack(...)
resp = ls_oai.chat.completions.create(model=ls_model, messages=messages_for_api, ...)
```

#### Auto-Detection of LlamaStack Route

The `start.sh` script auto-detects the LlamaStack endpoint from the OpenShift route `llamastack-http`, detecting TLS edge termination to use the correct protocol.

```bash
# frontend/start.sh
ROUTE_HOST=$(oc get route llamastack-http -n "$_NS" -o jsonpath='{.spec.host}')
TLS=$(oc get route llamastack-http -n "$_NS" -o jsonpath='{.spec.tls.termination}')
if [ -n "$TLS" ] && [ "$TLS" != "null" ]; then
    export LLAMA_STACK_ENDPOINT="https://$ROUTE_HOST"
else
    export LLAMA_STACK_ENDPOINT="http://$ROUTE_HOST"
fi
```

### Configuration

- **Environment variables:**
  - `LLAMA_STACK_ENDPOINT` -- LlamaStack server URL (default: `http://llamastack:8321`); auto-detected from OpenShift route by `start.sh`
  - `LLAMA_STACK_API_TOKEN` -- Optional bearer token for LlamaStack
  - `F5_GUARDRAIL_URL` -- F5 AI Guardrails Moderator endpoint (persisted to `guardrails_state.json`)
  - `F5_GUARDRAIL_API_TOKEN` -- Bearer token for the Moderator proxy
  - `F5_GUARDRAILS_STATE_FILE` -- Path to persist guardrail URL and token (default: `/data/guardrails_state.json`)
- **Config files:**
  - Subchart defaults managed by `ai-architecture-charts`; no local `run.yaml` needed
- **Helm values:**
  - `global.models` -- Shared model map controlling both `llm-service` (vLLM ServingRuntimes) and `llama-stack` (model registration)
  - `llm-service.secret.hf_token` -- Hugging Face token for model downloads
  - `llama-stack.rawDeploymentMode` -- Toggle raw deployment mode (bypasses KServe)
  - `llama-stack.secrets` -- Extra environment variables as JSON (via `LLAMA_STACK_ENV` Makefile var)

### Known Gotchas

- The `LLAMA_STACK_ENDPOINT` env var in the parent chart's `values.yaml` points to `http://llamastack:8321` (in-cluster service name). When running the frontend locally with `dev-on-cluster.sh`, the script auto-detects the route or uses `PORT_FORWARD=1` to tunnel to the cluster service (`deploy/helm/rag/values.yaml` line 27, `frontend/dev-on-cluster.sh`).
- The Makefile `logs` target shows logs from the LlamaStack pod specifically (`oc logs -n $(NAMESPACE) -l app=llamastack`) and the `install` target waits for `oc rollout status deploy/llamastack` with a 900-second timeout (`deploy/helm/Makefile` lines 467, 584).
- The `guardrails_state.json` file is stored on an `emptyDir` volume at `/data`. If the pod is replaced, the persisted F5 Guardrails URL and API token are lost. Use a PVC on `/data` for persistence across rescheduling (`deploy/helm/rag/values.yaml` comment on line 38).
- LlamaStack 0.6+ changed the chat completions path from `/v1/openai/v1/chat/completions` to `/v1/chat/completions`. The URL normalization function strips legacy suffixes, but if users paste old-format URLs from documentation, they must be normalized before use (`frontend/llama_stack_ui/distribution/ui/modules/api.py` lines 32-54).
- The `vector_dbs` resource may not exist on all LlamaStack 0.6+ distributions (e.g., the `distribution-starter` image). The code falls back to `client.vector_stores.list()` (OpenAI-compatible endpoint) when `/v1/vector-dbs` returns 404 (`api.py` lines 270-301).

### Testing Notes

- Verify LlamaStack is running after Helm install: `oc rollout status deploy/llamastack -n <namespace>`
- Check LlamaStack health: `oc logs -n <namespace> -l app=llamastack --tail=100`
- Test OpenAI compatibility: `curl -sk https://<route>/v1/models` should return registered models
- The `dev-on-cluster.sh` script provides local development against a cluster-deployed LlamaStack (`NAMESPACE=my-rag ./dev-on-cluster.sh`)

### Additional Patterns from RAG Quickstart

#### File Processors Configuration

The `llama-stack` subchart supports inline file processors for document extraction. The RAG quickstart enables PyPDF for PDF processing via Helm values.

```yaml
# deploy/helm/rag/values.yaml
llama-stack:
  fileProcessors:
    enabled: true
    providers:
      - provider_id: pypdf
        provider_type: inline::pypdf
```

#### Vector DB Register + RAG Tool Insert/Query Workflow

The RAG quickstart demonstrates the full lifecycle of LlamaStack vector database operations: registering a vector DB with the pgvector provider, inserting documents via the `tool_runtime.rag_tool`, and querying. The embedding dimension 384 corresponds to the `all-MiniLM-L6-v2` model.

```python
# client-examples-python/rag-create-vector-db.py
client.vector_dbs.register(
    vector_db_id=vector_db_id,
    embedding_dimension=384,
    embedding_model="all-MiniLM-L6-v2",
    provider_id="pgvector"
)
client.tool_runtime.rag_tool.insert(
    documents=documents,
    vector_db_id=vector_db_id,
    chunk_size_in_tokens=512,
)
```

Querying uses a separate `tool_runtime.rag_tool.query` call, then passes the retrieved context as a system message to `client.chat.completions.create()`:

```python
# client-examples-python/rag-use-vector-db.py
rag_response = client.tool_runtime.rag_tool.query(
    content=user_query,
    vector_db_ids=[vector_db_id]
)
completion = client.chat.completions.create(
    model=INFERENCE_MODEL,
    messages=[
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": f"Context: {rag_response.content}\nQuestion: {user_query}"},
    ],
    temperature=0.1,
)
```

#### Client Timeout for Large Document Uploads

The frontend sets a 600-second (10-minute) timeout on the LlamaStackClient for large document uploads, overriding the default 60 seconds.

```python
# frontend/llama_stack_ui/distribution/ui/modules/api.py
timeout = float(os.environ.get("LLAMA_STACK_TIMEOUT", "600"))
self.client = LlamaStackClient(
    base_url=os.environ.get("LLAMA_STACK_ENDPOINT", "http://localhost:8321"),
    timeout=timeout,
    provider_data={
        "tavily_search_api_key": os.environ.get("TAVILY_SEARCH_API_KEY", ""),
    },
)
```

#### MaaS E2E Testing with initContainers Override

For Kind-based e2e tests using Model-as-a-Service (MaaS) instead of local model serving, the llama-stack subchart's init containers are overridden to empty and model waiting is skipped, since models are external.

```yaml
# tests/integration/llamastack/values-e2e.yaml
llama-stack:
  enabled: true
  initContainers: []
  skipModelWait: true
  resources:
    requests:
      memory: "512Mi"
      cpu: "500m"
    limits:
      memory: "1Gi"
      cpu: "1"
```

In the GitHub Actions workflow, this is applied via `--set-json llama-stack.initContainers='[]'`.

#### OpenAI Base URL Auto-Detection with Fallback Candidates

Integration tests auto-detect the correct OpenAI-compatible base URL by trying multiple candidate paths, since LlamaStack changed from `/v1/openai/v1` to `/v1` between versions.

```python
# tests/integration/llamastack/test_user_workflow.py
openai_base_candidates = []
if explicit_openai:
    openai_base_candidates.append(explicit_openai.rstrip("/"))
openai_base_candidates.append(f"{endpoint}/v1")
openai_base_candidates.append(f"{endpoint}/v1/openai/v1")

for base in openai_base_candidates:
    candidate = OpenAI(api_key="not_needed", base_url=base, timeout=30.0)
    try:
        models = candidate.models.list()
        client = candidate
        break
    except Exception:
        continue
```

#### TAVILY Secrets Management via Helm Values

The TAVILY web search API key is managed through `llama-stack.secrets` in Helm values and also injected into the parent chart's deployment template so both LlamaStack and the frontend have access.

```yaml
# deploy/helm/rag/templates/deployment.yaml
{{- if (index .Values "llama-stack").secrets.TAVILY_SEARCH_API_KEY }}
- name: TAVILY_SEARCH_API_KEY
  value: {{ (index .Values "llama-stack").secrets.TAVILY_SEARCH_API_KEY | quote }}
{{- end }}
```

The Makefile supports injecting secrets at install time via `LLAMA_STACK_ENV` JSON:

```makefile
# deploy/helm/Makefile
$(if $(LLAMA_STACK_ENV),--set-json llama-stack.secrets='$(LLAMA_STACK_ENV)',)
```

### Additional Gotchas from RAG Quickstart

- The `llama-stack-client` version pinning differs between the frontend (`0.6.0` in `pyproject.toml`) and integration tests (`>=0.2.9,<0.2.13` in `tests/integration/llamastack/requirements.txt`). The frontend ships with `llama-stack==0.6.0` (server) plus `llama-stack-client==0.6.0` (client SDK), while integration tests use an older client range compatible with the deployed server.
- The `LLAMA_STACK_ENDPOINT` env var name differs between contexts: `LLAMA_STACK_ENDPOINT` in the frontend and tests, but `LLAMA_STACK_SERVER` in the client-examples-python scripts. Both point to the same LlamaStack server at port 8321.
- LlamaStack models may use `identifier` (older API) or `id` (newer API) as the model ID attribute. The e2e tests handle both: `model_ids = [getattr(model, 'identifier', getattr(model, 'id', None)) for model in models.data]` (see `tests/integration/llamastack/test_user_workflow.py`).
- The LlamaStack server does not require an API key for in-cluster communication. The OpenAI client uses `api_key="not-needed"` or `api_key="no-key"` as a placeholder (see `conftest.py` and `api.py`).
- Deploying on Kind for e2e tests requires installing the OpenShift Route CRD (`route.openshift.io`) as a stub since the Helm chart templates reference it, even though Routes are not functional in Kind (see `.github/workflows/e2e-tests.yaml`).
- The `rawDeploymentMode` toggle is passed to both `llm-service` and `llama-stack` subcharts via the Makefile to bypass KServe when deploying in non-OpenShift environments (see `deploy/helm/Makefile` lines 629-630).

---

## Approach D: Helm Subchart with Responses API and PostgreSQL Persistence (from it-self-service-agent)

### When to Use

Use this approach when deploying LlamaStack as an ai-architecture-charts Helm subchart with the Responses API for agentic workflows, PostgreSQL-backed persistence for multi-replica horizontal scaling, MCP tool integration and knowledge base file_search via the responses tools array, and a post-init scaler Job that coordinates initialization before scaling up replicas. This is the pattern for production multi-agent applications where multiple llama-stack replicas share state through PostgreSQL.

### Differences from Approach A

- **Deployment**: ai-architecture-charts Helm subchart (`llama-stack` v0.8.5) instead of docker-compose service
- **Persistence**: PostgreSQL for metadata store, vector_io kvstore, agent state, and responses instead of SQLite
- **Multi-replica**: Supports horizontal scaling with emptyDir volumes (no shared PVC needed since state is in PostgreSQL)
- **Service discovery**: Kubernetes auto-injected env vars (`LLAMASTACK_SERVICE_HOST`, `LLAMASTACK_SERVICE_PORT`) instead of hardcoded compose URLs
- **Client pattern**: Centralized factory module (`llamastack_client.py`) producing sync, async, and OpenAI-compatible clients

### Differences from Approach C

- **Client API**: Responses API (`client.responses.create()`) for agentic inference instead of OpenAI `chat.completions.create()`
- **Agent management**: Custom `Agent` class managing tools, retries, and temperature per agent config instead of direct chat
- **Persistence**: Explicit PostgreSQL configuration for metadata, kvstore, and SQL backends instead of subchart defaults
- **Scaling**: Post-init scaler Helm hook Job that waits for asset registration before scaling to target replicas
- **Tools**: Combined MCP server tools and file_search (vector store) tools passed to the Responses API instead of separate RAG tool queries

### Tech Stack & Dependencies

- **Runtime:** LlamaStack distribution server (subchart default image)
- **Container image:** Managed by `ai-architecture-charts` `llama-stack` subchart v0.8.5
- **Key dependencies:** `llama-stack-client==0.5.0` (Python SDK), `openai` Python SDK, `llm-service` subchart for vLLM
- **Helm subchart:** `llama-stack` v0.8.5 from `https://rh-ai-quickstart.github.io/ai-architecture-charts`

### Key Patterns

#### Centralized Client Factory with Kubernetes Auto-Discovery

All LlamaStack client creation goes through a factory module that automatically uses Kubernetes-injected service environment variables. The factory produces three client types: native sync, native async, and OpenAI-compatible.

```python
# agent-service/src/agent_service/utils/llamastack_client.py
# Host: Use Kubernetes auto-injected LLAMASTACK_SERVICE_HOST
host = llamastack_host or os.environ.get("LLAMASTACK_SERVICE_HOST", "llamastack")

# Port: Check Helm override first, then Kubernetes auto-injected, then default
# Note: We avoid LLAMASTACK_PORT as Kubernetes sets it to "tcp://host:port" format
port_str = os.environ.get("LLAMASTACK_CLIENT_PORT") or os.environ.get(
    "LLAMASTACK_SERVICE_PORT", "8321"
)
```

The OpenAI-compatible client targets the `/v1/openai/v1` base path on the LlamaStack server and uses a dummy API key since in-cluster communication does not require authentication.

```python
# agent-service/src/agent_service/utils/llamastack_client.py
base_url = f"http://{host}:{port_num}{path}"
return openai.OpenAI(
    api_key=key,  # default: "dummy-key"
    base_url=base_url,
    timeout=timeout_val,
)
```

#### Responses API with MCP and File Search Tools

The Agent class uses `client.responses.create()` with a tools array that combines MCP server tools and file_search tools (for knowledge base vector stores). MCP tools include dynamic per-request headers for user identity, tracing context, and ServiceNow API keys.

```python
# agent-service/src/agent_service/langgraph/responses_agent.py
if tools_to_use:
    response = await self.async_llama_client.responses.create(
        input=messages_with_system,
        model=self.model,
        **response_config,
        tools=tools_to_use,
    )
```

Knowledge base tools are built from vector store IDs discovered at runtime:

```python
# agent-service/src/agent_service/langgraph/responses_agent.py
knowledge_base_tool = {
    "type": "file_search",
    "vector_store_ids": vector_store_ids,
}
tools_to_use.append(knowledge_base_tool)
```

MCP tools include headers built dynamically per request:

```python
# agent-service/src/agent_service/langgraph/responses_agent.py
mcp_tool: Dict[str, Any] = {
    "type": "mcp",
    "server_label": server_name,
    "server_url": server_uri,
    "require_approval": server_config.get("require_approval", "never"),
}
if authoritative_user_id:
    tool_headers["AUTHORITATIVE_USER_ID"] = authoritative_user_id
```

#### PostgreSQL Persistence for Multi-Replica Support

All LlamaStack internal state is backed by PostgreSQL (via the shared pgvector subchart) instead of SQLite. This enables multiple llama-stack replicas to share state. Volumes use `emptyDir` instead of PVC since no shared filesystem is needed.

```yaml
# helm/values.yaml
llama-stack:
  metadataStore:
    type: postgres
    db_path: null  # Explicitly unset SQLite field
    host: ${env.POSTGRES_HOST:=pgvector}
    port: ${env.POSTGRES_PORT:=5432}
    db: ${env.POSTGRES_DBNAME:=rag_blueprint}
    namespace: llamastack_registry

  storage:
    backends:
      kv_default:
        type: kv_postgres
        host: ${env.POSTGRES_HOST:=pgvector}
        db: llama_agents
      sql_default:
        type: sql_postgres
        host: ${env.POSTGRES_HOST:=pgvector}
        db: llama_responses
```

The pgvector chart creates dedicated databases for LlamaStack agent persistence:

```yaml
# helm/values.yaml
pgvector:
  args:
    - "-c"
    - "max_connections=200"
  extraDatabases:
    - name: llama_agents
      vectordb: false
    - name: llama_responses
      vectordb: false
```

#### Post-Init Scaler Helm Hook

A Kubernetes Job runs as a Helm post-install/post-upgrade hook. It waits for the init job (which registers knowledge bases and assets with LlamaStack) to complete, then scales the llama-stack deployment to the target replica count. This is triggered when `REPLICA_COUNT` is set in the Makefile.

```yaml
# helm/templates/llama-stack-post-init-scaler-job.yaml
{{- if .Values.llamastack.postInitScaling.enabled }}
apiVersion: batch/v1
kind: Job
metadata:
  annotations:
    "helm.sh/hook": post-install,post-upgrade
    "helm.sh/hook-weight": "10"
spec:
  template:
    spec:
      containers:
      - name: scale-deployment
        image: bitnami/kubectl:latest
        env:
        - name: DEPLOYMENT_NAME
          value: "llamastack"
        - name: TARGET_REPLICAS
          value: {{ .Values.llamastack.postInitScaling.targetReplicas | quote }}
```

The scaler has its own ServiceAccount, Role (get/list/watch jobs, get/patch/update deployments), and RoleBinding created via pre-install hooks.

#### Knowledge Base Registration via OpenAI-Compatible API

The init job registers knowledge bases by creating vector stores through LlamaStack's OpenAI-compatible API, specifying `provider_id: pgvector` in the extra_body to route storage to the PostgreSQL-backed pgvector provider.

```python
# agent-service/src/agent_service/knowledge/kb_manager.py
vector_store = self._llama_client.vector_stores.create(
    name=vector_store_name, extra_body={"provider_id": "pgvector"}
)
# Upload files to vector store
with open(file_path, "rb") as f:
    file_create_response = self._llama_client.files.create(
        file=f, purpose="assistants"
    )
self._llama_client.vector_stores.files.create(
    vector_store_id=vector_store_id, file_id=file_id
)
```

#### Lazy Model Discovery

The Agent class defers model selection to first use. When no model is configured in the agent YAML, it queries LlamaStack for the first available LLM model via `models.list()` filtering by `custom_metadata.model_type == "llm"`.

```python
# agent-service/src/agent_service/langgraph/responses_agent.py
models = await self.async_llama_client.models.list()
model_id = next(
    m.id
    for m in models
    if m.custom_metadata and m.custom_metadata.get("model_type") == "llm"
)
```

#### Retry with Exponential Backoff

The `create_response_with_retry` method wraps response creation with configurable retries (default 3), exponential backoff (1s, 2s, 4s, 8s, capped at 16s), and distinguishes between empty responses, error responses, and exceptions.

### Configuration

- **Environment variables:**
  - `LLAMASTACK_SERVICE_HOST` -- Kubernetes auto-injected hostname (default: `llamastack`)
  - `LLAMASTACK_SERVICE_PORT` -- Kubernetes auto-injected port (default: `8321`)
  - `LLAMASTACK_CLIENT_PORT` -- Helm-configurable port override (takes precedence over `SERVICE_PORT`)
  - `LLAMASTACK_API_KEY` -- API key (default: `dummy-key`; not required in-cluster)
  - `LLAMASTACK_OPENAI_BASE_PATH` -- OpenAI API path (default: `/v1/openai/v1`)
  - `LLAMASTACK_TIMEOUT` -- Request timeout in seconds (default: `120`)
  - `LLAMA_STACK_URL` -- Used by the init job for readiness polling (default: `http://llamastack:8321`)
  - `USE_NEMO_GUARDRAILS` -- Enable NeMo Guardrails safety checks on input/output (default: disabled)
- **Config files:**
  - `agent-service/config/agents/*.yaml` -- Agent definitions with model, system_message, mcp_servers, knowledge_bases
- **Helm values:**
  - `llama-stack.replicaCount` -- Initial replica count (default: `1`, scaled up by post-init job)
  - `llama-stack.metadataStore` -- PostgreSQL connection for LlamaStack metadata registry
  - `llama-stack.storage.backends` -- `kv_postgres` and `sql_postgres` backends for agent and responses state
  - `llama-stack.volumes` -- Override to `emptyDir` instead of PVC for multi-replica support
  - `llamastack.postInitScaling.enabled` -- Enable post-init scaling (default: `false`, auto-enabled by `REPLICA_COUNT`)
  - `llamastack.postInitScaling.targetReplicas` -- Target replica count after init completes
  - `llama_stack_url` -- Init job readiness URL (default: `http://llamastack:8321`)

### Known Gotchas

- `LLAMASTACK_PORT` must not be used directly because Kubernetes sets it to `tcp://host:port` format. The client factory explicitly avoids it and uses `LLAMASTACK_CLIENT_PORT` (Helm override) or `LLAMASTACK_SERVICE_PORT` (K8s auto-injected numeric port) instead (see `llamastack_client.py` lines 73-75).
- The `llama-stack` subchart volumes are overridden in `values.yaml` to use `emptyDir` instead of PVC. This is intentional because all persistence is handled by PostgreSQL, and PVCs cannot be shared across replicas with `ReadWriteOnce` access mode.
- The `db_path: null` in `metadataStore` explicitly unsets the SQLite field to prevent LlamaStack from falling back to file-based storage when PostgreSQL is configured.
- The init job polls `$LLAMA_STACK_URL/` with `curl -ks` (tolerating self-signed certs) in a retry loop before running asset registration. The poll uses both `--fail` and a fallback `--silent` check because LlamaStack may return non-2xx on the root endpoint in some versions.
- The `max_connections=200` setting on pgvector is shared across all consumers (app services, LlamaStack metadata, LlamaStack kvstore, LlamaStack SQL). Pool sizes (`poolSize: 8`, `maxOverflow: 8`) are unified across test and production environments to avoid connection exhaustion.
- The post-init scaler Job uses `bitnami/kubectl:latest` image. In air-gapped or restricted environments, this image must be mirrored to an internal registry.
- Max output tokens for LlamaStack are set server-side in the run config per-model (`maxTokens`). The Responses API does not support per-request `max_tokens` (see LlamaStack issue #3562 referenced in `laptop-refresh-agent.yaml`).
- The async LlamaStack client is wrapped with a fault injection decorator (`wrap_client_with_fault_injection`) that can simulate timeouts, connection errors, API errors, or empty responses for resilience testing (controlled via Helm values `faultInjection.*`).

### Testing Notes

- Verify LlamaStack readiness: `curl -ks http://llamastack:8321/`
- Check init job completion: `kubectl get job <release>-init -n <namespace>` (should show `1/1` completions)
- If post-init scaling is enabled, verify replica count: `kubectl get deploy llamastack -n <namespace>` (should show target replicas)
- Monitor knowledge base registration: check init job logs for `Successfully registered knowledge base via LlamaStack` messages
- Fault injection can be enabled at deploy time: `FAULT_INJECTION_ENABLED=true FAULT_INJECTION_RATE=0.1 make install`

---

## Approach E: Standalone Helm Chart with OpenTelemetry Observability (from lls-observability)

### When to Use

Use this approach when deploying LlamaStack as a standalone Helm chart with a direct Kubernetes Deployment, integrated OpenTelemetry collector sidecar for distributed tracing and metrics, Milvus for vector I/O, and network policies restricting access to specific pods. This is the pattern for observability-focused deployments where LlamaStack telemetry data needs to flow through an enterprise observability stack (Tempo, Grafana, OpenTelemetry Collector).

### Differences from Approach A

- **Deployment**: Standalone Helm chart with Kubernetes Deployment instead of docker-compose service
- **Inference provider**: `remote::vllm` instead of `remote::ollama`
- **Container image**: Red Hat ET image (`quay.io/redhat-et/llama:vllm-0.2.6`) instead of `ogxai/distribution-starter:0.6.1`
- **Observability**: OpenTelemetry collector sidecar via `OpenTelemetryCollector` CRD with traces and metrics export
- **Vector I/O**: `inline::milvus` instead of no vector DB / SQLite-only
- **Network policies**: Built-in restricting access to openshift-ingress and llama-stack-playground pods

### Differences from Approach B

- **Deployment**: Direct Kubernetes Deployment managed by Helm instead of `LlamaStackDistribution` CRD managed by OpenShift AI operator
- **Container image**: Explicit Red Hat ET image (`quay.io/redhat-et/llama:vllm-0.2.6`) instead of operator-managed distribution
- **Observability**: Integrated OTel collector sidecar with `otel_trace` and `otel_metric` telemetry sinks instead of no observability integration
- **Vector I/O**: `inline::milvus` with file-based DB instead of no vector DB
- **MCP integration**: Dynamic MCP servers from Helm values array with auto-appended `/sse` suffix instead of static endpoint

### Differences from Approach C

- **Deployment**: Standalone Helm chart instead of `ai-architecture-charts` Helm subchart
- **No application-level client**: No Python application consuming LlamaStack APIs; serves as an API endpoint accessed through llama-stack-playground
- **Vector I/O**: `inline::milvus` instead of pgvector
- **Observability**: Native OpenTelemetry integration via sidecar injection instead of no observability

### Differences from Approach D

- **Deployment**: Standalone Helm chart instead of `ai-architecture-charts` Helm subchart
- **Persistence**: PVC-backed storage at `/.llama` (single replica) instead of PostgreSQL-backed multi-replica
- **Scaling**: Single replica with PVC (ReadWriteOnce) instead of horizontal scaling with PostgreSQL shared state
- **Observability**: Integrated OTel collector sidecar instead of no observability integration
- **Vector I/O**: `inline::milvus` instead of pgvector

### Tech Stack & Dependencies

- **Runtime:** LlamaStack distribution server (pre-built Red Hat ET image)
- **Container image:** `quay.io/redhat-et/llama:vllm-0.2.6`
- **Key dependencies:** vLLM model server (via KServe predictor), Llama Guard for safety, sentence-transformers for embeddings, Milvus (inline) for vector I/O, OpenTelemetry Operator for sidecar injection
- **Helm subchart:** None (standalone chart at `helm/03-ai-services/llama-stack/`)

### Key Patterns

#### Standalone Helm Chart with Direct Deployment

LlamaStack is deployed as a standard Kubernetes Deployment managed directly by Helm, not through an operator CRD or a shared subchart. The chart includes its own templates for Deployment, Service, ConfigMap, PVC, network policies, and an OpenTelemetry collector sidecar.

```yaml
# helm/03-ai-services/llama-stack/Chart.yaml
apiVersion: v2
name: llama-stack
description: A Helm chart for Llama Stack server
type: application
version: 1.0.0
appVersion: "latest"
keywords:
  - llama-stack
  - ai
  - mcp
  - agents
```

#### OpenTelemetry Collector Sidecar via Operator CRD

The chart deploys an `OpenTelemetryCollector` CRD in sidecar mode. Any pod with the annotation `sidecar.opentelemetry.io/inject: <collector-name>` gets an OTel collector sidecar injected by the OpenTelemetry Operator. The sidecar receives traces and metrics via OTLP and exports them to a central OTel collector in the `observability-hub` namespace.

```yaml
# templates/otel-collector-sidecar.yaml
apiVersion: opentelemetry.io/v1beta1
kind: OpenTelemetryCollector
metadata:
  name: {{ .Values.otelCollector.name | default "llamastack-otelsidecar" }}
spec:
  mode: sidecar
  config:
    exporters:
      otlphttp:
        # all sidecars export to the central observability-hub otel-collector
        endpoint: {{ .Values.otelCollector.exporter.endpoint | quote }}
        tls:
          insecure: {{ .Values.otelCollector.exporter.tls.insecure }}
    receivers:
      otlp:
        protocols:
          grpc: {}
          http: {}
    service:
      pipelines:
        traces:
          exporters:
            - debug
            - otlphttp
          receivers:
            - otlp
```

The Deployment template injects the sidecar via annotation:

```yaml
# templates/deployment.yaml
template:
  metadata:
    annotations:
      sidecar.opentelemetry.io/inject: {{ .Values.otelCollector.name | default "llamastack-otelsidecar" }}
```

#### Telemetry Sinks Configuration

LlamaStack's built-in telemetry provider is configured to emit traces and metrics to both SQLite (local) and the OTel collector sidecar. The `TELEMETRY_SINKS` env var enables all four sinks simultaneously.

```yaml
# templates/deployment.yaml (env section)
- name: OTEL_SERVICE_NAME
  value: llamastack
- name: OTEL_TRACE_ENDPOINT
  value: http://otel-collector-collector.observability-hub.svc.cluster.local:4318/v1/traces
- name: OTEL_METRIC_ENDPOINT
  value: http://otel-collector-collector.observability-hub.svc.cluster.local:4318/v1/metrics
- name: TELEMETRY_SINKS
  value: "console, sqlite, otel_trace, otel_metric"
```

The telemetry provider in the ConfigMap wires these environment variables:

```yaml
# templates/configmap.yaml (telemetry provider)
telemetry:
- provider_id: meta-reference
  provider_type: inline::meta-reference
  config:
    service_name: ${env.OTEL_SERVICE_NAME:llama-stack}
    sinks: ${env.TELEMETRY_SINKS:console, sqlite}
    otel_trace_endpoint: ${env.OTEL_TRACE_ENDPOINT:}
    sqlite_db_path: ${env.SQLITE_DB_PATH:~/.llama/distributions/remote-vllm/trace_store.db}
```

#### Inline Milvus for Vector I/O

Vector I/O uses `inline::milvus` which runs Milvus Lite as an embedded library inside the LlamaStack process, storing data in a file on the PVC. No external Milvus server is required.

```yaml
# templates/configmap.yaml (vector_io provider)
vector_io:
- provider_id: milvus
  provider_type: inline::milvus
  config:
    db_path: ${env.MILVUS_DB_PATH}
```

The `MILVUS_DB_PATH` env var is set to `milvus.db` (relative path) in the Deployment, which resolves to the working directory inside the container.

#### Dual Safety Model with Separate vLLM Provider

The run config registers two vLLM inference providers: one for the primary LLM and one for the safety model (Llama Guard). Each has its own URL, max_tokens, and TLS settings.

```yaml
# templates/configmap.yaml (safety provider)
inference:
- provider_id: vllm-inference
  provider_type: remote::vllm
  config:
    url: ${env.VLLM_URL:http://localhost:8000/v1}
    max_tokens: ${env.VLLM_MAX_TOKENS:4096}
- provider_id: vllm-safety
  provider_type: remote::vllm
  config:
    url: ${env.SAFETY_MODEL:http://llama-guard-3-1b-predictor:8080/v1}
    max_tokens: ${env.VLLM_SAFETY_MAX_TOKENS:20000}
```

#### Dynamic MCP Server Registration via Helm Values

MCP servers are declared as a list in Helm values and templated into the run config as `mcp::` toolgroups. The weather endpoint gets a `/sse` suffix appended automatically.

```yaml
# templates/configmap.yaml (tool_groups)
{{- range .Values.mcpServers }}
- toolgroup_id: mcp::{{ .name }}
  provider_id: model-context-protocol
  mcp_endpoint:
    uri: {{ .uri }}{{ if eq .name "weather" }}/sse{{ end }}
{{- end }}
```

#### Network Policy Restricting Access

The chart includes network policies limiting inbound traffic to port 8321 from two sources: the OpenShift ingress namespace and pods labeled as `llama-stack-playground`.

```yaml
# values.yaml (networkPolicy section)
networkPolicy:
  enabled: true
  ingress:
    - from:
      - namespaceSelector:
          matchLabels:
            name: openshift-ingress
      ports:
      - protocol: TCP
        port: 8321
    - from:
      - podSelector:
          matchLabels:
            app.kubernetes.io/name: llama-stack-playground
      ports:
      - protocol: TCP
        port: 8321
```

#### OpenShift-Compatible Security Context

The security context drops all capabilities and runs as non-root without specifying a UID/GID, letting OpenShift assign them from the project's SCC range. The root filesystem is not read-only because LlamaStack and Milvus write state files at runtime.

```yaml
# values.yaml
podSecurityContext:
  runAsNonRoot: true
  # Remove specific UID/GID to let OpenShift assign them

securityContext:
  allowPrivilegeEscalation: false
  capabilities:
    drop:
    - ALL
  readOnlyRootFilesystem: false
  runAsNonRoot: true
```

#### PVC Persistence for LlamaStack State

A 5Gi PVC named `llama-persist` is mounted at `/.llama` for LlamaStack's internal state (SQLite stores, Milvus DB, model metadata). Two `emptyDir` volumes handle ephemeral caches (`/.cache` and `/pythainlp-data`).

```yaml
# templates/deployment.yaml (volumes)
volumes:
  - name: run-config-volume
    configMap:
      name: run-config
  - name: llama-persist
    persistentVolumeClaim:
      claimName: llama-persist
  - name: cache
    emptyDir: {}
  - name: pythain
    emptyDir: {}
```

#### Optional MaaS Provider

The chart supports an optional Model-as-a-Service provider (via LiteLLM gateway) that registers an additional model alongside the local vLLM-served one. The MaaS provider is conditionally included in both the run config and the models list.

```yaml
# values.yaml (maas section)
maas:
  enabled: false
  apiToken: "your-api-token-here"
  url: "https://litellm-litemaas.apps.prod.rhoai.rh-aiservices-bu.com/v1"
  maxTokens: 200000
  tlsVerify: false
  modelId: "Llama-4-Scout-17B-16E-W4A16"
```

### Configuration

- **Environment variables:**
  - `VLLM_URL` -- vLLM inference endpoint URL (default: `http://llama3-2-3b-predictor:8080/v1`)
  - `INFERENCE_MODEL` -- Model ID for the primary LLM (default: `llama3-2-3b`)
  - `VLLM_MAX_TOKENS` / `MAX_TOKENS` -- Max token limit for inference (default: `60000`)
  - `VLLM_API_TOKEN` -- API token for vLLM auth (default: `fake`)
  - `SAFETY_MODEL` -- Safety model URL (default: `http://llama-guard-3-1b-predictor:8080/v1`)
  - `VLLM_SAFETY_MAX_TOKENS` -- Max tokens for safety model (default: `20000`)
  - `MILVUS_DB_PATH` -- File path for Milvus Lite DB (default: `milvus.db`)
  - `OTEL_SERVICE_NAME` -- Service name for OTel traces (default: `llamastack`)
  - `OTEL_TRACE_ENDPOINT` -- OTel collector trace endpoint
  - `OTEL_METRIC_ENDPOINT` -- OTel collector metric endpoint
  - `TELEMETRY_SINKS` -- Comma-separated sinks: `console, sqlite, otel_trace, otel_metric`
  - `LLAMA_STACK_LOGGING` -- Logging level (default: `all=debug`)
  - `LLAMA_STACK_PORT` -- Server port (default: `8321`)
  - `LLAMA_STACK_HOST` -- Bind address (default: `0.0.0.0`)
  - `CUSTOM_TIKTOKEN_CACHE_DIR` -- Tiktoken cache path (default: `/app/cache`)
- **Config files:**
  - ConfigMap `run-config` containing `config.yaml` -- Full distribution run config with providers, models, shields, and tool groups
- **Helm values:**
  - `image.repository` / `image.tag` -- Container image (default: `quay.io/redhat-et/llama:vllm-0.2.6`)
  - `llamaStack.configFile` -- Run config filename (default: `run-vllm.yaml`)
  - `llamaStack.inferenceModel` -- Model ID for vLLM provider
  - `llamaStack.vllmUrl` -- vLLM service URL
  - `llamaStack.storage.size` -- PVC size (default: `5Gi`)
  - `otelCollector.enabled` -- Enable OTel collector sidecar (default: `true`)
  - `otelCollector.name` -- Collector name for sidecar injection annotation (default: `llamastack-otelsidecar`)
  - `otelCollector.exporter.endpoint` -- Central OTel collector endpoint (default: `http://otel-collector-collector.observability-hub.svc.cluster.local:4318`)
  - `networkPolicy.enabled` -- Enable network policies (default: `true`)
  - `route.enabled` -- Create OpenShift Route with TLS edge termination (default: `true`)
  - `maas.enabled` -- Enable MaaS provider (default: `false`)
  - `mcpServers` -- List of MCP server entries with `name` and `uri`

### Known Gotchas

- The container image `quay.io/redhat-et/llama:vllm-0.2.6` is a Red Hat Emerging Technology image, not the upstream `llamastack/distribution-remote-vllm`. The original upstream image is commented out in `values.yaml` (line 6-7), indicating a deliberate switch to the Red Hat ET build.
- The `readOnlyRootFilesystem` is set to `false` in the security context because LlamaStack writes SQLite databases and Milvus Lite writes its DB file to the container filesystem. The `/.llama` path is backed by a PVC, but other paths (e.g., the Milvus `milvus.db` at the working directory) may write outside the PVC mount.
- The `MILVUS_DB_PATH` is set to the relative path `milvus.db` in the Deployment env, meaning it resolves to the container's working directory. This file is NOT on the PVC mount at `/.llama` and would be lost on pod replacement unless the working directory is also a volume mount.
- The `VLLM_API_TOKEN` is hardcoded to `"fake"` in the Deployment template (line 74), not sourced from a Kubernetes Secret. This works for cluster-internal communication but is not suitable for external-facing deployments.
- The `pythain` emptyDir volume at `/pythainlp-data` is required because the `pythainlp` library (transitive dependency) attempts to write data files there at startup, which would fail without a writable mount.
- The `CUSTOM_TIKTOKEN_CACHE_DIR` is set to `/app/cache` in the container env, but the `cache` emptyDir volume is mounted at `/.cache`. These are different paths -- tiktoken will write to `/app/cache` which is on the root filesystem, not the emptyDir.
- The PVC comment in `pvc.yaml` says "MinIO Persistent Volume Claim" (line 1) but the PVC is actually for LlamaStack state at `/.llama` -- this is a copy-paste artifact from another chart.
- The ArgoCD sync-wave annotation on the Deployment is set to `"5"`, indicating LlamaStack should be deployed after lower-priority components (operators at wave 1-2, observability infrastructure at 3-4).
- The liveness probe has a 60-second `initialDelaySeconds` and the readiness probe has a 30-second `initialDelaySeconds`, giving LlamaStack time to initialize providers and load model metadata from the vLLM endpoints.
- The configmap checksum annotation (`checksum/config`) on the Deployment pod template ensures pods are restarted when the ConfigMap content changes, preventing config drift after Helm upgrades.
- The `LLAMA3B_URL` and `LLAMA3B_MODEL` env vars (lines 69-72 of deployment.yaml) reference a separate Llama 3.2 3B endpoint at `llama32-3b.llama-serve.svc.cluster.local` but these are not wired into the run config providers -- they appear to be leftover from an earlier configuration iteration.

### Testing Notes

- Verify LlamaStack health: `curl -f http://llama-stack:80/health` (through the Service at port 80, mapped to container port 8321)
- Check OTel sidecar injection: `oc get pod -l app.kubernetes.io/name=llama-stack -o jsonpath='{.items[0].spec.containers[*].name}'` should show both `llama-stack` and the sidecar container
- Verify traces reaching the central collector: check the `observability-hub` namespace for traces with service name `llamastack`
- Confirm network policies: `oc get networkpolicy -l app.kubernetes.io/name=llama-stack` should show the policy, and only llama-stack-playground pods and openshift-ingress should be able to reach port 8321
- Check PVC binding: `oc get pvc llama-persist` should show `Bound` status
- Verify MCP servers are registered: after deployment, the tool_groups section of the running config should include entries for each declared `mcpServers` value

---

## Choosing Between Approaches

| Criteria | Approach A (ai-virtual-agent) | Approach B (data-governance-co-pilot) | Approach C (f5-ai-guardrails) | Approach D (it-self-service-agent) | Approach E (lls-observability) |
|----------|-------------------------------|---------------------------------------|-------------------------------|-------------------------------------|-------------------------------|
| Deployment method | docker-compose service | Helm chart + LlamaStackDistribution CRD (OpenShift AI operator) | ai-architecture-charts Helm subchart | ai-architecture-charts Helm subchart | Standalone Helm chart with direct Kubernetes Deployment |
| Inference backend | Ollama (local) | Remote vLLM via KServe InferenceService | Remote vLLM via llm-service subchart | Remote vLLM via llm-service subchart | Remote vLLM via KServe predictor |
| LlamaStack version | 0.6.1 | 0.3.5 | 0.6.1 (subchart v0.8.6) | subchart v0.8.5 (llama-stack-client 0.5.0) | Red Hat ET image (vllm-0.2.6) |
| Client API | Responses API with Conversations | Agents alpha API with sessions | OpenAI chat.completions + LlamaStackClient | Responses API via centralized client factory | Server-only (consumed via playground or direct API) |
| Agent management | Runner handles agentic loop, LlamaStack streams responses | LlamaStack manages full agentic loop, provider maps events | No agent loop; direct chat completions for RAG Q&A | Custom Agent class with retry, MCP tools, and file_search | LlamaStack-native agents API (no custom application code) |
| MCP integration | Dynamic toolgroup resolution at runtime | Static MCP endpoint in run.yaml ConfigMap | Tool groups listed from LlamaStack for UI display | MCP tools in responses tools array with per-request headers | Dynamic MCP servers from Helm values array with /sse suffix |
| Auth model | K8s SA token + X-Forwarded headers | API key in K8s Secret, no user header forwarding | Optional bearer token, TLS via HTTPX client factory | Dummy API key (in-cluster only), user ID via MCP headers | Hardcoded VLLM_API_TOKEN, network policy for access control |
| Safety | Input shields via `client.safety.run_shield()` | `inline::llama-guard` provider declared in run.yaml | External F5 AI Guardrails Moderator proxy | Optional NeMo Guardrails via external endpoint | `inline::llama-guard` with separate vLLM safety provider |
| Storage | SQLite at container-local path | SQLite at operator-managed path | Subchart defaults | PostgreSQL (kv_postgres + sql_postgres) for multi-replica | PVC at /.llama (SQLite) + inline Milvus for vector I/O |
| Platform | Local dev (compose), OpenShift (future) | OpenShift AI with operator | OpenShift with shared Helm subcharts | OpenShift with shared Helm subcharts | OpenShift with standalone chart, ArgoCD sync-wave |
| Multi-framework | Pluggable runner (LlamaStack/LangGraph/CrewAI) | Pluggable provider (mcp_direct/llama_stack) | Single path (OpenAI SDK for chat) | Agent class per agent config YAML | Single path (LlamaStack native APIs) |
| Horizontal scaling | Single instance | Operator-managed replicas | Single instance | Post-init scaler Job, PostgreSQL-backed shared state | Single instance (PVC ReadWriteOnce) |
| Observability | None | None | None | None | OpenTelemetry sidecar with traces + metrics to central collector |
| Vector I/O | None | None | pgvector via subchart | pgvector via subchart | inline::milvus (file-based Milvus Lite) |
