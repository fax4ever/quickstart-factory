---
name: prompt-chaining
description: Multi-step LLM prompt pipelines using LangGraph StateGraph for NL-to-SQL alert evaluation with conditional routing
summary: "Implements deterministic multi-step LLM prompt pipelines via LangGraph StateGraph DAGs for converting natural language alert rules into validated PostgreSQL SQL, using three graph instances — a 7-node validation chain (classify, parse SQL, execute, validate, similarity-check, describe, status), a trigger graph with conditional saved-SQL reuse via should_use_saved_sql routing, and a simplified parse graph. Use when sequential LLM calls need deterministic DAG orchestration with interspersed non-LLM validation steps rather than agent-orchestration tool-calling loops; supports OpenAI-compatible/LlamaStack/VertexAI via factory pattern, six YAML-stored prompts loaded through prompt_loader with Jinja2 templating, and structured state passing between RunnableLambda-wrapped nodes instead of direct prompt output chaining. Critical patterns: alert_parser.yaml uses 23 hard rules plus schema/user-context injection via Jinja2 to constrain PostgreSQL CTE-based SQL generation; extract_sql() sanitizes LLM output by stripping <think> blocks, extracting from markdown code fences, and wrapping bare subqueries in CTEs; SQL correctness validated post-hoc via execution rather than structural prevention. Gotchas: dual SQLAlchemy engines (sync psycopg2 for LangGraph, async asyncpg for FastAPI) create concurrent DB connections during evaluation; substitute_timestamp replaces only the first TIMESTAMP literal (count=1) breaking multi-timestamp window queries; background alert processing spawns new threads with separate async event loops and connection pools per transaction."
metadata:
  type: architecture
tags:
  tech_stack: [fastapi, langchain, langgraph, python, postgresql, jinja2]
  ai_pattern: [prompt-chaining, agents]
  platform: [openshift, vllm, llamastack]
  data_layer: [postgresql, pgvector]
source_examples:
  - quickstart: "spending-transaction-monitor"
    repo: "https://github.com/rh-ai-quickstart/spending-transaction-monitor"
    notes: "Three LangGraph StateGraph DAGs chaining LLM calls for NL-to-SQL alert rule parsing, validation with similarity checking, and alert message generation with conditional routing for saved SQL reuse"
    approach: "A"
---

# Prompt Chaining

## Overview

This architecture implements multi-step LLM prompt pipelines where a sequence of LLM calls, each with a distinct prompt template, are chained together via LangGraph StateGraph to accomplish a complex task. Unlike agent orchestration (which uses tool-calling loops and planning), prompt chaining defines a deterministic DAG of LLM invocations interspersed with non-LLM validation steps. Each node in the graph transforms state, and the full chain converts a user's natural language input into a structured, validated output.

## Data Flow

1. User submits a natural language alert rule (e.g., "Alert me if I spend more than $100 in a single transaction") via the React frontend
2. FastAPI backend invokes the appropriate LangGraph StateGraph (validate, trigger, or parse)
3. `create_alert_rule` node: LLM classifies the alert text into type (spending/location/merchant/pattern) and extracts metadata (thresholds, merchant names, timeframes) as structured JSON
4. `parse_alert` node: LLM generates a PostgreSQL SQL query from the natural language rule using a detailed Jinja2 prompt template that includes database schema, transaction context, and user location data
5. `execute_sql` node: Generated SQL is executed against PostgreSQL via SQLAlchemy to verify correctness
6. `validate_sql` node: Deterministic check verifies SQL executed without errors and rule is applicable
7. `check_similarity` node: LLM compares the new rule against existing rules to detect duplicates
8. `generate_description` node: LLM produces a plain English description of what the generated SQL query does
9. `generate_alert_message` node: LLM generates a user-facing notification subject and message body when an alert triggers
10. Final state returned to the API route, which persists the alert rule and sends notifications via SMTP/SMS

## Component Wiring

| From | To | Protocol | Purpose |
|------|----|----------|---------|
| React frontend | FastAPI backend | REST | Submit NL alert rule, receive validation/trigger results |
| FastAPI backend | LangGraph StateGraph | Python method call (`graph.invoke()`) | Orchestrate multi-step LLM pipeline |
| LangGraph nodes | LLM provider | HTTP (OpenAI-compatible / LlamaStack SDK) | Each node calls LLM with distinct prompt |
| `execute_sql` node | PostgreSQL | SQLAlchemy (psycopg2 sync) | Execute generated SQL to validate or trigger alert |
| AlertRuleService | NotificationService | Python method call | Send email/SMS when alert triggers |
| NotificationService | SMTP server | SMTP | Email alert notifications |
| NotificationService | Twilio | REST | SMS alert notifications |
| BackgroundAlertService | AlertRuleService | Python method call (background thread) | Process alert rules asynchronously per transaction |

## Key Integration Points

### LangGraph StateGraph Definition

Three separate StateGraph instances handle different flows: validation (full 7-node chain), triggering (conditional routing for saved SQL reuse), and parsing (simplified SQL generation). Each graph shares the same node implementations but wires them differently.

```python
# packages/api/src/services/alerts/generate_alert_graph.py (lines 24-26, 59-62, 80-81, 137-158)
graph = StateGraph(AppState)

graph.add_node(
    'route_sql_generation',
    RunnableLambda(lambda state: state),  # Pass-through node for routing
)

# Conditional routing: saved SQL vs new generation
graph.add_conditional_edges(
    'route_sql_generation',
    should_use_saved_sql,
    {'substitute_timestamp': 'substitute_timestamp', 'parse_alert': 'parse_alert'},
)

# Both parse_alert and substitute_timestamp lead to execute_sql
graph.add_edge('parse_alert', 'execute_sql')
graph.add_edge('substitute_timestamp', 'execute_sql')
graph.add_edge('execute_sql', 'create_alert')
graph.add_edge('create_alert', 'generate_alert_message')

app = graph.compile()
```

### Conditional SQL Routing

When an alert rule has been previously validated, its generated SQL is saved. On subsequent triggers, only the timestamp is substituted instead of re-generating SQL from scratch. This optimization avoids redundant LLM calls.

```python
# packages/api/src/services/alerts/generate_alert_graph.py (lines 42-55)
def should_use_saved_sql(state):
    """
    Conditional routing: decides whether to use saved SQL or generate new SQL.
    Returns 'substitute_timestamp' if SQL exists, 'parse_alert' otherwise.
    """
    alert_rule = state.get('alert_rule', {})
    saved_sql = alert_rule.get('sql_query')

    if saved_sql and saved_sql.strip():
        print('Using saved SQL query - substituting timestamp only')
        return 'substitute_timestamp'
    else:
        print('No saved SQL - generating new query')
        return 'parse_alert'
```

### YAML-Based Prompt Management with Jinja2

All LLM prompts are stored in YAML files with metadata and loaded via a `prompt_loader` utility. The loader supports both simple Python `.format()` and Jinja2 templating for complex prompts with conditionals.

```python
# packages/api/src/services/agents/prompts/prompt_loader.py (lines 64-95)
def load_prompt(prompt_file: str, prompt_name: str, **variables: Any) -> str:
    data = _load_yaml_file(f'{prompt_file}.yaml')
    metadata = data.get('metadata', {})
    template_type = metadata.get('template_type', 'simple')

    template_str = get_prompt_template(prompt_file, prompt_name)

    if template_type == 'jinja2':
        env = _get_jinja_env()
        template = env.from_string(template_str)
        return template.render(**variables)
    else:
        return template_str.format(**variables)
```

### Multi-Provider LLM Client Factory

The system supports three LLM providers (OpenAI-compatible, LlamaStack, VertexAI) via a factory function. All three implement the same `invoke(prompt)` interface, making provider swaps transparent to the prompt chain.

```python
# packages/api/src/services/agents/utils.py (lines 51-58)
def get_llm_client():
    provider = os.getenv('LLM_PROVIDER', 'openai')
    if provider == 'vertexai':
        return VertexAIClient()
    elif provider == 'llamastack':
        return LlamastackClient()
    else:
        return LLMClient()
```

### NL-to-SQL Generation Prompt

The core prompt is a detailed Jinja2 template that includes 23 hard rules for PostgreSQL SQL generation, database schema injection, user location context, and transaction data. The prompt ensures the LLM generates correct CTE-based SQL with proper aggregation, timestamp handling, and geospatial distance calculation.

```yaml
# packages/api/src/services/agents/prompts/alert_parser.yaml (lines 1-10, partial)
metadata:
  version: "1.0"
  description: "SQL generation prompt for parsing natural language alerts"
  template_type: jinja2

prompts:
  build_sql:
    description: "Generate PostgreSQL query to evaluate an alert rule"
    template: |
      You are a SQL assistant.
      You must generate **PostgreSQL-compatible SQL** only.
      {% if user_context %}
      {{ user_context }}
      {% endif %}
      ...
      Schema:
      {{ schema }}
      Natural language alert: "{{ alert_text }}"
      Generate a valid SQL query that evaluates the alert.
```

### SQL Output Sanitization

LLM-generated SQL output is cleaned by stripping `<think>` reasoning blocks, extracting SQL from markdown code fences, and wrapping bare subqueries in CTEs.

```python
# packages/api/src/services/agents/utils.py (lines 16-34)
def extract_sql(sql: str) -> str:
    """Clean and normalize LLM SQL output."""
    if '</think>' in sql:
        sql = sql.split('</think>')[-1]

    code_block = re.search(r'```sql(.*?)```', sql, re.DOTALL | re.IGNORECASE)
    if code_block:
        sql = code_block.group(1)

    sql = sql.strip()
    if 'FROM (' in sql.upper() and not sql.strip().upper().startswith('WITH'):
        sql = f'WITH subquery AS ({sql}) SELECT * FROM subquery'

    return sql.strip()
```

### Validation Graph with Similarity Checking

The full validation pipeline chains seven nodes sequentially: create rule, parse to SQL, execute SQL, validate results, check similarity against existing rules, generate SQL description, and determine final validation status.

```python
# packages/api/src/services/alerts/validate_rule_graph.py (lines 155-173)
graph.add_node('create_alert_rule', RunnableLambda(create_alert_rule_node))
graph.add_node('parse_alert', RunnableLambda(parse_alert_node))
graph.add_node('execute_sql', RunnableLambda(execute_sql_node))
graph.add_node('validate_sql', RunnableLambda(validate_sql_node))
graph.add_node('check_similarity', RunnableLambda(check_similarity_node))
graph.add_node('generate_description', RunnableLambda(generate_description_node))
graph.add_node('determine_status', RunnableLambda(determine_validation_status))

graph.set_entry_point('create_alert_rule')
graph.add_edge('create_alert_rule', 'parse_alert')
graph.add_edge('parse_alert', 'execute_sql')
graph.add_edge('execute_sql', 'validate_sql')
graph.add_edge('validate_sql', 'check_similarity')
graph.add_edge('check_similarity', 'generate_description')
graph.add_edge('generate_description', 'determine_status')

app = graph.compile()
```

## Prompt / Chain Patterns

The system uses six distinct LLM prompts, each stored in a YAML file under `packages/api/src/services/agents/prompts/`:

| Prompt File | Purpose | Output Format |
|-------------|---------|---------------|
| `create_alert_rule.yaml` | Classify NL alert into type and extract metadata | JSON with alert_type, thresholds, merchant info |
| `alert_parser.yaml` | Generate PostgreSQL SQL from NL rule + schema + context | Raw SQL query string |
| `generate_alert_message.yaml` | Create user-facing notification subject and body | `SUBJECT:` / `MESSAGE:` text block |
| `alert_recommender.yaml` | Generate personalized alert recommendations | JSON array of recommendations |
| `rule_similarity_checker.yaml` | Compare new rule against existing rules for duplicates | JSON with is_similar, similarity_score |
| `sql_description_generator.yaml` | Explain generated SQL in plain English | Plain text description |

Each prompt is invoked independently (no prompt output feeds directly as input to the next prompt). Instead, the LangGraph state carries structured data between nodes -- the SQL string, validation result, and alert rule metadata flow through the graph as state fields.

## Gotchas

- The `execute_sql` node creates a separate synchronous SQLAlchemy engine (`psycopg2` driver) because LangGraph runs synchronously while the FastAPI app uses asyncpg. This means two database connections exist concurrently during alert evaluation -- see `packages/api/src/services/agents/sql_executor.py` lines 10-14.
- LLM-generated SQL can contain `<think>` reasoning blocks (from models like DeepSeek that use chain-of-thought). The `extract_sql()` utility in `packages/api/src/services/agents/utils.py` strips these, but if the model format changes, SQL extraction may silently fail.
- The `substitute_timestamp` optimization replaces only the first `TIMESTAMP '...'` occurrence in saved SQL (`count=1` in `re.sub`). If the generated SQL contains multiple timestamp literals (e.g., time window queries with `BETWEEN`), only the first gets updated, potentially causing stale date comparisons -- see `packages/api/src/services/agents/timestamp_substitutor.py` line 36.
- Background alert processing spawns a new thread with its own async event loop and database engine to avoid conflicts with FastAPI's main event loop -- see `packages/api/src/services/alerts/background_alert_service.py` lines 285-318. This means each transaction creates a new database connection pool per background thread.
- The LLM prompt for SQL generation includes 23 hard rules in `alert_parser.yaml` to constrain output format. Despite this, the prompt relies on the LLM correctly following CTE structure, `CASE`/`ELSE` patterns, and `COALESCE` wrapping. SQL validation via execution catches errors post-hoc rather than preventing them.

## Related Architectures

- [agent-orchestration](agent-orchestration.md) -- Uses LangGraph for agent loops with tool calling; prompt chaining uses LangGraph for deterministic DAGs without agent planning
- [recommendation-pipeline](recommendation-pipeline.md) -- The same quickstart's ML recommendation pipeline uses a separate Kubeflow Pipeline for training a KNN model that supplements the LLM-based alert recommendations
