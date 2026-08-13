---
name: rh-qs-discovery
description: >-
  Ideation and interview phase for new AI Quickstarts. Orchestrates PRD
  structuring and backlog matching subagents to produce a validated PRD.
  Supports structured interviews, uploaded documents, and gap analysis.
argument-hint: "Start a new quickstart idea, upload documents, or analyze coverage gaps"
allowed-tools: Bash, Read, Write, Edit, Agent
---

# rh-qs-discovery

**Category:** `inception/`

## Goal

Produce a validated Product Requirements Document (PRD) at `.rhoai-qs/<slug>/prds/prd.md` that is ready for handoff to `rh-qs-architect`. The PRD captures the user's quickstart idea with enough detail for architectural design without pre-deciding implementation choices.

## Input

- User says **"hello"** (guided from scratch)
- **"I want to build X"** (idea-driven)
- User uploads or pastes a document with ideas (design doc, meeting notes, issue text)
- **"Identify gaps"** / **"Coverage analysis"** (gap analysis mode — see below)
- **"Continue <quickstart>"** / **"Refine the <quickstart> PRD"** (resuming an existing idea)

## Supporting Documents

**Main agent reads directly:**

| File | When |
|------|------|
| [reasoning-guardrails.md](./reasoning-guardrails.md) | Phases 1-6 — organic awareness while drafting (the formal Phase 7 check is delegated to the prd-validator subagent) |
| [spec-template.md](./spec-template.md) | Phase 4 — generating the discovery spec |
| [output-templates.md](./output-templates.md) | Phase 8 — writing the final PRD (also passed by path to the prd-structurer subagent in Phase 5 and the prd-validator subagent in Phase 7) |
| [references/gap-analysis-template.md](./references/gap-analysis-template.md) | Gap analysis mode only |

**Subagents read (pass by file path only — do NOT read these):**

| File | Subagent |
|------|----------|
| [subagents/validation-skill-prompt.md](./subagents/validation-skill-prompt.md) | Quickstart slug resolution |
| [subagents/prd-structurer-prompt.md](./subagents/prd-structurer-prompt.md) | PRD structurer |
| [subagents/backlog-matcher-prompt.md](./subagents/backlog-matcher-prompt.md) | Backlog matcher |
| [subagents/prd-griller-prompt.md](./subagents/prd-griller-prompt.md) | PRD griller |
| [subagents/prd-validator-prompt.md](./subagents/prd-validator-prompt.md) | PRD validator |

## Workflow

### Phase 0: Resolve Quickstart Context

`rh-qs-discovery` is the pipeline's entry point, so this phase behaves differently depending on whether this is a **brand-new idea** or the user is **continuing/refining an existing one**:

- **Brand-new idea** ("I want to build X", uploading a fresh document, saying "hello" to start from scratch): skip this phase entirely — there is no slug yet. It gets created in Phase 4 once the idea has a name.
- **Continuing an existing idea** ("continue mortgage-processor", "refine the fraud-detector PRD", or an ambiguous "continue where we left off"): spawn the **validation-skill subagent** to resolve which quickstart this session is about:

```python
Agent(
    description="Resolve which quickstart this discovery session continues",
    prompt=f"""
Read and follow instructions from:
core/skills/rh-qs-discovery/subagents/validation-skill-prompt.md

User message: {user_message}
Existing slugs: {existing_slugs}
Is entry point: true
Calling skill: rh-qs-discovery
"""
)
```

Where `existing_slugs` comes from `ls .rhoai-qs/ 2>/dev/null` (excluding `reports` and `blog-drafts`), run by the main agent — never by the subagent.

Handle the result per [validation-skill-template.md](../../../docs/foundation/validation-skill-template.md#main-agent-handling). If `resolution: new_quickstart`, treat this as a brand-new idea and proceed to Phase 1 normally.

### Phase 1: Initial Input

Accept the user's input and determine the input type:
- **`document`**: User uploaded or pasted structured content (design doc, RFC, meeting notes)
- **`conversation`**: User is describing an idea interactively
- **`raw_idea`**: User gave a brief description (1-3 sentences)

Extract initial keywords for the backlog check: technologies mentioned, industry/domain, AI capabilities, use case pattern.

### Phase 2: Backlog Check

Check if this idea already exists in the backlog:

```bash
python3 core/skills/gh-backlog-reader/scripts/read_backlog.py --search "<keywords>"
```

Spawn the **backlog-matcher subagent** to compare the idea against the backlog:

```python
Agent(
    description="Check backlog for duplicate quickstart ideas",
    prompt=f"""
Read and follow instructions from:
core/skills/rh-qs-discovery/subagents/backlog-matcher-prompt.md

Idea summary: {idea_summary}
Idea keywords: {keywords}
Backlog data: {backlog_output}
"""
)
```

Based on the match report:
- **`duplicate`**: Present the matching issue to the user. Ask: continue anyway, or work on the existing issue?
- **`similar`**: Present matches and ask: extend the existing issue, or create a distinct PRD?
- **`unique`**: Proceed to Phase 3.

Record the user's decision in the discovery spec.

### Phase 3: Issue Destination

**Ask the user** where to store feature requests and backlog items before creating issues:

| Destination | Repo / tool | Use when |
|-------------|-------------|----------|
| **Quickstart backlog** (default) | `rh-ai-quickstart/ai-quickstart-contrib` | Standard quickstart suggestions — use **`gh-issue-creator`** |
| **RFE (Request for Enhancement)** | [opendatahub-io/rfe-creator](https://github.com/opendatahub-io/rfe-creator) | Platform or OpenShift AI product feedback; partners may lack access — confirm first |
| **Strategy / roadmap** | [opendatahub-io/strat-creator](https://github.com/opendatahub-io/strat-creator) | Strategic themes, not a single quickstart implementation |

Record the chosen destination. The issue URL will be added to the PRD header when an issue is created.

### Phase 4: Generate Discovery Spec

For a brand-new idea, mint the slug now: lowercase, hyphenated, derived from the quickstart's working title (e.g., `mortgage-application-processor`). This is the slug every subsequent phase — and every downstream skill — will use to namespace files under `.rhoai-qs/<slug>/`.

Read [spec-template.md](./spec-template.md). Based on the input type, initial analysis, and backlog check results, generate `.rhoai-qs/<slug>/pipeline/discovery-spec.yaml` with:
- Completed sections (what we already know from the user's input)
- Remaining interview questions (what we still need to ask)
- Gap questions relevant to this idea
- Backlog check results and user decision

Present the spec to the user for approval before proceeding to the interview.

### Phase 5: Structured Interview / PRD Structuring

**If the user uploaded documents:** Spawn the **prd-structurer subagent** to extract structured PRD sections:

```python
Agent(
    description="Structure uploaded document into PRD sections",
    prompt=f"""
Read and follow instructions from:
core/skills/rh-qs-discovery/subagents/prd-structurer-prompt.md

Raw input: {document_content}
Input type: document
Output template path: core/skills/rh-qs-discovery/output-templates.md
"""
)
```

Review the subagent's output. For sections with `medium` or `low` confidence, ask follow-up questions from the interview table below.

**If conversational:** Run the structured interview. Ask until every PRD section can be filled:

| Topic | Question |
|-------|----------|
| Problem | What problem does this quickstart solve? (one sentence) |
| User | Who is the target user? (developer, data scientist, business analyst) |
| Flow | What's the primary user flow? (upload → process → display?) |
| UI | Does it need a UI or is API-only acceptable? |
| AI capability | What AI capability is central? (text generation, RAG, agents, classification, vision). **This must be true — if there is no AI capability, the quickstart should be rejected.** |
| Data | What data does it work with? (documents, transactions, images, real-time streams) |
| Storage | Does it need persistent storage? What kind? |
| Models | Any specific model requirements? (size constraints, safety, multilingual) |
| Deploy | Deploy target: OpenShift AI only, or also local dev with podman? |
| Compliance | Any compliance/security considerations? |

**Gap questions (not an exhaustive list — ask whichever apply, and anything else that feels unclear):**

- Real-time inference or batch processing?
- How many concurrent users or expected scale?
- Any other technical or business constraint the user hasn't mentioned yet?

Update the discovery spec as answers come in: move items from `remaining_questions` to `completed_sections`.

### Phase 6: Requirement Mapping

Map vague ideas to concrete requirements using known patterns:

| Vague idea | Concrete requirement |
|------------|---------------------|
| Chat with documents | RAG + pgvector + ingestion pipeline |
| Agent with tools | Llama Stack + optional MCP servers |
| PDF upload and processing | MinIO + extraction service |
| On-cluster LLM | llm-service chart + GPU |

Record these mappings in the PRD but do not pre-decide the architecture — the mapping provides context for `rh-qs-architect`, not binding decisions.

### Phase 6.5: PRD Grilling (Stress-Test)

An enhancement, not a gate — this phase deepens the draft before the validator checks it's structurally sound. If the user wants to skip grilling, honor that and go straight to Phase 7.

**Conditional gate — only run on medium/high coverage.** If the prd-structurer subagent ran in Phase 5, reuse its `overall_coverage` field. Otherwise (conversational interview), assess coverage yourself using the same bucketing convention as [output-templates.md](./output-templates.md)'s "PRD Section Requirements" table: `high` if 5+ of the 6 required sections have substantive content, `medium` for 3-4, `low` for 0-2. Skip this phase entirely on `low` coverage — there isn't enough draft to grill yet — and proceed directly to Phase 7.

Spawn the **prd-griller subagent** once — a single invocation returns the full question set and its dependency graph, so there is no need to re-spawn it between rounds:

```python
Agent(
    description="Stress-test PRD draft with dependency-ordered questions",
    prompt=f"""
Read and follow instructions from:
core/skills/rh-qs-discovery/subagents/prd-griller-prompt.md

Draft PRD: {prd_draft}
Backlog check result: {backlog_check_result}
Requirement mapping: {requirement_mapping}
Guardrails path: core/skills/rh-qs-discovery/reasoning-guardrails.md
"""
)
```

Work the returned question graph in **rounds**:

1. If `answered_by_cross_reference` is non-empty, show those to the user as FYI — they're already resolved by another section of the draft, no question needed.
2. Compute the initial **frontier**: every question with `depends_on: null`, sorted by `impact` (`high` first). Present the whole frontier as one round, one entry per question:

   ```
   ❓ **Q1** - **<title>**: <question>

   ➡️ <recommended_answer>
   ```

3. Collect the user's answers for the round — they may accept the recommended answer, give a different one, or skip a question.
4. Fold the answers into the draft PRD.
5. Recompute the frontier: any question whose `depends_on` was just answered is now unblocked. Present the next round using the same format.
6. Repeat until no questions remain.

No re-invocation of the subagent between rounds — the full dependency graph came back in step 1's spawn.

### Phase 7: PRD Validation and Refinement

The main agent does not self-validate the draft it just wrote — it has been drafting alongside the user and is anchored to its own choices. Instead, spawn the **prd-validator subagent** for an independent, clean-context review:

```python
Agent(
    description="Review PRD draft for completeness and guardrail adherence",
    prompt=f"""
Read and follow instructions from:
core/skills/rh-qs-discovery/subagents/prd-validator-prompt.md

PRD draft: {prd_draft}
Validation rules: {validation_rules}
Guardrails path: core/skills/rh-qs-discovery/reasoning-guardrails.md
Output template path: core/skills/rh-qs-discovery/output-templates.md
"""
)
```

**The subagent only recommends — it never edits the PRD.** Review its findings using your own broader context of the actual conversation with the user; the subagent doesn't have that context, so some of its flags may not apply. Use judgment about which findings to act on.

If any `blocker`-severity finding remains after your review, fix the PRD before presenting it to the user.

Present the draft PRD to the user. **Uncapped refinement** — the user can refine as many times as they want. This is a collaborative, user-driven conversation with no iteration limit.

For each refinement round:
1. Present the current PRD draft
2. User provides feedback (changes, additions, corrections)
3. Update the PRD
4. Re-spawn the prd-validator subagent for a fresh, unbiased pass on the updated draft
5. Present again — repeat until the user approves

### Phase 8: Write PRD

Read [output-templates.md](./output-templates.md). Write the final PRD to `.rhoai-qs/<slug>/prds/prd.md` using the template format. Include the PRD header with:
- Issue destination and URL (if created)
- Slug
- Date

Slug convention: lowercase, hyphenated (e.g., `mortgage-application-processor`).

Confirm with the user before handing off to `rh-qs-architect`.

## Gap Analysis Mode

When the user asks to identify gaps (absorbs rh-qs-quickstart-identifier), **skip Phase 0** — this mode surveys the whole backlog and doesn't apply to one specific quickstart:

1. Fetch the backlog:
   ```bash
   python3 core/skills/gh-backlog-reader/scripts/read_backlog.py --summary
   python3 core/skills/gh-backlog-reader/scripts/read_backlog.py --detail
   ```
2. Read [references/industry-trends.md](./references/industry-trends.md) (if available)
3. Compare coverage by industry, technology, and use case
4. Propose 3-5 new quickstart ideas with rationale
5. Save report to `.rhoai-qs/reports/gap-analysis-<date>.md` using the template from [references/gap-analysis-template.md](./references/gap-analysis-template.md)

If the user wants to pursue one of the proposed ideas, transition into the standard discovery flow (Phase 1 onward, as a brand-new idea) with the gap analysis context as initial input.

## Guidelines

**DO:**
- Preserve the user's language — use their words in the PRD, not your rephrasing
- Flag ambiguities as open questions rather than resolving them yourself
- Use the validation-skill subagent when continuing an existing idea — never guess the slug
- Use the backlog-matcher subagent before starting the interview
- Spawn the prd-griller subagent once in Phase 6.5 when coverage allows, then work its question graph in dependency-ordered rounds yourself — no re-spawning between rounds
- Use the prd-validator subagent for every Phase 7 review pass — never self-grade the draft you just wrote
- Update the discovery spec as the interview progresses
- Let the user refine the PRD as many times as they want

**DON'T:**
- Read subagent prompt files directly — pass them by file path to the Agent tool
- Invent requirements the user didn't state
- Pre-decide the technology stack — that's `rh-qs-architect`'s job
- Assume GPU is needed without evidence
- Skip the backlog check
- Resolve open questions without asking the user
- Treat the prd-griller's or prd-validator's recommendations as decided — both are suggestions; the user (griller) or you with full context (validator) still decide
- Force the prd-griller step when PRD coverage is too low to grill, or when the user wants to skip it

## Next Skill

When PRD is approved → **`rh-qs-architect`**
