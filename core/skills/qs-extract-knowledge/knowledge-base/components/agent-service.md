---
name: agent-service
description: "CloudEvent-driven FastAPI agent service with LangGraph state machines, LlamaStack LLM integration, and multi-agent routing"
summary: "CloudEvent-driven FastAPI agent service that orchestrates multi-agent conversations using YAML-driven LangGraph state machines (state types: llm_processor, intent_classifier, llm_validator, waiting, terminal) with LlamaStack Responses API for LLM inference, receiving REQUEST_CREATED events via Knative broker and publishing AGENT_RESPONSE events with Langfuse/MLflow/OpenTelemetry observability. Use when building event-driven multi-agent backends with configurable conversation flows — a routing agent classifies intent and delegates to specialist agents with specialist lock and channel behavior policies controlling auto-return; session ordering uses PostgreSQL advisory locks (HTTP 503 rejection) and idempotent try-claim releasing on retriable errors (502/503/504) for broker redelivery. Agents defined in YAML (config/agents/*.yaml) with MCP server connections, pgvector-backed LlamaStack vector stores using file_search tools, NeMo Guardrails input/output shields via /v1/guardrail/checks, and LangGraph state machine configs overridable at runtime via LG_PROMPT_<AGENT_NAME> env vars. Critical gotchas: Kubernetes auto-injects LLAMASTACK_PORT as tcp:// URI — use LLAMASTACK_CLIENT_PORT or LLAMASTACK_SERVICE_PORT instead; LlamaStack requires dummy api_key (\"dummy-key\"); AsyncPostgresSaver connection drops need retry with checkpointer singleton reset; SESSION_LOCK_WAIT_TIMEOUT (default 180s) must exceed agent processing timeout; LangGraph waiting nodes require _consumed_this_invoke flag to prevent duplicate message consumption."
metadata:
  type: component
tags:
  tech_stack: [fastapi, python, langgraph, langchain, llamastack, openai, pydantic, sqlalchemy, structlog, httpx, uvicorn]
  ai_pattern: [agents, guardrails, vector-search, prompt-chaining]
  platform: [openshift, kubernetes]
  data_layer: [pgvector, postgresql]
source_examples:
  - quickstart: "it-self-service-agent"
    repo: "https://github.com/rh-ai-quickstart/it-self-service-agent"
    notes: "Multi-agent IT self-service backend with routing agent, specialist agents, YAML-driven LangGraph state machines, and LlamaStack Responses API"
    approach: "A"
---

# Agent Service

## Overview

The agent service is a CloudEvent-driven FastAPI backend that orchestrates multi-agent conversations using LangGraph state machines and LlamaStack for LLM inference. It receives user requests as CloudEvents from a Knative broker, routes them through a configurable agent hierarchy (routing agent to specialist agents), manages conversation state via PostgreSQL-backed LangGraph checkpoints, and publishes response events back through the broker. The service integrates with MCP tool servers, vector-store-backed knowledge bases, and observability platforms (Langfuse, MLflow, OpenTelemetry).

## Tech Stack & Dependencies

- **Runtime:** Python 3.12+, FastAPI >= 0.129.0, Uvicorn
- **Container image:** No standalone Dockerfile; built as part of a monorepo workspace
- **Key dependencies:**
  - `langgraph==1.0.7` with `langgraph-checkpoint-postgres` for persistent state machines
  - `llama-stack-client==0.5.0` for LLM inference via LlamaStack Responses API
  - `langchain-core>=1.2.11` for message types (HumanMessage, AIMessage)
  - `cloudevents>=1.10.0` for CloudEvent parsing/creation
  - `httpx>=0.25.0` for async HTTP (broker publishing, NeMo Guardrails calls)
  - `sqlalchemy` (async) for session/request database operations
  - `structlog` for structured JSON logging
  - `langfuse>=3.0.0` and `mlflow>=2.14.0` for LLM observability
  - `opentelemetry-instrumentation-fastapi` for distributed tracing
  - Local workspace packages: `shared-models`, `shared-clients`, `tracing-config`
- **Helm subchart:** N/A (uses shared Kubernetes service configuration)

## Key Patterns

### YAML-Driven LangGraph State Machine

Conversation flows are defined entirely in YAML, not code. Each agent references a `lg_state_machine_config` YAML file that declares states, transitions, prompts, and business fields. The `StateMachine` class dynamically creates a TypedDict state schema and LangGraph `StateGraph` from the YAML at runtime.

```yaml
# config/lg-prompts/routing.yaml (excerpt)
settings:
  initial_state: "greet_and_identify_need"
  terminal_state: "end"
  empty_response_retry_count: 5

state_schema:
  business_fields:
    routing_decision:
      type: "string"
      default: null

states:
  greet_and_identify_need:
    type: "llm_processor"
    temperature: 0.3
    prompt: |
      You are a routing agent...
    transitions:
      success: "waiting_user_need"
```

State types include `llm_processor` (sends prompt to LLM), `intent_classifier` (classifies user intent), `llm_validator` (validates user input), `waiting` (pauses for user message), and `terminal` (ends the flow).

### Multi-Agent Routing with Specialist Lock

The `ResponsesSessionManager` manages a hierarchy of agents: a routing agent classifies user intent, then hands off to specialist agents. Once on a specialist, a "specialist lock" prevents routing decisions from accidentally leaving the current specialist. Channel behavior policies can disable auto-return to the router for ticket-scoped sessions.

```python
# session_manager.py - specialist lock logic
if (
    routed_agent
    and self._is_specialist_session()
    and self.current_agent_name
    and routed_agent != self.current_agent_name
):
    allow_return_to_router = (
        routed_agent == self.effective_router_id
        and self._allow_auto_return_to_router()
    )
    if not allow_return_to_router:
        routed_agent = None
```

### LlamaStack Responses API Integration

Agents call LLMs through `llama-stack-client` using the Responses API (not Chat Completions). The client factory uses Kubernetes-injected service discovery environment variables with a specific port resolution order to avoid the `LLAMASTACK_PORT` variable that Kubernetes sets to a `tcp://` URI.

```python
# utils/llamastack_client.py - port resolution
port_str = os.environ.get("LLAMASTACK_CLIENT_PORT") or os.environ.get(
    "LLAMASTACK_SERVICE_PORT", "8321"
)
```

### CloudEvent-Based Event-Driven Architecture

The service receives `REQUEST_CREATED` CloudEvents, processes them, and publishes `AGENT_RESPONSE` CloudEvents back through a Knative broker. An idempotent try-claim pattern prevents duplicate event processing, and retriable errors (502, 503, 504) release the claim so the broker can redeliver.

```python
# main.py - try-claim with retriable error handling
claimed = await DatabaseUtils.try_claim_event_for_processing(
    db, event_id, event_type, event_source, "agent-service",
)
if not claimed:
    return {"status": "skipped", "reason": "duplicate event"}
```

### Agent Configuration via YAML

Each agent is defined in a YAML file under `config/agents/` specifying name, system message, LangGraph state machine config path, MCP server connections, and knowledge base references.

```yaml
# config/agents/laptop-refresh-agent.yaml
name: "laptop-refresh"
system_message: "You are a helpful laptop refresh assistant..."
lg_state_machine_config: "config/lg-prompts/lg-prompt-big.yaml"
mcp_servers:
  - name: "snow"
    uri: "http://mcp-self-service-agent-snow:8000/mcp"
    require_approval: "never"
knowledge_bases: ["laptop-refresh"]
```

### Session Locking and Request Ordering

A PostgreSQL advisory lock per session ensures only one request processes at a time. An ordering check rejects requests (HTTP 503) if an earlier request for the same session is still pending, relying on the Knative broker's retry mechanism to redeliver.

```python
# main.py - session lock with ordering defense
if await has_earlier_pending_or_processing(
    request.session_id, created_at, lock_db
):
    raise HTTPException(status_code=503, detail="Earlier request still processing")
acquired = await acquire_agent_session_lock(
    request.session_id, lock_db, timeout_seconds=_AGENT_LOCK_TIMEOUT
)
```

### Knowledge Base Registration via LlamaStack Vector Stores

The `KnowledgeBaseManager` creates pgvector-backed vector stores through LlamaStack's OpenAI-compatible API, uploading `.txt` files and attaching them to vector stores that agents reference by name at inference time via `file_search` tools.

```python
# knowledge/kb_manager.py - vector store creation
vector_store = self._llama_client.vector_stores.create(
    name=vector_store_name, extra_body={"provider_id": "pgvector"}
)
```

### NeMo Guardrails Integration

Input and output guardrails are optionally applied via NeMo Guardrails `/v1/guardrail/checks` endpoint. The `check_input_shield` runs before the state machine sees the message; `check_output_shield` runs before the response is returned to the user.

## Configuration

- **Environment variables:**
  - `BROKER_URL` (required): Knative broker URL for CloudEvent publishing
  - `LLAMASTACK_SERVICE_HOST` / `LLAMASTACK_CLIENT_PORT`: LlamaStack connection (Kubernetes-injected)
  - `DEFAULT_AGENT_ID`: Default routing agent name (default: `routing-agent`)
  - `SESSION_LOCK_WAIT_TIMEOUT`: PostgreSQL advisory lock timeout in seconds (default: `180`)
  - `LG_PROMPT_<AGENT_NAME>`: Override LangGraph YAML config path per agent at runtime
  - `USE_NEMO_GUARDRAILS` / `NEMO_GUARDRAILS_URL`: Enable/configure NeMo guardrails
  - `LANGFUSE_ENABLED` / `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` / `LANGFUSE_HOST`: Langfuse tracing
  - `MLFLOW_ENABLED` / `MLFLOW_TRACKING_URI` / `MLFLOW_EXPERIMENT_NAME`: MLflow tracing
  - `SERVICENOW_API_KEY`: Passed through to MCP servers as `SERVICE_NOW_TOKEN` header
  - `SHOW_EMPTY_RESPONSE_INFO`: Enable detailed debug output for empty LLM responses
  - `FAULT_INJECTION_MAX_RETRIES`: Override retry count for testing
- **Config files:**
  - `config/config.yaml`: Global config (timeout settings)
  - `config/agents/*.yaml`: Per-agent definitions (model, system message, MCP servers, knowledge bases)
  - `config/lg-prompts/*.yaml`: LangGraph state machine configurations (states, prompts, transitions)
- **Helm values:** Not directly configured; environment variables are set via Helm chart values

## Known Gotchas

- **Kubernetes `LLAMASTACK_PORT` collision:** Kubernetes auto-injects `LLAMASTACK_PORT` as `tcp://host:port`, which breaks URL construction. The code explicitly avoids this variable and uses `LLAMASTACK_CLIENT_PORT` (Helm override) or `LLAMASTACK_SERVICE_PORT` instead (see `utils/llamastack_client.py`).
- **LlamaStack dummy API key:** LlamaStack in-cluster does not require authentication, but the OpenAI client library requires an `api_key` parameter. The code uses `"dummy-key"` as a placeholder (see `utils/llamastack_client.py`).
- **AsyncPostgresSaver connection loss:** The PostgreSQL checkpoint connection can drop. `_get_state_with_retry` in `ConversationSession` detects "connection is closed" errors, resets the global checkpointer singleton, and retries once with a fresh connection.
- **LangGraph waiting node message consumption:** Each `invoke` call allows only one waiting node to consume a HumanMessage (tracked via `_consumed_this_invoke` flag). Without this, multiple waiting nodes in a single invocation would each try to consume the same message.
- **LangGraph prompt override via env vars:** Each agent's LangGraph config can be overridden at runtime by setting `LG_PROMPT_<AGENT_NAME_UPPER>` (hyphens converted to underscores). This is used for A/B testing prompt variants without redeploying.
- **Session lock timeout must exceed agent timeout:** The `SESSION_LOCK_WAIT_TIMEOUT` (default 180s) must be >= the agent processing timeout so queued requests can wait rather than fail immediately.

## Testing Notes

- Unit tests exist at `agent-service/tests/` covering channel behavior policy loading and the try-claim event pattern
- The `fault_injector.py` utility wraps the LlamaStack client to inject failures for resilience testing, controllable via `FAULT_INJECTION_*` environment variables
- Verify the agent service health via `GET /health` (lightweight, no DB) and `GET /health/detailed` (includes database connectivity check)
- After deployment, confirm CloudEvent flow by sending a test `REQUEST_CREATED` event to the `/api/v1/events/cloudevents` endpoint and checking for a published response event

## Related Patterns

- LlamaStack model serving and vector stores
- CloudEvent / Knative eventing architecture
- MCP server integration for tool use
- PostgreSQL session management and LangGraph checkpointing
