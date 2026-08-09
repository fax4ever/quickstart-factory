# Discovery Subagents

This directory contains specialized subagent prompts that handle focused tasks during quickstart discovery. The main discovery skill ([../SKILL.md](../SKILL.md)) orchestrates these subagents to keep context lean while maintaining PRD quality.

## Architecture

**Main Agent** (SKILL.md):
- Orchestrates the discovery workflow phases
- Conducts the structured interview with the user
- Reads reasoning guardrails organically while drafting (Phases 1-6)
- Reviews subagent outputs — including the `prd-griller`'s questions and the `prd-validator`'s findings — and decides what to change, using conversational context the subagents don't have
- Runs the `prd-griller`'s question rounds directly with the user (frontier computation, presentation, and re-computation are all main-agent work — the subagent is invoked once)
- Presents the draft PRD to the user and manages the uncapped refinement loop

**Subagents** (this directory):
- Execute focused, self-contained tasks
- Return structured data (JSON schemas enforced)
- Don't need full context — only specific inputs from the main agent
- Keep main agent context low (~60-70% reduction)

## Subagent Prompts

### 1. validation-skill-prompt.md

| Field | Description |
|-------|-------------|
| **Name** | `validation-skill-prompt.md` |
| **Purpose** | Resolve which quickstart (by slug) this session applies to, when continuing or refining an existing idea |
| **Input** | User's raw message, list of existing slugs under `.rhoai-qs/` (excluding `reports` and `blog-drafts`), `is_entry_point: true`, calling skill name |
| **Output** | Resolution status as JSON — resolved/needs_user_input/new_quickstart/error, with slug and confidence |
| **When used** | Phase 0 — only when continuing/refining an existing idea; skipped for brand-new ideas (no slug exists yet) |
| **Why subagent** | Mechanical slug matching against a list, no reasoning about the PRD itself, self-contained — see [validation-skill-template.md](../../../../docs/foundation/validation-skill-template.md) for the full spec |

**Output schema:**

```json
{
  "resolution": "resolved|needs_user_input|new_quickstart|error",
  "slug": "mortgage-processor",
  "confidence": "high|medium|low",
  "confirm_with_user": false,
  "question_for_user": null,
  "error_message": null
}
```

---

### 2. prd-structurer-prompt.md

| Field | Description |
|-------|-------------|
| **Name** | `prd-structurer-prompt.md` |
| **Purpose** | Convert unstructured notes, uploaded documents, or conversation summaries into structured PRD sections |
| **Input** | Raw user input (document text, conversation notes, pasted ideas), input type, path to output-templates.md |
| **Output** | Structured PRD sections as JSON — each section with content, confidence level, and gaps |
| **When used** | Phase 5 (Structured Interview / PRD Structuring) — when the user uploads documents instead of answering questions interactively |
| **Why subagent** | Pure document parsing and extraction — no reasoning decisions, self-contained, saves context |

**Output schema:**

```json
{
  "sections": [
    {
      "section_name": "use_case_summary",
      "content": "...",
      "confidence": "high|medium|low",
      "gaps": ["missing detail about..."]
    }
  ],
  "overall_coverage": "high|medium|low",
  "suggested_interview_questions": ["..."]
}
```

---

### 3. backlog-matcher-prompt.md

| Field | Description |
|-------|-------------|
| **Name** | `backlog-matcher-prompt.md` |
| **Purpose** | Check if the user's quickstart idea duplicates or overlaps with existing backlog issues |
| **Input** | Idea summary (1-3 sentences), idea keywords, full backlog data from gh-backlog-reader |
| **Output** | Match report as JSON — match status, matched issues, and recommendation |
| **When used** | Phase 2 (Backlog Check) — before the interview begins |
| **Why subagent** | Mechanical comparison across multiple dimensions, no interpretation needed, self-contained |

**Output schema:**

```json
{
  "match_status": "duplicate|similar|unique",
  "matches": [
    {
      "issue_number": 42,
      "title": "...",
      "overlap_pct": 85,
      "overlap_explanation": "Both target RAG with pgvector for financial documents"
    }
  ],
  "recommendation": "stop|extend|proceed",
  "recommendation_rationale": "..."
}
```

---

### 4. prd-validator-prompt.md

| Field | Description |
|-------|-------------|
| **Name** | `prd-validator-prompt.md` |
| **Purpose** | Independently review the PRD draft for completeness, validation-rule compliance, and guardrail adherence — from a clean context, with no memory of how the draft was written |
| **Input** | Current PRD draft text, `validation_rules` from the discovery spec, path to `reasoning-guardrails.md`, path to `output-templates.md` |
| **Output** | Structured findings as JSON — overall status, section findings, validation rule results, guardrail flags. **Never a revised PRD** — recommendations only |
| **When used** | Phase 7 (PRD Validation and Refinement) — once per draft revision, including every round of the refinement loop |
| **Why subagent** | The agent that wrote the draft is biased toward its own choices; a fresh, unbiased pass with no drafting history catches things the main agent would talk itself out of. The subagent may only recommend — the main agent retains final authority and the broader conversational context to judge which findings actually apply. |

**Output schema:**

```json
{
  "overall_status": "ready|needs_revision",
  "section_findings": [
    {
      "section": "ai_touchpoints",
      "issue": "...",
      "severity": "blocker|warning",
      "recommendation": "..."
    }
  ],
  "validation_rule_results": [
    {
      "rule_id": "vr-2",
      "passed": true,
      "severity": "blocker",
      "detail": "..."
    }
  ],
  "guardrail_flags": [
    {
      "concern_area": "Technology Bias",
      "observation": "...",
      "cited_section": "ai_touchpoints",
      "recommendation": "..."
    }
  ]
}
```

---

### 5. prd-griller-prompt.md

| Field | Description |
|-------|-------------|
| **Name** | `prd-griller-prompt.md` |
| **Purpose** | Stress-test the draft PRD with tough, open-ended questions that surface contradictions, vague language, missing non-goals, and untested assumptions — complementary to `prd-validator`'s structural completeness checks, not a replacement for them |
| **Input** | Current draft PRD content, the `backlog-matcher` output, the Phase 6 requirement mapping |
| **Output** | Structured findings as JSON — a dependency graph of questions (each with a `recommended_answer` and `depends_on`), plus any weak spots already resolved by cross-referencing another PRD section. **Never a revised PRD** — recommendations only |
| **When used** | Phase 6.5 (PRD Grilling) — once per PRD draft, between requirement mapping and PRD validation, and only when overall PRD coverage is medium or high |
| **Why subagent** | Open-ended stress-testing benefits from a focused, self-contained pass, and working out the full question dependency graph in one invocation lets the main agent run multiple question rounds with the user without ever re-spawning the subagent |

**Output schema:**

```json
{
  "questions": [
    {
      "question_id": "q1",
      "title": "Scanned vs. text-only documents",
      "question": "...",
      "recommended_answer": "...",
      "depends_on": null,
      "impact": "high|medium|low"
    }
  ],
  "answered_by_cross_reference": [
    {
      "question": "...",
      "answer_found_in_section": "user_flows",
      "answer": "..."
    }
  ]
}
```

---

## Important Notes

### For Main Agent

**DO NOT read these subagent prompt files directly.** Pass them by file path to the Agent/Task tool:

```python
Agent(
    description="Check backlog for duplicates",
    prompt=f"""
Read and follow instructions from:
core/skills/rh-qs-discovery/subagents/backlog-matcher-prompt.md

Idea summary: {idea_summary}
Idea keywords: {keywords}
Backlog data: {backlog_data}
"""
)
```

### For Subagents

Each subagent prompt is **self-contained** with:
1. **Your Role** (2-3 paragraphs): what you do, why it matters, how output is used
2. **Instructions**: step-by-step task execution with input parameters
3. **Output specification**: JSON schema with concrete example

### What the Main Agent Reads Directly

| File | When |
|------|------|
| `SKILL.md` | Always (orchestrator instructions) |
| `reasoning-guardrails.md` | Phases 1-6 — organic awareness while drafting. The formal Phase 7 check is now delegated to the `prd-validator` subagent, which reads this file independently for its own clean-context review. |
| `spec-template.md` | When generating the discovery spec (Phase 4) |
| `output-templates.md` | When writing the final PRD (Phase 8). Also read by the prd-structurer subagent (Phase 5) and the prd-validator subagent (Phase 7), passed by path — the main agent only reads it directly for its own Phase 8 write. |
| `../../../../docs/foundation/validation-skill-template.md` | Never — this is background for humans; the subagent prompt itself is self-contained |
