# ADR-001: Upgrade Factory Skills Into Production Ready

```
Status: Proposed
Date: 2026-06-24
Authors: Matan Talvi, Yossi Elias
```

## Context

The Quickstart Factory currently operates a 7-stage pipeline with 10 skills (7 pipeline + 3 utility). Each skill is a flat `SKILL.md` that the agent reads and follows directly — no subagent orchestration, no feedback loops, no validation beyond `make lint && make test`, no hooks, and no knowledge base.

The [rhoai-blueprint-skill-kit](https://github.com/rh-ai-quickstart/rhoai-blueprint-skill-kit) demonstrates what production-grade AI agent skills look like: subagent orchestration with parallel execution, spec-as-contract workflows, bounded feedback loops, namespace-scoped security hooks, living knowledge bases with scored retrieval, temp-file handoff between phases, and reasoning guardrails. Output quality is measurably higher because errors are caught in validation loops before the user ever sees them.

This ADR proposes upgrading all factory skills to this level of sophistication, while preserving the factory's existing strengths (agentskills.io spec compliance, multi-client portability, Makefile-driven validation, `skill-validator` CI).

Additionally, this ADR introduces 2 new pipeline skills and 3 new utility skills to close gaps in the current lifecycle.

## Decision

### New Pipeline (9 stages + 6 utilities)

```
MAIN PIPELINE (new quickstarts):

 1. rh-qs-discovery         → PRD
 2. rh-qs-architect         → Design doc
 3. rh-qs-scaffold          → GitHub repo
 4. rh-qs-implement         → Working code  (test subagent loop)
 5. rh-qs-deploy            → Helm + compose (deploy review subagent loop)
 6. rh-qs-security          → Security verified                          [NEW]
 7. rh-qs-debug-and-deploy  → Deployed + validated on OpenShift cluster  [NEW]
 8. rh-qs-document          → README + docs
 9. rh-qs-ship              → PR + blog

UTILITY SKILLS:

 - rh-qs-gh-backlog-reader     (existing)
 - rh-qs-gh-issue-creator      (existing)
 - rh-qs-pipeline-grooming     (existing)
 - rh-qs-update                (update released quickstarts)              [NEW]
 - rh-qs-handoff               (continue partial implementations)         [NEW]
 - rh-qs-extract-knowledge     (mine completed quickstarts for KB)        [NEW]
```

---

## Architectural Patterns (All Skills)

Every factory skill will be restructured to follow 8 architectural patterns.

### Pattern 1: Subagent Orchestration

Each skill's `SKILL.md` becomes an **orchestrator** that delegates heavy work to subagent prompts in a `subagents/` directory. This pattern is proven in the [rhoai-blueprint-skill-kit](https://github.com/rh-ai-quickstart/rhoai-blueprint-skill-kit), where every skill follows this structure.

**Critical design rule:** The main agent must NOT read subagent prompt files. It passes them by file path to the Task/Agent tool. This saves 60–70% of context window.

**Directory structure per skill:**

```
rh-qs-<name>/
├── SKILL.md                          # Orchestrator instructions
├── reasoning-guardrails.md           # Concern areas for organic self-checking
├── spec-template.md                  # YAML spec structure definition
├── output-templates.md               # Output format definitions
├── subagents/
│   ├── README.md                     # Subagent index and roles
│   └── <role>-prompt.md              # One file per subagent
├── knowledge-base/                   # If applicable
│   └── *.md
└── references/
    └── *.md
```

### Pattern 2: Spec-as-Contract

Before any skill modifies files, it generates a YAML spec describing *what* it will do, validates the spec with parallel subagents, refines it based on validation results, and only then hands it to an implementer subagent.

```
Analyze → Generate Spec → User Approval → Validate Spec (parallel) → Refine → Implement → Post-validate
```

Each spec is written to `.rhoai-qs/<slug>/pipeline/<skill>-spec.yaml` following a structure defined in `spec-template.md`.

**User-approved acceptance criteria:** For key workflow stages (architecture, implementation, deployment), the spec must include acceptance criteria that the user reviews and approves before implementation begins. These criteria define what "done" looks like and serve as the contract that post-validation checks against. Specs may also reference externally defined test cases, contract tests, or example patterns provided by the user or domain experts.

### Pattern 3: Feedback Loops with Bounded Iteration

Every skill that produces artifacts validates its output and iterates on failures, with a hard maximum to prevent infinite loops.

**Standard loop protocol (all skills):**

```
1. Run validation
2. If failures:
   a. Analyze errors
   b. Fix root cause (not symptoms)
   c. Re-run validation
3. Max N iterations (skill-specific, typically 3)
4. If still failing after max:
   a. Document remaining failures in the pipeline spec file
   b. Ask user: proceed, provide guidance, or stop
5. Only advance to next phase when validation passes
```

### Pattern 4: Persistent-File Handoff

Skills pass structured artifacts to each other via files in `.rhoai-qs/`, not conversation context — this matters because each skill typically runs in its own separate chat session.

**Namespace scoping:** All pipeline files are scoped to a quickstart-specific directory: `.rhoai-qs/<slug>/pipeline/` (e.g., `.rhoai-qs/spending-transaction-monitor/pipeline/`), inside the `quickstart-factory` repo itself. This prevents name clashes between different quickstarts and preserves context from previous runs when resuming. Every skill resolves `<slug>` via the `validation-skill` subagent (Phase 0) before touching any of these files — see [pipeline-convention.md](foundation/pipeline-convention.md) and [validation-skill-template.md](foundation/validation-skill-template.md).

| Transition | File | Format |
|-----------|----------|--------|
| Discovery → Architect | `.rhoai-qs/<slug>/prds/prd.md` | Markdown |
| Architect → Scaffold | `.rhoai-qs/<slug>/pipeline/architecture-spec.yaml` | YAML |
| Scaffold → Implement | `.rhoai-qs/<slug>/pipeline/scaffold-manifest.yaml` | YAML |
| Implement → Deploy | `.rhoai-qs/<slug>/pipeline/implementation-manifest.yaml` | YAML |
| Deploy → Security | `.rhoai-qs/<slug>/pipeline/deploy-manifest.yaml` | YAML |
| Security → Debug-and-Deploy | `.rhoai-qs/<slug>/pipeline/security-report.yaml` | YAML |
| Debug-and-Deploy → Document | `.rhoai-qs/<slug>/pipeline/deploy-state.yaml` | YAML |
| Document → Ship | `.rhoai-qs/<slug>/pipeline/doc-manifest.yaml` | YAML |

### Pattern 5: Reasoning Guardrails

Each skill gets a `reasoning-guardrails.md` file — NOT a checklist, but a set of concern areas the agent should reason about organically and self-check periodically during execution.

### Pattern 6: Hooks

Project-level hooks for safety and automation, gating destructive commands, enforcing namespace-scoped cluster operations, and auto-formatting edited files.

**Existing implementation:** The [oc-policy-gate](https://github.com/rh-ai-quickstart/oc-policy-gate) repo already implements cluster-operation hooks (namespace gating, destructive command blocking). It lives in a separate repo intentionally so it can be reused across multiple quickstart repos. Integration strategy: use `git subtree` to fetch it into each quickstart project and keep it updated from the upstream source.

### Pattern 7: Knowledge Base

A shared, tagged, scored knowledge base of reusable patterns mined from completed quickstarts. Each KB file has structured frontmatter with a Chain of Density summary for efficient retrieval without loading full files. Architecture follows the [rhoai-blueprint-skill-kit](https://github.com/rh-ai-quickstart/rhoai-blueprint-skill-kit)'s KB pattern (e.g., `bp-convert-to-rhoai/knowledge-base/`).

### Pattern 8: Multi-Layer Validation

| Layer | When | What | Mechanism |
|-------|------|------|-----------|
| **Pre-implementation** | After spec, before code | Spec correctness: valid chart versions, coherent schemas, valid model IDs | Parallel validator subagents per component |
| **Post-implementation** | After code, before deploy | Code quality + functional: lint, test, no placeholders, env vars match | Validator subagent + `make lint && make test` |
| **Security** | After deploy config, before cluster deploy | Compliance: no secrets in code, non-root containers, minimal SCCs, no CVEs | 4 parallel security scanner subagents |
| **Deploy-time** | After security verified, on cluster | Cluster health: resources running, endpoints responding | Health scanner + debug loop |

---

## Skill-by-Skill Specifications

### 1. rh-qs-discovery (Enhanced)

**Subagents:**

| Subagent | Role | Input | Output |
|----------|------|-------|--------|
| `prd-structurer-prompt.md` | Convert unstructured notes/docs into PRD sections | User-uploaded documents, conversation notes | Structured PRD sections in JSON |
| `backlog-matcher-prompt.md` | Check if idea duplicates existing backlog issues | Idea summary + backlog data | Match report (duplicate/similar/unique) |

**Spec file:** `.rhoai-qs/<slug>/pipeline/discovery-spec.yaml` (interview plan based on initial input)

**Validation:** After drafting the PRD, the agent validates completeness — all required PRD sections are populated (problem statement, target persona, success metrics, scope boundaries, technology constraints). Missing or vague sections are flagged for the user to clarify.

**Loop:** Validate → present PRD draft to user → user refines (no cap on refinement rounds — this is a collaborative, user-driven conversation)

**Guardrails:** Scope creep (don't invent requirements), technology bias (don't pre-decide stack), GPU assumptions.

---

### 2. rh-qs-architect (Enhanced)

**Subagents:**

| Subagent | Role | Input | Output |
|----------|------|-------|--------|
| `architecture-analyzer-prompt.md` | Parse PRD into feature vector | PRD markdown | JSON feature vector (AI capabilities, data needs, UI/API, scale) |
| `chart-selector-prompt.md` | Match features to ai-architecture-charts | Feature vector + KB | Component bill of materials with rationale |
| `diagram-generator-prompt.md` | Generate Mermaid architecture diagram | Bill of materials | Mermaid diagram code |

**Spec file:** `.rhoai-qs/<slug>/pipeline/architecture-spec.yaml`

**Knowledge base:** `knowledge-base/components/`, `knowledge-base/deployment-types/`, `knowledge-base/industries/`

**KB scoring:** `knowledge-scorer-prompt.md` scores KB files by relevance using component (+10), deployment type (+5), architecture (+5), industry (+3) tag matching. Returns XML summaries from frontmatter `summary:` fields without loading full files.

**Reuse from rhoai-blueprint-skill-kit:** The `knowledge-scorer-prompt.md`, `architecture-analyzer-prompt.md`, and `chart-selector-prompt.md` subagents share significant overlap with their counterparts in the blueprint kit. Use the blueprint kit's existing prompts as the starting point and adapt for quickstart-specific context (ai-architecture-charts, quickstart scope constraints).

**Loop:** Chart selector → validate charts exist (helm search, ArtifactHub) → refine (max 2 iterations)

**Guardrails:** Model sizing, GPU dependency, data residency, chart compatibility, scope creep.

---

### 3. rh-qs-scaffold (Enhanced)

**Subagents:**

| Subagent | Role | Input | Output |
|----------|------|-------|--------|
| `structure-generator-prompt.md` | Generate directory tree and file skeletons | Architecture spec | File list with skeleton contents |
| `ci-generator-prompt.md` | Generate GitHub Actions workflows | Component list from spec | CI/CD YAML files |
| `scaffold-validator-prompt.md` | Validate generated scaffold | Generated files | Validation report (READY/BLOCKED) |

**Spec file:** `.rhoai-qs/<slug>/pipeline/scaffold-spec.yaml` (repo name, packages to create, CI jobs, linting config)

**Output manifest:** `.rhoai-qs/<slug>/pipeline/scaffold-manifest.yaml` (lists all created files/paths for rh-qs-implement)

**Loop:** Generate → validate (files parseable, paths consistent, no placeholder strings) → fix (max 2 iterations)

---

### 4. rh-qs-implement (Major Restructure)

This is the most significant change. The implementation skill gains a **two-agent feedback loop** between a test-writing subagent and the main agent.

**Subagents:**

| Subagent | Role | Input | Output |
|----------|------|-------|--------|
| `test-writer-prompt.md` | Generate tests from PRD + architecture | PRD, design doc, scaffold manifest | Test files (pytest, vitest) |
| `backend-implementer-prompt.md` | Implement FastAPI backend | Implementation spec | Backend code |
| `frontend-implementer-prompt.md` | Implement React frontend | Implementation spec | Frontend code |
| `db-schema-prompt.md` | Generate SQLAlchemy models + Alembic migration | Implementation spec | DB package code |

**Spec file:** `.rhoai-qs/<slug>/pipeline/implementation-spec.yaml` (endpoints, schemas, services, DB models, UI routes)

**The Test Loop (core innovation):**

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│  test-writer subagent                                       │
│  (reads PRD + architecture + scaffold manifest)             │
│  → generates test files                                     │
│  → writes to .rhoai-qs/<slug>/pipeline/test-spec.yaml (test inventory)           │
│                                                             │
│          ↓ test files                                       │
│                                                             │
│  main agent (orchestrator)                                  │
│  → runs tests: make test                                    │
│  → tests fail                                               │
│  → routes failures to the relevant implementer subagent     │
│    (backend-implementer or frontend-implementer)            │
│  → implementer fixes its own code with full context         │
│  → main agent re-runs tests                                 │
│  → writes results to .rhoai-qs/<slug>/pipeline/test-results.yaml                 │
│                                                             │
│          ↓ if tests still fail after implementer fixes      │
│                                                             │
│  test-writer subagent (resumed)                             │
│  → reads .rhoai-qs/<slug>/pipeline/test-results.yaml                             │
│  → reviews failures: are tests wrong or is code wrong?      │
│  → adjusts tests ONLY if they were over-specified or wrong  │
│  → writes updated tests + rationale                         │
│                                                             │
│          ↓ back to main agent                               │
│                                                             │
│  main agent re-runs tests, routes failures if needed        │
│                                                             │
│  MAX 3 full loops. After 3: document failures, ask user.    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**The critical rule:** The main agent orchestrates the loop but NEVER fixes implementation code directly — it routes failures to the implementer subagent that owns that code (backend-implementer or frontend-implementer), who has the full context to make the right fix. Only the test-writer subagent can adjust tests, and only when it determines the tests themselves were wrong (not the code).

**Parallelism:** Backend + frontend implementer subagents run in parallel. DB schema runs first (dependency).

**Output manifest:** `.rhoai-qs/<slug>/pipeline/implementation-manifest.yaml` (lists endpoints, DB models, packages, test coverage)

**Guardrails:** Vertical slice (thinnest path), hardcoded values, error handling, async consistency, security.

---

### 5. rh-qs-deploy (Enhanced)

**Subagents:**

| Subagent | Role | Input | Output |
|----------|------|-------|--------|
| `helm-wiring-prompt.md` | Generate Chart.yaml dependencies + values.yaml | Deploy spec, implementation manifest | Helm chart files |
| `compose-generator-prompt.md` | Generate/update compose.yml | Deploy spec | compose.yml |
| `containerfile-generator-prompt.md` | Generate multi-stage Containerfiles | Package list from implementation manifest | Containerfiles per package |
| `deploy-reviewer-prompt.md` | Validate all deployment artifacts | All deploy files | Validation report (READY/BLOCKED/PARTIAL) |

**Spec file:** `.rhoai-qs/<slug>/pipeline/deploy-spec.yaml` (chart dependencies, values overrides, compose services, Containerfile specs)

**The Deploy Review Loop:**

```
┌──────────────────────────────────────────────────────────┐
│                                                          │
│  main agent generates deploy artifacts                   │
│          ↓                                               │
│  deploy-reviewer subagent validates:                     │
│  - Chart.yaml dependencies valid (helm search)           │
│  - values.yaml internally consistent                     │
│  - compose.yml services match Helm services              │
│  - Containerfiles build (podman build --dry-run)         │
│  - helm lint passes                                      │
│  - helm template renders both modes (remote + on-cluster)│
│  → writes .rhoai-qs/<slug>/pipeline/deploy-validation.yaml                    │
│          ↓                                               │
│  if BLOCKED: main agent routes failures back to the      │
│  relevant subagent (deploy-reviewer for Helm/compose,    │
│  containerfile-generator for Containerfiles) to fix with │
│  full deploy spec context → re-validate                  │
│  MAX 3 iterations                                        │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

**Output manifest:** `.rhoai-qs/<slug>/pipeline/deploy-manifest.yaml` (charts used, services, routes, env vars, validation status)

**Guardrails:** Chart version compatibility, secret exposure, GPU resource configuration, image registry accessibility.

---

### 6. rh-qs-security [NEW]

**Category:** `core/skills/security/rh-qs-security/`

**Purpose:** Comprehensive security verification of the quickstart before cluster deployment. Runs after rh-qs-deploy generates Helm/compose configs so that any security issues requiring code or config changes are caught and fixed *before* deploying to the cluster — ensuring rh-qs-debug-and-deploy always tests the final, security-verified code.

**Subagents:**

| Subagent | Role | Input | Output |
|----------|------|-------|--------|
| `code-security-scanner-prompt.md` | Scan for hardcoded secrets, injection vulnerabilities, insecure patterns | Source code | `.rhoai-qs/<slug>/pipeline/qs-security-code.yaml` |
| `container-security-reviewer-prompt.md` | Verify Containerfiles (non-root, minimal base, no secrets baked in) | Containerfiles | `.rhoai-qs/<slug>/pipeline/qs-security-containers.yaml` |
| `helm-security-reviewer-prompt.md` | Verify Helm charts (RBAC, NetworkPolicies, SCCs, secret management) | Helm chart | `.rhoai-qs/<slug>/pipeline/qs-security-helm.yaml` |
| `dependency-scanner-prompt.md` | Check Python/Node dependencies for known CVEs | pyproject.toml, package.json | `.rhoai-qs/<slug>/pipeline/qs-security-deps.yaml` |

**Workflow:**

```
Phase 1: Parallel scan (all 4 subagents run simultaneously)
         → 4 temp files with findings

Phase 2: Main agent aggregates findings into severity categories:
         - CRITICAL: Must fix before ship (secrets in code, root containers,
                     CVEs with known exploits)
         - HIGH:     Should fix (overly permissive RBAC, missing NetworkPolicy)
         - MEDIUM:   Recommended (dependency updates, hardening suggestions)
         - LOW:      Informational (best practice deviations)

Phase 3: FIX LOOP for CRITICAL + HIGH findings:

         ┌──────────────────────────────────────────┐
         │ main agent applies fixes                 │
         │ re-runs relevant scanner subagent        │
         │ MAX 3 iterations                         │
         │ If CRITICAL remains: block ship, ask user│
         │ If only HIGH remains: warn, allow proceed│
         └──────────────────────────────────────────┘

Phase 4: Generate security report → .rhoai-qs/<slug>/pipeline/security-report.yaml
```

**Security checklist areas:**

- No API keys, tokens, passwords in source code or Helm values
- Containers run as non-root with arbitrary UID support (filesystem and entrypoint must work with any non-root UID, compatible with OpenShift's arbitrary UID model)
- Minimal base images (python:slim, UBI, alpine)
- No `privileged: true` or `allowPrivilegeEscalation: true` without justification
- SCCs are minimum necessary (prefer `restricted-v2`, document if `anyuid` required)
- Routes use TLS edge termination
- CORS is not `*` in production config
- Dependencies have no known critical CVEs
- Secrets use Kubernetes Secrets, not ConfigMaps
- NetworkPolicies restrict pod-to-pod traffic

**Guardrails:** False positive filtering (some warnings are acceptable for demos), compliance context (HIPAA/PCI if PRD specifies), GPU security contexts (some GPU workloads require elevated permissions — document the justification).

**Post-publication CVE monitoring:** This skill covers build-time security scanning during development. For published quickstarts, ongoing CVE detection is handled at the CI/CD layer — each quickstart repo should enable GitHub Dependabot / Renovate for automated dependency alerts and PRs. When a new CVE is detected post-publication, the remediation path is `rh-qs-update` (re-entry at stages 5+6) which already supports the "Security patch" update type.

---

### 7. rh-qs-debug-and-deploy [NEW]

**Category:** `core/skills/deployment/rh-qs-debug-and-deploy/`

**Purpose:** Take security-verified source code and YAML/Helm files, deploy to an OpenShift cluster, iteratively debug and fix failures, and run E2E verification from TEST-PLAN.md. Runs after rh-qs-security so that all code and config changes from security fixes are included in the cluster deployment.

**Reuse from rhoai-blueprint-skill-kit:** This skill is based on `bp-deploy-and-debug` from the blueprint kit. The core workflow (cluster access validation, deploy, health scan, debug loop, E2E testing) can be adopted with minor adjustments for quickstart-specific context (ai-architecture-charts, quickstart namespace conventions, TEST-PLAN.md format).

**Subagents:**

| Subagent | Phase | Role | Input | Output |
|----------|-------|------|-------|--------|
| `cluster-access-validator-prompt.md` | 1a | Validate login, namespace, permissions | Namespace name | Access report |
| `project-analyzer-prompt.md` | 1b | Discover deploy commands and dependencies | Project path | `.rhoai-qs/<slug>/pipeline/qs-deploy-analysis.yaml` |
| `health-scanner-prompt.md` | 3, 4c | Scan all resources, produce health snapshot | Namespace, expected resources | `.rhoai-qs/<slug>/pipeline/qs-deploy-state.yaml` |
| `resource-debugger-prompt.md` | 4a | Root-cause analysis per failing resource | Resource name/kind, namespace | `.rhoai-qs/<slug>/pipeline/qs-debug-{resource}.yaml` |
| `fix-applier-prompt.md` | 4b | Validate fix against Red Hat best practices, apply | Debug report | `.rhoai-qs/<slug>/pipeline/qs-fix-{resource}.yaml` |
| `e2e-tester-prompt.md` | 5 | Run TEST-PLAN.md end-to-end verification | Project path, namespace | `.rhoai-qs/<slug>/pipeline/qs-e2e-results.yaml` |

**Workflow:**

```
Phase 1a: cluster-access-validator → verify login + namespace + policy
Phase 1b: project-analyzer → discover deploy commands + dependency order
Phase 2:  main agent runs deploy commands from analysis
Phase 3:  health-scanner → .rhoai-qs/<slug>/pipeline/qs-deploy-state.yaml

Phase 4:  DEBUG LOOP (per unhealthy resource, dependency order):

          ┌──────────────────────────────────────────────────┐
          │ 4a. resource-debugger → root cause + proposed fix│
          │ 4b. fix-applier → validate + apply + re-deploy   │
          │ 4c. health-scanner → re-scan resource            │
          │                                                  │
          │ MAX 3 attempts per resource                      │
          │ On attempt 3 failure: ask user                   │
          │   - skip resource                                │
          │   - provide guidance                             │
          │   - stop deployment                              │
          └──────────────────────────────────────────────────┘

Phase 5:  e2e-tester → run TEST-PLAN.md (no re-entry to debug on E2E fail)
Phase 6:  Final report → .rhoai-qs/<slug>/pipeline/deploy-state.yaml
```

**Fix boundary rules:**

- **Auto-apply:** Config/infra changes (ports, SCCs, resource limits, env vars, image tags, probes, volume mounts, init containers, route configs, PVC sizes)
- **Auto-apply:** OpenShift-specific source changes (inside `if openshift_mode` blocks, OCP config files)
- **Ask user:** Non-OpenShift source code changes (application logic, business logic, data flow)

**Attempt tracking:** Debug and fix files append `attempt_N` keys — never overwrite previous attempts. The debugger reviews previous attempts before proposing a new fix to avoid repeating failed approaches.

**Output:** `.rhoai-qs/<slug>/pipeline/deploy-state.yaml` (final health state, persistent from the start — no `/tmp/` intermediate)

**Guardrails:** Namespace isolation (every `oc`/`helm` command must use `-n <namespace>`), don't change application intent, dependency-order debugging (fix leaves first then work up), max 3 attempts per resource.

---

### 8. rh-qs-document (Enhanced)

**Subagents:**

| Subagent | Role | Input | Output |
|----------|------|-------|--------|
| `readme-generator-prompt.md` | Generate README from implementation + deploy manifests | All manifests + security report | README.md draft |
| `doc-validator-prompt.md` | Validate all documented commands exist and work | README + Makefile + repo | Validation report |

**Loop:** Generate → validate (every `make` target exists, every URL well-formed, diagram matches components) → present draft to user → user refines (no cap on refinement rounds — documentation quality is subjective and requires human judgment)

**Prompt engineering note:** The `readme-generator-prompt.md` is a high-effort deliverable that will require significant experimentation. LLMs tend to generate overly verbose documentation that explains implementation details rather than user-facing usage. The prompt must enforce conciseness: focus on what the quickstart does, how to deploy it, and how to use it — not how it was built. This prompt, once refined, becomes a reusable asset across all quickstarts.

---

### 9. rh-qs-ship (Enhanced)

**Subagents:**

| Subagent | Role | Input | Output |
|----------|------|-------|--------|
| `pr-body-generator-prompt.md` | Generate PR description from all manifests | All temp manifests + security report | PR body markdown |
| `blog-writer-prompt.md` | Generate blog post draft | PRD + architecture + README | Blog post markdown |

**Loop:** Create PR → wait for CI → if CI fails, diagnose + fix → re-push (max 3 iterations)

---

### 10. rh-qs-update [NEW]

**Category:** `core/skills/lifecycle/rh-qs-update/`

**Purpose:** Update existing, released quickstarts. Handles image tag bumps, dependency updates, chart version updates, security patches, and feature additions.

**Subagents:**

| Subagent | Role | Input | Output |
|----------|------|-------|--------|
| `change-analyzer-prompt.md` | Analyze what needs updating and scope the change | Repo + update request | `.rhoai-qs/<slug>/pipeline/qs-update-analysis.yaml` |
| `impact-assessor-prompt.md` | Determine which pipeline stages need re-running | Update analysis | `.rhoai-qs/<slug>/pipeline/qs-update-impact.yaml` |
| `update-applier-prompt.md` | Apply the updates to source files | Update analysis | Modified files |
| `update-validator-prompt.md` | Validate updates don't break existing functionality | Modified files | Validation report |

**How it fits in the pipeline flow:**

```
User: "Update the spending-transaction-monitor to use Llama 3.3"

rh-qs-update analyzes the change:
  → change-analyzer: "Image tag update + values.yaml + env config"
  → impact-assessor: "Re-run stages 5–9 (deploy through ship)"

rh-qs-update applies the change:
  → update-applier: modifies files
  → update-validator: make lint + make test pass

Then hands off to the pipeline at the detected re-entry point:
  → rh-qs-deploy         (re-validate Helm)
  → rh-qs-security       (re-scan)
  → rh-qs-debug-and-deploy (re-deploy to cluster)
  → rh-qs-document       (update README if needed)
  → rh-qs-ship           (create PR for update)
```

**Update types and re-entry points:**

| Update Type | Example | Re-entry Stage |
|-------------|---------|---------------|
| Image tag bump | `vLLM 0.6 → 0.7` | 5 (deploy) |
| Chart version bump | `llama-stack 0.7.3 → 0.8.0` | 5 (deploy) |
| Dependency update | `FastAPI 0.110 → 0.115` | 4 (implement: re-run tests) |
| Security patch | CVE fix in base image | 5 (deploy) + 6 (security) |
| Feature addition | Add new endpoint | 4 (implement) |
| Configuration change | Switch model size | 5 (deploy) |

**Guardrails:** Backward compatibility, semantic versioning awareness, test regression detection.

---

### 11. rh-qs-handoff [NEW]

**Category:** `core/skills/lifecycle/rh-qs-handoff/`

**Purpose:** Assess a partially implemented quickstart and continue from wherever it left off. The factory detects the current state and routes to the appropriate pipeline stage.

> **TODO:** Decide whether rh-qs-handoff should also handle converting external PoC repos (e.g., `github.com/robbybrodie/pragma-encoder`) into quickstarts — either via an explicit "conversion mode" or as a separate skill. See @sauagarwa's comment on the PR.

**Subagents:**

| Subagent | Role | Input | Output |
|----------|------|-------|--------|
| `state-detector-prompt.md` | Analyze repo and determine completion state per stage | Repo path | `.rhoai-qs/<slug>/pipeline/qs-handoff-state.yaml` |
| `gap-analyzer-prompt.md` | Identify specific gaps within each incomplete stage | State report + repo | `.rhoai-qs/<slug>/pipeline/qs-handoff-gaps.yaml` |
| `context-reconstructor-prompt.md` | Reconstruct PRD/design from existing code (if missing) | Repo code | Reconstructed PRD or design doc |

**Workflow:**

```
Phase 1: state-detector scans the repo for evidence of each stage:

         ┌────────────────────────────────────────────────────────────────┐
         │ Stage 1 (Discovery):  .rhoai-qs/<slug>/prds/prd.md exists?    │
         │ Stage 2 (Architect):  .rhoai-qs/<slug>/designs/design.md?     │
         │ Stage 3 (Scaffold):   .github/workflows/ exists?               │
         │ Stage 4 (Implement):  packages/api/src/main.py?                │
         │ Stage 5 (Deploy):     deploy/helm/? compose.yml?               │
         │ Stage 6 (Security):   .rhoai-qs/<slug>/pipeline/security-report.yaml? │
         │ Stage 7 (Debug):      .rhoai-qs/<slug>/pipeline/deploy-state.yaml?   │
         │ Stage 8 (Document):   README.md beyond placeholder?            │
         │ Stage 9 (Ship):       Open PR exists?                          │
         └──────────────────────────────────────────────────────┘

Phase 2: gap-analyzer identifies specific missing pieces within
         each partially complete stage

Phase 3: If PRD or design doc is missing but code exists,
         context-reconstructor reverse-engineers the PRD/design
         from the existing implementation

Phase 4: Present handoff report to user:

         "This quickstart is at Stage 4 (Implement).
          Backend is 80% complete, frontend is missing.
          Stage 3 (Scaffold) is fully complete.
          Recommended: Continue from Stage 4 with frontend
          implementation."

Phase 5: User confirms → route to appropriate skill with
         reconstructed context in temp files
```

**Guardrails:** Don't redo completed work, preserve existing code patterns, match the existing codebase's style conventions.

---

### 12. rh-qs-extract-knowledge [NEW]

**Category:** `core/skills/knowledge/rh-qs-extract-knowledge/`

**Purpose:** Mine completed quickstarts for reusable patterns and populate the shared knowledge base. Inspired by `bp-extract-blueprint-knowledge` from the rhoai-blueprint-skill-kit. Runs after `rh-qs-ship` completes a quickstart, or on-demand against any existing repo.

**Subagents:**

| Subagent | Role | Input | Output |
|----------|------|-------|--------|
| `component-pattern-extractor-prompt.md` | Extract component usage patterns (config, wiring, gotchas) | Source code + Helm chart | `.rhoai-qs/<slug>/pipeline/qs-kb-components.yaml` |
| `deployment-pattern-extractor-prompt.md` | Extract deployment patterns (chart combos, env configs, resource sizing) | Helm + compose + deploy report | `.rhoai-qs/<slug>/pipeline/qs-kb-deployment.yaml` |
| `industry-pattern-extractor-prompt.md` | Extract domain-specific patterns (data schemas, compliance, workflows) | PRD + source code | `.rhoai-qs/<slug>/pipeline/qs-kb-industry.yaml` |
| `security-pattern-extractor-prompt.md` | Extract security patterns (SCC configs, secret handling, hardening) | Security report + Helm chart | `.rhoai-qs/<slug>/pipeline/qs-kb-security.yaml` |
| `kb-dedup-scorer-prompt.md` | Deduplicate against existing KB, score novelty, merge or create | Extracted patterns + existing KB | `.rhoai-qs/<slug>/pipeline/qs-kb-update-plan.yaml` |

**Workflow:**

```
Phase 1: Parallel extraction (4 extractor subagents run simultaneously)
         → 4 temp files with candidate patterns

Phase 2: kb-dedup-scorer compares candidates against existing
         core/knowledge-base/ files:
         - If pattern already exists: merge new details, update
           source_quickstarts list, refresh summary
         - If pattern is novel: create new KB file with frontmatter
         - Score novelty: high (new component combo), medium (new
           config variant), low (minor variation)

Phase 3: Main agent applies the update plan:
         - Write/update KB .md files with Chain of Density summaries
         - Update KB README.md index
         - Run validation: frontmatter schema check, no duplicate
           entries, all tags reference valid components

Phase 4: Generate extraction report → .rhoai-qs/<slug>/pipeline/qs-kb-extraction-report.yaml
```

**Chain of Density summary format:** Each KB file's `summary:` field uses a 4-sentence Chain of Density summary — progressively denser sentences that pack maximum information for scored retrieval without loading the full file.

**Output:** Updated `core/knowledge-base/` files, extraction report

**Guardrails:** No proprietary data in KB files (patterns only, not business logic), deduplicate before creating new files, preserve existing KB file structure, validate frontmatter schema.

---

## Hooks Specification

### `.cursor/hooks.json`

```json
{
  "version": 1,
  "hooks": {
    "beforeShellExecution": [
      {
        "command": ".cursor/hooks/oc-policy-gate.sh",
        "matcher": "\\boc\\b|\\bkubectl\\b|\\bhelm\\b",
        "failClosed": true
      }
    ]
  }
}
```

**`oc-policy-gate.sh`** — Provided by `oc-policy-gate` (fetched via `git subtree`). Enforces namespace-scoped oc/kubectl/helm commands, blocks destructive cluster operations, and hard-denies missing `-n` flag and output redirects (`>`, `>>`).

Each hook requires a test script (`.cursor/hooks/test-<name>.sh`) with comprehensive test cases covering verbs, namespaces, pipes, subshells, and edge cases.

---

## Knowledge Base Specification

### Location: `core/knowledge-base/` (shared across skills)

```
core/knowledge-base/
├── README.md                          # Index + scoring algorithm
├── components/
│   ├── llama-stack-patterns.md
│   ├── pgvector-patterns.md
│   ├── minio-patterns.md
│   ├── vllm-serving-patterns.md
│   ├── fastapi-patterns.md
│   └── react-frontend-patterns.md
├── deployment-types/
│   ├── helm-with-ai-architecture-charts.md
│   ├── compose-local-dev.md
│   └── github-actions-ci.md
├── industries/
│   ├── financial-services.md
│   ├── healthcare.md
│   ├── supply-chain.md
│   └── retail.md
├── security/
│   ├── openshift-scc-patterns.md
│   ├── container-hardening.md
│   └── secret-management.md
└── standards/
    ├── makefile-targets.md
    ├── repo-structure.md
    └── ci-requirements.md
```

**Frontmatter schema per KB file:**

```yaml
---
type: component-pattern | deployment-pattern | industry-pattern | security-pattern | standard-pattern
components: [llama-stack, pgvector]
deployment_types: [helm]
industries: [financial-services]
source_quickstarts: [ai-supply-chain-agent, spending-transaction-monitor]
links:
  - title: "pgvector on OpenShift AI"
    url: "https://docs.redhat.com/..."
  - title: "Llama Stack deployment guide"
    url: "https://github.com/..."
summary: "4-sentence Chain of Density summary for scored retrieval..."
---
```

**Standards category:** The `standards/` directory contains cross-cutting requirements that apply to **every** quickstart regardless of components or industry — e.g., required Makefile targets (`make deploy`, `make test`, `make lint`), repo structure conventions, and CI workflow requirements. Hard requirements from `standards/` are enforced by `rh-qs-scaffold` during repo creation; best practices are advisory and scored like any other KB file.

**Growth mechanism:** After `rh-qs-ship` completes a quickstart, `rh-qs-extract-knowledge` mines the repo for reusable patterns and creates/updates KB files with Chain of Density summaries. Can also run on-demand against any existing quickstart repo.

**Scoring algorithm:** Component match (+10), deployment type (+5), architecture (+5), industry (+3). Knowledge scorer returns XML with summaries; full files loaded only for top matches.

---

## Updated AGENTS.md Routing

| User Request | Route To |
|--------------|----------|
| (all existing routes unchanged) | ... |
| "Deploy to cluster" / "Debug deployment" / "Fix deployment" | rh-qs-debug-and-deploy |
| "Security check" / "Security audit" / "Is it secure?" | rh-qs-security |
| "Update quickstart" / "Bump image" / "Upgrade dependencies" | rh-qs-update |
| "Continue this" / "Pick up where we left off" / "Finish this quickstart" | rh-qs-handoff |
| "Extract patterns" / "Update knowledge base" / "Mine quickstart for KB" | rh-qs-extract-knowledge |

---

## Evaluation Benchmark

Prompt-based skills are susceptible to **silent drift** — a text change can degrade agent behavior without producing obvious errors. To detect this, we introduce an evaluation benchmark integrated with CI/CD.

### The Problem

When a skill's SKILL.md or subagent prompt is modified, there is no automated way to verify the change improved (or at least did not degrade) the agent's output quality. Manual review catches some issues, but cannot scale across 15 skills and ~43 subagent prompts.

### The Solution: [ABEvalFlow](https://github.com/RHEcosystemAppEng/ABEvalFlow) Integration

We will leverage [ABEvalFlow](https://github.com/RHEcosystemAppEng/ABEvalFlow) — an OpenShift/Tekton-orchestrated evaluation platform that measures skill efficacy through controlled A/B experiments. [ABEvalFlow](https://github.com/RHEcosystemAppEng/ABEvalFlow) runs the agent with and without a skill on the same tasks, producing statistical metrics (pass rates, reward gaps, p-values) and a unified scorecard.

### Benchmark Components

**1. Static Test PRDs**

Create a small, curated set of test PRDs in `tests/benchmark/prds/` that represent canonical quickstart scenarios:

| Test PRD | Scenario | Exercises |
|----------|----------|-----------|
| `minimal-api.md` | API-only, no frontend, no RAG | Stages 1–5, 8–9 |
| `full-stack-rag.md` | Frontend + backend + pgvector + Llama Stack | All stages |
| `notebook-only.md` | RHOAI notebook, no Helm | Stages 1–2, 4, 6–9 |

Each test PRD has a known-good reference implementation so outcomes can be verified against expected artifacts.

**2. Skill Submissions**

Package each factory skill as a Harbor submission for [ABEvalFlow](https://github.com/RHEcosystemAppEng/ABEvalFlow):

```
tests/benchmark/submissions/rh-qs-implement/
├── metadata.yaml          # eval_engine: harbor, n_trials, gate_policy
├── instruction.md         # Task description for the benchmark
├── skills/
│   └── SKILL.md           # Symlink to core/skills/.../SKILL.md
└── tests/
    └── test_outputs.py    # Verifier: checks generated artifacts
```

**3. Evaluation Engines**

| Engine | Use Case | When |
|--------|----------|------|
| **Harbor** (A/B) | Gold standard — measures skill uplift with container isolation | Pre-merge gating on skill changes |
| **ASE** (lightweight) | Fast feedback — LLM-as-judge assertions | PR CI for rapid iteration |

**4. Metrics Produced**

| Metric | Description | Pass Criteria |
|--------|-------------|---------------|
| `mean_reward_gap` | Treatment (with skill) minus control (without) | ≥ 0.0 (no degradation) |
| `pass_rate` | Fraction of trials that produced correct artifacts | Treatment ≥ control |
| `ttest_p_value` | Statistical significance of reward difference | < 0.05 for confident claims |
| Scorecard recommendation | Combined evaluation + security + quality gates | `pass` or `warn` (not `fail`) |

**5. CI/CD Integration**

| Trigger | Pipeline | Action on Failure |
|---------|----------|-------------------|
| PR modifying `core/skills/**` | ASE (fast, ~5 min) | Block merge if scorecard = `fail` |
| PR modifying `core/skills/**` + label `full-eval` | Harbor (thorough, ~30 min) | Block merge if `mean_reward_gap < 0` |
| Weekly scheduled | Harbor on all skills vs baseline | Slack alert if degradation detected |

**6. Monitoring and Regression Detection**

[ABEvalFlow](https://github.com/RHEcosystemAppEng/ABEvalFlow)'s monitoring pipeline runs canary skills periodically and compares against historical baselines stored in PostgreSQL. If a skill's score drops below 85% of its previous baseline, the system flags a degradation and sends alerts.

### Benchmark Maintenance

- Test PRDs are **static** — they change only through deliberate, reviewed PRs
- Reference implementations are versioned alongside the test PRDs
- New test PRDs are added when new skill patterns emerge (e.g., after adding rh-qs-security)
- [ABEvalFlow](https://github.com/RHEcosystemAppEng/ABEvalFlow) `metadata.yaml` configurations are stored in `tests/benchmark/submissions/` and validated by `skill-validator`

---

## agentskills.io Spec Compliance

All skills — existing and new — must strictly follow the [agentskills.io](https://agentskills.io) open standard. Drift from the spec causes inconsistent behavior across agent harnesses (Cursor, Claude Code, Codex, Gemini).

### Enforced Constraints

| Constraint | Enforcement |
|-----------|-------------|
| `name` field matches directory name exactly | `validate-skills.sh` + `skill-validator --strict` |
| `name` uses lowercase letters, numbers, hyphens only (max 64 chars) | `skill-validator` |
| `description` is non-empty (max 1024 chars) | `skill-validator` |
| SKILL.md body uses valid markdown with correct code fences | `skill-validator` |
| Internal file references resolve (scripts/, references/) | `skill-validator` |
| Token budget within spec limits | `skill-validator` |
| No Windows-style paths | `skill-validator` |

### Extended Frontmatter

Some agent clients support extended frontmatter fields (`allowed-tools`, `disable-model-invocation`, `argument-hint`). These are permitted via `--allow-extra-frontmatter` in `skill-validator` but must not break harnesses that ignore them.

### CI Validation

The existing `make skills-check` target runs both layout validation and spec validation on every PR:

```bash
make skills-check
# 1. validate-skills.sh      — layout: core/skills/<category>/<skill-name>/SKILL.md
# 2. validate-skills-spec.sh — agentskills.io via skill-validator --strict --allow-extra-frontmatter
# 3. sync-clients.sh          — symlink into .cursor/, .claude/, .codex/, .gemini/
# 4. symlink count check      — all skills discoverable by all clients
```

### New Skills Must Pass

Every new skill introduced in this ADR (rh-qs-security, rh-qs-debug-and-deploy, rh-qs-update, rh-qs-handoff, rh-qs-extract-knowledge) must pass `skill-validator --strict` before merge. Subagent prompts in `subagents/` directories are not required to follow the agentskills.io spec (they are not standalone skills), but their parent SKILL.md must.

---

## Implementation Phases

| Phase | Workstreams | Risk |
|-------|------------|------|
| **Phase 1: Foundation** | Hooks + guardrails files for all existing skills | Low — additive, no restructuring |
| **Phase 2: Validation** | Feedback loops + multi-layer validation for existing skills | Medium — modifies SKILL.md files |
| **Phase 3: Orchestration** | Subagent prompts + spec-as-contract for all existing skills (~25 subagent prompts) | High — core architecture change |
| **Phase 4: New Skills** | rh-qs-security + rh-qs-debug-and-deploy (~10 subagent prompts) | High — new deployment infrastructure |
| **Phase 5: Lifecycle** | rh-qs-update + rh-qs-handoff (~7 subagent prompts) | Medium — utility skills |
| **Phase 6: Knowledge Base** | rh-qs-extract-knowledge (~5 subagent prompts), KB creation, scoring | Medium — requires extraction skill |
| **Phase 7: Evaluation Benchmark** | Test PRDs, [ABEvalFlow](https://github.com/RHEcosystemAppEng/ABEvalFlow) submissions, CI/CD gating | Medium — requires [ABEvalFlow](https://github.com/RHEcosystemAppEng/ABEvalFlow) infra |

**Totals:**

- New subagent prompts: ~43
- New skills: 2 (pipeline) + 3 (utility) = 5
- Total skills after upgrade: 15 (9 pipeline + 6 utility)

---

## Consequences

### Positive

- **Dramatically higher output quality** — errors caught in validation loops before users see them
- **Faster execution** — parallel subagents (backend + frontend, 4 security scanners simultaneously)
- **Context efficiency** — subagent delegation saves 60–70% context window
- **Auditability** — temp files create an audit trail of every decision and fix attempt
- **Growing intelligence** — knowledge base improves with each completed quickstart
- **Safety** — hooks prevent destructive operations and enforce namespace-scoped cluster commands
- **Full lifecycle coverage** — update and handoff skills close gaps for released and partial quickstarts
- **Security by default** — dedicated security stage before cluster deployment, ensuring security fixes are always tested on the real cluster
- **Test quality** — separated test authoring from code fixes ensures tests represent real requirements, not implementation artifacts
- **Measurable skill quality** — [ABEvalFlow](https://github.com/RHEcosystemAppEng/ABEvalFlow) benchmark provides statistical proof that skill changes improve or maintain output quality
- **Regression detection** — scheduled monitoring catches silent drift before it reaches users
- **Spec compliance** — strict agentskills.io validation ensures consistent behavior across Cursor, Claude Code, Codex, and Gemini

### Negative

- **Complexity increase** — from 10 flat SKILL.md files to 15 skills with ~43 subagent prompts, hooks, KB, and guardrails
- **Maintenance burden** — more files to keep consistent and up to date
- **Debugging difficulty** — multi-subagent orchestration is harder to debug than flat skills
- **Onboarding cost** — new contributors must understand the orchestration patterns
- **Concurrency limitation** — running the same quickstart's pipeline concurrently in two sessions is not safe (see [pipeline-convention.md](foundation/pipeline-convention.md#concurrency))

### Mitigations

- Each skill's `subagents/README.md` documents all subagent roles clearly
- `make skills-check` continues to validate all skills against agentskills.io spec
- Persistent reports (`.rhoai-qs/<slug>/pipeline/deploy-state.yaml`, `.rhoai-qs/<slug>/pipeline/security-report.yaml`) live in `quickstart-factory` itself, not `/tmp/`, so they survive reboots and separate chat sessions
- Phase-gated rollout allows validating each change before the next

---

## References

- [agentskills.io](https://agentskills.io) — skill spec standard
- [ai-architecture-charts](https://github.com/rh-ai-quickstart/ai-architecture-charts) — Helm chart repo
- [ai-quickstart-template](https://github.com/rh-ai-quickstart/ai-quickstart-template) — monorepo template
- [docs/skills-development.md](../skills-development.md) — existing development guide
- [ABEvalFlow](https://github.com/RHEcosystemAppEng/ABEvalFlow) — evaluation benchmark platform for AI skills
- [skill-validator](https://github.com/agent-ecosystem/skill-validator) — agentskills.io spec validation tool
- [rhoai-blueprint-skill-kit](https://github.com/rh-ai-quickstart/rhoai-blueprint-skill-kit) — reference implementation for advanced skill patterns (subagent orchestration, KB scoring, deploy-and-debug, knowledge extraction)
