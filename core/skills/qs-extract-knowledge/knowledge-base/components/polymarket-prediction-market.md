---
name: polymarket-prediction-market
description: "NAT plugin that searches Polymarket events and markets via the public Gamma API, returning citable document blocks"
summary: "Provides a NAT plugin that searches Polymarket prediction markets and events via the public Gamma API (no authentication), returning XML-style citable <Document> blocks with outcome probabilities, volume, liquidity, and end dates for domain-routed research agents. Use as one of several domain-routed search tools (alongside tavily_web_search, duckduckgo_news_search, google_scholar_paper_search) when a research agent needs market-implied probability data; registers via Python entry points and @register_function with Pydantic FunctionBaseConfig validation, gracefully degrading to a FunctionInfo.from_fn stub if httpx is missing. Configure in workflow YAML as _type: polymarket_search under a prediction_market domain; dual parallel asyncio.gather calls fetch high-volume active events (scored client-side via lexical matching, controlled by event_scan_limit default 100, max 500) and keyword-searched standalone markets, deduplicating and ranking up to max_results (default 5, max 20). Gamma API returns JSON-encoded strings for list fields like outcomes/outcomePrices (handled by _as_list() with json.loads); queries are truncated to 300 chars; asyncio.wait_for wraps the combined gather as a separate timeout layer atop per-request httpx timeouts with exponential backoff retries capped at 30s; and low event_scan_limit values miss relevant lower-volume events since event search uses client-side keyword scoring, not API-side text search."
metadata:
  type: component
tags:
  tech_stack: [python, httpx, pydantic, nat]
  ai_pattern: [agents, data-pipeline]
  platform: []
  data_layer: []
source_examples:
  - quickstart: "rh-research"
    repo: "https://github.com/rh-ai-quickstart/rh-research"
    notes: "Polymarket prediction market search tool registered as a NAT plugin for domain-routed research agent"
    approach: "A"
---

# Polymarket Prediction Market

## Overview

A NAT-based data source plugin that searches Polymarket prediction markets and events using the public Gamma API. It requires no API key and returns XML-style citable document blocks containing event/market titles, outcome probabilities, volume, liquidity, and end dates. In quickstart architectures, it serves as one of several domain-routed search tools available to the research agent.

## Tech Stack & Dependencies
- **Runtime:** Python >=3.11,<3.14
- **Container image:** N/A (installed as a workspace package within the agent container)
- **Key dependencies:** `httpx>=0.27.0`, `pydantic>=2.0.0`, NAT framework (`nat.builder`, `nat.cli`, `nat.data_models`)
- **Helm subchart:** None (deployed as part of the agent application)

## Key Patterns

### NAT Plugin Registration via Entry Points

The tool registers itself with NAT using Python entry points and the `@register_function` decorator pattern. The config class inherits from `FunctionBaseConfig` and uses Pydantic `Field` validators for all parameters.

```toml
# pyproject.toml entry point registration
[project.entry-points."nat.plugins"]
polymarket_prediction_market = "polymarket_prediction_market.register"
```

```python
# Config schema with Pydantic validation
class PolymarketSearchToolConfig(FunctionBaseConfig, name="polymarket_search"):
    """Search Polymarket events and markets using the public Gamma API."""
    max_results: int = Field(default=5, ge=1, le=20, description="Maximum document blocks to return")
    active: bool = Field(default=True, description="Restrict searches to active/open markets when supported")
    event_scan_limit: int = Field(default=100, ge=10, le=500, description="Number of high-volume active events to scan for keyword matches")
    timeout: float = Field(default=15.0, gt=0, description="Maximum seconds to wait for one API attempt")
    max_retries: int = Field(default=2, ge=1, description="Maximum number of API attempts")
```

### Dual-Search Strategy with Lexical Scoring

The tool runs two parallel API calls -- one for events (with nested markets) and one for standalone markets -- then deduplicates and ranks results using simple lexical term matching against the query.

```python
events, markets = await asyncio.wait_for(
    asyncio.gather(
        _search_events(client, tool_config, query),
        _search_markets(client, tool_config, query),
    ),
    timeout=tool_config.timeout,
)
```

Events are fetched by volume (top N active events) then scored client-side against query terms, while markets use the API's `keyword` parameter and are re-ranked locally.

### Graceful Degradation on Missing httpx

The registration function checks for `httpx` at import time inside the generator body and yields a stub function with an informative error message if the package is not installed.

```python
try:
    import httpx
except ImportError:
    async def _polymarket_search_stub(query: str) -> str:
        """Prediction market search unavailable because the `httpx` package is not installed."""
        return (
            "Error: Polymarket search is unavailable because the `httpx` package is not installed. "
            "Install the polymarket-prediction-market workspace package dependencies and restart AIQ."
        )
    yield FunctionInfo.from_fn(_polymarket_search_stub, description=_polymarket_search_stub.__doc__)
    return
```

### Citable Document Block Output Format

Results are rendered as XML-style document blocks with `<Document href="...">`, `<title>`, `<source>`, `<source_type>prediction_market</source_type>`, and metadata tags. All user-facing text is HTML-escaped to prevent injection.

```python
f'<Document href="{url}">\n<title>\n{title}\n</title>\n'
+ "\n".join(metadata_lines) + f"\n{body}\n</Document>"
```

### Retry with Exponential Backoff

Failed API calls are retried with exponential backoff capped at 30 seconds. The broad `except Exception` catch is intentional (commented as `noqa: BLE001`) because transport-specific exceptions from httpx vary.

```python
await asyncio.sleep(min(2**attempt, MAX_RETRY_BACKOFF_SECONDS))
```

## Configuration
- **Environment variables:** None required -- the tool uses the public Gamma API with no authentication
- **Config files:** Workflow YAML references the tool by `_type: polymarket_search`
- **Helm values:** N/A

Workflow YAML configuration example:

```yaml
polymarket_search_tool:
  _type: polymarket_search
  max_results: 5
```

The tool is assigned to a `prediction_market` domain for domain-routed agent workflows:

```yaml
- id: prediction_market
  name: "Prediction Markets"
  description: "Search Polymarket events and market-implied probabilities."
  tools:
    - polymarket_search_tool
```

## Known Gotchas
- The Gamma API returns JSON-encoded strings for list fields like `outcomes` and `outcomePrices` (e.g., `'["Yes","No"]'` instead of `["Yes","No"]`). The `_as_list()` helper handles this by attempting `json.loads` on string values before returning them.
- Query strings are truncated to 300 characters before being sent to the API to prevent oversized requests.
- The `event_scan_limit` parameter (default 100, max 500) controls how many high-volume events are fetched for client-side keyword scoring -- this is not an API-side text search, so low scan limits can miss relevant events with lower volume.
- The `asyncio.wait_for` timeout wraps the combined event+market gather, providing a separate timeout layer on top of the per-request httpx timeout.

## Testing Notes
- Tests use `monkeypatch` to replace `_fetch_json` and `asyncio.sleep`, avoiding real API calls
- The test suite validates HTML escaping of injected content in both event and market document formatting
- Retry behavior is tested by making the first API attempts raise `ConnectionError` then succeed on retry
- Config defaults and inheritance from `FunctionBaseConfig` are verified

## Related Patterns
- Other NAT source plugins in the same repo follow the identical `@register_function` / `FunctionBaseConfig` / entry-point pattern (e.g., `tavily_web_search`, `duckduckgo_news_search`, `google_scholar_paper_search`)
- Domain routing configuration groups tools by research domain in workflow YAML
