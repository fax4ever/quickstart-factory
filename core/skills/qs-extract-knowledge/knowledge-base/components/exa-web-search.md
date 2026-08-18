---
name: exa-web-search
description: "NAT plugin providing Exa-powered web search with graceful API key degradation and token-efficient result modes"
summary: "NAT plugin wrapping the Exa API (langchain-exa) to give research agents web search with auto/fast/deep modes and token-efficient retrieval — highlights (default snippets) or full_text truncated to max_content_length (default 10,000 chars), rendered as XML-like Document blocks. Choose over Tavily (alternative NAT search plugin) or DuckDuckGo news search when Exa neural search or deep search mode is needed; configure via workflow YAML functions section with _type: exa_web_search and fields max_results, search_type, full_text, highlights, max_content_length. Registers via pyproject.toml entry point inheriting FunctionBaseConfig with graceful missing-key degradation — registers a stub (single warning via _missing_key_warned flag) instead of crashing; api_key uses SecretStr and is written to os.environ at registration; queries truncated at 400 chars with exponential backoff retry (2^attempt seconds). Config-provided api_key overwrites any existing EXA_API_KEY env var for the process lifetime, full_text: false passes False to Exa rather than omitting the parameter, the stub still appears in agents' tool lists causing attempted calls that return errors, and 400-char query truncation silently drops context from complex research questions."
metadata:
  type: component
tags:
  tech_stack: [python, langchain, pydantic]
  ai_pattern: [agents, rag]
  platform: []
  data_layer: []
source_examples:
  - quickstart: "rh-research"
    repo: "https://github.com/rh-ai-quickstart/rh-research"
    notes: "Exa web search as a NAT plugin tool for research agents with configurable search depth and content modes"
    approach: "A"
---

# Exa Web Search

## Overview

Exa web search is a NeMo Agent Toolkit (NAT) plugin that wraps the Exa API (`langchain-exa`) as a tool callable by research agents. It provides web search with configurable search depth (auto/fast/deep) and token-efficient result modes (highlights vs full text). The component follows the NAT function registration pattern with graceful degradation when the API key is missing.

## Tech Stack & Dependencies

- **Runtime:** Python >=3.11,<3.14
- **Container image:** Installed into the main application container via `uv pip install --no-deps -e ./sources/exa_web_search` in `deploy/Dockerfile`
- **Key dependencies:** `pydantic>=2.0.0`, `langchain-exa>=1.1.0`
- **Helm subchart:** None (bundled into the main application image)

## Key Patterns

### NAT Plugin Registration via Entry Point

The component registers itself as a NAT plugin using a `pyproject.toml` entry point, which NAT discovers automatically at startup. The config class inherits from `FunctionBaseConfig` with `name="exa_web_search"` so workflow YAML can reference it via `_type: exa_web_search`.

```toml
# sources/exa_web_search/pyproject.toml
[project.entry-points."nat.plugins"]
exa_web_search = "exa_web_search.register"
```

```python
# sources/exa_web_search/src/register.py
class ExaWebSearchToolConfig(FunctionBaseConfig, name="exa_web_search"):
    max_results: int = Field(default=5)
    api_key: SecretStr | None = Field(default=None)
    search_type: Literal["auto", "deep", "fast"] = Field(default="auto")
    full_text: bool = Field(default=False)
    highlights: bool = Field(default=True)
    max_content_length: int | None = Field(default=10000)
```

### Graceful Missing-Key Degradation

When `EXA_API_KEY` is not set and no `api_key` is provided in config, the tool registers a stub function that returns an informative error instead of crashing at import or registration time. A module-level flag (`_missing_key_warned`) ensures the warning is logged only once.

```python
# sources/exa_web_search/src/register.py
if not os.environ.get("EXA_API_KEY"):
    global _missing_key_warned
    if not _missing_key_warned:
        logger.warning(
            "EXA_API_KEY not found. The web search tool will be registered but will "
            "return an error when called."
        )
        _missing_key_warned = True

    async def _exa_web_search_stub(question: str) -> str:
        return (
            "Error: Exa web search is unavailable because EXA_API_KEY is not set.\n"
            "To enable this tool:\n"
            "1. Get an API key from https://exa.ai/\n"
            "2. Set the API key in your environment or in your .env file\n"
            "3. Restart the application"
        )
```

### Token-Efficient Result Modes

The tool supports two content retrieval strategies controlled by `full_text` and `highlights` config flags. By default, only highlights (short snippets) are returned to minimize token usage. When `full_text` is enabled, full page text is returned but truncated to `max_content_length` (default 10,000 characters).

```python
# sources/exa_web_search/src/register.py
def _truncate_content(content: str) -> str:
    if tool_config.max_content_length and len(content) > tool_config.max_content_length:
        return content[: tool_config.max_content_length - 3] + "..."
    return content
```

Results are rendered as XML-like `<Document>` blocks separated by `---`, with highlights falling back when text is absent:

```python
# sources/exa_web_search/src/register.py
def _render(doc) -> str:
    url = getattr(doc, "url", "") or ""
    title = getattr(doc, "title", "") or ""
    text = _truncate_content(getattr(doc, "text", "") or "")
    highlights_list = getattr(doc, "highlights", None) or []
    body = text if text else "\n".join(highlights_list)
    return f'<Document href="{url}">\n<title>\n{title}\n</title>\n{body}\n</Document>'
```

### Query Truncation and Retry with Exponential Backoff

Long queries are truncated to 400 characters before sending to the Exa API. Failed requests are retried with exponential backoff (`2**attempt` seconds), and specific HTTP error codes (401) produce user-friendly messages.

```python
# sources/exa_web_search/src/register.py
if len(question) > 400:
    question = question[:397] + "..."

for attempt in range(tool_config.max_retries):
    try:
        response = await exa_search.ainvoke({...})
        # ...
    except Exception as e:
        if attempt == tool_config.max_retries - 1:
            # Return friendly error messages for 401, ValueError, etc.
            ...
        await asyncio.sleep(2**attempt)
```

## Configuration

- **Environment variables:**
  - `EXA_API_KEY` -- Exa API key (can also be set via `api_key` in workflow YAML config; the config value is written to the environment at registration time using `SecretStr`)
- **Config files:** Workflow YAML under `configs/` -- the tool is wired in the `functions` section with `_type: exa_web_search`
- **Workflow YAML example** (from `docs/source/customization/configuration-reference.md`):

```yaml
functions:
  web_search_tool:
    _type: exa_web_search
    max_results: 5
    full_text: true
    max_content_length: 10000

  deep_web_search_tool:
    _type: exa_web_search
    max_results: 5
    search_type: deep
```

## Known Gotchas

- **API key from config overwrites environment:** When `api_key` is set in the tool config, it is written to `os.environ["EXA_API_KEY"]` at registration time. This means a config-provided key will override any previously set environment variable for the lifetime of the process (see `register.py` lines 95-96).
- **`full_text: false` still passes `text_contents_options: False` to Exa:** The `full_text` boolean is passed directly as `text_contents_options` to `ExaSearchResults.ainvoke`, so Exa receives `False` rather than the key being omitted (see `register.py` line 150).
- **Query truncation uses hard 400-char limit:** Queries longer than 400 characters are silently truncated with `"..."` appended, which could cut off important context in complex research questions (see `register.py` lines 135-136).
- **Stub still registers as a tool:** When the API key is missing, the tool is still registered (with a stub), meaning agents will see it in their tool list and may attempt to call it, receiving an error message rather than not seeing the tool at all.

## Testing Notes

- Tests use a fake `langchain_exa` module injected via `monkeypatch` to avoid network calls (see `tests/test_register.py`)
- The test suite validates: default config values, config override, stub behavior without API key, document formatting, query truncation, content truncation, empty results handling, retry behavior, and 401 error messages
- Run tests from the repo root: `uv run pytest sources/exa_web_search/`

## Related Patterns

- Tavily web search (`sources/tavily_web_search/`) follows the same NAT plugin pattern and is the alternative web search provider
- DuckDuckGo news search (`sources/duckduckgo_news_search/`) is another NAT search tool plugin
- The `aiq-add-tool` maintainer skill (`.agents/skills/aiq-add-tool/`) documents the canonical pattern for adding new tools, using `exa_web_search` as one of the reference implementations
