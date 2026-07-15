---
description: Template for discovery specification YAML file structure
---

# Discovery Specification Template

This template defines the structure of `.rhoai-qs/pipeline/discovery-spec.yaml` — the interview plan and PRD tracking document that serves as the contract between initial input analysis and PRD generation.

Discovery is the first skill in the pipeline, so this spec has no upstream dependencies. It tracks what information has been gathered, what questions remain, and whether the idea is unique in the backlog.

## File Location

```
.rhoai-qs/pipeline/discovery-spec.yaml
```

See [pipeline-convention.md](../../docs/foundation/pipeline-convention.md) for directory scoping rules.

## File Structure

```yaml
# ─── Header ───────────────────────────────────────────────
spec_version: 1
quickstart_name: "<Human-readable project name>"
slug: "<lowercase-hyphenated-identifier>"
skill: rh-qs-discovery
created_at: "<ISO 8601 timestamp>"

# ─── Inputs ──────────────────────────────────────────────
inputs:
  prior_manifests: []    # Discovery is the first skill — no upstream manifests
  user_inputs:
    - type: "<document|conversation|raw_idea>"
      source: "<Description of what the user provided>"

# ─── Interview Plan ──────────────────────────────────────
interview_plan:
  completed_sections:
    - section: "<PRD section name>"
      source: "<user_input|interview|inferred>"
      confidence: "<high|medium|low>"
      summary: "<Brief summary of what was captured>"

  remaining_questions:
    - topic: "<Interview topic>"
      question: "<Specific question to ask>"
      why_needed: "<Which PRD section this fills>"
      priority: "<high|medium|low>"

  gap_questions:
    - question: "<Gap question>"
      relevance: "<Why this applies to this idea>"

# ─── Backlog Check ───────────────────────────────────────
backlog_check:
  status: "<duplicate|similar|unique>"
  matches:
    - issue_number: <N>
      title: "<Issue title>"
      overlap_pct: <0-100>
      overlap_explanation: "<Why this overlaps>"
  decision: "<User's decision: extend|proceed|stop>"
  decision_rationale: "<Why the user chose this>"

# ─── Issue Destination ───────────────────────────────────
issue_destination:
  repo: "<Chosen destination repo>"
  issue_url: "<URL if issue was created, empty string if not yet>"

# ─── Acceptance Criteria ─────────────────────────────────
acceptance_criteria:
  - id: ac-1
    description: "PRD has a concrete problem statement with target persona"
    validation: "manual review"
    requires_user_approval: true
  - id: ac-2
    description: "At least one user flow is described step by step"
    validation: "manual review"
    requires_user_approval: true
  - id: ac-3
    description: "AI touchpoints are identified with rationale"
    validation: "manual review"
    requires_user_approval: true
  - id: ac-4
    description: "Deploy target is specified with GPU determination"
    validation: "manual review"
    requires_user_approval: true
  - id: ac-5
    description: "Scope boundaries are defined with at least one non-goal"
    validation: "manual review"
    requires_user_approval: true
  - id: ac-6
    description: "No invented requirements — all PRD content traces to user input"
    validation: "manual review"
    requires_user_approval: true

# ─── Validation Rules ────────────────────────────────────
validation_rules:
  - id: vr-1
    check: "All required PRD sections have content (use_case_summary, user_flows, data_model, ai_touchpoints, deploy_target, constraints_and_non_goals)"
    severity: blocker
  - id: vr-2
    check: "AI touchpoints section identifies at least one AI capability — if none, the quickstart should be rejected"
    severity: blocker
  - id: vr-3
    check: "Backlog check was performed and result recorded"
    severity: blocker
  - id: vr-4
    check: "Slug follows naming convention (lowercase, hyphenated, no special characters)"
    severity: blocker
  - id: vr-5
    check: "Open questions section exists (may be empty if all questions resolved)"
    severity: warning

# ─── Dependencies ────────────────────────────────────────
dependencies: []
# Discovery is the first pipeline skill — no upstream spec dependencies.
# Downstream skills (rh-qs-architect) will reference the PRD at
# data/prds/<slug>.md, not this spec file.
```

## Field Descriptions

### Header Fields

| Field | Type | Description |
|-------|------|-------------|
| `spec_version` | integer | Schema version — starts at 1, bump when fields change |
| `quickstart_name` | string | Human-readable project name |
| `slug` | string | Lowercase hyphenated identifier used for PRD filename and pipeline scoping |
| `skill` | string | Always `rh-qs-discovery` |
| `created_at` | string (ISO 8601) | Timestamp of spec generation |

### Interview Plan

The interview plan tracks the discovery process — which PRD sections have been filled and which questions remain.

| Field | Type | Description |
|-------|------|-------------|
| `completed_sections` | list | PRD sections that have been populated from user input |
| `completed_sections[].section` | string | PRD section name (e.g., `use_case_summary`, `ai_touchpoints`) |
| `completed_sections[].source` | string | How this was answered: `user_input` (from uploaded doc), `interview` (from Q&A), `inferred` (from context) |
| `completed_sections[].confidence` | string | `high`, `medium`, or `low` |
| `completed_sections[].summary` | string | Brief summary of what was captured |
| `remaining_questions` | list | Questions still to be asked |
| `remaining_questions[].topic` | string | Interview topic (Problem, User, Flow, UI, AI capability, Data, Storage, Models, Deploy, Compliance) |
| `remaining_questions[].question` | string | The specific question |
| `remaining_questions[].why_needed` | string | Which PRD section this fills |
| `remaining_questions[].priority` | string | `high` (critical gap), `medium` (important), `low` (nice to have) |
| `gap_questions` | list | Contextual gap questions relevant to this idea |

### Backlog Check

| Field | Type | Description |
|-------|------|-------------|
| `status` | string | `duplicate`, `similar`, or `unique` — from backlog-matcher subagent |
| `matches` | list | Matching issues with overlap details |
| `decision` | string | User's decision after seeing matches |
| `decision_rationale` | string | Why the user chose this path |

### Issue Destination

| Field | Type | Description |
|-------|------|-------------|
| `repo` | string | Destination repo for the issue (e.g., `rh-ai-quickstart/ai-quickstart-contrib`) |
| `issue_url` | string | GitHub issue URL if created, empty string if not yet |

### Acceptance Criteria

All discovery acceptance criteria use `requires_user_approval: true` because discovery is a user-driven conversation. The PRD is the output of a collaborative process — only the user can judge whether it accurately captures their intent.

### Validation Rules

Validation rules are checked by the main agent before presenting the PRD to the user. They catch structural issues (missing sections, no AI capability) that should be fixed before the user reviews.

## Example: Mortgage Application Processor

```yaml
spec_version: 1
quickstart_name: "Mortgage Application Processor"
slug: mortgage-application-processor
skill: rh-qs-discovery
created_at: "2026-07-15T12:00:00Z"

inputs:
  prior_manifests: []
  user_inputs:
    - type: document
      source: "Design doc uploaded by user — 3 pages covering mortgage processing with AI-assisted document review"

interview_plan:
  completed_sections:
    - section: use_case_summary
      source: user_input
      confidence: high
      summary: "AI-assisted mortgage application review — extracts data from uploaded documents, checks compliance, flags risks"
    - section: data_model
      source: user_input
      confidence: medium
      summary: "PDF mortgage applications, income verification docs, credit reports"
    - section: ai_touchpoints
      source: user_input
      confidence: high
      summary: "RAG for document understanding, classification for risk scoring"

  remaining_questions:
    - topic: UI
      question: "Does this need a reviewer dashboard UI, or is API-only acceptable?"
      why_needed: user_flows
      priority: high
    - topic: Deploy
      question: "Deploy target: OpenShift AI only, or also local dev with podman?"
      why_needed: deploy_target
      priority: high
    - topic: Compliance
      question: "Are there specific compliance requirements (HMDA, ECOA, Fair Lending)?"
      why_needed: constraints_and_non_goals
      priority: medium

  gap_questions:
    - question: "Will this need RAG?"
      relevance: "Document understanding suggests RAG — confirm with user"
    - question: "How many concurrent users?"
      relevance: "Affects model serving and API scaling decisions"

backlog_check:
  status: unique
  matches: []
  decision: proceed
  decision_rationale: "No existing mortgage or loan processing quickstarts in the backlog"

issue_destination:
  repo: rh-ai-quickstart/ai-quickstart-contrib
  issue_url: ""

acceptance_criteria:
  - id: ac-1
    description: "PRD has a concrete problem statement with target persona"
    validation: "manual review"
    requires_user_approval: true
  - id: ac-2
    description: "At least one user flow is described step by step"
    validation: "manual review"
    requires_user_approval: true
  - id: ac-3
    description: "AI touchpoints are identified with rationale"
    validation: "manual review"
    requires_user_approval: true
  - id: ac-4
    description: "Deploy target is specified with GPU determination"
    validation: "manual review"
    requires_user_approval: true
  - id: ac-5
    description: "Scope boundaries are defined with at least one non-goal"
    validation: "manual review"
    requires_user_approval: true
  - id: ac-6
    description: "No invented requirements — all PRD content traces to user input"
    validation: "manual review"
    requires_user_approval: true

validation_rules:
  - id: vr-1
    check: "All required PRD sections have content"
    severity: blocker
  - id: vr-2
    check: "AI touchpoints section identifies at least one AI capability"
    severity: blocker
  - id: vr-3
    check: "Backlog check was performed and result recorded"
    severity: blocker
  - id: vr-4
    check: "Slug follows naming convention"
    severity: blocker
  - id: vr-5
    check: "Open questions section exists"
    severity: warning

dependencies: []
```

## Usage

### For Main Agent (Phase 4)

Read this template, then generate `.rhoai-qs/pipeline/discovery-spec.yaml` based on the user's initial input and the backlog check results. The spec serves as the interview plan — it tracks which sections are covered and which questions remain.

Update the spec as the interview progresses: move items from `remaining_questions` to `completed_sections` as answers come in.

### For Validation (Phase 7)

Before presenting the PRD to the user, check each `validation_rules` entry against the current state. All `blocker` rules must pass before the PRD is shown. `warning` rules are reported to the user but don't block.

### Downstream Consumer

`rh-qs-architect` reads the PRD at `data/prds/<slug>.md`, not this spec. This spec is an internal working document for the discovery process. The PRD is the handoff artifact.
