---
name: tavily-web-search
description: "NAT plugin providing Tavily web search as an async tool with graceful API key degradation"
summary: "NAT plugin (Python >=3.11, httpx/langchain-tavily/pydantic) wrapping the Tavily web search API as an async tool for agentic research workflows, self-registering via nat.plugins entry point with @register_function and FunctionBaseConfig(name=\"tavily_web_search\") Pydantic config from an installable package under sources/tavily_web_search/. Use the dual config pattern to instantiate basic (max_results: 5, max_content_length: 1000) and advanced (advanced_search: true, max_results: 2) search modes from the same _type in workflow YAML, grouped under data_source_registry for UI toggling; when TAVILY_API_KEY is unset, a FunctionInfo.from_fn stub registers gracefully with deduplicated warnings via a module-level _missing_key_warned flag instead of crashing. Critical implementation: queries are truncated at 400 chars (Tavily API limit), retries use asyncio.sleep(2**attempt) exponential backoff (max_retries: 3), and optional max_content_length truncates individual result content for token control; no dedicated tests exist -- verify via CLI mode and unset-key degradation check. Gotchas: api_key SecretStr is written to os.environ process-wide for langchain-tavily compatibility; include_answer defaults to \"advanced\" (string, not boolean) adding latency and cost per call; response parsing defensively handles string, non-dict, error-keyed, and missing-results shapes from the API."
metadata:
  type: component
tags:
  tech_stack: [python, langchain-tavily, pydantic, httpx]
  ai_pattern: [agents, web-search]
  platform: [nat, nvidia-aiq]
source_examples:
  - quickstart: "rh-research"
    repo: "https://github.com/rh-ai-quickstart/rh-research"
    notes: "Tavily web search tool registered as NAT plugin with dual config (basic + advanced search)"
    approach: "A"
---

# Tavily Web Search

## Overview

A NeMo Agent Toolkit (NAT) plugin that wraps the Tavily web search API as an async tool for agentic research workflows. It is used in the NVIDIA AI-Q Blueprint (rh-research) to give shallow and deep research agents real-time web search capabilities. The component ships as a standalone installable Python package under `sources/tavily_web_search/` and self-registers via the `nat.plugins` entry point.

## Tech Stack & Dependencies

- **Runtime:** Python >=3.11,<3.14
- **Container image:** N/A (installed as a pip package inside the main application image)
- **Key dependencies:** `httpx>=0.24.0`, `pydantic>=2.0.0`, `langchain-tavily>=0.1.0`
- **Helm subchart:** N/A (deployed as part of the parent application)

## Key Patterns

### NAT Plugin Registration via Entry Point

The package registers itself as a NAT plugin through `pyproject.toml` entry points, allowing automatic discovery by the NAT runtime without explicit imports in the main application:

```toml
# sources/tavily_web_search/pyproject.toml
[project.entry-points."nat.plugins"]
tavily_web_search = "tavily_web_search.register"
```

The registration function uses the `@register_function` decorator with a Pydantic config class:

```python
# sources/tavily_web_search/src/register.py
class TavilyWebSearchToolConfig(FunctionBaseConfig, name="tavily_web_search"):
    include_answer: str = Field(default="advanced", ...)
    max_results: int = Field(default=3, ...)
    api_key: SecretStr | None = Field(default=None, ...)
    max_retries: int = Field(default=3, ...)
    advanced_search: bool = Field(default=False, ...)
    max_content_length: int | None = Field(default=None, ...)
    api_base_url: str | None = Field(default=None, ...)

@register_function(config_type=TavilyWebSearchToolConfig)
async def tavily_web_search(tool_config: TavilyWebSearchToolConfig, builder: Builder):
```

The `name="tavily_web_search"` on `FunctionBaseConfig` is the `_type` value used in workflow YAML configs.

### Graceful Degradation When API Key Is Missing

The tool registers a stub function that returns a descriptive error message instead of crashing when `TAVILY_API_KEY` is not set. A module-level `_missing_key_warned` flag prevents duplicate log warnings:

```python
# sources/tavily_web_search/src/register.py
if not os.environ.get("TAVILY_API_KEY"):
    global _missing_key_warned
    if not _missing_key_warned:
        logger.warning(
            "TAVILY_API_KEY not found. The web search tool will be registered but will "
            "return an error when called."
        )
        _missing_key_warned = True

    async def _tavily_web_search_stub(question: str) -> str:
        """Web search tool (unavailable - missing TAVILY_API_KEY)."""
        return "Error: Web search is unavailable because TAVILY_API_KEY is not set...."

    yield FunctionInfo.from_fn(_tavily_web_search_stub, ...)
    return
```

### Dual Config Pattern (Basic vs Advanced Search)

Workflow YAML configs instantiate the same `_type` twice under different function names to provide both basic and advanced search modes:

```yaml
# configs/config_cli_default.yml
functions:
  web_search_tool:
    _type: tavily_web_search
    max_results: 5
    max_content_length: 1000

  advanced_web_search_tool:
    _type: tavily_web_search
    max_results: 2
    advanced_search: true
```

Both tools are registered in the data source registry under a single `web_search` source so the UI can toggle them together:

```yaml
# configs/config_cli_default.yml
data_sources:
  _type: data_source_registry
  sources:
    - id: web_search
      name: "Web Search"
      tools:
        - web_search_tool
        - advanced_web_search_tool
```

### Query Truncation and Retry Logic

The search function truncates queries exceeding 400 characters (a Tavily API constraint) and implements exponential backoff retries:

```python
# sources/tavily_web_search/src/register.py
if len(question) > 400:
    question = question[:397] + "..."

for attempt in range(tool_config.max_retries):
    try:
        search_docs = await tavily_search.ainvoke({"query": question})
        # ... process results
    except Exception as e:
        if attempt == tool_config.max_retries - 1:
            # Return user-friendly error on final attempt
            ...
        await asyncio.sleep(2**attempt)
```

### Content Truncation for Token Management

An optional `max_content_length` config truncates individual search result content to control token usage when feeding results to an LLM:

```python
# sources/tavily_web_search/src/register.py
def _truncate_content(content: str) -> str:
    if tool_config.max_content_length and len(content) > tool_config.max_content_length:
        return content[: tool_config.max_content_length - 3] + "..."
    return content
```

## Configuration

- **Environment variables:**
  - `TAVILY_API_KEY` (required) -- API key for Tavily service; set in environment, `.env` file, or via `api_key` config field
- **Config files:** Workflow YAML under `configs/` (e.g., `config_cli_default.yml`) -- defines tool instances under `functions:` with `_type: tavily_web_search`
- **Helm values:** N/A (configured via workflow YAML and environment variables, not Helm)

## Known Gotchas

- The Tavily API enforces a 400-character query limit; the tool silently truncates longer queries to 397 characters plus "..." rather than raising an error (see `register.py` line 98-99).
- The `api_key` config field uses `SecretStr` for security, but the tool sets it into `os.environ["TAVILY_API_KEY"]` at registration time, making it available process-wide. This is intentional for `langchain-tavily` compatibility but means the key persists in the environment (see `register.py` line 56-57).
- The `include_answer` config defaults to `"advanced"` (a string, not a boolean) which triggers Tavily's AI-generated answer feature; this adds latency and token cost to each search call.
- Response parsing handles multiple error shapes: string responses, non-dict responses, dict with `"error"` key, and missing `"results"` key. This defensive handling reflects real-world API edge cases encountered (see `register.py` lines 121-136).

## Testing Notes

- No dedicated test files exist for this component in the repo's `tests/` directory.
- Verify by running the CLI mode: `./scripts/start_cli.sh` and issuing a question that triggers web search.
- Check graceful degradation by unsetting `TAVILY_API_KEY` and confirming the tool registers without crashing and returns a descriptive error when invoked.

## Related Patterns

- Other NAT source plugins follow the same pattern: `sources/duckduckgo_news_search/`, `sources/exa_web_search/`, `sources/google_scholar_paper_search/`
- Data source registry (`data_source_registry`) groups tools for UI toggles and agent inheritance
