---
name: observability-summarization
description: LLM-powered observability analysis using tool-calling agents to query and summarize metrics, traces, logs, and alerts
summary: "Enables natural-language cluster health analysis by using LLM tool-calling agents that autonomously query OpenShift observability backends (Prometheus/Thanos, Tempo, Korrel8r, Alertmanager) and synthesize results into human-readable summaries via a React/OpenShift Console plugin frontend. Use when building an agentic observability assistant needing multi-provider LLM support -- the chatbot factory routes by model name prefix to provider-specific tool-calling implementations (OpenAI function calling, Anthropic tool_use blocks, Google function declarations, Llama/vLLM via Llama Stack), with three prompt patterns: autonomous tool-calling chat loops, structured single-shot analysis (analyze_vllm/analyze_openshift via summarize_with_llm()), and a separate CronJob alert receiver using LlamaStackClient for Slack notifications. Critical patterns include namespace-scoped PromQL injection via regex with a 60+ entry _PROMQL_SKIP frozenset to avoid false injection into non-metric identifiers, MCPServerAdapter executing FastMCP tools in-process with tool results returned to the LLM loop, Korrel8r cross-signal correlation with concurrent Tempo trace fetching (asyncio semaphore capped at 10), and API key resolution via priority chain (UI-provided then Kubernetes Secret fallback). Key gotchas: local vLLM models require temperature=0.1 and repetition_penalty=1.5 with 400 max tokens (vs temperature=0 and 6000 tokens for external); DeterministicChatBot fallback for Llama 3.2 achieves only ~67% tool-call accuracy via regex parsing; message truncation must preserve tool-call/result pair atomicity to prevent LLM hallucination from orphaned calls; and the Anthropic chatbot must strip spurious function_calls XML blocks emitted alongside native tool_use API responses."
metadata:
  type: architecture
tags:
  tech_stack: [fastapi, fastmcp, python, react, patternfly, typescript, openai-sdk, anthropic-sdk, httpx]
  ai_pattern: [agents, prompt-chaining, model-serving]
  platform: [rhoai, openshift, vllm, kserve, kubernetes]
  data_layer: []
source_examples:
  - quickstart: "openshift-ai-observability-summarizer"
    repo: "https://github.com/rh-ai-quickstart/openshift-ai-observability-summarizer"
    notes: "Multi-provider chatbot with tool-calling LLMs that dynamically query Prometheus/Thanos, Tempo, Korrel8r, and Alertmanager to produce natural-language observability summaries"
    approach: "A"
---

# Observability Summarization

## Overview

This architecture uses LLM-powered tool-calling agents to dynamically query OpenShift observability backends (Prometheus/Thanos for metrics, Tempo for traces, Korrel8r for signal correlation, Alertmanager for alerts, Loki for logs) and produce natural-language summaries of cluster and workload health. Rather than hard-coding which queries to run, the LLM receives a system prompt describing available observability tools and autonomously decides which tools to call based on the user's question. A multi-provider chatbot factory routes to the appropriate LLM provider (OpenAI, Anthropic, Google, Llama/local vLLM) with each implementing its own tool-calling loop. Namespace scoping is enforced by injecting namespace filters into PromQL queries and tool arguments before execution.

## Data Flow

1. User submits a natural-language question via React UI or OpenShift Console plugin
2. Frontend calls the `chat` MCP tool via JSON-RPC HTTP with model name, question, namespace, and optional conversation history
3. The `chat` tool creates a chatbot instance via the factory (selecting provider-specific implementation based on model name)
4. Chatbot receives the user question with a system prompt listing available observability tools and their usage patterns
5. LLM decides which tools to call (e.g., `search_metrics`, `execute_promql`, `chat_tempo_tool`, `korrel8r_get_correlated`)
6. Chatbot routes tool calls via `MCPServerAdapter` which executes them in-process against the FastMCP server
7. Tool implementations query external observability backends (Prometheus/Thanos, Tempo, Korrel8r, Alertmanager) via HTTP
8. Tool results are returned to the LLM, which may call additional tools or produce the final summary
9. LLM generates a natural-language response with analysis, recommendations, and technical details (PromQL used, metric sources)
10. Response is returned to the frontend with progress log and iteration count

## Component Wiring

| From | To | Protocol | Purpose |
|------|----|----------|---------|
| React/Console UI | MCP Server (`/mcp`) | HTTP (JSON-RPC) | Call `chat`, `analyze_vllm`, `analyze_openshift`, `fetch_*_metrics_data` tools |
| MCP `chat` tool | Chatbot Factory | Python (in-process) | Create provider-specific chatbot with MCPServerAdapter |
| Chatbot (any provider) | MCPServerAdapter | Python (in-process, ToolExecutor interface) | Execute MCP tools during tool-calling loop |
| MCPServerAdapter | FastMCP tools | Python (async, separate thread) | Run tool functions via `tool.run(arguments)` |
| Prometheus tools | Thanos/Prometheus | HTTP REST (`/api/v1/query_range`, `/api/v1/label/__name__/values`) | Execute PromQL queries, search metrics, get metadata |
| Tempo tools | Tempo (TempoStack gateway) | HTTP REST | Query traces, get trace details |
| Korrel8r tools | Korrel8r service | HTTP REST (`/api/v1/objects`, `/api/v1/lists/goals`) | Signal correlation across metrics, traces, logs, alerts |
| Alertmanager integration | Alertmanager | HTTP REST (`/api/v2/alerts`) | Fetch active alerts for LLM summarization |
| Alert receiver | Llama Stack (local model) | HTTP REST (`/chat/completions`) | Generate plain-English alert descriptions |
| Alert receiver | Slack | HTTP (webhook) | Post formatted alert summaries |
| OpenShift/vLLM analyze tools | Thanos + LLM | HTTP + Python | Fetch metrics then summarize with LLM via `summarize_with_llm()` |

## Key Integration Points

### Multi-Provider Chatbot Factory

The chatbot factory detects the provider from the model name and creates the appropriate implementation. Each provider implements its own tool-calling loop (OpenAI function calling, Anthropic tool_use blocks, Google function declarations, Llama native tool calls). All share the same `BaseChatBot` base class with common tool execution, namespace injection, and message truncation logic.

```python
# src/chatbots/factory.py (lines 108-144)
PROVIDER_PATTERNS = {
    "maas": [("maas/", True)],
    "anthropic": [("anthropic/", True), ("claude", False)],
    "openai": [("openai/", True), ("gpt-", True), ("o1-", True)],
    "google": [("google/", True), ("gemini", False)]
}

model_lower = model_name.lower()
provider = None
for prov, patterns in PROVIDER_PATTERNS.items():
    for pattern, is_startswith in patterns:
        if model_lower.startswith(pattern) if is_startswith else (pattern in model_lower):
            provider = prov
            break

# Route to provider-specific implementation
if provider == "anthropic":
    return AnthropicChatBot(model_name, api_key, tool_executor)
elif provider == "openai":
    return OpenAIChatBot(model_name, api_key, api_url, tool_executor)
elif provider == "google":
    return GoogleChatBot(model_name, api_key, tool_executor)
```

For local models (Llama), capability detection determines whether to use the tool-calling `LlamaChatBot` (3.1/3.3 with 8B/70B) or the `DeterministicChatBot` fallback (3.2 or unknown models with 67% tool-calling accuracy, using regex-based deterministic parsing).

### System Prompt Engineering for Observability Context

The base chatbot constructs a detailed system prompt that describes the environment (OpenShift cluster with AI/ML workloads, GPUs), available tools with usage guidelines, alert query strategies (Prometheus-first with Korrel8r escalation), response format requirements, and critical rules for metric interpretation (boolean status metrics, gauge vs counter handling, mandatory grouping by pod/namespace).

```python
# src/chatbots/base.py (lines 580-735)
def _get_base_prompt(self, namespace: Optional[str] = None) -> str:
    prompt = f"""You are an expert Kubernetes and Prometheus observability assistant.
    ...
    **Your Environment:**
    - Cluster: OpenShift with AI/ML workloads, GPUs, and comprehensive monitoring
    - Scope: {self._format_scope_line(namespace)}
    - Tools: Direct access to Prometheus/Thanos metrics via MCP tools
    {self._format_namespace_directive(namespace)}

    **Available Tools:**
    - search_metrics: Pattern-based metric search
    - execute_promql: Execute PromQL queries for actual data
    - chat_tempo_tool: Conversational trace analysis
    - get_correlated_logs: Namespace/pod log retrieval
    - korrel8r_get_correlated: Cross-signal correlation
    ...
    **Your Workflow:**
    1. Determine what the user is asking for (trace, metrics, logs, or alerts?)
    2. Discover -- for metrics questions, ALWAYS call search_metrics first
    3. Execute the query tool with the discovered metric names
    4. Answer with the specific data -- DONE!"""
```

### Namespace-Scoped PromQL Injection

When a namespace is active, the chatbot automatically injects `namespace="X"` into PromQL queries before sending them to Prometheus. This handles metrics with no existing labels, metrics with existing labels, and nested function calls (rate, histogram_quantile). A skip list of PromQL functions/keywords prevents false injection into non-metric identifiers.

```python
# src/chatbots/base.py (lines 319-379)
def _inject_namespace_into_promql(self, query: str, namespace: str) -> str:
    # If namespace filter already present, replace it
    if f'namespace="' in query:
        return re.sub(r'namespace\s*(?:!?=~?|!~)\s*["\'][^"\']*["\']',
                       f'namespace="{namespace}"', query)

    # Skip PromQL functions/keywords - they aren't metric selectors
    _PROMQL_SKIP = frozenset({'sum', 'avg', 'rate', 'irate', 'histogram_quantile', ...})

    def inject_ns(match):
        metric = match.group(1)
        if metric.lower() in _PROMQL_SKIP:
            return match.group(0)
        labels = match.group(2) or ''
        rest = match.group(3) or ''
        if labels:
            inner = labels[1:-1].strip()
            return f'{metric}{{{inner},namespace="{namespace}"}}{rest}'
        else:
            return f'{metric}{{namespace="{namespace}"}}{rest}'

    return re.sub(
        r'([a-zA-Z_:][a-zA-Z0-9_:]*)'  # metric name
        r'(\{[^}]*\})?'                  # optional labels
        r'(\[[^\]]*\])?',                # optional range vector
        inject_ns, query)
```

### Korrel8r Signal Correlation

Korrel8r bridges observability domains by taking a start query (e.g., a pod reference) and finding correlated objects across alert, trace, log, and metric domains. The `fetch_goal_query_objects` function executes Korrel8r's `list_goals` API, then for each goal queries the actual objects. For trace goals, it extracts unique trace IDs from Korrel8r results, fetches full trace details from Tempo concurrently (with asyncio semaphore limiting to 10 concurrent requests), and simplifies span data with namespace/pod enrichment from the Korrel8r context.

```python
# src/core/korrel8r_service.py (lines 390-512)
def fetch_goal_query_objects(goals, query, max_traces_per_query=None):
    client = Korrel8rClient()
    goals_result = client.list_goals(goals=goals, start={"queries": [query]})
    aggregated = {"logs": [], "traces": []}

    for item in goals_result:
        # Route by domain
        domain = goal_name.split(":", 1)[0].lower()
        bucket = "traces" if domain == "trace" else "logs"

        for q in item.get("queries", []):
            obj_result = client.query_objects(q["query"])
            if bucket == "traces":
                trace_ids = _extract_unique_trace_ids(obj_result, max_traces=max_traces_per_query)
                all_traces = _get_trace_details_sync(ids_to_fetch)
                for dt in all_traces:
                    aggregated[bucket].extend(_simplify_trace_detail_to_spans(dt, obj_result))
            elif bucket == "logs":
                simplified = client.simplify_log_objects(obj_result)
                aggregated[bucket].extend(simplified)
    return aggregated
```

### Tool Loop Detection and Message Truncation

The chatbot prevents infinite tool-calling loops by tracking consecutive iterations calling the same single tool. After 5 consecutive iterations with the same tool, the loop breaks. Message truncation preserves tool-call/result pair atomicity -- an assistant message with `tool_calls` is grouped with its subsequent tool-result messages, and truncation drops entire groups from the oldest end. This prevents orphaned tool calls that cause LLM hallucination.

```python
# src/chatbots/base.py (lines 134-170)
_MAX_CONSECUTIVE_SAME_TOOL = 5

def _check_tool_loop(self, tool_names_this_iteration, consecutive_tool_tracker):
    if len(tool_names_this_iteration) == 1:
        tool_name = next(iter(tool_names_this_iteration))
        if tool_name == consecutive_tool_tracker.get("name"):
            consecutive_tool_tracker["count"] += 1
        else:
            consecutive_tool_tracker["name"] = tool_name
            consecutive_tool_tracker["count"] = 1
    else:
        consecutive_tool_tracker["name"] = None
        consecutive_tool_tracker["count"] = 0
    return consecutive_tool_tracker["count"] >= self._MAX_CONSECUTIVE_SAME_TOOL
```

### Alert Summarization Pipeline

A separate alert receiver CronJob pulls active alerts from Alertmanager, filters for new vLLM alerts within a configurable time window, generates plain-English descriptions using a local Llama Stack model via `client.inference.chat_completion()`, and sends formatted Slack messages. The LLM prompt instructs interpretation of the alert's `expr` and `for` fields without exposing raw PromQL, affected component identification, and troubleshooting steps.

```python
# src/alerting/alert_receiver.py (lines 66-96)
def generate_description(labels: str) -> str:
    client = LlamaStackClient(base_url=LLAMA_STACK_URL)
    llm = next(m for m in client.models.list() if m.model_type == "llm")

    prompt = """You are an AI assistant designed to generate concise, informative,
    and *technically detailed* Slack message descriptions for OpenShift vLLM alerts.
    Analyze the provided alert data, *especially the 'expr' and 'for' fields*..."""

    response = client.inference.chat_completion(
        model_id=llm.identifier,
        messages=[
            {"role": "system", "content": prompt},
            {"role": "user", "content": labels},
        ],
        stream=False
    )
    return str(response.completion_message.content)
```

### API Key Resolution with Kubernetes Secret Fallback

The `resolve_api_key` function implements a priority chain: (1) API key provided directly by the UI, (2) API key from Kubernetes Secret. In production mode (running inside a pod), it reads the service account token and queries the Kubernetes API for secrets in the current namespace matching the model provider. In dev mode, the frontend auto-injects cached API keys from browser storage based on provider detection from the model name.

```python
# src/core/api_key_manager.py (concept)
# Priority: 1) Provided api_key (from UI), 2) Kubernetes secret
resolved_api_key = resolve_api_key(api_key=api_key, model_id=model_name)

# Frontend auto-injection in dev mode
# openshift-plugin/src/core/services/mcpClient.ts (lines 156-223)
async function injectDevCredentials(toolName, args):
    if (!checkDevMode()) return args;
    if (args.api_key) return args;
    // Detect provider from model_id, look up dev storage
    const devModel = devModels[modelId];
    if (devModel?.apiKey) injectedArgs.api_key = devModel.apiKey;
    if (devModel?.endpoint) injectedArgs.api_url = devModel.endpoint;
```

## Prompt / Chain Patterns

The architecture uses three distinct prompt patterns:

1. **Tool-calling chat loop**: The system prompt describes available tools; the LLM autonomously calls tools and synthesizes results. Each provider implements this differently -- OpenAI uses `function` tool type with `tool_calls` finish reason, Anthropic uses `tool_use` content blocks, Google uses `function_declarations`, and Llama uses OpenAI-compatible format via the Llama Stack chat/completions endpoint.

2. **Structured analysis prompts**: The `analyze_vllm` and `analyze_openshift` tools build domain-specific prompts with pre-fetched metrics data, then call `summarize_with_llm()` for a single-shot summary. The prompt includes the metric values, time range, and structured output requirements (5 analysis sections, max 150 words each).

3. **Alert summarization prompts**: The alert receiver sends alert labels to a local Llama model with instructions to produce a human-readable alert description suitable for Slack messages, interpreting PromQL expressions without exposing them directly.

## Gotchas

- Local vLLM models use `temperature=0.1` and `repetition_penalty=1.5` with stop sequences to prevent output degeneration. External models use `temperature=0` without repetition penalties since they handle this internally. Max tokens is capped at 400 for local models vs 6000 for external models.
- The `_inject_namespace_into_promql` method maintains a 60+ entry `_PROMQL_SKIP` frozenset of PromQL functions, keywords, and common Kubernetes label names to avoid injecting namespace filters into non-metric identifiers. This list is defined at module level to avoid rebuilding on every call.
- The `DeterministicChatBot` fallback for local models with unreliable tool calling (Llama 3.2) uses regex-based parsing of the model's text output to extract tool calls, achieving approximately 67% accuracy. This is selected automatically by the factory based on model version detection.
- The `BaseChatBot._truncate_messages()` method groups assistant messages with tool_calls alongside their subsequent tool-result messages as atomic units. Truncation drops entire groups from the oldest end (keeping at least the most recent group) to prevent orphaned tool calls that cause LLMs to hallucinate responses for tool calls they never received results for.
- Korrel8r normalization in `_normalize_korrel8r_query()` handles common AI-provided query format issues: missing class for alert domain (`alert:{` -> `alert:alert:{`), misclassified alerts (`k8s:Alert:` -> `alert:alert:`), unquoted selector keys, and escaped quotes.
- The Anthropic chatbot strips spurious `<function_calls>` XML blocks from text responses using regex, as the model sometimes emits XML tool-call syntax alongside the native `tool_use` API.
- The alert receiver runs as a separate CronJob and uses `LlamaStackClient` directly (not the MCP tool-calling chatbot), connecting to a local Llama Stack instance for alert description generation. If the LLM fails, it falls back to a generic hardcoded description.

## Related Architectures

- [mcp-tool-integration](mcp-tool-integration.md) -- Approach G describes the MCP server architecture that exposes the tools consumed by this observability summarization pipeline
- [llm-observability-pipeline](llm-observability-pipeline.md) -- Covers the OpenTelemetry/Tempo instrumentation side of observability (what generates the traces that this architecture queries)
- [model-serving-gateway](model-serving-gateway.md) -- The vLLM model serving infrastructure that this architecture monitors and summarizes
