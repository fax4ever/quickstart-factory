---
name: duckduckgo-news-search
description: "NAT plugin providing DuckDuckGo news search as an async tool with retry, timeout, and HTML-escaped output"
summary: "NAT plugin (Python >=3.11) wrapping the `ddgs` package to provide DuckDuckGo news search as an async tool for the deep-research agent, registered via setuptools entry points (`nat.plugins`) with a Pydantic `FunctionBaseConfig` subclass defining max_results (1-25), region, safesearch, timelimit (d/w/m/y), and timeout; gracefully degrades to a stub function if `ddgs` is not installed. Use when adding no-API-key news/current-events search to a NAT agent workflow -- searches Bing, DuckDuckGo, and Yahoo simultaneously via `NEWS_BACKENDS` constant; sibling plugins (`tavily_web_search`, `exa_web_search`, `google_scholar_paper_search`) follow the same registration pattern for web and academic sources. Register via setuptools entry point, define config with `name=\"duckduckgo_news_search\"`, configure in workflow YAML as `_type: duckduckgo_news_search` mapped to a data source domain; uses `asyncio.to_thread` + `asyncio.wait_for` with exponential backoff retries (`2**attempt` seconds) and formats results as HTML-escaped XML `<Document>` blocks with `_result_value` helper resolving inconsistent backend keys (`url`/`href`/`link`). `DDGSException(\"No results found.\")` must be caught and converted to empty results rather than propagated, queries over 400 chars are silently truncated to 397+`\"...\"`, the broad `Exception` catch in the retry loop is intentional due to unpredictable DDGS transport exceptions, and deferred `ddgs` import means a missing package yields a stub error message rather than a crash."
metadata:
  type: component
tags:
  tech_stack: [python, pydantic, ddgs, nat]
  ai_pattern: [agents, data-pipeline]
  platform: []
  data_layer: []
source_examples:
  - quickstart: "rh-research"
    repo: "https://github.com/rh-ai-quickstart/rh-research"
    notes: "DuckDuckGo news search registered as a NAT function for the deep-research agent's news_search domain"
    approach: "A"
---

# DuckDuckGo News Search

## Overview

A NAT (NeMo Agent Toolkit) plugin that wraps the `ddgs` Python package to provide DuckDuckGo news search as an async tool for AI agents. It is registered via setuptools entry points and used by the deep-research agent as the primary tool for the `news_search` data-source domain. Results are formatted as XML-style `<Document>` blocks with HTML-escaped fields to prevent injection.

## Tech Stack & Dependencies
- **Runtime:** Python >=3.11,<3.14
- **Container image:** Part of the main AI-Q agent image (not a standalone service)
- **Key dependencies:** `ddgs>=9.14.4,<10`, `pydantic>=2.0.0`, NAT framework (`nat.builder`, `nat.cli`, `nat.data_models`)
- **Helm subchart:** None (bundled as a Python package within the agent)

## Key Patterns

### NAT Plugin Registration via Entry Points

The package registers itself as a NAT plugin through a setuptools entry point, allowing automatic discovery by the NAT runtime without hardcoded imports.

```toml
# pyproject.toml
[project.entry-points."nat.plugins"]
duckduckgo_news_search = "duckduckgo_news_search.register"
```

The tool function is decorated with `@register_function` linking it to a Pydantic config class that defines the `_type` name used in workflow YAML:

```python
class DuckDuckGoNewsSearchToolConfig(FunctionBaseConfig, name="duckduckgo_news_search"):
    """DuckDuckGo news search using the `ddgs` package."""
    max_results: int = Field(default=5, ge=1, le=25)
    region: str = Field(default="us-en")
    safesearch: Literal["on", "moderate", "off"] = Field(default="moderate")
    timelimit: Literal["d", "w", "m", "y"] | None = Field(default="w")
    timeout: float = Field(default=20.0, gt=0)
    max_retries: int = Field(default=2, ge=1)
```

### Async Wrapper with Retry and Timeout

The synchronous `ddgs.news()` call is wrapped with `asyncio.to_thread` and `asyncio.wait_for` to avoid blocking the event loop. Retries use exponential backoff (`2**attempt` seconds between retries):

```python
for attempt in range(tool_config.max_retries):
    try:
        results = await asyncio.wait_for(
            asyncio.to_thread(_search), timeout=tool_config.timeout
        )
        if results:
            return "\n\n---\n\n".join(
                _format_news_result(result) for result in results
            )
        return "News search returned no results"
    except Exception as exc:
        if attempt == tool_config.max_retries - 1:
            return "Error: News search failed"
        await asyncio.sleep(2**attempt)
```

### Graceful Degradation When ddgs Is Not Installed

The `ddgs` import is deferred to runtime inside the registered function. If the package is missing, a stub function is yielded instead, returning an error message rather than crashing:

```python
try:
    from ddgs import DDGS
    from ddgs.exceptions import DDGSException
except ImportError:
    async def _duckduckgo_news_search_stub(query: str) -> str:
        """News search tool unavailable because the `ddgs` package is not installed."""
        return "Error: DuckDuckGo news search is unavailable..."
    yield FunctionInfo.from_fn(_duckduckgo_news_search_stub, ...)
    return
```

### HTML-Escaped Document Block Output

Results are formatted as XML-style `<Document>` blocks with all user-supplied fields HTML-escaped to prevent injection. The `_result_value` helper handles inconsistent key names across DDGS backends (e.g., `url`/`href`/`link`, `body`/`snippet`/`description`):

```python
def _format_news_result(result: dict) -> str:
    url = html_escape(_result_value(result, "url", "href", "link"), quote=True)
    title = html_escape(_result_value(result, "title"), quote=True)
    body = html_escape(_result_value(result, "body", "snippet", "description"), quote=True)
    # ...
    return f'<Document href="{url}">\n<title>\n{title}\n</title>{metadata}\n{body}\n</Document>'
```

### Multi-Backend News Search

The tool sends searches to multiple backends simultaneously via the `NEWS_BACKENDS` constant:

```python
NEWS_BACKENDS = "bing,duckduckgo,yahoo"
```

This is passed as `backend=NEWS_BACKENDS` to `ddgs.news()`, aggregating results from Bing, DuckDuckGo, and Yahoo news feeds in a single call.

## Configuration
- **Environment variables:** None (no API key required; DuckDuckGo search is free)
- **Config files:** Workflow YAML defines the tool instance via `_type: duckduckgo_news_search` with overridable fields (`max_results`, `timelimit`, etc.)
- **Helm values:** None (Python package, not a standalone deployment)

Example workflow YAML configuration:

```yaml
duckduckgo_news_search_tool:
  _type: duckduckgo_news_search
  max_results: 5
  timelimit: w
```

The tool is mapped to the `news_search` data source domain in the domain routing config:

```yaml
- id: news_search
  name: "News Search"
  description: "Search recent news articles and current events."
  tools:
    - duckduckgo_news_search_tool
```

## Known Gotchas
- **DDGSException for "No results found"**: The `ddgs` library raises a `DDGSException` with the text `"No results found."` instead of returning an empty list. The code explicitly catches this case and converts it to an empty result set rather than propagating the error.
- **Query length limit**: Queries longer than 400 characters are silently truncated to 397 characters plus `"..."` to avoid backend errors.
- **Inconsistent result keys across backends**: Different DDGS backends return results with varying key names (e.g., `url` vs `href` vs `link`). The `_result_value` helper tries multiple key names in priority order to handle this.
- **Broad exception catch on retries**: The retry loop catches all exceptions (`Exception`), not just timeout or network errors, because DDGS source APIs can raise transport-specific exceptions that are not part of the public API.

## Testing Notes
- Tests use a `_FakeDDGS` mock class and `monkeypatch` to replace the `ddgs` module at the `sys.modules` level, allowing full control over search results and exceptions without network calls.
- The test suite verifies HTML escaping of special characters (script tags, ampersands, quotes) in results to confirm injection prevention.
- `asyncio.sleep` is monkeypatched in timeout/retry tests to avoid real delays.
- The citation verification tests confirm that status messages like `"News search returned no results"` and `"Error: News search failed"` are not treated as citable evidence by the citation system.

## Related Patterns
- Domain routing configuration that maps tools to research domains
- Sibling source packages (`tavily_web_search`, `exa_web_search`, `google_scholar_paper_search`) follow the same NAT plugin registration pattern
