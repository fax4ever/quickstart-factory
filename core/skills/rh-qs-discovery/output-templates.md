---
description: PRD output format definition for rh-qs-discovery
---

# Discovery Output Templates

This document defines the PRD format produced by rh-qs-discovery. The main agent and the prd-structurer subagent reference this document to ensure consistent output structure.

For the gap analysis report format, see [references/gap-analysis-template.md](./references/gap-analysis-template.md).

## PRD Template

**Location:** `.rhoai-qs/<slug>/prds/prd.md`

**Slug convention:** lowercase, hyphenated (e.g., `mortgage-application-processor`, `supply-chain-anomaly-detector`).

```markdown
# <Quickstart Title>

**Issue:** <destination repo>#<issue number> (or "not yet created")
**Slug:** <slug>
**Date:** <YYYY-MM-DD>

## Use case summary

One paragraph describing the problem this quickstart solves, who it serves, and the
core value proposition. This should be concrete enough that a reader unfamiliar with
the project understands the "why" in 30 seconds.

## User flows

Describe the primary user flow step by step. Include the entry point, key
interactions, and expected outcomes. If there are multiple flows (e.g., admin vs
end-user), list each as a subsection.

### Primary flow
1. User does X
2. System does Y
3. User sees Z

## Data model

What data does this quickstart work with? Describe:
- Input data types (documents, transactions, images, streams)
- Storage requirements (persistent DB, vector store, object storage)
- Data lifecycle (ingestion, processing, retrieval, expiration)

## AI touchpoints

Which AI capabilities are central to this quickstart? For each:
- **Capability:** (RAG, text generation, classification, agents, vision, etc.)
- **Why:** What problem does this AI capability solve in the user flow?
- **Model considerations:** Size constraints, safety requirements, multilingual needs

## Deploy target

- **Primary:** OpenShift AI (required)
- **Secondary:** Local dev with podman-compose (if applicable)
- **GPU:** Required / Optional / Not needed — with rationale
- **Scale:** Expected concurrent users or request volume

## Constraints and non-goals

What this quickstart will NOT do. Explicit scope boundaries prevent scope creep
in downstream skills. Include:
- Features explicitly excluded
- Scale limitations
- Technology constraints (if any)
- Compliance requirements (if any)

## Open questions (if any)

Unresolved items that need answers before architecture can begin. Each question
should note which PRD section it affects.

- [ ] Question 1 (affects: Data model)
- [ ] Question 2 (affects: Deploy target)
```

### PRD Section Requirements

Every PRD must have substantive content in these sections before it can be approved for handoff to `rh-qs-architect`:

| Section | Required content |
|---------|-----------------|
| Use case summary | Concrete problem statement with target persona |
| User flows | At least one step-by-step flow |
| Data model | Input data types and storage needs |
| AI touchpoints | At least one AI capability with rationale |
| Deploy target | Primary target + GPU determination |
| Constraints and non-goals | At least one explicit non-goal |

`Open questions` may be empty — that means the PRD is fully resolved.
