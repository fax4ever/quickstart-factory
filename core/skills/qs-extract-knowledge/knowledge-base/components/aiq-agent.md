---
name: aiq-agent
description: NVIDIA AI-Q Blueprint backend -- multi-agent research system built on NAT with LangGraph orchestration
summary: "Implements the NVIDIA AI-Q Blueprint multi-agent research backend on NeMo Agent Toolkit (NAT) 1.7.0, using LangGraph StateGraph for intent classification with shallow (bounded tool-calling loop with auto-escalation) and deep (DeepAgents create_deep_agent with orchestrator/planner/researcher/writer subagents) research paths, plus optional clarifier dialog. Use when building NAT plugin-based research agents needing role-based LLMProvider mapping semantic roles (router, planner, writer) to different models, config-driven YAML data source registry with automatic tool inheritance, and knowledge layer factory supporting llamaindex/ChromaDB and foundational_rag retriever backends. Critical patterns: agents registered via @register_function with Pydantic FunctionBaseConfig and pyproject.toml entry points, SourceRegistryMiddleware captures URLs during tool calls for citation verification and report sanitization post-processing, lazy __getattr__ imports in __init__.py defer heavy LangGraph/DeepAgents loading. Gotchas: singleton ingestors silently ignore config after first instantiation, DeepAgents StateBackend path rewriting works around CompositeBackend phantom-path bug, deep research requires recursion_limit: 2000 to avoid premature termination, and agents omitting the tools field inherit all registry tools (use exclude_tools to specialize)."
metadata:
  type: component
tags:
  tech_stack: [python, fastapi, langchain, langgraph, deepagents, pydantic, dask, uv]
  ai_pattern: [agents, rag, prompt-chaining, evaluation, data-pipeline]
  platform: [nvidia-nim, opentelemetry]
  data_layer: [chromadb, postgresql, sqlite]
source_examples:
  - quickstart: "rh-research"
    repo: "https://github.com/rh-ai-quickstart/rh-research"
    notes: "Multi-agent research backend with shallow/deep research, clarification, and citation verification"
    approach: "A"
---

# AIQ Agent

## Overview

The `aiq_agent` package is the core backend of the NVIDIA AI-Q Blueprint, an enterprise research agent built on the NeMo Agent Toolkit (NAT). It implements a multi-agent research workflow that classifies user intent, routes to shallow or deep research paths, optionally clarifies queries before research, and post-processes results with citation verification and report sanitization. The package is structured as a set of NAT plugins registered via entry points, with agents orchestrated using LangGraph and DeepAgents.

## Tech Stack & Dependencies

- **Runtime:** Python >=3.11,<3.14 (container uses Python 3.13)
- **Container image:** `nvcr.io/nvidia/distroless/python:3.13-v4.0.5` (runtime), `nvcr.io/nvidia/base/ubuntu:noble-20260217` (builder)
- **Key dependencies:** `nvidia-nat-core==1.7.0`, `nvidia-nat[langchain,async_endpoints,phoenix,mcp]==1.7.0`, `deepagents>=0.6.5`, `langgraph-checkpoint-postgres>=3.0.0`, `langchain-modal==0.0.5`, `knowledge-layer[all]`
- **Package management:** `uv` with workspace members in `sources/` and `frontends/`
- **Helm subchart:** None -- deployed via Docker Compose and Helm charts in `deploy/`

## Key Patterns

### NAT Plugin Registration

All agents and extensions are registered as NAT plugins via entry points and the `@register_function` decorator. Config schemas use Pydantic and inherit from `FunctionBaseConfig`. The `_type` field in YAML config selects the registered function.

```python
# src/aiq_agent/agents/deep_researcher/register.py
class DeepResearchAgentConfig(FunctionBaseConfig, name="deep_research_agent"):
    orchestrator_llm: LLMRef = Field(..., description="LLM for orchestrator")
    researcher_llm: LLMRef | None = Field(default=None)
    planner_llm: LLMRef | None = Field(default=None)
    writer_llm: LLMRef | None = Field(default=None)
    tools: list[FunctionRef | FunctionGroupRef] = Field(default_factory=list)
    exclude_tools: list[str] = Field(default_factory=list)

@register_function(config_type=DeepResearchAgentConfig, framework_wrappers=[LLMFrameworkEnum.LANGCHAIN])
async def deep_research_agent(config: DeepResearchAgentConfig, builder: Builder):
    ...
```

Entry points are declared in `pyproject.toml`:

```toml
# pyproject.toml
[project.entry-points."nat.plugins"]
aiq_chat_researcher = "aiq_agent.agents.chat_researcher.register"
aiq_deep_researcher = "aiq_agent.agents.deep_researcher.register"
aiq_shallow_researcher = "aiq_agent.agents.shallow_researcher.register"
aiq_fastapi_extensions = "aiq_agent.fastapi_extensions.register"
aiq_clarifier = "aiq_agent.agents.clarifier.register"
aiq_data_source_registry = "aiq_agent.common.data_source_registry"
```

### Role-Based LLM Provider

The `LLMProvider` pattern allows mapping different LLM configurations to semantic roles in the research workflow, enabling A/B testing and cost optimization. Each agent role (router, planner, researcher, writer, etc.) can use a different model.

```python
# src/aiq_agent/common/llm_provider.py
class LLMRole(StrEnum):
    ROUTER = "router"
    PLANNER = "planner"
    RESEARCHER = "researcher"
    REPORT_WRITER = "report_writer"
    ORCHESTRATOR = "orchestrator"
    CLARIFIER = "clarifier"
    # ... plus EVIDENCE_JUDGE, GRADER, SUMMARIZER, REFLECTION, META_CHATTER

provider = LLMProvider()
provider.set_default(nim_llm)
provider.configure(LLMRole.REPORT_WRITER, qwen_llm)
writer_llm = provider.get(LLMRole.REPORT_WRITER)  # returns qwen_llm
router_llm = provider.get(LLMRole.ROUTER)          # falls back to nim_llm
```

### Multi-Agent Research Workflow (LangGraph)

The `ChatResearcherAgent` orchestrates the full workflow using a LangGraph `StateGraph` with conditional routing:

1. **Intent classification** -- determines if the query is "meta" (casual) or "research"
2. **Depth routing** -- routes to shallow or deep research based on complexity
3. **Clarifier** (optional) -- multi-turn dialog to refine the query before deep research, with optional plan preview/approval
4. **Shallow research** -- fast bounded research using LangGraph tool-calling loop with max iteration limits
5. **Deep research** -- multi-phase workflow using DeepAgents with subagents (source-router, planner, researcher, writer)
6. **Escalation** -- optional automatic escalation from shallow to deep when results are insufficient

```python
# src/aiq_agent/agents/chat_researcher/agent.py
graph = StateGraph(ChatResearcherState)
graph.add_node("intent_classifier", intent_classifier_node)
graph.add_node("shallow_research", shallow_research_node)
graph.add_node("clarifier", clarifier_node)
graph.add_node("deep_research", deep_research_node)
graph.set_entry_point("intent_classifier")
graph.add_conditional_edges("intent_classifier", route_after_orchestration, ...)
graph.add_conditional_edges("shallow_research", should_escalate, ...)
```

### Deep Research Graph (DeepAgents)

The deep researcher uses the `deepagents` library's `create_deep_agent` to build a graph with an orchestrator, subagents (source-router, planner, writer), and isolated researcher workers. The graph includes middleware stacks for tool retry, model retry, source registry, and tool result pruning.

```python
# src/aiq_agent/agents/deep_researcher/factory.py
agent = create_deep_agent(
    model=llm_provider.get(LLMRole.ORCHESTRATOR),
    tools=[*tool_set.helper_tools, research_batch_tool],
    system_prompt=render_prompt_template(prompts["orchestrator"], ...),
    subagents=build_deep_research_subagents(...),
    store=InMemoryStore(),
    middleware=middleware_set.orchestrator,
    backend=backend,
).with_config({"recursion_limit": 2000})
```

### Knowledge Layer Factory

The knowledge subsystem uses a registry-based factory pattern for retriever and ingestor backends. Backends are registered with decorators and instantiated by name at runtime. Ingestors use singleton caching for job state persistence.

```python
# src/aiq_agent/knowledge/factory.py
@register_retriever("llamaindex")
class LlamaIndexRetriever(BaseRetriever): ...

retriever = get_retriever("llamaindex", {"persist_dir": "/data/chroma"})
ingestor = get_ingestor("foundational_rag", {"rag_url": "...", "ingest_url": "..."})
```

Supported backends: `llamaindex` (ChromaDB-backed) and `foundational_rag` (external RAG server).

### Config-Driven Data Source Registry

Data sources are declared in YAML config and registered at startup. The registry maps tool names to data source IDs, enabling per-request source filtering in the UI and automatic tool inheritance by agents.

```yaml
# configs/config_cli_default.yml
functions:
  data_sources:
    _type: data_source_registry
    sources:
      - id: web_search
        name: "Web Search"
        description: "Search the web for real-time information."
        tools:
          - web_search_tool
          - advanced_web_search_tool
```

Agents with no explicit `tools` list inherit all tools from the registry. Use `exclude_tools` to specialize.

### Citation Verification and Report Sanitization

Both shallow and deep research agents post-process reports through citation verification (matching citations against a `SourceRegistry` populated during tool calls) and report sanitization (stripping body URLs, shortened URLs, unsafe URLs). The `SourceRegistryMiddleware` captures source URLs from tool results during research.

```python
# src/aiq_agent/agents/deep_researcher/agent.py
if self.source_registry_middleware.has_sources():
    registry = self.source_registry_middleware.active_registry()
    verification = verify_citations(final_message, registry, ...)
    final_message = verification.verified_report

sanitization = sanitize_report(final_message)
final_message = sanitization.sanitized_report
```

### Lazy Module Imports

The top-level `__init__.py` uses `__getattr__` for lazy imports to avoid loading heavy dependencies (LangGraph, DeepAgents) when only lightweight submodules like `aiq_agent.knowledge` are needed.

```python
# src/aiq_agent/__init__.py
def __getattr__(name: str):
    if name == "deep_research_agent":
        from .agents import deep_research_agent
        _lazy_imports[name] = deep_research_agent
        return deep_research_agent
    raise AttributeError(...)
```

## Configuration

- **Environment variables:**
  - `KNOWLEDGE_RETRIEVER_BACKEND` / `KNOWLEDGE_INGESTOR_BACKEND` -- default knowledge backends (default: `llamaindex`)
  - `AIQ_CHROMA_DIR` -- ChromaDB persistence directory for LlamaIndex backend
  - `AIQ_VERBOSE` -- enable verbose logging (`1`, `true`, `yes`)
  - `CONFIG_FILE` -- workflow config YAML path (default: `/app/configs/config_web_default_llamaindex.yml`)
  - `NVIDIA_API_KEY` -- API key for NVIDIA NIM endpoints
  - `DEBUG_PROMPTS` -- log rendered system prompts
  - `HOST` / `PORT` -- web server bind address (default: `0.0.0.0:8000`)
  - `DASK_SCHEDULER_PORT` / `DASK_NWORKERS` / `DASK_NTHREADS` -- Dask cluster config
  - `AIQ_CHECKPOINT_DB` -- checkpoint database path (default: `./checkpoints.db`)
- **Config files:** YAML workflow configs in `configs/` define LLMs, functions (agents, tools, data sources), and the top-level workflow
- **Helm values:** Helm charts are in `deploy/helm/`

## Known Gotchas

- **Lazy imports are intentional:** The `__init__.py` uses `__getattr__` to defer heavy imports. Direct imports like `from aiq_agent.agents.deep_researcher import ...` bypass lazy loading and pull in the full dependency chain (LangGraph, DeepAgents, etc.).
- **Tool inheritance from data source registry:** When an agent config omits the `tools` field, it inherits all tools from the `data_source_registry`. Use `exclude_tools` to remove specific tools. This behavior is implemented in each agent's `register.py` via `get_all_tool_refs()`.
- **DeepAgents StateBackend path rewriting:** The `_PrefixedStateBackend` in `deepagents_runtime.py` works around a DeepAgents `CompositeBackend` bug where error messages reference stripped path prefixes (e.g., `/0_weather_data.txt` instead of `/shared/0_weather_data.txt`), causing the agent to chase phantom paths via shell.
- **Singleton ingestors:** The knowledge factory caches ingestor instances per backend name. Config passed after first instantiation is silently ignored, which can cause confusion if different configs reference the same backend.
- **SkillsConfig deprecation:** The `sources` and `default_sources` fields on `SkillsConfig` are deprecated. Use `agent_sources` with per-agent mappings instead. The validator warns and drops deprecated fields.
- **Citation verification can strip all citations:** If `verify_citations` removes all citations and only one source was captured, the shallow researcher appends a minimal citation. Deep research logs a warning but does not fail.
- **Modal sandbox recreation:** The `_LazyModalSandboxBackend` auto-recreates the sandbox on `NotFoundError`, but uploaded files in the previous sandbox are lost. This is logged as a warning.
- **Recursion limit for deep research:** The deep research graph is configured with `recursion_limit: 2000` to accommodate the multi-phase, multi-subagent workflow. Lower limits can cause premature termination.

## Testing Notes

- Run tests with `uv run pytest` from the repo root
- Test paths: `tests/` and `sources/**/tests/`
- Uses `pytest-asyncio` with `auto` mode and `session`-scoped event loop
- Lint: `uv run ruff check .`; format: `uv run ruff format --check .`
- Backend API serves at `http://localhost:8000`; start with `nat serve --config_file configs/config_cli_default.yml --port 8000`

## Related Patterns

- Knowledge layer backends (LlamaIndex, Foundational RAG) are separate workspace packages in `sources/`
- Frontend is a Next.js/React app in `frontends/ui/`
- Data source tool packages (Tavily, Google Scholar, Exa, DuckDuckGo) are workspace packages in `sources/`
- Tokenomics subsystem parses NAT profiler traces for cost analysis reports
