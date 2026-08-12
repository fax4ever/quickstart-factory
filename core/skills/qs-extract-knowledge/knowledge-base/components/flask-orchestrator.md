---
name: flask-orchestrator
description: Flask-based multi-agent orchestrator that discovers remote tool servers and runs OpenAI-compatible agentic loops
summary: "Solves multi-agent coordination where a Flask backend (Python 3.12/UBI10 minimal, openai SDK 2.5.0) discovers tools from remote HTTP servers via HttpToolServer GET /tools and invokes them via POST /tools/{tool_name} with duplicate-name detection, running an OpenAI-compatible agentic loop capped at 20 iterations for LLM-driven tool selection across microservices. Use for multi-service architectures requiring a two-phase pipeline -- Phase 1 (/pipeline) runs deterministic sequential tool calls (guidelines, portfolio, VaR with retry up to 10 attempts, email) without LLM selection, while Phase 2 provides conversational chat with the LLM choosing from a restricted PHASE2_TOOLS subset with full context injection and dynamic per-request LLM endpoint/model/API key from client payload for vLLM compatibility; prefer fastapi-backend when async performance is needed. Configure tool servers via comma-separated TOOL_SERVERS env var, toggle NeMo Guardrails sidecar (validates both check_input and check_output with graceful degradation when unreachable) via guardrails.enabled Helm value and GUARDRAILS_URL env var, and use /health as Kubernetes readiness probe. ToolRegistry is lazily constructed per request via Flask's g context adding discovery latency; tool name collisions across servers raise ValueError/RuntimeError halting discovery; numpy/scipy/scikit-learn require separate binary-only pip install before requirements.txt on UBI minimal; the 20-iteration agentic loop cap exits without error risking silent truncation of complex multi-step interactions."
metadata:
  type: component
tags:
  tech_stack: [flask, python, openai, requests]
  ai_pattern: [agents, guardrails, prompt-chaining]
  platform: [openshift]
  data_layer: []
source_examples:
  - quickstart: "portfolio-manager-agent"
    repo: "https://github.com/rh-ai-quickstart/portfolio-manager-agent"
    notes: "Flask orchestrator coordinating risk, portfolio, and guidelines tool servers with NeMo Guardrails integration"
    approach: "A"
---

# Flask Orchestrator

## Overview

A Flask backend that acts as the central orchestrator in a multi-agent architecture. It discovers tools from remote HTTP tool servers at runtime, builds OpenAI function-calling payloads, and runs an agentic loop where an LLM decides which tools to invoke. Used in quickstarts where multiple specialized microservices (each exposing tools via HTTP) need to be coordinated by an LLM-driven conversation.

## Tech Stack & Dependencies

- **Runtime:** Python 3.12 on UBI10 minimal (`registry.access.redhat.com/ubi10/python-312-minimal`)
- **Container image:** `quay.io/ikatav/portfolio-manager-agent:orchestrator`
- **Key dependencies:** Flask 3.1.2, flask-cors 6.0.1, openai 2.5.0 (OpenAI-compatible SDK), requests 2.32.5, numpy, scipy, scikit-learn
- **Helm subchart:** None -- part of a monolithic Helm chart at `deploy/helm/`

## Key Patterns

### HTTP Tool Server Discovery

The `HttpToolServer` class discovers tools from remote agent servers via `GET /tools` and invokes them via `POST /tools/{tool_name}`. Tools are registered into a flat map keyed by tool name, with duplicate detection.

```python
class HttpToolServer:
    def discover(self) -> list[DiscoveredTool]:
        url = urljoin(self.base_url, "tools")
        resp = requests.get(url, timeout=self.timeout)
        resp.raise_for_status()
        tools = []
        for item in resp.json():
            tools.append(
                DiscoveredTool(
                    name=item["name"],
                    description=item.get("description", ""),
                    parameters=item.get("parameters", {"type": "object", "properties": {}}),
                    server_base=self.base_url,
                )
            )
        return tools
```

### Agentic Loop with Tool Calling

The `Orchestrator._run_agentic_loop` method sends messages to an OpenAI-compatible LLM, processes any tool calls from the response, appends results back to the conversation, and repeats. A hard cap of 20 iterations prevents runaway loops.

```python
while need_to_call_llm and llm_count < 20:
    kwargs: dict = {
        "model": self.model,
        "messages": prompts,
        "temperature": temperature,
    }
    if tools:
        kwargs["tools"] = tools
    response = self.openai.chat.completions.create(**kwargs)
    need_to_call_llm = False
    # ... process tool_calls, append to prompts, set need_to_call_llm = True
```

### Two-Phase Pipeline Architecture

Phase 1 is a deterministic pipeline of tool calls (parse guidelines, build portfolio, calculate VaR, generate email) with no LLM decision-making on which tools to call. Phase 2 is a conversational chat endpoint where the LLM selects from a restricted tool subset (`PHASE2_TOOLS`) with full portfolio context injected into the system prompt.

```python
PHASE2_TOOLS = {"portfolio_equities", "portfolio_replace_symbol", "value_at_risk"}

# Phase 1: deterministic pipeline
result = run_pipeline(registry, llm_client, llm_model, url, portfolio_value, qty_symbols, max_var)

# Phase 2: agentic chat with context and tool subset
result = orchestrator.chat_with_context(
    system, messages, ctx,
    allowed_tools=PHASE2_TOOLS,
    temperature=temperature,
    on_tool_result=on_tool,
)
```

### Dynamic LLM Configuration Per Request

The LLM endpoint, model, and API key are not hardcoded or set via environment variables. They come from the client payload on each request, allowing the frontend to point at different OpenAI-compatible inference endpoints (e.g., vLLM on RHOAI).

```python
def parse_llm_config(payload: dict) -> tuple[OpenAI, str] | tuple[None, str]:
    config = payload.get("config") or {}
    llm_base_url = config.get("llmUrl") or config.get("llm_url")
    llm_model = config.get("model")
    llm_api_key = config.get("apiKey") or config.get("api_key")
    client = OpenAI(base_url=llm_base_url, api_key=llm_api_key)
    return client, llm_model
```

### NeMo Guardrails Sidecar Integration

Input and output guardrails are applied via an optional NeMo Guardrails service. The client gracefully degrades: if `GUARDRAILS_URL` is unset or the service is unreachable, all messages pass through. Both user input (`check_input`) and LLM output (`check_output`) are validated.

```python
GUARDRAILS_URL = os.getenv("GUARDRAILS_URL", "").rstrip("/")

def _check(messages: list[dict], model: str = "test") -> CheckResult:
    if not GUARDRAILS_URL:
        return CheckResult(allowed=True, detail="guardrails not configured")
    url = f"{GUARDRAILS_URL}/v1/guardrail/checks"
    payload = {"model": model, "messages": messages}
    try:
        resp = requests.post(url, json=payload, timeout=_TIMEOUT)
        # ...
    except requests.RequestException as exc:
        return CheckResult(allowed=True, detail=f"guardrails unavailable: {exc}")
```

### VaR Retry Loop

When building a portfolio in Phase 1, the pipeline retries up to `MAX_PORTFOLIO_ATTEMPTS` (10) times if the calculated Value-at-Risk exceeds the threshold, raising a `RuntimeError` with the last VaR value if all attempts fail.

```python
for attempt in range(1, MAX_PORTFOLIO_ATTEMPTS + 1):
    portfolio = build_portfolio(registry, portfolio_value, qty_symbols, prohibited_tickers)
    var_result = calculate_var(registry, portfolio)
    value_at_risk = float(var_result.get("valueAtRisk", 0))
    if value_at_risk <= max_var:
        return portfolio, value_at_risk, attempts
raise RuntimeError(
    f"Could not build a portfolio within max VaR (${max_var:,.2f}) after "
    f"{MAX_PORTFOLIO_ATTEMPTS} attempts. Last VaR: ${value_at_risk:,.2f}."
)
```

## Configuration

- **Environment variables:**
  - `PORT` -- Flask listen port (default `5000`)
  - `TOOL_SERVERS` -- Comma-separated URLs of remote tool agent servers (default `http://localhost:7001,http://localhost:7002,http://localhost:7003`)
  - `GUARDRAILS_URL` -- Optional NeMo Guardrails endpoint; empty string disables guardrails
  - `GUARDRAILS_TIMEOUT` -- Timeout in seconds for guardrails calls (default `10`)
  - `PYTHONUNBUFFERED` -- Set to `1` in deployment for real-time log output
- **Config files:** None -- all configuration is via environment variables and request payload
- **Helm values:**
  - `image.repository` and `image.tags.orchestrator` -- container image reference
  - `guardrails.enabled` -- toggles `GUARDRAILS_URL` env var injection in the deployment template
  - `replicas` -- number of orchestrator pods

## Known Gotchas

- The `ToolRegistry` is constructed lazily via Flask's `g` context, so tool discovery HTTP calls happen once per incoming HTTP request. This avoids stale caches but adds latency to each request. Found in `app.py` `get_tool_registry()`.
- The Dockerfile installs `numpy`, `scipy`, and `scikit-learn` as binary-only packages (`--only-binary=:all:`) in a separate `pip install` before the main `requirements.txt`, because these packages require native compilation that would fail on UBI minimal without a full build toolchain. Found in `orchestrator/src/Dockerfile`.
- The agentic loop hard cap of 20 iterations means complex multi-step tool interactions could silently truncate. The loop exits without error, returning whatever partial content the LLM last produced. Found in `orchestrator.py` `_run_agentic_loop`.
- The `openai` SDK is used to talk to OpenAI-compatible endpoints (e.g., vLLM), not the OpenAI API itself. The `base_url` is set dynamically per request from the frontend payload. Found in `app.py` `parse_llm_config`.
- Tool name collisions across multiple tool servers raise `ValueError` (in `Orchestrator.refresh_tools`) or `RuntimeError` (in `ToolRegistry.__init__`), halting discovery. Each tool server must expose globally unique tool names. Found in `orchestrator.py` and `pipeline.py`.

## Testing Notes

- The `/health` endpoint returns `{"status": "ok"}` and is used as the Kubernetes readiness probe (`initialDelaySeconds: 5`, `periodSeconds: 5`)
- The `/info` endpoint returns app metadata including `max_portfolio_attempts`, useful for integration test assertions
- Phase 1 pipeline endpoints can be tested individually (`/pipeline/guidelines`, `/pipeline/portfolio`, `/pipeline/var`, `/pipeline/email`) or as a single call to `/pipeline`
- Guardrails integration can be tested by toggling `GUARDRAILS_URL` -- when unset, the orchestrator should pass all messages through without error

## Related Patterns

- `nemo-guardrails` -- NeMo Guardrails service used as the validation sidecar
- `mcp-risk-server` -- similar HTTP tool server pattern for risk calculation
- `fastapi-backend` -- alternative Python backend framework used in other quickstarts
