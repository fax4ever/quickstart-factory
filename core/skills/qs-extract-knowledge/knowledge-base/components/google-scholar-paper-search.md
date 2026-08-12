---
name: google-scholar-paper-search
description: "NAT plugin tool that searches Google Scholar for academic papers via the Serper API"
summary: "NAT plugin that registers a Google Scholar search tool via Python entry points (`[project.entry-points.\"nat.plugins\"]`) and the `@register_function` decorator with Pydantic `PaperSearchToolConfig`, enabling research agents to find peer-reviewed papers through the Serper API. Use for the `scholarly_technical` domain where academic papers are needed — configured in workflow YAML with `_type: paper_search` and wired into domain-based routing alongside `web_search` and `knowledge_layer`; only active in `config_domain_routing_and_skills.yml` (commented out in all other configs). The NAT-independent `PaperSearchTool` core class uses `asyncio.gather` for concurrent paginated Serper requests (50-result cost cap, 20/request API limit) with flexible year filtering (single, range, open-start/end), and requires `SERPER_API_KEY` — when missing, a stub function yields an informative error via `FunctionInfo.from_fn` instead of crashing. Key gotchas: `pyproject.toml` declares `httpx` but runtime uses `aiohttp` (transitive via NAT), the stub's `AliasChoices(\"query\",\"question\")` accepts both parameter names but the live function only accepts `query`, and the plugin pattern in `sources/` is shared with `tavily_web_search`, `duckduckgo_news_search`, and `exa_web_search`."
metadata:
  type: component
tags:
  tech_stack: [python, aiohttp, pydantic, nat]
  ai_pattern: [agents, data-pipeline]
  platform: []
  data_layer: []
source_examples:
  - quickstart: "rh-research"
    repo: "https://github.com/rh-ai-quickstart/rh-research"
    notes: "NAT plugin for academic paper search via Google Scholar (Serper), used by deep research agent"
    approach: "A"
---

# Google Scholar Paper Search

## Overview

A NAT (NeMo Agent Toolkit) plugin that provides academic paper search capabilities via the Serper Google Scholar API. It registers as a tool function that research agents can invoke to find peer-reviewed publications, returning formatted results with citation counts, snippets, and links. The component is designed as an independent, self-contained package under `sources/` with graceful degradation when the API key is missing.

## Tech Stack & Dependencies

- **Runtime:** Python >=3.11,<3.14
- **Container image:** Not standalone; packaged into the main agent image
- **Key dependencies:** `httpx>=0.24.0`, `pydantic>=2.0.0`, `aiohttp` (used at runtime for async HTTP)
- **Helm subchart:** None (tool plugin, not a standalone service)
- **Build system:** setuptools with `setuptools-scm>=8`

## Key Patterns

### NAT Plugin Registration via Entry Points

The tool registers itself as a NAT plugin through Python entry points, making it automatically discoverable by the NAT framework without hard-coded imports in the main application.

```toml
# pyproject.toml
[project.entry-points."nat.plugins"]
paper_search = "google_scholar_paper_search.register"
```

The registration function uses NAT's `@register_function` decorator with a Pydantic config class:

```python
# src/register.py
class PaperSearchToolConfig(FunctionBaseConfig, name="paper_search"):
    timeout: int = Field(default=30, description="Timeout in seconds for the search requests")
    max_results: int = Field(default=10, description="Maximum number of search results to return")
    serper_api_key: SecretStr | None = Field(default=None, description="The API key for Serper (Google Scholar)")

@register_function(config_type=PaperSearchToolConfig)
async def paper_search(tool_config: PaperSearchToolConfig, builder: Builder):
    ...
    yield FunctionInfo.from_fn(_paper_search, description=_paper_search.__doc__)
```

### Graceful Degradation with Stub Function

When the `SERPER_API_KEY` is missing, the tool still registers but yields a stub function that returns an informative error message instead of crashing. A module-level flag prevents duplicate warnings.

```python
# src/register.py
_missing_key_warned = False

# Inside register function, when key is missing:
async def _paper_search_stub(
    query: str = Field(..., validation_alias=AliasChoices("query", "question")),
    year: str | None = None,
) -> str:
    """Paper search tool (unavailable - missing SERPER_API_KEY)."""
    return "Error: Paper search is unavailable because SERPER_API_KEY is not set.\n..."

yield FunctionInfo.from_fn(_paper_search_stub, description=_paper_search_stub.__doc__)
```

### Async Paginated Search with Concurrent Requests

The search implementation uses `asyncio.gather` to fetch multiple pages concurrently from the Serper API. Results are capped at 50 per search for cost control, with a per-request limit of 20 enforced by the API.

```python
# src/paper_search.py
limit = min(limit, 50)           # Cost control cap
page_size = 10
total_pages = math.ceil(limit / page_size)

tasks = []
for page in range(total_pages):
    current_limit = min(page_size, limit - (page * page_size))
    if current_limit <= 0:
        break
    tasks.append(self._fetch_serper_page(query, current_limit, page * page_size, start_year, end_year))

page_results = await asyncio.gather(*tasks)
```

### Year Range Parsing

The tool supports flexible year filtering: single year (`"2023"`), year range (`"2020-2023"`), open-start (`"-2023"`), or open-end (`"2020-"`). Integer years are also accepted and converted to strings.

```python
# src/paper_search.py
if year:
    if "-" in year:
        parts = year.split("-")
        if len(parts) == 2:
            start_year = parts[0] if parts[0] else None
            end_year = parts[1] if parts[1] else None
    else:
        start_year = year
        end_year = year
```

### NAT-Independent Core Class

The `PaperSearchTool` class is deliberately NAT-independent -- it receives all dependencies via constructor injection. NAT-specific wiring (config, `FunctionInfo`, `Builder`) is isolated in `register.py`, keeping the core logic testable without NAT.

```python
# src/paper_search.py
class PaperSearchTool:
    def __init__(self, serper_api_key: str, *, timeout: int = 30, max_results: int = 10) -> None:
        self.serper_api_key = serper_api_key
        self.timeout = timeout
        self.max_results = max_results
```

## Configuration

- **Environment variables:**
  - `SERPER_API_KEY` -- API key for the Serper Google Scholar endpoint. Can also be provided via workflow config YAML using `serper_api_key: ${SERPER_API_KEY}`
- **Config files:** Configured in NAT workflow YAML under the `functions` section with `_type: paper_search`
- **Helm values:** None (not a standalone service)

### Workflow YAML Configuration

```yaml
# configs/config_domain_routing_and_skills.yml
paper_search_tool:
  _type: paper_search
  max_results: 5
  serper_api_key: ${SERPER_API_KEY}
```

The tool is wired into the data source registry for domain-based routing:

```yaml
# configs/domain_catalogs/deep_research_domain_catalog.yml
- domain_id: scholarly_technical
  domain_name: Scholarly and Technical Research
  description: Scientific, engineering, medical, benchmark, method, paper, and standards-heavy questions.
  preferred_source_ids:
    - paper_search
    - web_search
    - knowledge_layer
```

## Known Gotchas

- The `pyproject.toml` declares `httpx>=0.24.0` as a dependency but the actual HTTP calls in `paper_search.py` use `aiohttp`, which is not listed as an explicit dependency. It is available transitively through the NAT framework.
- The Serper API caps results at 20 per request (`min(num, 20)` in `_fetch_serper_page`), so requesting more than 20 results requires pagination across multiple API calls.
- The tool is commented out by default in most workflow configs (`config_cli_default.yml`, `config_frontier_models.yml`, `config_web_default_llamaindex.yml`). Only `config_domain_routing_and_skills.yml` has it enabled.
- The `AliasChoices("query", "question")` on the stub function allows the agent to invoke the tool with either parameter name, but the live function does not use `AliasChoices` -- it only accepts `query`.

## Testing Notes

- Tests use `pytest` with `pytest-asyncio` and mock all HTTP calls via `unittest.mock.patch` on `aiohttp.ClientSession`
- The `conftest.py` provides `paper_search_tool`, `sample_serper_response`, and `sample_papers` fixtures
- Tests cover: initialization, result formatting (including missing fields), year parsing (single, range, open-start, open-end), pagination, result aggregation, API payload construction, and the per-request 20-result cap

## Related Patterns

- Other search tool plugins in `sources/` follow the same NAT plugin pattern: `tavily_web_search`, `duckduckgo_news_search`, `exa_web_search`
- Domain-based source routing in `configs/domain_catalogs/` determines when this tool is preferred over web search
