---
name: pipeline-grooming
description: Groom, prioritize, and categorize the AI Quickstarts backlog. Use when preparing backlog for sprint planning or reporting on pipeline health.
---

# pipeline-grooming

## Purpose

Groom, prioritize, and categorize the AI Quickstarts backlog. Ensures consistent readiness, industry/technology coverage, and clear progression from Idea → In Progress → Done.

## Grooming Checklist

Use this checklist per quickstart item:

- [ ] **Business outcome** documented (why this quickstart matters)
- [ ] **Owner** assigned or proposed
- [ ] **Scope** clear (what's in/out for v1)
- [ ] **Technology** tagged (RHOAI, Llama Stack, MCP, etc.)
- [ ] **Industry** tagged if applicable (Financial Services, Healthcare, Retail, etc.)
- [ ] **Dependencies** identified
- [ ] **Readiness** scored using rubric (see references)

## Categorization

**By Readiness:** Idea → In Progress → Done (gates in `references/grooming-criteria.md`)

**By Industry:** Financial Services, Healthcare, Retail, IT Ops, Manufacturing, Public Sector, Telecom, Energy

**By Technology:** RHOAI, Llama Stack, MCP, LangGraph, vLLM, Vision Models, etc.

## Report Template

Grooming spans the whole backlog, not one quickstart, so save the report to the top-level `.rhoai-qs/reports/grooming-report-<date>.md` (see [pipeline-convention.md](../../../docs/foundation/pipeline-convention.md)) — never under a single quickstart's slug folder.

When producing a grooming report:

```markdown
# Pipeline Grooming Report — [Date]

## Summary
- Total: X | Idea: Y | In Progress: Z | Done: W

## Readiness Gaps
[List items missing gates for next stage]

## Coverage
- Industry: [table or list]
- Technology: [table or list]

## Recommendations
1. [Prioritization suggestion]
2. [Gap to address]
```

## References

- **Scoring and gates:** [references/grooming-criteria.md](references/grooming-criteria.md)
- **Backlog data:** Use `gh-backlog-reader` to fetch and filter issues from the GitHub backlog
