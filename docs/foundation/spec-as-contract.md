# Spec-as-Contract Convention

This document defines the YAML spec-as-contract format used by every factory skill that modifies files. Before any skill writes code, configs, or deployment artifacts, it generates a spec describing *what* it will do, validates the spec, and only then proceeds to implementation.

## Workflow

Every skill that produces artifacts follows this flow:

```
Analyze → Generate Spec → User Approval → Validate Spec (parallel) → Refine → Implement → Post-validate
```

### Phase breakdown

| Phase | Actor | Description |
|-------|-------|-------------|
| **Analyze** | Main agent | Read inputs (PRD, prior manifests, KB files), reason about the problem |
| **Generate Spec** | Main agent | Write the spec YAML to `.rhoai-qs/<slug>/pipeline/<skill>-spec.yaml` |
| **User Approval** | User | Review the spec, approve or request changes (see [acceptance-criteria.md](acceptance-criteria.md)) |
| **Validate Spec** | Validator subagent(s) | Check spec correctness in parallel (e.g., chart versions exist, schemas are valid) |
| **Refine** | Main agent | Incorporate validation feedback, write `<skill>-spec-refined.yaml` |
| **Implement** | Implementer subagent(s) | Read the refined spec, produce artifacts exactly as specified |
| **Post-validate** | Main agent or validator subagent | Verify implementation matches the spec's acceptance criteria |

### Why this matters

- **Separates reasoning from file edits** — the agent reasons about *what* to do in the spec phase, then a focused subagent applies changes without re-reasoning.
- **Catches errors before implementation** — parallel validators check the spec for consistency, missing fields, and invalid references before any code is written.
- **Creates an audit trail** — the spec YAML in `.rhoai-qs/<slug>/pipeline/` documents every decision made during analysis.
- **Enables user control** — the user reviews and approves the plan before implementation begins.

## Spec File Location

All specs are written to the quickstart's namespaced pipeline directory, once the skill has resolved the slug via `validation-skill` (see [pipeline-convention.md](pipeline-convention.md#resolving-the-quickstart-slug)):

```
.rhoai-qs/<slug>/pipeline/<skill>-spec.yaml          # Initial spec
.rhoai-qs/<slug>/pipeline/<skill>-spec-refined.yaml   # After validation feedback
```

See [pipeline-convention.md](pipeline-convention.md) for the full scoping rules.

## Required Fields

Every spec YAML must include these top-level sections:

```yaml
# ─── Header ───────────────────────────────────────────────
spec_version: 1                  # Schema version — bump when fields change
quickstart_name: "Spending Transaction Monitor"
slug: spending-transaction-monitor
skill: rh-qs-architect          # Which skill generated this spec
created_at: "2026-07-01T12:00:00Z"

# ─── Inputs ──────────────────────────────────────────────
inputs:
  prior_manifests:              # Pipeline files from previous skills
    - path: .rhoai-qs/spending-transaction-monitor/pipeline/scaffold-manifest.yaml
      skill: rh-qs-scaffold
  user_inputs: []               # Any direct user-provided data

# ─── Plan ─────────────────────────────────────────────────
components:                     # Skill-specific: what this skill will do
  <component-name>:
    # ... skill-specific fields (see below)

# ─── Acceptance Criteria ──────────────────────────────────
acceptance_criteria:
  - id: ac-1
    description: "Human-readable description of what done looks like"
    validation: "How to verify (command, check, or manual review)"
    requires_user_approval: true|false

# ─── Validation Rules ────────────────────────────────────
validation_rules:
  - id: vr-1
    check: "What the validator subagent checks"
    severity: blocker|warning    # blocker = must fix, warning = inform user

# ─── Dependencies ─────────────────────────────────────────
dependencies:
  - spec: architecture-spec.yaml
    fields_used: [components, deployment_mode]
    content_hash: "sha256:..."   # Hash of upstream spec when this was generated
```

### Field descriptions

**Header fields:**

| Field | Type | Description |
|-------|------|-------------|
| `spec_version` | integer | Schema version of this spec format. Starts at 1, bumped when fields are added/changed. Consuming skills check this and fail loudly if they encounter an unsupported version. |
| `quickstart_name` | string | Human-readable project name |
| `slug` | string | Lowercase hyphenated identifier, used for repo naming and pipeline scoping |
| `skill` | string | The skill that generated this spec (e.g., `rh-qs-architect`) |
| `created_at` | string (ISO 8601) | Timestamp of spec generation |

**Inputs:**

| Field | Type | Description |
|-------|------|-------------|
| `inputs.prior_manifests` | list | Pipeline files from previous stages, with path and producing skill |
| `inputs.user_inputs` | list | Any data the user provided directly (documents, decisions, constraints) |

**Components:**

The `components` section is skill-specific. Each skill's `spec-template.md` defines what fields appear here. The structure follows the pattern established in the blueprint kit's `spec-template.md`:

```yaml
components:
  <component-name>:
    type: <skill-specific type>

    approach:
      strategy: "What this skill will do for this component"
      rationale: "Why this approach was chosen"

    implementation:
      files_to_modify:
        - path: relative/path/to/file
          changes: ["Description of each change"]
      files_to_create:
        - path: relative/path/to/new-file
          content_description: "What this file contains"
      configuration:
        # Skill-specific config (chart versions, image tags, etc.)

    kb_sources:
      - "<path to knowledge-base file that informed this component's approach>"

    dependencies:
      - component: other-component
        reason: "Why this dependency exists"
```

**Acceptance Criteria:**

See [acceptance-criteria.md](acceptance-criteria.md) for the full convention. In the spec, each criterion has:

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique identifier (e.g., `ac-1`) |
| `description` | string | What "done" looks like for this criterion |
| `validation` | string | How to verify (command to run, file to check, or "manual review") |
| `requires_user_approval` | boolean | Whether the user must explicitly approve this criterion |

**Validation Rules:**

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique identifier (e.g., `vr-1`) |
| `check` | string | What the validator subagent verifies |
| `severity` | enum | `blocker` (must fix before implementation) or `warning` (inform user, proceed) |

**Dependencies:**

| Field | Type | Description |
|-------|------|-------------|
| `spec` | string | Filename of the upstream spec or manifest this spec depends on |
| `fields_used` | list of strings | Which fields from that spec are referenced |
| `content_hash` | string | SHA-256 hash of the upstream spec at the time this spec was generated. Used for staleness detection — if the upstream spec changes, downstream skills can detect the mismatch and warn the user. |

## Validation Flow

After the spec is generated, one or more validator subagents check it in parallel:

```
┌──────────────────────────────────────────────────────────┐
│  Main agent writes .rhoai-qs/<slug>/pipeline/<skill>-spec.yaml│
│                                                          │
│  Spawn validator subagents in parallel:                  │
│  ┌─────────────────┐  ┌─────────────────┐               │
│  │ Validator A      │  │ Validator B      │              │
│  │ (e.g., chart     │  │ (e.g., schema    │              │
│  │  version check)  │  │  consistency)    │              │
│  └────────┬────────┘  └────────┬────────┘               │
│           │                    │                         │
│           ▼                    ▼                         │
│  Main agent reads validation results                     │
│                                                          │
│  If blockers found:                                      │
│    → Fix the spec (not the code — spec hasn't been       │
│      implemented yet)                                    │
│    → Write <skill>-spec-refined.yaml                     │
│    → Re-validate (max 2 iterations)                      │
│                                                          │
│  If still blocked after max iterations:                  │
│    → Document remaining blockers                         │
│    → Ask user: proceed, provide guidance, or stop        │
│                                                          │
│  If no blockers:                                         │
│    → Hand refined spec to implementer subagent           │
└──────────────────────────────────────────────────────────┘
```

Validators return a per-component status:

```yaml
validation_results:
  <component-name>:
    status: READY | BLOCKED | PARTIAL
    blockers:
      - rule_id: vr-1
        message: "Chart bitnami/redis:99.0.0 not found on ArtifactHub"
        suggestion: "Use bitnami/redis:19.0.2 (latest stable)"
    warnings:
      - rule_id: vr-3
        message: "GPU resource limit not set — defaults may apply"
```

## Refinement

When validators find blockers, the main agent:

1. Reads validation results
2. Fixes the spec (not code — nothing has been implemented yet)
3. Writes `.rhoai-qs/<slug>/pipeline/<skill>-spec-refined.yaml`
4. Re-runs validators on the refined spec
5. Max 2 refinement iterations per skill (configurable in `spec-template.md`)

The refined spec replaces the original as the contract for implementation.

## Staleness Detection

When a skill starts, it checks whether its upstream dependencies have changed since its own spec or manifest was generated:

1. Read each entry in `dependencies`
2. Hash the current content of the upstream file
3. Compare to the recorded `content_hash`
4. If they differ: warn the user that upstream has changed and offer to re-run the current skill with the updated input, or proceed with stale data

This prevents silent inconsistencies when a user re-runs an upstream skill (e.g., re-running `rh-qs-architect` to change the component list) without re-running downstream skills.

## Post-Implementation Validation

After the implementer subagent produces artifacts, the main agent (or a post-validator subagent) checks each acceptance criterion:

```yaml
post_validation:
  - criterion_id: ac-1
    status: pass | fail
    evidence: "helm search repo bitnami/redis returned 19.0.2"
  - criterion_id: ac-2
    status: fail
    evidence: "make test exited with code 1: 2 failures in test_endpoints.py"
```

If any criterion fails, the skill enters its feedback loop (see ADR-001 Pattern 3):

1. Analyze the failure
2. Route to the relevant subagent to fix
3. Re-validate
4. Max N iterations (skill-specific, typically 3)
5. If still failing: document failures, ask user

## Complete Example: architecture-spec.yaml

This example shows a fully populated spec for the Architect skill (`rh-qs-architect`), converting a PRD into a component bill of materials.

```yaml
spec_version: 1
quickstart_name: "Spending Transaction Monitor"
slug: spending-transaction-monitor
skill: rh-qs-architect
created_at: "2026-07-01T12:00:00Z"

inputs:
  prior_manifests:
    - path: .rhoai-qs/spending-transaction-monitor/prds/prd.md
      skill: rh-qs-discovery
  user_inputs:
    - type: constraint
      value: "Must run on 2x A100 GPUs or less"

components:
  llm-service:
    type: inference
    approach:
      strategy: "Deploy Llama 3.3 70B via vLLM on ai-architecture-charts/llm-service"
      rationale: "PRD requires conversational AI; 70B model fits within 2x A100 VRAM budget"
    implementation:
      files_to_create:
        - path: deploy/helm/values-llm.yaml
          content_description: "vLLM serving config with model ID and GPU allocation"
      configuration:
        helm_chart: ai-architecture-charts/llm-service:0.3.0
        model_id: meta-llama/Llama-3.3-70B-Instruct
        gpu_count: 2
        gpu_type: nvidia.com/gpu
    kb_sources:
      - core/knowledge-base/components/vllm-serving-patterns.md
    dependencies: []

  vector-db:
    type: database
    approach:
      strategy: "Deploy pgvector via ai-architecture-charts/pgvector for RAG retrieval"
      rationale: "PRD requires semantic search over transaction descriptions"
    implementation:
      files_to_create:
        - path: deploy/helm/values-pgvector.yaml
          content_description: "pgvector config with storage and connection settings"
      configuration:
        helm_chart: ai-architecture-charts/pgvector:0.2.1
        storage: 20Gi
    kb_sources:
      - core/knowledge-base/components/pgvector-patterns.md
    dependencies: []

  api-server:
    type: backend
    approach:
      strategy: "FastAPI backend connecting LLM service and pgvector"
      rationale: "Standard quickstart backend pattern"
    implementation:
      files_to_create:
        - path: packages/api/src/main.py
          content_description: "FastAPI application with RAG endpoints"
      configuration:
        framework: fastapi
        python_version: "3.12"
    kb_sources:
      - core/knowledge-base/components/fastapi-patterns.md
    dependencies:
      - component: llm-service
        reason: "API calls LLM for inference"
      - component: vector-db
        reason: "API queries pgvector for context retrieval"

  frontend:
    type: ui
    approach:
      strategy: "React chat interface for transaction queries"
      rationale: "PRD specifies conversational UI"
    implementation:
      files_to_create:
        - path: packages/ui/src/App.tsx
          content_description: "Chat UI component"
      configuration:
        framework: react
        node_version: "22"
    kb_sources:
      - core/knowledge-base/components/react-frontend-patterns.md
    dependencies:
      - component: api-server
        reason: "UI calls API endpoints"

deployment_mode: helm
architecture_diagram: |
  graph TB
    User --> Frontend
    Frontend --> APIServer
    APIServer --> LLMService
    APIServer --> VectorDB

acceptance_criteria:
  - id: ac-1
    description: "All Helm charts exist in ai-architecture-charts or public registries"
    validation: "helm search repo <chart> returns results for each chart"
    requires_user_approval: false
  - id: ac-2
    description: "Total GPU requirement does not exceed 2x A100"
    validation: "Sum of gpu_count across components <= 2"
    requires_user_approval: true
  - id: ac-3
    description: "Architecture supports both Helm and docker-compose deployment"
    validation: "Review component list — all have compose-compatible alternatives"
    requires_user_approval: true
  - id: ac-4
    description: "Component bill of materials matches PRD requirements"
    validation: "Manual review: each PRD feature maps to at least one component"
    requires_user_approval: true

validation_rules:
  - id: vr-1
    check: "All helm_chart references resolve to real charts with valid versions"
    severity: blocker
  - id: vr-2
    check: "No circular dependencies in components"
    severity: blocker
  - id: vr-3
    check: "GPU allocation is specified for inference components"
    severity: warning
  - id: vr-4
    check: "All model IDs are valid HuggingFace or registry references"
    severity: blocker

dependencies:
  - spec: .rhoai-qs/spending-transaction-monitor/prds/prd.md
    fields_used: [problem_statement, target_persona, technology_constraints, success_metrics]
    content_hash: "sha256:e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
```

## Per-Skill Spec Fields

Each skill's `spec-template.md` extends the common fields above with skill-specific sections. The table below shows what the `components` section looks like per skill:

| Skill | Spec File | Key Component Fields |
|-------|-----------|---------------------|
| rh-qs-discovery | `discovery-spec.yaml` | Interview plan, PRD section targets |
| rh-qs-architect | `architecture-spec.yaml` | Charts, deployment mode, GPU allocation, architecture diagram |
| rh-qs-scaffold | `scaffold-spec.yaml` | Repo name, packages, CI jobs, linting config |
| rh-qs-implement | `implementation-spec.yaml` | Endpoints, schemas, services, DB models, UI routes |
| rh-qs-deploy | `deploy-spec.yaml` | Chart dependencies, values overrides, compose services, Containerfile specs |
| rh-qs-security | `security-spec.yaml` | Scan targets, severity thresholds, compliance context |
| rh-qs-update | `update-spec.yaml` | Change type, affected files, re-entry stage |

## Relationship to Other Foundation Docs

- **[skill-directory-structure.md](skill-directory-structure.md)** — each skill's `spec-template.md` file defines the skill-specific fields
- **[acceptance-criteria.md](acceptance-criteria.md)** — details when user approval is required and how criteria are validated
- **[pipeline-convention.md](pipeline-convention.md)** — defines the `.rhoai-qs/<slug>/pipeline/` directory where specs and manifests are written
- **[validation-skill-template.md](validation-skill-template.md)** — how the slug is resolved before any spec is written
- **[pipeline-contracts.md](pipeline-contracts.md)** — defines the output manifests that consuming skills expect (downstream of specs)
