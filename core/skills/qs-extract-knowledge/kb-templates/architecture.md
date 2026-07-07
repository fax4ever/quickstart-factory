# Architecture KB File Body Template

Use this structure for all files in `knowledge-base/architectures/`. Each file describes an AI pattern — how components are wired together to implement a specific AI capability (RAG, agents, guardrails, etc.).

## Body Structure

```markdown
# <Architecture Pattern Name>

## Overview
<2-3 sentences: what AI pattern this represents, what problem it solves, how components interact at a high level.>

## Data Flow
<Describe the end-to-end data flow through the system. Use a numbered list or ASCII diagram showing how a request moves through components.>

1. User submits query via frontend
2. Backend receives request, calls embedding model
3. Vector DB returns relevant chunks
4. LLM generates response with retrieved context
5. Response returned to user

## Component Wiring
<How components connect to each other — API contracts, message passing, shared state.>

| From | To | Protocol | Purpose |
|------|----|----------|---------|
| <component> | <component> | <REST/gRPC/SDK> | <what data flows> |

## Key Integration Points

### <Integration Point Name>
<Description with a short code/YAML snippet showing how the integration works.>

```python
# or yaml — 5-15 lines showing the wiring pattern
```

<Repeat for each critical integration point.>

## Prompt / Chain Patterns
<If applicable: how prompts are structured, chain-of-thought patterns, tool use patterns, agent orchestration logic.>

```python
# Example prompt template or chain definition
```

## Gotchas
- <Gotcha 1: integration issue and its solution>
- <Gotcha 2: ...>

## Related Architectures
- <Links to related architecture KB files, e.g., a RAG pipeline that also uses guardrails>
```

## Guidelines

- Architecture files describe **how components interact**, not what individual components do (that's `components/`)
- Focus on the AI-specific wiring — data flow, prompt patterns, model interaction
- Include actual code showing integration points (API calls, chain definitions, retriever setup)
- If the architecture combines multiple patterns (e.g., RAG + guardrails), note this and link to the other architecture file
- Keep component wiring tables factual — describe what exists in the repo, don't design ideal architectures
