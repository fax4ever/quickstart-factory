---
name: llamastack
description: "LlamaStack distribution server providing inference, agents, safety, tool runtime, and vector I/O APIs"
summary: "LlamaStack provides a unified AI orchestration server exposing inference, agents, safety, tool runtime, vector I/O, and files APIs between the application backend and model providers (Ollama or vLLM), with Approach A (ai-virtual-agent, v0.6.1) using compose with Responses API and StreamAggregator-based SSE streaming in a pluggable LlamaStack/LangGraph/CrewAI runner dispatch, Approach B (data-governance-co-pilot, v0.3.5) deploying a LlamaStackDistribution CRD via OpenShift AI operator with alpha.agents API managing the full agentic loop and session-to-conversation event mapping, and Approach C (f5-ai-guardrails, v0.6.1) using ai-architecture-charts llama-stack subchart v0.8.6 with dual-client pattern (LlamaStackClient + OpenAI SDK) for RAG with F5 guardrails proxy dual-panel comparison. Use Approach A for local dev or when the application manages the agentic loop with dynamic MCP toolgroup resolution, input shield validation via client.safety.run_shield(), and automatic tool retry with exclusion; use Approach B for production OpenShift AI deployments where the operator manages LlamaStack lifecycle (600s DeploymentReady wait, 100m/256Mi lightweight proxy resources), vLLM serves inference via KServe, and Makefile populates Helm model.name/url/apiKey values at install time; use Approach C for RAG apps needing shared Helm subcharts with global.models across llm-service/llama-stack, Streamlit frontend with URL normalization for 0.6+, and external guardrails proxy -- Nemotron models are incompatible with llama_stack mode (enforced by check-model-provider-compatibility, use mcp_direct). Configured via llamastack-run.yaml (RUN_CONFIG_PATH) declaring providers -- Approach A uses remote::ollama with AsyncLlamaStackClient (180s timeout, K8s SA token + X-Forwarded-User/Email auth headers for RBAC); Approach B uses remote::vllm with provider-prefixed model name (vllm-inference/<model>), vLLM URL derived from KServe predictor (https://<model>-predictor.<ns>.svc.cluster.local:8443/v1), VLLM_TLS_VERIFY='false' for self-signed certs, and static MCP endpoint in Helm-templated ConfigMap; Approach C uses dual clients with OpenAI SDK targeting LlamaStack /v1/chat/completions, HTTPX verify=False for cluster TLS, and auto-detects LlamaStack route via start.sh for TLS protocol selection. Container runs as root (user 0:0) with 90s healthcheck start_period, SDK attribute names changed between 0.3.x and 0.6.1 (identifier to id, api_model_type to model_type) requiring _get_model_type/_get_model_id helpers, SQLite storage is dev-only, platform linux/amd64 causes ARM emulation perf hit, regex-based tool retry parsing (Tool '(\\w+)' not found) is fragile, has_output_text=False emits error event to prevent silent empty responses, Approach B values.yaml has empty placeholders requiring Makefile --set population, static agent instructions require conversation restart on policy update via requires_conversation_restart_on_policy_update(), Approach C guardrails_state.json on emptyDir is lost on pod replacement, and legacy URL suffix /v1/openai/v1 must be stripped for 0.6+ compatibility."
metadata:
  type: component
tags:
  tech_stack: [llamastack, ollama, python, fastapi, llama-stack-client, vllm, helm, streamlit, openai-sdk]
  ai_pattern: [agents, model-serving, guardrails, rag, vector-search, mcp]
  platform: [openshift, kubernetes, rhoai, kserve]
  data_layer: [sqlite, faiss, pgvector]
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

---

## Choosing Between Approaches

| Criteria | Approach A (ai-virtual-agent) | Approach B (data-governance-co-pilot) | Approach C (f5-ai-guardrails) |
|----------|-------------------------------|---------------------------------------|-------------------------------|
| Deployment method | docker-compose service | Helm chart + LlamaStackDistribution CRD (OpenShift AI operator) | ai-architecture-charts Helm subchart |
| Inference backend | Ollama (local) | Remote vLLM via KServe InferenceService | Remote vLLM via llm-service subchart |
| LlamaStack version | 0.6.1 | 0.3.5 | 0.6.1 (subchart v0.8.6) |
| Client API | Responses API with Conversations | Agents alpha API with sessions | OpenAI chat.completions + LlamaStackClient |
| Agent management | Runner handles agentic loop, LlamaStack streams responses | LlamaStack manages full agentic loop, provider maps events | No agent loop; direct chat completions for RAG Q&A |
| MCP integration | Dynamic toolgroup resolution at runtime | Static MCP endpoint in run.yaml ConfigMap | Tool groups listed from LlamaStack for UI display |
| Auth model | K8s SA token + X-Forwarded headers | API key in K8s Secret, no user header forwarding | Optional bearer token, TLS via HTTPX client factory |
| Safety | Input shields via `client.safety.run_shield()` | `inline::llama-guard` provider declared in run.yaml | External F5 AI Guardrails Moderator proxy |
| Storage | SQLite at container-local path | SQLite at operator-managed path | Subchart defaults |
| Platform | Local dev (compose), OpenShift (future) | OpenShift AI with operator | OpenShift with shared Helm subcharts |
| Multi-framework | Pluggable runner (LlamaStack/LangGraph/CrewAI) | Pluggable provider (mcp_direct/llama_stack) | Single path (OpenAI SDK for chat) |
