# User-Approved Acceptance Criteria

This document defines how specs include acceptance criteria, when the user must approve them, and how they are validated after implementation. Acceptance criteria are the contract between the agent and the user — they define what "done" looks like for each pipeline stage.

## What Acceptance Criteria Are

Every spec includes an `acceptance_criteria` section (see [spec-as-contract.md](spec-as-contract.md)). Each criterion is a single, verifiable statement about the output:

```yaml
acceptance_criteria:
  - id: ac-1
    description: "All Helm charts exist in ai-architecture-charts or public registries"
    validation: "helm search repo <chart> returns results for each chart"
    requires_user_approval: false
  - id: ac-2
    description: "Total GPU requirement does not exceed 2x A100"
    validation: "Sum of gpu_count across components <= 2"
    requires_user_approval: true
```

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `id` | string | Unique identifier within the spec (e.g., `ac-1`) |
| `description` | string | What "done" looks like — written so a human can judge pass/fail |
| `validation` | string | How to verify: a command to run, a file to check, or `"manual review"` |
| `requires_user_approval` | boolean | Whether the user must explicitly approve this criterion before implementation begins |

## When User Approval Is Required

Not every criterion needs the user to sign off. The rule:

- **`requires_user_approval: true`** — The criterion involves a judgment call, a tradeoff, or a decision the agent cannot make alone. The user must review and approve before the skill proceeds to implementation.
- **`requires_user_approval: false`** — The criterion is objectively verifiable by automation (a command passes, a file exists, a value is within range). The agent validates it without asking.

### Approval matrix by skill

| Skill | Criteria that require user approval | Criteria that don't |
|-------|-------------------------------------|---------------------|
| rh-qs-discovery | All — the PRD is a user-driven conversation | None |
| rh-qs-architect | Component choices, GPU budget, deployment mode | Chart existence, circular dependency checks |
| rh-qs-scaffold | None (scaffold is deterministic from the architecture spec) | File creation, CI job presence, linting config |
| rh-qs-implement | None (implementation follows the spec) | Tests pass, endpoints exist, no placeholder strings |
| rh-qs-deploy | None (deployment follows architecture + implementation) | Helm lint, helm template, Containerfile builds |
| rh-qs-security | Whether to accept `HIGH` findings and proceed | `CRITICAL` findings (always block), scanner execution |
| rh-qs-debug-and-deploy | Non-OpenShift source code changes during debug | Config/infra fixes, health scans |
| rh-qs-document | All — documentation quality is subjective | Make targets exist, URLs well-formed, diagram matches |
| rh-qs-ship | PR description review | CI passes |

### The two user-driven skills

Two skills have **uncapped refinement** — the user can refine as many times as they want:

1. **rh-qs-discovery** — The PRD is a collaborative conversation. The agent drafts, the user refines, there is no iteration limit.
2. **rh-qs-document** — Documentation quality is subjective. The agent generates, the user reviews, refinement continues until the user approves.

All other skills have bounded iteration (typically max 3 attempts), after which the agent documents failures and asks the user how to proceed.

## Approval Flow

When a spec contains criteria with `requires_user_approval: true`, the skill follows this flow:

```
1. Agent generates the spec with acceptance criteria
2. Agent presents the spec to the user
3. For each criterion with requires_user_approval: true:
   → User reviews and either:
     a. Approves — agent proceeds
     b. Requests changes — agent updates the spec and re-presents
     c. Rejects — agent stops and asks for guidance
4. Once all user-approved criteria are accepted:
   → Proceed to validation (parallel subagents)
   → Then implementation
```

The user approval step happens **before** validation and implementation — it gates the entire downstream pipeline. The agent never implements a spec the user hasn't approved.

## Post-Implementation Validation

After the implementer subagent produces artifacts, the main agent checks every criterion — both user-approved and automated:

```yaml
post_validation:
  - criterion_id: ac-1
    status: pass | fail
    evidence: "helm search repo bitnami/redis returned 19.0.2"
  - criterion_id: ac-2
    status: pass
    evidence: "Total GPU: 2 (llm-service: 2, all others: 0) — within 2x A100 budget"
  - criterion_id: ac-3
    status: fail
    evidence: "make test exited with code 1: 2 failures in test_endpoints.py"
```

### Fields

| Field | Type | Description |
|-------|------|-------------|
| `criterion_id` | string | References an `id` from the spec's `acceptance_criteria` |
| `status` | enum | `pass` or `fail` |
| `evidence` | string | Concrete proof — command output, file content, or observation |

### What happens on failure

When a criterion fails post-implementation, the skill enters its feedback loop (ADR-001 Pattern 3):

```
1. Analyze the failure evidence
2. Route to the relevant subagent to fix
   (e.g., backend-implementer for API failures,
    containerfile-generator for build failures)
3. Re-run the failing criterion's validation
4. Max N iterations (skill-specific, typically 3)
5. If still failing after max:
   → Document remaining failures
   → Ask user: proceed anyway, provide guidance, or stop
```

The agent never silently skips a failing criterion. Every failure is either fixed, or explicitly acknowledged by the user.

## Mid-Execution Approval

User approval doesn't only happen at the spec level. During debug and fix loops, the agent may need to make changes that weren't anticipated in the original spec. The rule is based on the **fix boundary** — what the agent can auto-apply vs what requires the user's permission.

### Fix boundary

| Fix type | Auto-apply? | Example |
|----------|-------------|---------|
| Config/infra changes | Yes | Ports, service names, storage classes, security contexts, resource limits, env vars, image tags, probes, volume mounts, init containers, PVC sizes, route configs |
| OpenShift-specific source changes | Yes | Code inside `if openshift_mode` blocks, OCP config files, deployment scripts |
| Non-OpenShift source code changes | **Ask user** | Application logic, business logic, data flow, API endpoints |

### How it works

When a skill's debug loop proposes a fix that changes application source code:

```
1. Skill identifies the fix: "Resource api-server has CrashLoopBackOff.
   Fix requires changing packages/api/src/main.py: add retry logic for
   database connection."

2. This modifies application source code, not just config/infra.

3. Agent asks the user:
   "Resource api-server has issue CrashLoopBackOff. Fix requires changing
    packages/api/src/main.py: add retry logic for DB connection. This
    modifies application source code. Approve?"

4. User approves or provides alternative guidance.

5. Fix is applied and recorded with user_approval_required: true
```

### Recording mid-execution approval

Each fix attempt records whether user approval was needed:

```yaml
fix_attempt:
  fix_category: config | source-code
  user_approval_required: true | false
  result: success | failed | partial
```

- `fix_category: config` → auto-applied, `user_approval_required: false`
- `fix_category: source-code` → depends on whether it's OpenShift-specific
  - OpenShift-specific → auto-applied, `user_approval_required: false`
  - Non-OpenShift → `user_approval_required: true`, agent asked the user

This pattern is used primarily by `rh-qs-debug-and-deploy` during its debug loop, but any skill with a fix loop should follow the same boundary.

## Validation Rules vs Acceptance Criteria

Specs contain both `acceptance_criteria` and `validation_rules`. They serve different purposes:

| Aspect | Acceptance Criteria | Validation Rules |
|--------|-------------------|-----------------|
| **When checked** | Post-implementation | Pre-implementation (on the spec itself) |
| **What they check** | Did the implementation meet the plan? | Is the plan internally consistent? |
| **Who defines them** | The producing skill, reviewed by the user | The producing skill |
| **User involvement** | Some require user approval | None — automated checks only |
| **Failure action** | Feedback loop (fix code, re-validate) | Fix the spec, re-validate (max 2 iterations) |
| **Severity** | All are blockers (must pass or user must accept) | `blocker` or `warning` |

**Example:**

A validation rule checks that `helm_chart: ai-architecture-charts/llm-service:0.3.0` resolves to a real chart (pre-implementation, on the spec). An acceptance criterion checks that `helm install` actually succeeds with that chart (post-implementation, on the deployed artifacts).

## Writing Good Criteria

### Do

- Make each criterion independently verifiable — it should be possible to check one criterion without checking others
- Include the validation method — a command, file check, or "manual review"
- Be specific about thresholds — "GPU count <= 2", not "GPU usage is reasonable"
- Use `requires_user_approval: true` only for genuine judgment calls

### Don't

- Don't create criteria that overlap — each aspect should be checked by exactly one criterion
- Don't use vague descriptions — "code quality is good" is not verifiable
- Don't mark everything as `requires_user_approval: true` — this slows the pipeline unnecessarily
- Don't create criteria that can only be validated after deployment if the skill runs before deployment

## Complete Example: rh-qs-implement Acceptance Criteria

```yaml
acceptance_criteria:
  - id: ac-1
    description: "All API endpoints from the implementation spec are implemented and respond"
    validation: "make test-api passes with 0 failures"
    requires_user_approval: false
  - id: ac-2
    description: "All database models from the implementation spec exist with correct fields"
    validation: "Alembic migration generates without errors, model fields match spec"
    requires_user_approval: false
  - id: ac-3
    description: "Frontend routes from the implementation spec are implemented"
    validation: "make test-ui passes with 0 failures"
    requires_user_approval: false
  - id: ac-4
    description: "No placeholder strings remain in generated code"
    validation: "grep -r 'TODO\\|FIXME\\|PLACEHOLDER\\|CHANGEME' packages/ returns 0 results"
    requires_user_approval: false
  - id: ac-5
    description: "Environment variables are read from config, not hardcoded"
    validation: "grep -r 'hardcoded\\|localhost:' packages/api/src/ returns 0 results (excluding test files)"
    requires_user_approval: false
```

Note: all criteria for `rh-qs-implement` are `requires_user_approval: false` because they are objectively verifiable. The user already approved the architecture and the implementation spec — the implement skill just executes the plan.

## Relationship to Other Foundation Docs

- **[spec-as-contract.md](spec-as-contract.md)** — defines the `acceptance_criteria` and `validation_rules` fields within the spec format, and the post-implementation validation flow
- **[pipeline-convention.md](pipeline-convention.md)** — specs containing acceptance criteria live in `.rhoai-qs/<slug>/pipeline/`
- **[pipeline-contracts.md](pipeline-contracts.md)** — handoff manifests may reference acceptance criteria results from upstream skills
- **[reasoning-guardrails-template.md](reasoning-guardrails-template.md)** — guardrails are concern areas the agent reasons about organically; acceptance criteria are concrete, verifiable pass/fail checks
