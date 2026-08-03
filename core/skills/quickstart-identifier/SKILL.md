---
name: quickstart-identifier
description: Identify potential new AI Quickstarts from industry trends and gaps. Use when analyzing pipeline coverage or proposing new quickstart ideas.
---

# quickstart-identifier

## Purpose

Identify potential new AI Quickstarts by:
- **Coverage analysis:** Compare current pipeline to industry and technology targets
- **Gap identification:** Find underserved industries, use cases, or technologies
- **Proposal generation:** Produce structured suggestions for backlog

## Workflow

1. **Load backlog:** Use `gh-backlog-reader` to get current issues from GitHub
2. **Compare to targets:** Use [references/industry-trends.md](references/industry-trends.md) for industry and technology coverage
3. **Identify gaps:** Industries/technologies with zero or low coverage
4. **Propose:** Generate [Quickstart suggestion] compatible proposals with rationale

## Proposal Format

```markdown
## Proposed Quickstart: [Name]

- **Industry:** [e.g. Financial Services]
- **Technology:** [e.g. Llama Stack, MCP]
- **Use case:** [1–2 sentences]
- **Rationale:** Why this gap matters
- **Suggested owner:** (if known)
```

## Output

Coverage analysis spans the whole backlog, not one quickstart, so save any report to `.rhoai-qs/_shared/reports/` (see [pipeline-convention.md](../../docs/foundation/pipeline-convention.md)) — never under a single quickstart's slug folder. If the user decides to pursue one of the proposed ideas, hand off to `rh-qs-discovery`, which will create the actual slug folder.

## References

- **Industry and technology trends:** [references/industry-trends.md](references/industry-trends.md)
- **Grooming targets:** `pipeline-grooming/references/grooming-criteria.md`
