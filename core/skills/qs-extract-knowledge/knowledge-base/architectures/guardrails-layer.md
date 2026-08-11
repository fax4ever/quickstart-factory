---
name: guardrails-layer
description: Input/output safety shields via LlamaStack safety API with per-agent configuration
summary: "Implements AI safety guardrails via LlamaStack's safety.run_shield API with two mechanisms: per-agent input shields that sequentially validate extracted user text before inference via AsyncLlamaStackClient, short-circuiting the SSE stream on violation, and output refusal handling where the Responses API emits refusal content types caught by _handle_response_completed in the StreamAggregator. Use when building multi-agent LlamaStack systems needing per-agent safety policies with independent shield configurations stored as JSON columns on the VirtualAgent model; shield execution runs before RAG retrieval so blocked content never reaches knowledge base search — not available for LangGraph or CrewAI runners which lack equivalent validation. Each agent's input_shields and output_shields are JSON columns in PostgreSQL while a separate FastAPI CRUD API (/api/v1/guardrails/) manages named policy rules for UI presentation — these are distinct from server-side LlamaStack shield IDs (e.g., Llama Guard) that perform actual safety classification via client.safety.run_shield(shield_id=shield_id, messages=[{\"role\": \"user\", \"content\": text_content}]). Architecture is fail-open — input shield errors are caught and logged but don't block chat flow, meaning network errors or misconfiguration bypass safety validation entirely; output_shields rely on LlamaStack server-side enforcement rather than explicit runner execution; and the CRUD API guardrail records are separate from the LlamaStack shield IDs configured on agents."
metadata:
  type: architecture
tags:
  tech_stack: [fastapi, llamastack, python]
  ai_pattern: [guardrails, agents]
  platform: [llamastack, rhoai, openshift]
  data_layer: [postgresql]
source_examples:
  - quickstart: "ai-virtual-agent"
    repo: "https://github.com/rh-ai-quickstart/ai-virtual-agent"
    notes: "Per-agent input shields via LlamaStack safety.run_shield API, guardrail CRUD for policy management, and refusal handling in response stream"
    approach: "A"
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
