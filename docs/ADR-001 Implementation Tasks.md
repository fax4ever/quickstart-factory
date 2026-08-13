# ADR-001 Implementation Tasks
```
Status: Proposed
Date: 2026-06-28
Authors: Matan Talvi, Yossi Elias
```


## Dependency Graph

```
PHASE 1 — FOUNDATION (no dependencies, can run in parallel)
┌─────────────────────────────────────────────────────────────┐
│  EPIC-01: Foundation Infrastructure                         │
│  EPIC-02: Hooks Infrastructure                              │
│  EPIC-03: Knowledge Base Infrastructure                     │
└──────────────────────────┬──────────────────────────────────┘
                           │
PHASE 2–3 — PIPELINE SKILL UPGRADES (sequential pipeline order)
┌──────────────────────────▼──────────────────────────────────┐
│  EPIC-04: rh-qs-discovery ──► EPIC-05: rh-qs-architect     │
│      ──► EPIC-06: rh-qs-scaffold ──► EPIC-07: rh-qs-implement │
│      ──► EPIC-08: rh-qs-deploy                              │
│                                                             │
│  EPIC-05 also depends on EPIC-03 (KB infrastructure)        │
│  EPIC-06 also depends on EPIC-03 (standards KB)             │
│  EPIC-14: Existing Utility Skills (parallel with pipeline)  │
└──────────────────────────┬──────────────────────────────────┘
                           │
PHASE 4 — NEW PIPELINE SKILLS (sequential, extend the pipeline)
┌──────────────────────────▼──────────────────────────────────┐
│  EPIC-09: rh-qs-security ──► EPIC-10: rh-qs-debug-and-deploy │
│      ──► EPIC-11: rh-qs-document ──► EPIC-12: rh-qs-ship   │
└──────────────────────────┬──────────────────────────────────┘
                           │
PHASE 5 — LIFECYCLE SKILLS (depend on full pipeline)
┌──────────────────────────▼──────────────────────────────────┐
│  EPIC-13: rh-qs-update     (parallel)                       │
│  EPIC-15: rh-qs-handoff    (parallel)                       │
└──────────────────────────┬──────────────────────────────────┘
                           │
PHASE 6 — KNOWLEDGE EXTRACTION (depends on KB infra + pipeline)
┌──────────────────────────▼──────────────────────────────────┐
│  EPIC-16: rh-qs-extract-knowledge                           │
└──────────────────────────┬──────────────────────────────────┘
                           │
PHASE 7 — EVALUATION & FINALIZATION
┌──────────────────────────▼──────────────────────────────────┐
│  EPIC-17: Evaluation Benchmark                              │
│  EPIC-18: Documentation & Routing Updates                   │
└─────────────────────────────────────────────────────────────┘
```

---

## EPIC-01: Foundation Infrastructure

**Description:** Set up the foundational patterns, templates, and conventions that all skill EPICs depend on. This includes the directory structure standard, spec-template conventions, reasoning guardrails template, and temp-file namespace scoping.

**Blocked by:** Nothing
**Blocks:** All skill EPICs (EPIC-04 through EPIC-16)

| ID | Task | Description |
|----|------|-------------|
| 01-01 | Define skill directory structure standard | Document the canonical directory layout for upgraded skills (`SKILL.md`, `reasoning-guardrails.md`, `spec-template.md`, `output-templates.md`, `subagents/`, `knowledge-base/`, `references/`). Create a reference example that all skill EPICs follow. |
| 01-02 | Create spec-template convention doc | Define the YAML spec-as-contract format: required fields, acceptance criteria section, validation rules. This template is used by all skills that generate specs. |
| 01-03 | Create reasoning guardrails template | Define the standard format for `reasoning-guardrails.md` files — concern areas structure, self-check prompts, scope-specific sections. Provide an example that skill EPICs adapt. |
| 01-04 | Define temp-file namespace scoping convention | Document the `.rhoai-qs/<slug>/pipeline/` scoping convention. Create a helper reference that skills use to construct scoped temp paths. Define cleanup policy. |
| 01-05 | Define temp-file contract formats | Specify the YAML schema for each inter-skill handoff file (architecture-spec, scaffold-manifest, implementation-manifest, deploy-manifest, security-report, deploy-state, doc-manifest). These contracts must be defined before skills are implemented. |
| 01-06 | Define user-approved acceptance criteria pattern | Document how specs include acceptance criteria, when user approval is required, and how acceptance criteria are validated post-implementation. |

---

## EPIC-02: Hooks Infrastructure

**Description:** Set up project-level hooks for safety and automation. Integrate `oc-policy-gate` via git subtree.

**Blocked by:** Nothing
**Blocks:** All skill EPICs (hooks apply during skill execution)

| ID | Task | Description |
|----|------|-------------|
| 02-01 | Integrate oc-policy-gate via git subtree | Fetch the `oc-policy-gate` repo into the project using `git subtree`. Configure it as `.cursor/hooks/oc-policy-gate.sh`. Validate it enforces namespace-scoped `oc`/`kubectl`/`helm` commands and blocks destructive operations. |
| 02-02 | Create hooks.json configuration | Write `.cursor/hooks.json` wiring the oc-policy-gate hook with correct matchers and `failClosed` settings. |
| 02-03 | Create hook test scripts | Write `.cursor/hooks/test-oc-policy-gate.sh` with comprehensive test cases covering edge cases (pipes, subshells, quoted args). |

---

## EPIC-03: Knowledge Base Infrastructure

**Description:** Create the shared knowledge base directory structure, frontmatter schema, scoring algorithm, and initial standards files. This is a prerequisite for skills that use KB (especially rh-qs-architect).

**Blocked by:** Nothing
**Blocks:** EPIC-05 (rh-qs-architect), EPIC-06 (rh-qs-scaffold), EPIC-16 (rh-qs-extract-knowledge)

| ID | Task | Description |
|----|------|-------------|
| 03-01 | Create KB directory structure | Create `core/knowledge-base/` with subdirectories: `components/`, `deployment-types/`, `industries/`, `security/`, `standards/`. Add `README.md` with index and scoring algorithm documentation. |
| 03-02 | Define frontmatter schema | Document the required frontmatter fields: `type` (component-pattern, deployment-pattern, industry-pattern, security-pattern, standard-pattern), `components`, `deployment_types`, `industries`, `source_quickstarts`, `links`, `summary`. Add schema validation rules. |
| 03-03 | Create standards KB files | Write `standards/makefile-targets.md` (required `make deploy`, `make test`, `make lint` targets), `standards/repo-structure.md` (directory conventions), `standards/ci-requirements.md` (GitHub Actions workflow requirements). |
| 03-04 | Create seed component KB files | Write initial KB files for known components: `components/llama-stack-patterns.md`, `components/pgvector-patterns.md`, `components/vllm-serving-patterns.md`, `components/fastapi-patterns.md`, `components/react-frontend-patterns.md`, `components/minio-patterns.md`. Use Chain of Density summaries. |
| 03-05 | Create seed deployment-type KB files | Write `deployment-types/helm-with-ai-architecture-charts.md`, `deployment-types/compose-local-dev.md`, `deployment-types/github-actions-ci.md`. |
| 03-06 | Create seed security KB files | Write `security/openshift-scc-patterns.md`, `security/container-hardening.md`, `security/secret-management.md`. |
| 03-07 | Implement knowledge-scorer-prompt.md | Write the knowledge scorer subagent prompt that scores KB files by relevance: component (+10), deployment type (+5), architecture (+5), industry (+3). Returns XML summaries from frontmatter without loading full files. Adapt from blueprint kit's existing knowledge-scorer. |

---

## EPIC-04: rh-qs-discovery (Enhanced)

**Description:** Upgrade the discovery skill from a flat SKILL.md to an orchestrator with subagents, spec-as-contract, explicit validation criteria, and uncapped user-driven refinement.

**Blocked by:** EPIC-01 (foundation)
**Blocks:** EPIC-05 (rh-qs-architect — depends on PRD output format)

| ID | Task | Description |
|----|------|-------------|
| 04-01 | Create discovery directory structure | Set up `core/skills/inception/rh-qs-discovery/` with `subagents/`, `references/` directories and `subagents/README.md`. |
| 04-02 | Create prd-structurer-prompt.md | Write the subagent prompt that converts unstructured notes/docs into structured PRD sections (JSON). Handles uploaded documents, conversation notes, and raw ideas. |
| 04-03 | Create backlog-matcher-prompt.md | Write the subagent prompt that checks if the user's idea duplicates or overlaps with existing backlog issues. Takes idea summary + backlog data, produces match report (duplicate/similar/unique). |
| 04-04 | Create spec-template.md | Define the discovery spec format (`.rhoai-qs/<slug>/pipeline/discovery-spec.yaml`) — interview plan structure based on initial input. |
| 04-05 | Create reasoning-guardrails.md | Define concern areas: scope creep (don't invent requirements), technology bias (don't pre-decide stack), GPU assumptions, completeness without over-specification. |
| 04-06 | Restructure SKILL.md as orchestrator | Rewrite SKILL.md to orchestrate the two subagents, generate the spec, validate PRD completeness (problem statement, target persona, success metrics, scope boundaries, technology constraints), and present drafts to the user for refinement with no cap on rounds. |
| 04-07 | Add prd-griller subagent | Write the subagent prompt that stress-tests a draft PRD with dependency-ordered tough questions (rounds/frontier pattern), wired into Phase 6.5 between requirement mapping and validation. |
| 04-08 | Validate with skill-validator | Run `skill-validator --strict --allow-extra-frontmatter` against the updated SKILL.md. Fix any compliance issues. |

---

## EPIC-05: rh-qs-architect (Enhanced)

**Description:** Upgrade the architect skill with KB-scored component selection, parallel validation subagents, blueprint kit prompt reuse, and spec-as-contract workflow.

**Blocked by:** EPIC-01 (foundation), EPIC-03 (KB infrastructure), EPIC-04 (discovery — PRD output format)
**Blocks:** EPIC-06 (rh-qs-scaffold — depends on architecture spec format)

| ID | Task | Description |
|----|------|-------------|
| 05-01 | Create architect directory structure | Set up `core/skills/architecture/rh-qs-architect/` with `subagents/`, `knowledge-base/`, `references/` directories and `subagents/README.md`. |
| 05-02 | Create architecture-analyzer-prompt.md | Write the subagent prompt that parses a PRD into a feature vector (AI capabilities, data needs, UI/API requirements, scale). Adapt from blueprint kit's equivalent. |
| 05-03 | Create chart-selector-prompt.md | Write the subagent prompt that matches feature vectors to ai-architecture-charts (llama-stack, llm-service, pgvector, minio, mcp-servers, ingestion-pipeline). Produces component bill of materials with rationale. Adapt from blueprint kit's equivalent. |
| 05-04 | Create diagram-generator-prompt.md | Write the subagent prompt that generates a Mermaid architecture diagram from the component bill of materials. |
| 05-05 | Create spec-template.md | Define the architecture spec format (`.rhoai-qs/<slug>/pipeline/architecture-spec.yaml`) — components, chart versions, deployment mode, feature-to-component mapping. |
| 05-06 | Create reasoning-guardrails.md | Define concern areas: model sizing, GPU dependency, data residency, chart compatibility, scope creep, over-engineering. |
| 05-07 | Restructure SKILL.md as orchestrator | Rewrite SKILL.md to orchestrate the 4 subagents (analyzer, chart-selector, diagram-generator, knowledge-scorer), run KB scoring, validate chart existence (helm search, ArtifactHub), and present the bill of materials for user approval. Max 2 validation iterations. |
| 05-08 | Validate with skill-validator | Run `skill-validator --strict` against the updated SKILL.md. |

---

## EPIC-06: rh-qs-scaffold (Enhanced)

**Description:** Upgrade the scaffold skill with parallel subagents for structure generation, CI generation, and validation. Enforce standards from the KB.

**Blocked by:** EPIC-01 (foundation), EPIC-03 (standards KB), EPIC-05 (architect — architecture spec format)
**Blocks:** EPIC-07 (rh-qs-implement — depends on scaffold manifest format)

| ID | Task | Description |
|----|------|-------------|
| 06-01 | Create scaffold directory structure | Set up `core/skills/github/rh-qs-scaffold/` with `subagents/` directory and `subagents/README.md`. |
| 06-02 | Create structure-generator-prompt.md | Write the subagent prompt that generates the directory tree and file skeletons from the architecture spec. Must enforce standards from `core/knowledge-base/standards/`. |
| 06-03 | Create ci-generator-prompt.md | Write the subagent prompt that generates GitHub Actions workflows (ci.yaml, integration.yaml, deploy.yaml) from the component list. |
| 06-04 | Create scaffold-validator-prompt.md | Write the subagent prompt that validates the generated scaffold: files are parseable, paths are consistent, no placeholder strings remain, required Makefile targets exist, CI workflows are valid YAML. |
| 06-05 | Create spec-template.md | Define the scaffold spec format (`.rhoai-qs/<slug>/pipeline/scaffold-spec.yaml`) — repo name, packages to create, CI jobs, linting config. |
| 06-06 | Create reasoning-guardrails.md | Define concern areas: over-scaffolding, missing CI coverage, placeholder pollution, standards compliance. |
| 06-07 | Restructure SKILL.md as orchestrator | Rewrite SKILL.md to orchestrate the 3 subagents, generate then validate the scaffold with max 2 fix iterations, and produce the scaffold manifest. |
| 06-08 | Validate with skill-validator | Run `skill-validator --strict` against the updated SKILL.md. |

---

## EPIC-07: rh-qs-implement (Major Restructure)

**Description:** The most significant upgrade. Restructure the implement skill with a two-agent test loop: test-writer generates tests, implementer subagents fix code (not the main agent), and the test-writer reviews failures. Backend and frontend run in parallel.

**Blocked by:** EPIC-01 (foundation), EPIC-06 (scaffold — scaffold manifest format)
**Blocks:** EPIC-08 (rh-qs-deploy — depends on implementation manifest format)

| ID | Task | Description |
|----|------|-------------|
| 07-01 | Create implement directory structure | Set up `core/skills/implementation/rh-qs-implement/` with `subagents/` directory and `subagents/README.md`. |
| 07-02 | Create test-writer-prompt.md | Write the subagent prompt that generates tests from PRD + architecture + scaffold manifest. Produces pytest and vitest test files. Must be resumable — on subsequent calls, it reads test results and adjusts tests ONLY if they were over-specified or wrong. |
| 07-03 | Create backend-implementer-prompt.md | Write the subagent prompt that implements the FastAPI backend from the implementation spec. Must be able to receive test failure context and fix its own code with full understanding of the backend architecture. |
| 07-04 | Create frontend-implementer-prompt.md | Write the subagent prompt that implements the React frontend from the implementation spec. Must be able to receive test failure context and fix its own code. Runs in parallel with backend-implementer. |
| 07-05 | Create db-schema-prompt.md | Write the subagent prompt that generates SQLAlchemy models and Alembic migrations from the implementation spec. Runs before backend/frontend (dependency). |
| 07-06 | Create spec-template.md | Define the implementation spec format (`.rhoai-qs/<slug>/pipeline/implementation-spec.yaml`) — endpoints, schemas, services, DB models, UI routes. |
| 07-07 | Create reasoning-guardrails.md | Define concern areas: vertical slice (thinnest path), hardcoded values allowed for MVP, error handling, async consistency, security basics. |
| 07-08 | Restructure SKILL.md as orchestrator | Rewrite SKILL.md to orchestrate the test loop: test-writer generates tests → main agent runs `make test` → routes failures to relevant implementer subagent → implementer fixes → re-run tests → if still failing, resume test-writer to review. Max 3 full loops. Main agent NEVER fixes code directly. |
| 07-09 | Create review sub-agent | Write the review sub-agent prompt that reviews implementation against the spec and code quality best practices, and runs formatting checks (`ruff` for Python, `prettier` for TypeScript). All checks run once after implementation edits are complete, not per-edit. _(Formatting was originally a per-edit hook in EPIC-02. Moved here because a per-edit hook disrupts implementation sub-agent continuity by triggering repeated failures on each edit. Running it once during review is both more reliable and more token-efficient.)_ |
| 07-10 | Validate with skill-validator | Run `skill-validator --strict` against the updated SKILL.md. |

---

## EPIC-08: rh-qs-deploy (Enhanced)

**Description:** Upgrade the deploy skill with a deploy review loop where the deploy-reviewer subagent validates artifacts and failures are routed back to the relevant subagent (not the main agent) for fixing.

**Blocked by:** EPIC-01 (foundation), EPIC-07 (implement — implementation manifest format)
**Blocks:** EPIC-09 (rh-qs-security — depends on deploy manifest format)

| ID | Task | Description |
|----|------|-------------|
| 08-01 | Create deploy directory structure | Set up `core/skills/deployment/rh-qs-deploy/` with `subagents/` directory and `subagents/README.md`. |
| 08-02 | Create helm-wiring-prompt.md | Write the subagent prompt that generates Chart.yaml dependencies and values.yaml from the deploy spec and implementation manifest. |
| 08-03 | Create compose-generator-prompt.md | Write the subagent prompt that generates/updates compose.yml from the deploy spec for local development. |
| 08-04 | Create containerfile-generator-prompt.md | Write the subagent prompt that generates multi-stage Containerfiles per package. Must support arbitrary UID (OpenShift's arbitrary UID model). |
| 08-05 | Create deploy-reviewer-prompt.md | Write the subagent prompt that validates all deployment artifacts: Chart.yaml deps valid, values.yaml consistent, compose.yml matches Helm, Containerfiles build, helm lint passes, helm template renders. Produces validation report (READY/BLOCKED/PARTIAL). |
| 08-06 | Create spec-template.md | Define the deploy spec format (`.rhoai-qs/<slug>/pipeline/deploy-spec.yaml`) — chart dependencies, values overrides, compose services, Containerfile specs. |
| 08-07 | Create reasoning-guardrails.md | Define concern areas: chart version compatibility, secret exposure, GPU resource configuration, image registry accessibility. |
| 08-08 | Restructure SKILL.md as orchestrator | Rewrite SKILL.md to orchestrate artifact generation and the deploy review loop. On BLOCKED: route failures to the relevant subagent (deploy-reviewer for Helm/compose, containerfile-generator for Containerfiles). Max 3 iterations. |
| 08-09 | Validate with skill-validator | Run `skill-validator --strict` against the updated SKILL.md. |

---

## EPIC-09: rh-qs-security [NEW]

**Description:** Create the new security verification skill that runs after deploy (stage 6). Scans code, Containerfiles, Helm charts, and dependencies in parallel with 4 subagents. Fixes CRITICAL+HIGH findings before allowing cluster deployment.

**Blocked by:** EPIC-01 (foundation), EPIC-08 (deploy — deploy manifest format)
**Blocks:** EPIC-10 (rh-qs-debug-and-deploy — depends on security report format)

| ID | Task | Description |
|----|------|-------------|
| 09-01 | Create security skill directory structure | Create `core/skills/security/rh-qs-security/` with full directory layout: SKILL.md, subagents/, reasoning-guardrails.md, spec-template.md. |
| 09-02 | Create code-security-scanner-prompt.md | Write the subagent prompt that scans source code for hardcoded secrets, injection vulnerabilities, and insecure patterns. Outputs findings to `.rhoai-qs/<slug>/pipeline/qs-security-code.yaml`. |
| 09-03 | Create container-security-reviewer-prompt.md | Write the subagent prompt that verifies Containerfiles: arbitrary UID support (not hardcoded USER), minimal base images (UBI/slim), no secrets baked in. Outputs to `.rhoai-qs/<slug>/pipeline/qs-security-containers.yaml`. |
| 09-04 | Create helm-security-reviewer-prompt.md | Write the subagent prompt that verifies Helm charts: RBAC, NetworkPolicies, SCCs (prefer restricted-v2), secret management via Kubernetes Secrets. Outputs to `.rhoai-qs/<slug>/pipeline/qs-security-helm.yaml`. |
| 09-05 | Create dependency-scanner-prompt.md | Write the subagent prompt that checks Python (pyproject.toml) and Node (package.json) dependencies for known CVEs. Outputs to `.rhoai-qs/<slug>/pipeline/qs-security-deps.yaml`. |
| 09-06 | Create spec-template.md | Define the security spec format and the security report output format (`.rhoai-qs/<slug>/pipeline/security-report.yaml`) — severity categories (CRITICAL/HIGH/MEDIUM/LOW), finding details, fix status. |
| 09-07 | Create reasoning-guardrails.md | Define concern areas: false positive filtering (demos may have acceptable warnings), compliance context (HIPAA/PCI if PRD specifies), GPU security contexts (elevated permissions may be justified). |
| 09-08 | Write SKILL.md orchestrator | Write SKILL.md that runs all 4 scanners in parallel, aggregates findings by severity, runs a fix loop for CRITICAL+HIGH (max 3 iterations), blocks ship if CRITICAL remains, and generates the persistent security report. |
| 09-09 | Validate with skill-validator | Run `skill-validator --strict` against SKILL.md. |
| 09-10 | Add post-publication CVE monitoring docs | Document the Dependabot/Renovate integration strategy for ongoing CVE detection on published repos, and the rh-qs-update remediation path. |

---

## EPIC-10: rh-qs-debug-and-deploy [NEW]

**Description:** Create the new cluster deployment and debugging skill (stage 7). Deploys security-verified code to OpenShift, iteratively debugs failures with a resource-level debug loop, and runs E2E verification. Based on `bp-deploy-and-debug` from the blueprint kit.

**Blocked by:** EPIC-01 (foundation), EPIC-09 (security — security report format)
**Blocks:** EPIC-11 (rh-qs-document — depends on deploy state format)

| ID | Task | Description |
|----|------|-------------|
| 10-01 | Create debug-and-deploy skill directory structure | Create `core/skills/deployment/rh-qs-debug-and-deploy/` with full directory layout. |
| 10-02 | Adapt bp-deploy-and-debug from blueprint kit | Fork the blueprint kit's `bp-deploy-and-debug` skill as the starting point. Identify and document the adjustments needed for quickstart-specific context (ai-architecture-charts, namespace conventions, TEST-PLAN.md format). |
| 10-03 | Create cluster-access-validator-prompt.md | Write the subagent prompt that validates cluster login, namespace existence, and RBAC permissions before any deployment. |
| 10-04 | Create project-analyzer-prompt.md | Write the subagent prompt that discovers deploy commands and dependency order from the project structure. Outputs to `.rhoai-qs/<slug>/pipeline/qs-deploy-analysis.yaml`. |
| 10-05 | Create health-scanner-prompt.md | Write the subagent prompt that scans all namespace resources and produces a health snapshot. Used in initial scan (Phase 3) and re-scans during debug loop (Phase 4c). |
| 10-06 | Create resource-debugger-prompt.md | Write the subagent prompt that performs root-cause analysis per failing resource. Reviews previous attempts before proposing fixes to avoid repeating failed approaches. |
| 10-07 | Create fix-applier-prompt.md | Write the subagent prompt that validates proposed fixes against Red Hat best practices and applies them. Enforces fix boundary rules: auto-apply config/infra changes, ask user for application logic changes. |
| 10-08 | Create e2e-tester-prompt.md | Write the subagent prompt that runs TEST-PLAN.md end-to-end verification against the deployed namespace. |
| 10-09 | Create spec-template.md | Define the deploy state format (`.rhoai-qs/<slug>/pipeline/deploy-state.yaml`) — resource health states, debug attempt history, E2E results. |
| 10-10 | Create reasoning-guardrails.md | Define concern areas: namespace isolation (every command uses `-n <namespace>`), don't change application intent, dependency-order debugging, max 3 attempts per resource. |
| 10-11 | Write SKILL.md orchestrator | Write SKILL.md that orchestrates the full workflow: access validation → project analysis → deploy → health scan → debug loop (per resource, max 3 attempts) → E2E test → final report. Copy persistent report to `{project}/.rhoai-qs/deploy-report.yaml`. |
| 10-12 | Validate with skill-validator | Run `skill-validator --strict` against SKILL.md. |

---

## EPIC-11: rh-qs-document (Enhanced)

**Description:** Upgrade the document skill with iterative user-driven refinement (no cap) and a prompt engineering focus on concise, user-facing documentation rather than verbose AI-generated prose.

**Blocked by:** EPIC-01 (foundation), EPIC-10 (debug-and-deploy — deploy state format)
**Blocks:** EPIC-12 (rh-qs-ship — depends on doc manifest format)

| ID | Task | Description |
|----|------|-------------|
| 11-01 | Create document directory structure | Set up `core/skills/documentation/rh-qs-document/` with `subagents/` directory and `subagents/README.md`. |
| 11-02 | Create readme-generator-prompt.md | Write the subagent prompt that generates README from implementation + deploy manifests + security report. This is a high-effort prompt requiring iteration — must enforce conciseness: what the quickstart does, how to deploy, how to use. Not how it was built. |
| 11-03 | Create doc-validator-prompt.md | Write the subagent prompt that validates all documented commands exist (`make` targets), all URLs are well-formed, and the architecture diagram matches the actual components. |
| 11-04 | Create reasoning-guardrails.md | Define concern areas: verbosity (prefer concise), accuracy (every command must work), completeness (all deploy/usage paths covered), audience (user-facing, not developer-facing). |
| 11-05 | Restructure SKILL.md as orchestrator | Rewrite SKILL.md to generate → validate → present draft to user → user refines (no cap on refinement rounds). |
| 11-06 | Validate with skill-validator | Run `skill-validator --strict` against the updated SKILL.md. |

---

## EPIC-12: rh-qs-ship (Enhanced)

**Description:** Upgrade the ship skill with subagents for PR body generation and blog writing, plus a CI feedback loop.

**Blocked by:** EPIC-01 (foundation), EPIC-11 (document — doc manifest format)
**Blocks:** EPIC-13 (rh-qs-update — needs full pipeline), EPIC-15 (rh-qs-handoff — needs full pipeline)

| ID | Task | Description |
|----|------|-------------|
| 12-01 | Create ship directory structure | Set up `core/skills/shipping/rh-qs-ship/` with `subagents/` directory and `subagents/README.md`. |
| 12-02 | Create pr-body-generator-prompt.md | Write the subagent prompt that generates a PR description from all temp manifests and the security report. |
| 12-03 | Create blog-writer-prompt.md | Write the subagent prompt that generates a blog post draft from the PRD, architecture, and README. |
| 12-04 | Create reasoning-guardrails.md | Define concern areas: PR description accuracy, blog post tone (technical but accessible), no credentials in PR body, backlog issue cross-reference. |
| 12-05 | Restructure SKILL.md as orchestrator | Rewrite SKILL.md to create PR → wait for CI → if CI fails, diagnose + fix → re-push (max 3 iterations). Generate blog draft at `.rhoai-qs/<slug>/blog-drafts/<date>.md`. Update backlog issue. |
| 12-06 | Validate with skill-validator | Run `skill-validator --strict` against the updated SKILL.md. |

---

## EPIC-13: rh-qs-update [NEW]

**Description:** Create the new skill for updating released quickstarts. Analyzes changes, determines which pipeline stages need re-running, applies updates, and hands off to the pipeline at the correct re-entry point.

**Blocked by:** EPIC-12 (ship — full pipeline must be functional for re-entry)
**Blocks:** Nothing

| ID | Task | Description |
|----|------|-------------|
| 13-01 | Create update skill directory structure | Create `core/skills/lifecycle/rh-qs-update/` with full directory layout. |
| 13-02 | Create change-analyzer-prompt.md | Write the subagent prompt that analyzes what needs updating and scopes the change (image tag, chart version, dependency, security patch, feature addition, config change). |
| 13-03 | Create impact-assessor-prompt.md | Write the subagent prompt that determines which pipeline stages need re-running based on the change analysis. Maps update types to re-entry stages. |
| 13-04 | Create update-applier-prompt.md | Write the subagent prompt that applies the updates to source files (values.yaml, pyproject.toml, Containerfile, etc.). |
| 13-05 | Create update-validator-prompt.md | Write the subagent prompt that validates updates don't break existing functionality (`make lint && make test`). |
| 13-06 | Create spec-template.md | Define the update analysis and impact assessment formats. |
| 13-07 | Create reasoning-guardrails.md | Define concern areas: backward compatibility, semantic versioning awareness, test regression detection. |
| 13-08 | Write SKILL.md orchestrator | Write SKILL.md that analyzes → assesses impact → applies → validates → hands off to pipeline at the detected re-entry point (deploy → security → debug-and-deploy → document → ship). |
| 13-09 | Validate with skill-validator | Run `skill-validator --strict` against SKILL.md. |

---

## EPIC-14: Existing Utility Skills Upgrade

**Description:** Apply foundational patterns (reasoning guardrails, light subagent structure) to the 3 existing utility skills that the ADR doesn't restructure but should follow the 8 patterns.

**Blocked by:** EPIC-01 (foundation)
**Blocks:** Nothing (can run in parallel with pipeline skill upgrades)

| ID | Task | Description |
|----|------|-------------|
| 14-01 | Add reasoning-guardrails.md to rh-qs-gh-backlog-reader | Create guardrails for the backlog reader: data freshness, GitHub API rate limits, filter accuracy. |
| 14-02 | Add reasoning-guardrails.md to rh-qs-gh-issue-creator | Create guardrails for the issue creator: duplicate detection, template compliance, no credentials in issue body. |
| 14-03 | Add reasoning-guardrails.md to rh-qs-pipeline-grooming | Create guardrails for pipeline grooming: scoring objectivity, readiness rubric consistency, prioritization bias. |
| 14-04 | Validate all 3 with skill-validator | Run `skill-validator --strict` against all 3 updated SKILL.md files. |

---

## EPIC-15: rh-qs-handoff [NEW]

**Description:** Create the new skill that assesses partially implemented quickstarts, detects the current pipeline stage, identifies gaps, reconstructs missing context (PRD/design), and routes to the appropriate skill.

**Blocked by:** EPIC-12 (ship — full pipeline must be functional for routing)
**Blocks:** Nothing

| ID | Task | Description |
|----|------|-------------|
| 15-01 | Create handoff skill directory structure | Create `core/skills/lifecycle/rh-qs-handoff/` with full directory layout. |
| 15-02 | Create state-detector-prompt.md | Write the subagent prompt that scans a repo for evidence of each pipeline stage (PRD exists? workflows exist? Helm charts? security report? deploy report? README? open PR?). Produces completion state per stage. |
| 15-03 | Create gap-analyzer-prompt.md | Write the subagent prompt that identifies specific missing pieces within each partially complete stage (e.g., "backend 80% complete, frontend missing"). |
| 15-04 | Create context-reconstructor-prompt.md | Write the subagent prompt that reverse-engineers a PRD or design doc from existing code when those documents are missing. |
| 15-05 | Create reasoning-guardrails.md | Define concern areas: don't redo completed work, preserve existing code patterns, match the existing codebase's style conventions. |
| 15-06 | Write SKILL.md orchestrator | Write SKILL.md that scans → analyzes gaps → reconstructs context if needed → presents handoff report to user → user confirms → routes to appropriate skill with reconstructed context in temp files. |
| 15-07 | Decide on external PoC conversion scope | Resolve the TODO: should handoff also handle converting external PoC repos into quickstarts (conversion mode), or should that be a separate skill? Document the decision. |
| 15-08 | Validate with skill-validator | Run `skill-validator --strict` against SKILL.md. |

---

## EPIC-16: rh-qs-extract-knowledge [NEW]

**Description:** Create the new skill that mines completed quickstarts for reusable patterns and populates the shared knowledge base. Runs after ship or on-demand. Inspired by `bp-extract-blueprint-knowledge` from the blueprint kit.

**Blocked by:** EPIC-03 (KB infrastructure), EPIC-12 (ship — needs at least one completed quickstart to extract from)
**Blocks:** Nothing

| ID | Task | Description |
|----|------|-------------|
| 16-01 | Create extract-knowledge skill directory structure | Create `core/skills/knowledge/rh-qs-extract-knowledge/` with full directory layout. |
| 16-02 | Create component-pattern-extractor-prompt.md | Write the subagent prompt that extracts component usage patterns (config, wiring, gotchas) from source code and Helm charts. |
| 16-03 | Create deployment-pattern-extractor-prompt.md | Write the subagent prompt that extracts deployment patterns (chart combos, env configs, resource sizing) from Helm, compose, and deploy reports. |
| 16-04 | Create industry-pattern-extractor-prompt.md | Write the subagent prompt that extracts domain-specific patterns (data schemas, compliance, workflows) from PRD and source code. |
| 16-05 | Create security-pattern-extractor-prompt.md | Write the subagent prompt that extracts security patterns (SCC configs, secret handling, hardening) from security reports and Helm charts. |
| 16-06 | Create kb-dedup-scorer-prompt.md | Write the subagent prompt that deduplicates extracted patterns against existing KB, scores novelty (high/medium/low), and produces an update plan (merge existing or create new). |
| 16-07 | Create reasoning-guardrails.md | Define concern areas: no proprietary data in KB files (patterns only), deduplicate before creating, preserve existing KB file structure, validate frontmatter schema. |
| 16-08 | Write SKILL.md orchestrator | Write SKILL.md that runs 4 extractors in parallel → dedup-scorer compares against existing KB → main agent applies update plan (write/update .md files with Chain of Density summaries, update README index) → validate → generate extraction report. |
| 16-09 | Validate with skill-validator | Run `skill-validator --strict` against SKILL.md. |

---

## EPIC-17: Evaluation Benchmark

**Description:** Set up the ABEvalFlow-integrated evaluation benchmark with static test PRDs, skill submissions, CI/CD gating, and regression monitoring.

**Blocked by:** All skill EPICs (EPIC-04 through EPIC-16 — benchmarks test the upgraded skills)
**Blocks:** Nothing

| ID | Task | Description |
|----|------|-------------|
| 17-01 | Create test PRD: minimal-api.md | Write a static test PRD for an API-only quickstart (no frontend, no RAG). Include known-good reference implementation. Exercises stages 1–5, 8–9. |
| 17-02 | Create test PRD: full-stack-rag.md | Write a static test PRD for a full-stack quickstart (frontend + backend + pgvector + Llama Stack). Include known-good reference implementation. Exercises all stages. |
| 17-03 | Create test PRD: notebook-only.md | Write a static test PRD for a RHOAI notebook quickstart (no Helm). Include known-good reference implementation. Exercises stages 1–2, 4, 6–9. |
| 17-04 | Create skill submission structure | Set up `tests/benchmark/submissions/` with one directory per skill. Each contains `metadata.yaml` (eval_engine, n_trials, gate_policy), `instruction.md`, `skills/SKILL.md` symlink, and `tests/test_outputs.py` verifier. |
| 17-05 | Configure ASE (lightweight) CI pipeline | Set up the ASE evaluation engine for fast PR feedback (~5 min). LLM-as-judge assertions. Runs on PRs modifying `core/skills/**`. Blocks merge if scorecard = `fail`. |
| 17-06 | Configure Harbor (A/B) CI pipeline | Set up the Harbor evaluation engine for thorough pre-merge gating (~30 min). Runs on PRs with `full-eval` label. Blocks merge if `mean_reward_gap < 0`. |
| 17-07 | Configure weekly regression monitoring | Set up scheduled Harbor runs on all skills vs baseline. Send Slack alert if degradation detected (score drops below 85% of previous baseline). |
| 17-08 | Document benchmark maintenance process | Document how to add new test PRDs, update reference implementations, and maintain ABEvalFlow configurations. |

---

## EPIC-18: Documentation & Routing Updates

**Description:** Update all project documentation (AGENTS.md, CLAUDE.md) with new routing rules, skill descriptions, and pipeline flow. Final integration validation.

**Blocked by:** All skill EPICs (EPIC-04 through EPIC-16)
**Blocks:** Nothing

| ID | Task | Description |
|----|------|-------------|
| 18-01 | Update AGENTS.md routing table | Add routing entries for all new skills: rh-qs-security, rh-qs-debug-and-deploy, rh-qs-update, rh-qs-handoff, rh-qs-extract-knowledge. Update pipeline stage numbering (6=security, 7=debug-and-deploy). |
| 18-02 | Update CLAUDE.md routing table | Mirror the AGENTS.md routing changes in CLAUDE.md. |
| 18-03 | Update pipeline documentation | Update any pipeline diagrams and stage descriptions across all docs to reflect the new 9-stage pipeline with the correct ordering. |
| 18-04 | Run full make skills-check | Run `make skills-check` to validate all 15 skills pass layout validation, spec validation, client symlinks, and symlink count checks. |
| 18-05 | End-to-end integration test | Run a manual end-to-end test using one of the benchmark test PRDs through the full pipeline (discovery → ship) to validate the complete flow works with all upgraded skills. |
| 18-06 | Update ADR status | Change ADR-001 status from `Proposed` to `Accepted` after all EPICs are completed. |

---

## Summary

| EPIC | Skill / Area | Tasks | Phase | Dependencies |
|------|-------------|-------|-------|-------------|
| 01 | Foundation Infrastructure | 6 | 1 | None |
| 02 | Hooks Infrastructure | 5 | 1 | None |
| 03 | Knowledge Base Infrastructure | 7 | 1 | None |
| 04 | rh-qs-discovery | 7 | 2–3 | 01 |
| 05 | rh-qs-architect | 8 | 2–3 | 01, 03, 04 |
| 06 | rh-qs-scaffold | 8 | 2–3 | 01, 03, 05 |
| 07 | rh-qs-implement | 9 | 2–3 | 01, 06 |
| 08 | rh-qs-deploy | 9 | 2–3 | 01, 07 |
| 09 | rh-qs-security | 10 | 4 | 01, 08 |
| 10 | rh-qs-debug-and-deploy | 12 | 4 | 01, 09 |
| 11 | rh-qs-document | 6 | 2–3 | 01, 10 |
| 12 | rh-qs-ship | 6 | 2–3 | 01, 11 |
| 13 | rh-qs-update | 9 | 5 | 12 |
| 14 | Existing Utility Skills | 4 | 2 | 01 |
| 15 | rh-qs-handoff | 8 | 5 | 12 |
| 16 | rh-qs-extract-knowledge | 9 | 6 | 03, 12 |
| 17 | Evaluation Benchmark | 8 | 7 | 04–16 |
| 18 | Documentation & Routing | 6 | 7 | 04–16 |
| | **TOTAL** | **137** | | |
