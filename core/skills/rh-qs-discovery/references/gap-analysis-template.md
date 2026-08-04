# Gap Analysis Report Template

This template is used by the main agent in **gap analysis mode** only (when the user asks to identify coverage gaps and suggest new quickstart ideas). It is not read during normal PRD discovery.

Gap analysis surveys the whole backlog — it runs before any specific quickstart slug exists, so this report is **not** namespaced under `.rhoai-qs/<slug>/`. It's a cross-cutting artifact, like a grooming report.

**Location:** `.rhoai-qs/reports/gap-analysis-<YYYY-MM-DD>.md`

```markdown
# Quickstart Gap Analysis — <Date>

## Backlog Summary

- Open issues: <count>
- By label: <breakdown>
- By industry: <breakdown>

## Coverage Matrix

| Industry | Current quickstarts | Gaps |
|----------|-------------------|------|
| Financial services | ... | ... |
| Healthcare | ... | ... |
| Manufacturing | ... | ... |

## Technology Coverage

| AI Capability | Covered by | Missing |
|---------------|-----------|---------|
| RAG | ... | ... |
| Agents | ... | ... |
| Classification | ... | ... |

## Proposed New Quickstarts

### 1. <Proposed title>
- **Industry:** ...
- **AI capability:** ...
- **Rationale:** Why this fills a gap
- **Complexity estimate:** Low / Medium / High

### 2. <Proposed title>
...

## Recommendations

Prioritized list of 3-5 new quickstarts with rationale for ordering.
```
