---
name: guardrails-layer
description: AI safety guardrails via LlamaStack shields or F5 AI Guardrails external proxy
summary: "Enforces AI safety guardrails on LLM interactions via two approaches: Approach A uses LlamaStack's safety.run_shield API for per-agent input shields with output refusals via Responses API refusal content type; Approach B uses F5 AI Guardrails (Calypso AI Moderator) as an external reverse proxy intercepting OpenAI-compatible requests with OOTB scanners (Prompt Injection, PII, EU AI Act, Restricted Topics) plus custom GenAI/Keyword/Regex scanners. Use Approach A for per-agent developer-managed shields with no extra GPU and fail-open semantics; use Approach B for centralized security-team management via Moderator UI with Block/Audit/Redact enforcement modes, fail-closed behavior, built-in dashboard/reporting/red-team, but requiring F5 AI Security Operator (OLM), two-pass Helm deploy, anyuid SCC for 7 SAs across 4 namespaces, and 1-3 additional GPUs for scanner models. Approach A stores input_shields/output_shields as JSON columns on the agent model and executes shields sequentially via client.safety.run_shield(shield_id=..., messages=[...]) before inference; Approach B requires pointing the OpenAI client base_url to https://<hostname>/openai/<connection-name>/chat/completions where connection-name is the display name from the Moderator UI, not the model ID. Approach A is fail-open (shield errors caught/logged, request proceeds without validation) and only LlamaStackRunner implements shields (LangGraph/CrewAI runners have none); Approach B's Prompt Injection scanner may false-positive on RAG context in prompts, extra_body parameters cause empty responses through the Moderator, and guardrail state on emptyDir volume is lost on pod replacement unless a PVC is mounted."
metadata:
  type: architecture
tags:
  tech_stack: [fastapi, llamastack, python, streamlit, calypso-ai]
  ai_pattern: [guardrails, agents]
  platform: [llamastack, rhoai, openshift]
  data_layer: [postgresql]
source_examples:
  - quickstart: "ai-virtual-agent"
    repo: "https://github.com/rh-ai-quickstart/ai-virtual-agent"
    notes: "Per-agent input shields via LlamaStack safety.run_shield API, guardrail CRUD for policy management, and refusal handling in response stream"
    approach: "A"
  - quickstart: "f5-ai-guardrails"
    repo: "https://github.com/rh-ai-quickstart/f5-ai-guardrails"
    notes: "F5 AI Guardrails (Calypso AI Moderator) as external reverse proxy intercepting OpenAI-compatible API calls with scanner-based content inspection, three enforcement modes (Block/Audit/Redact), and custom guardrails (GenAI/Keyword/Regex)"
    approach: "B"
---

# Guardrails Layer

## Overview

This architecture implements AI safety guardrails through two complementary mechanisms: per-agent input shields that validate user messages before they reach the LLM, and a guardrail policy CRUD API for managing safety rules. Input shields are executed via LlamaStack's `safety.run_shield` API before inference begins, blocking violating content with a user-facing error message. Output guardrails are handled by LlamaStack's Responses API which can emit `refusal` content types when the model's response triggers safety policies. Guardrail configurations are stored per-agent, allowing different virtual agents to have different safety policies.

## Data Flow

1. User sends a message via the chat endpoint
2. The LlamaStackRunner checks if the agent has `input_shields` configured
3. For each shield ID, the runner calls `client.safety.run_shield()` with the user's text content
4. If any shield returns a violation, the stream immediately returns an error event with the violation message and terminates
5. If shields pass, the runner proceeds with normal inference via the Responses API
6. During streaming, if the Responses API returns a `refusal` content type in `response.completed`, the runner emits an error event with the refusal message
7. Guardrail policies (name + rules) are managed separately via a CRUD API and stored in PostgreSQL

## Component Wiring

| From | To | Protocol | Purpose |
|------|----|----------|---------|
| LlamaStackRunner | LlamaStack safety API | HTTP (AsyncLlamaStackClient) | Execute input shields before inference |
| LlamaStack Responses API | LlamaStackRunner | HTTP streaming | Emit refusal content types for output violations |
| React frontend | FastAPI guardrails API | REST | CRUD for guardrail policies |
| FastAPI guardrails API | PostgreSQL | SQLAlchemy async | Persist guardrail rules |
| React frontend | FastAPI virtual agents API | REST | Configure input_shields and output_shields per agent |

## Key Integration Points

### Input Shield Execution

Input shields run sequentially before inference. Each shield is called with the user's text content, and any violation short-circuits the stream.

```python
# backend/app/services/runners/llamastack_runner.py (lines 504-552)
async def _run_input_shields(
    self, client, shield_ids: List[str], user_input: List[Any]
) -> Optional[Dict[str, Any]]:
    if not shield_ids:
        return None
    text_content = ""
    for item in user_input:
        if hasattr(item, "type") and item.type == "input_text":
            text_content += getattr(item, "text", "")
    if not text_content:
        return None
    for shield_id in shield_ids:
        shield_response = await client.safety.run_shield(
            shield_id=shield_id,
            messages=[{"role": "user", "content": text_content}],
            params={},
        )
        if hasattr(shield_response, "violation") and shield_response.violation:
            violation_msg = (
                shield_response.violation.user_message
                if hasattr(shield_response.violation, "user_message")
                else "Content policy violation"
            )
            return {"type": "error", "message": violation_msg}
    return None
```

### Shield Integration in Stream Flow

The input shield check is integrated into the main stream method, running after tool preparation but before starting inference.

```python
# backend/app/services/runners/llamastack_runner.py (lines 613-624)
async with get_llamastack_client_from_request(self.request) as client:
    # Run input shields
    if agent.input_shields and len(agent.input_shields) > 0:
        violation = await self._run_input_shields(
            client, agent.input_shields, prompt
        )
        if violation:
            violation["session_id"] = str(session_id)
            yield f"data: {json.dumps(jsonable_encoder(violation))}\n\n"
            yield "data: [DONE]\n\n"
            return
```

### Output Refusal Handling

When LlamaStack's Responses API detects an output violation, it includes a `refusal` content type in the completed response. The `StreamAggregator` catches this and converts it to an error event.

```python
# backend/app/services/runners/llamastack_runner.py (lines 335-348)
def _handle_response_completed(self, chunk):
    response = chunk.get("response", {})
    output = response.get("output", [])
    for output_item in output:
        if output_item.get("type") == "message":
            content = output_item.get("content", [])
            for content_item in content:
                if content_item.get("type") == "refusal":
                    refusal_msg = content_item.get(
                        "refusal", "Request blocked by safety guardrail"
                    )
                    yield self._create_event("error", {"message": refusal_msg})
                    return
```

### Per-Agent Shield Configuration

Each virtual agent stores its own shield lists, allowing different agents to apply different safety policies.

```python
# backend/app/models/agent.py (lines 42-43)
input_shields = Column(JSON, nullable=True, default=list)
output_shields = Column(JSON, nullable=True, default=list)
```

## Prompt / Chain Patterns

Guardrails operate outside the prompt chain. Input shields intercept user messages before they enter the LLM, and output refusals are detected after the LLM response is complete. The shield IDs reference policies registered in the LlamaStack server (e.g., Llama Guard models or custom safety classifiers). The guardrail CRUD API manages a separate set of named rules stored in PostgreSQL, which can be used for UI-driven policy configuration.

## Gotchas

- Input shield errors are caught and logged but do not block the chat flow (lines 550-552 of `llamastack_runner.py`). If a shield call fails due to a network error or misconfiguration, the request proceeds without safety validation. This is a deliberate fail-open design.
- Output shields are listed in the agent model (`output_shields` column) but are not explicitly executed by the runner code. Output safety relies on LlamaStack's server-side implementation via the Responses API, which emits `refusal` content types.
- The guardrail CRUD API (`/api/v1/guardrails/`) manages guardrail records in PostgreSQL but these are separate from the LlamaStack shield IDs configured on agents. The CRUD API stores named rules for UI presentation, while the actual shield execution depends on shields registered in the LlamaStack server.
- Only the LlamaStackRunner implements shield execution. The LangGraph and CrewAI runners do not call `safety.run_shield` and have no equivalent input validation step.

## Related Architectures

- [agent-orchestration](agent-orchestration.md) -- Shield configuration is stored on the VirtualAgent model and executed within the LlamaStack runner
- [rag-pipeline](rag-pipeline.md) -- Input shields run before RAG retrieval, so blocked content never reaches the knowledge base search

---

## Approach B: F5 AI Guardrails External Reverse Proxy (from f5-ai-guardrails)

### When to Use

Use this approach when deploying AI guardrails as an external network-level proxy that intercepts OpenAI-compatible API calls between the client and the model-serving backend. This approach requires no application code changes for enforcement -- the F5 AI Guardrails Moderator (powered by Calypso AI) sits between the client and LlamaStack, scanning prompts and responses against configurable policies. It suits scenarios where: guardrails must be managed centrally by a security team independent of application developers, enterprise compliance policies (EU AI Act, PII, topic restrictions) need defense-in-depth coverage, the application uses standard OpenAI-compatible chat completion APIs, and guardrail enforcement should be configurable in a management UI without code changes.

### Differences from Approach A

| Aspect | Approach A (LlamaStack Shields) | Approach B (F5 AI Guardrails) |
|--------|-------------------------------|------------------------------|
| Enforcement location | Application backend runner code | External reverse proxy (network layer) |
| Integration method | `client.safety.run_shield()` API calls in runner code | Client sends requests to Moderator URL instead of LlamaStack URL; no code changes needed |
| Configuration | Per-agent shield IDs stored as JSON columns in PostgreSQL | Central Moderator UI; projects, packages, and per-guardrail modes managed by security team |
| Scanner types | LlamaStack-registered shields (e.g., Llama Guard) | OOTB packages (Prompt Injection, PII, EU AI Act, Restricted Topics) + custom GenAI/Keyword/Regex scanners |
| Enforcement modes | Block only (fail-open on error) | Block (reject request), Audit (allow + flag), Redact (mask sensitive data at edge) |
| Failure behavior | Fail-open: shield errors are caught and logged, request proceeds | Fail-closed: Moderator errors return HTTP error to client, request does not reach model |
| Output scanning | LlamaStack Responses API refusal content types (server-side) | Response scanned on return path through Moderator before reaching client |
| Scope | Per-agent (different agents can have different shields) | Per-project (all requests through a connection share the same guardrail policies) |
| Operator dependency | None (LlamaStack built-in) | F5 AI Security Operator (OLM), Calypso AI Moderator, inference models for AI scanners |
| GPU requirements | No additional GPUs (uses LlamaStack safety models) | 1-3 additional GPUs for scanner/red-team models (cai-phi-4, cai-mistral-nemo) |

### Data Flow

1. Client (Streamlit UI or curl) sends an OpenAI-compatible `chat.completions.create` request to the F5 AI Guardrails Moderator endpoint (`https://<hostname>/openai/<connection-name>/chat/completions`)
2. Moderator receives the request and passes the prompt through the Guardrails engine
3. Guardrails engine evaluates the prompt against all active policies in sequence (each guardrail evaluates independently)
4. If any guardrail returns a violation in Block mode, the request is rejected immediately -- the prompt never reaches the model. The client receives an HTTP error response with a `cai_error` body containing `outcome: "blocked"` and per-scanner results
5. If all guardrails pass (or violations are in Audit/Redact mode), the request is forwarded to LlamaStack's OpenAI-compatible chat completions endpoint
6. LlamaStack routes the request to the vLLM model via KServe for inference
7. The model response is returned to the Moderator, which scans the response through the same guardrail policies
8. If the response violates a policy, it is blocked (or redacted); otherwise, it is returned to the client

For the dual-panel UI comparison flow:

1. User submits a query in the Streamlit chat app
2. If RAG is enabled, the frontend retrieves context from LlamaStack's vector stores via `rag_tool_query` (this call goes directly to LlamaStack, not through the Moderator)
3. The frontend builds the same prompt with context for both panels
4. **Left panel (F5 Guardrails):** Sends `chat.completions.create` to the Moderator endpoint via `create_openai_client(f5_ep, f5_tk)` -- guardrails scan the request
5. **Right panel (LlamaStack Direct):** Sends `chat.completions.create` directly to LlamaStack via `create_openai_client_for_llamastack()` -- no guardrails
6. Both responses are displayed side-by-side, showing the guardrail effect

### Component Wiring

| From | To | Protocol | Purpose |
|------|----|----------|---------|
| Streamlit frontend | F5 Moderator | HTTPS (OpenAI SDK, port 443 via Route) | Chat requests routed through guardrails |
| Streamlit frontend | LlamaStack | HTTP (OpenAI SDK, port 8321) | Direct chat requests (bypassing guardrails) and RAG queries |
| F5 Moderator | LlamaStack | HTTP (proxied OpenAI format) | Forward approved requests to model |
| F5 Moderator | Guardrails engine | Internal | Prompt/response policy evaluation |
| Guardrails engine | AI scanner models | Internal (KubeAI) | AI-driven content classification (prompt injection, PII, toxicity) |
| F5 AI Security Operator | Moderator + inference namespaces | Kubernetes API | Deploy and manage guardrail infrastructure |
| Streamlit frontend | F5 Moderator API | HTTPS (`/backend/v1/`) | Fetch scanner names for UI display |
| Streamlit frontend | pgvector | TCP (asyncpg, port 5432) | Direct document listing and deletion |

### Key Integration Points

#### OpenAI-Compatible Proxy Endpoint

The F5 Moderator exposes an OpenAI-compatible endpoint at `/openai/<connection-name>/chat/completions`. Clients use the standard OpenAI SDK with the Moderator URL as `base_url` -- no custom SDK or API changes needed.

```python
# frontend/llama_stack_ui/distribution/ui/modules/api.py (lines 84-91)
def create_openai_client(self, base_url: str, api_token: str) -> OpenAI:
    """Create an OpenAI client for the F5 AI Guardrails endpoint"""
    base = guardrail_openai_base_url(base_url)
    return OpenAI(
        base_url=base,
        api_key=api_token,
        http_client=httpx.Client(verify=False, follow_redirects=True, timeout=_HTTPX_TIMEOUT),
    )
```

#### Guardrail Block Error Handling

When the Moderator blocks a request, it returns an HTTP error with a structured `cai_error` body. The frontend parses this to display which scanners triggered.

```python
# frontend/llama_stack_ui/distribution/ui/page/playground/chat.py (lines 41-73)
def _format_guardrail_block(exc):
    """Parse a CAI guardrails block error into a user-friendly message."""
    body = getattr(exc, "body", None)
    if not isinstance(body, dict):
        return f"Blocked by Guardrail\n\n{exc}"

    cai_error = body.get("cai_error", {})
    scanner_results = cai_error.get("scanner_results", [])
    failed = [s for s in scanner_results if s.get("outcome") == "failed"]

    name_map = _get_scanner_names()

    lines = [f"Blocked by Guardrail -- {len(failed)} scanner(s) triggered:\n"]
    for s in failed:
        sid = s.get("scanner_id", "unknown")
        scanner_name = name_map.get(sid)
        if scanner_name:
            label = scanner_name
        else:
            raw_data = s.get("data")
            data = raw_data if isinstance(raw_data, dict) else {}
            stype = data.get("type", "unknown")
            label = f"Pattern Match (PII/Regex) -- `{sid}`" if stype == "regex" else f"AI Scanner -- `{sid}`"
        lines.append(f"- **{label}**")
```

#### Scanner Name Resolution from Moderator API

The frontend fetches human-readable scanner names from the Moderator's backend API, mapping scanner IDs to display names for the block error messages.

```python
# frontend/llama_stack_ui/distribution/ui/modules/api.py (lines 155-206)
def fetch_scanner_names(self, guardrail_url: str, api_token: str) -> dict[str, str]:
    """Fetch scanner ID -> name mapping from the F5 Moderator API."""
    url = guardrail_url.rstrip("/")
    if "/openai/" in url:
        base = url[:url.index("/openai/")]
    else:
        base = url

    headers = {"Authorization": f"Bearer {api_token}", "Accept": "application/json"}

    # Step 1: get projects to find the project ID
    resp = httpx.get(f"{base}/backend/v1/projects", headers=headers, verify=False, ...)
    projects = resp.json().get("projects", [])

    # Step 2: for each project, fetch scanner details
    for project in projects:
        pid = project.get("id", "")
        resp = httpx.get(f"{base}/backend/v1/ui/project-scanners",
                         params={"projectId": pid}, headers=headers, ...)
        scanners = resp.json().get("projectScanners", {}).get("scanners", {})
        for sid, info in scanners.items():
            mapping[sid] = info.get("name", "")
```

#### Simple Chat App Block Detection (app.py)

The standalone `app.py` Streamlit app detects blocks by catching OpenAI SDK exceptions and checking for the `cai_error.outcome == "blocked"` pattern in the error response body.

```python
# app.py (lines 203-213)
try:
    response = client.chat.completions.create(model=model, messages=api_messages)
    reply = response.choices[0].message.content
    st.session_state.messages.append({"role": "assistant", "content": reply, "time": time_str})
except Exception as e:
    body = getattr(getattr(e, "response", None), "json", lambda: {})()
    if body.get("error", {}).get("cai_error", {}).get("outcome") == "blocked":
        st.session_state.messages.append({"role": "blocked", "time": time_str})
    else:
        st.session_state.messages.pop()
        st.error(f"Error: {e}")
```

#### F5 AI Security Operator Deployment

The F5 AI Security Operator is installed via OLM Subscription from the `certified-operators` catalog. The `SecurityOperator` custom resource configures the Moderator, PostgreSQL database, Prefect workflow engine, and KubeAI-based inference models for AI scanners.

```yaml
# deploy/helm/f5-ai-security/templates/40-security-operator.yaml (lines 14-72)
apiVersion: ai.security.f5.com/v1alpha1
kind: SecurityOperator
metadata:
  name: {{ .Values.securityOperator.name }}
  namespace: {{ $modNs }}
spec:
  registryAuth:
    enabled: true
    existingSecret: {{ .Values.registry.secretName | quote }}
  postgresql:
    enabled: true
  jobManager:
    enabled: {{ .Values.securityOperator.jobManager.enabled }}
  moderator:
    enabled: true
    values:
      env:
        CAI_MODERATOR_BASE_URL: {{ $base | quote }}
  inference:
    enabled: true
    values:
      inference:
        guardrails:
          enabled: {{ .Values.securityOperator.inference.guardrails }}
        redteam:
          enabled: {{ .Values.securityOperator.inference.redteam }}
```

#### Moderator Routes (OpenShift)

The Moderator is exposed via two OpenShift Routes: one for the UI (port 5500) and one for authentication (port 8080), both served on the same hostname with TLS edge termination.

```yaml
# deploy/helm/f5-ai-security/templates/60-routes.yaml (lines 5-24)
apiVersion: route.openshift.io/v1
kind: Route
metadata:
  name: cai-moderator-ui
  namespace: {{ $modNs }}
spec:
  host: {{ .Values.routes.hostname | quote }}
  path: /
  port:
    targetPort: 5500
  tls:
    termination: {{ .Values.routes.tlsTermination }}
  to:
    kind: Service
    name: cai-moderator
```

#### Guardrail State Persistence

The frontend persists F5 guardrail URL and API token to a JSON file, enabling settings to survive page refreshes. The Helm chart sets this to an `emptyDir` volume; a PVC can be used for pod-restart persistence.

```python
# frontend/llama_stack_ui/distribution/ui/modules/guardrails_storage.py (lines 15-51)
def state_path() -> Path:
    override = os.environ.get("F5_GUARDRAILS_STATE_FILE", "").strip()
    if override:
        return Path(override)
    return Path.home() / ".config" / "f5-guardrails" / "guardrails_state.json"

def write_state(guardrail_url: str, api_token: str) -> None:
    p = state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump({"guardrail_url": guardrail_url, "api_token": api_token}, f, indent=2)
```

### Prompt / Chain Patterns

Guardrails operate entirely outside the prompt chain. The Moderator intercepts the request at the HTTP transport level -- the prompt content, system prompt, and any RAG context are all evaluated as-is by the guardrail scanners. No prompt modifications are needed for guardrail enforcement, and no guardrail-specific prompt templates exist. The client application sends standard OpenAI-compatible requests; the only difference is the target URL.

For the dual-panel chat (chat.py), both the F5-guarded and LlamaStack-direct paths receive exactly the same `messages_for_api` payload (including identical RAG context if selected). The Moderator does not modify prompts that pass -- it either blocks or forwards them unchanged.

### Gotchas

- The Moderator endpoint URL pattern is `https://<hostname>/openai/<connection-name>/chat/completions`. The `<connection-name>` is the display name set when creating a model connection in the Moderator UI (e.g., `llamastack`), not the model ID. The Makefile auto-generates the hostname from the OpenShift ingress domain and `MODERATOR_HOST_PREFIX` (default `aisec`): `aisec.<ingress.apps.domain>`. The Makefile passes this as `routes.hostname` and `securityOperator.moderator.baseUrl` to the Helm chart.
- The Prompt Injection guardrail may produce false positives when processing RAG content injected into prompts. The use case guide (docs/ai_guardrails_use_cases.md, line 221) warns: "consider tuning the guardrail sensitivity or relying on other guardrails for RAG-sourced content." Since RAG context is retrieved from LlamaStack directly (not through the Moderator), the Moderator sees the combined prompt+context and may flag retrieved content as injection.
- The `anyuid` SCC must be granted to seven service accounts across four namespaces (`cai-moderator`, `prefect`, `f5-ai-sec-inference`) -- see `50-scc-anyuid-bindings.yaml`. This is required because the Calypso AI containers run as specific non-root UIDs.
- The F5 AI Security Operator installation requires a two-pass Helm apply: the first pass installs the OLM Subscription and namespace resources, then the Makefile waits for the `SecurityOperator` CRD to be registered (up to 120s), and the second pass renders the `SecurityOperator` CR. The chart uses a `lookup` function to detect the CRD at render time (`securityOperator.waitForCrd: true`), skipping the CR on the first pass when the CRD does not yet exist.
- The controller-manager service account needs extra RBAC beyond what the OLM CSV provides: `pods/status` watch and `batch/cronjobs,jobs` CRUD for the jobManager Helm release, plus `securitycontextconstraints` patch on a pre-created SCC for inference models (see `56-controller-manager-rbac.yaml`). The inference model SCC (`extras/openshift-inference-models-scc.yaml`) must be pre-applied by a cluster admin because the operator SA cannot create SCCs.
- Guardrail state (URL + API token) is persisted to `F5_GUARDRAILS_STATE_FILE` (default `/data/guardrails_state.json` on the `emptyDir` volume). This is lost when the pod is replaced. The README notes: "use a PVC on /data for values that must survive rescheduling."
- The `extra_body={"repetition_penalty": ...}` parameter is sent only in the LlamaStack Direct panel, not through the F5 Guardrails panel (chat.py line 402 vs 447). The comment in chat.py line 401 explains: "Do not send vLLM-only extra_body through the Moderator; some stacks return 200 with empty messages."
- The Moderator requires 1-3 additional GPUs for AI scanner models (`cai-phi-4` at 24 GB VRAM) and optional red-team models (`cai-mistral-nemo` at 48 GB VRAM). These are separate from the LLM and embedding model GPUs.

---

## Choosing Between Approaches

| Criteria | Approach A (LlamaStack Shields) | Approach B (F5 AI Guardrails) |
|----------|-------------------------------|------------------------------|
| Enforcement model | Per-agent shields in runner code | External proxy at network level |
| Application changes needed | Yes (shield IDs in agent config, runner integration) | No (change target URL only) |
| Enforcement modes | Block only | Block, Audit, Redact |
| Failure behavior | Fail-open (shield errors logged, request proceeds) | Fail-closed (proxy errors block request) |
| Configuration management | Developer-managed (JSON columns, CRUD API) | Security-team-managed (Moderator UI) |
| OOTB scanner coverage | Depends on LlamaStack-registered shields | Prompt Injection, PII, EU AI Act, Restricted Topics + custom |
| Custom guardrail types | Shield models registered in LlamaStack | GenAI (NL description), Keyword, Regex |
| Observability | Application logs only | Dashboard, Logs, Reports in Moderator UI |
| Red team testing | Not built in | Built-in AI Red Team attack campaigns |
| GPU overhead | None (uses existing safety models) | 1-3 GPUs for scanner/red-team models |
| Scope | Per-agent (different policies per agent) | Per-project (shared policies for a connection) |
| Response scanning | LlamaStack Responses API refusal types | Moderator scans response on return path |
